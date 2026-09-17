from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import SETTINGS
from .pipeline import RankingPipeline
from .schemas import CandidateScore, HealthResponse, RankRequest, RankResponse


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
