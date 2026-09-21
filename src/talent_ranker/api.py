from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import SETTINGS
from .identifiers import validate_candidate_id
from .pipeline import RankingPipeline
from .schemas import (
    CandidateEvidenceResponse,
    CandidateScore,
    HealthResponse,
    RankRequest,
    RankResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/rank", response_model=RankResponse)
def rank_candidates(request: RankRequest) -> RankResponse:
    run_id, results = app.state.pipeline.rank(
        request.job_id, request.job_description, request.top_k
    )
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
            )
            for rank, result in enumerate(results, 1)
        ],
    )


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
