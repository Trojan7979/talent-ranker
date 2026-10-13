"""Expose ranking and screening through one FastAPI listener."""

from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from candidate_screening.api import create_app as create_screening_app
from candidate_screening.config import Settings as ScreeningSettings
from fastapi import FastAPI

from talent_ranker.api import app as ranking_app
from talent_ranker.config import SETTINGS as ranking_settings
from talent_ranker.external_evidence import EvidenceStore

from .agent_api import router as agent_router
from .agent_config import AgentSettings
from .drive_api import router as drive_router
from .evidence_api import router as evidence_router
from .indexing_store import IndexingStore
from .resume_api import router as resume_router
from .source_api import router as source_router


def screening_settings(repo_root: Path) -> ScreeningSettings:
    """Load service settings from the existing local layout when composed at repo root."""
    settings = ScreeningSettings(
        _env_file=[repo_root / "candidate-screening" / ".env", repo_root / ".env"]
    )
    standalone_default = ScreeningSettings.model_fields["gmail_web_redirect_uri"].default
    if settings.gmail_web_redirect_uri == standalone_default:
        settings.gmail_web_redirect_uri = (
            "http://127.0.0.1:8000/api/screening/oauth/gmail/callback"
        )
    return settings


screening_app = create_screening_app(
    settings=screening_settings(Path(__file__).resolve().parents[2])
)


def create_app(
    ranking: FastAPI = ranking_app, screening: FastAPI = screening_app,
    index_store: IndexingStore | None = None,
    evidence_store: EvidenceStore | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(ranking.router.lifespan_context(ranking))
            await stack.enter_async_context(screening.router.lifespan_context(screening))
            app.state.ranking_service = ranking
            app.state.screening_service = screening
            if index_store is not None:
                app.state.index_store = index_store
            elif ranking is ranking_app:
                app.state.index_store = IndexingStore(ranking_settings.database_url)
                stack.callback(app.state.index_store.close)
            if evidence_store is not None:
                app.state.evidence_store = evidence_store
            elif ranking is ranking_app:
                app.state.evidence_store = EvidenceStore(ranking_settings.database_url)
                stack.callback(app.state.evidence_store.close)
            yield

    app = FastAPI(title="Sieve API", lifespan=lifespan)
    app.state.screening_settings = getattr(screening.state, "settings", None)
    app.state.agent_settings = AgentSettings()
    app.include_router(agent_router)
    app.include_router(source_router)
    app.include_router(drive_router)
    app.include_router(resume_router)
    app.include_router(evidence_router)
    app.mount("/api/ranking", ranking)
    app.mount("/api", screening)
    return app


app = create_app()
