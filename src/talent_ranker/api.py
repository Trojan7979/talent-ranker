from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .calibration import calibrate_job_description, configured_extractor
from .config import SETTINGS
from .identifiers import validate_candidate_id
from .llm_priority_extraction import CalibrationError
from .pipeline import RankingPipeline
from .schemas import (
    ApproveJobProfileRequest,
    CalibrateJobRequest,
    CandidateEvidenceResponse,
    CandidateScore,
    HealthResponse,
    JobProfileResponse,
    RankRequest,
    RankResponse,
    UpdateJobProfileRequest,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    pipeline = RankingPipeline(SETTINGS)
    app.state.pipeline = pipeline
    try:
        yield
    finally:
        pipeline.repo.close()


app = FastAPI(title="Talent Ranker API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/rank", response_model=RankResponse)
def rank_candidates(request: RankRequest) -> RankResponse:
    profile = app.state.pipeline.repo.get_job_profile(str(request.job_profile_version_id))
    if profile is None:
        raise HTTPException(status_code=404, detail="job profile version not found")
    if profile["job_id"] != request.job_id:
        raise HTTPException(status_code=409, detail="job profile does not belong to requested job")
    if profile["status"] != "approved":
        raise HTTPException(status_code=409, detail="job profile must be approved before ranking")
    run_id, results = app.state.pipeline.rank(request.job_id, profile, request.top_k)
    return RankResponse(
        run_id=run_id,
        results=[
            CandidateScore(
                candidate_id=result.candidate_id,
                rank=rank,
                score=result.score,
                score_components=result.components,
                evidence=result.evidence,
                reasoning=result.reasoning,
                requirement_evidence=result.requirement_evidence,
            )
            for rank, result in enumerate(results, 1)
        ],
    )


@app.post("/jobs/calibrate", response_model=JobProfileResponse, status_code=201)
def calibrate_job(request: CalibrateJobRequest) -> JobProfileResponse:
    try:
        extractor, metadata = configured_extractor(SETTINGS)
        priorities = calibrate_job_description(
            request.job_description, request.overrides, extractor
        )
    except CalibrationError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    profile = app.state.pipeline.repo.create_job_profile(
        request.job_id,
        request.job_description,
        priorities.model_dump(mode="json"),
        metadata,
    )
    return JobProfileResponse.model_validate(profile)


@app.get(
    "/job-profiles/{profile_version_id}",
    response_model=JobProfileResponse,
    operation_id="get_job_profile",
)
def get_job_profile(profile_version_id: UUID) -> JobProfileResponse:
    profile = app.state.pipeline.repo.get_job_profile(str(profile_version_id))
    if profile is None:
        raise HTTPException(status_code=404, detail="job profile version not found")
    return JobProfileResponse.model_validate(profile)


@app.put(
    "/job-profiles/{profile_version_id}",
    response_model=JobProfileResponse,
    operation_id="update_job_profile",
)
def update_job_profile(
    profile_version_id: UUID, request: UpdateJobProfileRequest
) -> JobProfileResponse:
    existing = app.state.pipeline.repo.get_job_profile(str(profile_version_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="job profile version not found")
    if existing["status"] != "draft":
        raise HTTPException(status_code=409, detail="only draft job profiles can be edited")
    profile = app.state.pipeline.repo.update_job_profile(
        str(profile_version_id), request.priorities.model_dump(mode="json")
    )
    if profile is None:
        raise HTTPException(status_code=409, detail="job profile is no longer editable")
    return JobProfileResponse.model_validate(profile)


@app.post(
    "/job-profiles/{profile_version_id}/approve",
    response_model=JobProfileResponse,
    operation_id="approve_job_profile",
)
def approve_job_profile(
    profile_version_id: UUID, request: ApproveJobProfileRequest
) -> JobProfileResponse:
    existing = app.state.pipeline.repo.get_job_profile(str(profile_version_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="job profile version not found")
    if existing["status"] != "draft":
        raise HTTPException(status_code=409, detail="only draft job profiles can be approved")
    profile = app.state.pipeline.repo.approve_job_profile(
        str(profile_version_id), request.approved_by
    )
    if profile is None:
        raise HTTPException(status_code=409, detail="job profile is no longer approvable")
    return JobProfileResponse.model_validate(profile)


@app.get(
    "/ranking-runs/{run_id}/candidates/{candidate_id}/evidence",
    response_model=CandidateEvidenceResponse,
    operation_id="get_candidate_evidence",
)
def get_candidate_evidence(run_id: UUID, candidate_id: str) -> CandidateEvidenceResponse:
    try:
        candidate_id = validate_candidate_id(candidate_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    evidence = app.state.pipeline.repo.get_candidate_evidence(str(run_id), candidate_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="candidate evidence not found for ranking run")
    return CandidateEvidenceResponse.model_validate(evidence)
