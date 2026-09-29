"""Expose ranking and screening through one FastAPI listener."""

from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from candidate_screening.api import create_app as create_screening_app
from candidate_screening.config import Settings as ScreeningSettings
from fastapi import FastAPI

from talent_ranker.api import app as ranking_app


def screening_settings(repo_root: Path) -> ScreeningSettings:
    """Load service settings from the existing local layout when composed at repo root."""
    return ScreeningSettings(
        _env_file=[repo_root / "candidate-screening" / ".env", repo_root / ".env"]
    )


screening_app = create_screening_app(
    settings=screening_settings(Path(__file__).resolve().parents[2])
)


def create_app(ranking: FastAPI = ranking_app, screening: FastAPI = screening_app) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(ranking.router.lifespan_context(ranking))
            await stack.enter_async_context(screening.router.lifespan_context(screening))
            yield

    app = FastAPI(title="Sieve API", lifespan=lifespan)
    app.mount("/api/ranking", ranking)
    app.mount("/api", screening)
    return app


app = create_app()
