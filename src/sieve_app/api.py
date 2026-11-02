"""Expose ranking and screening through one FastAPI listener."""

from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from candidate_screening.api import create_app as create_screening_app
from candidate_screening.config import Settings as ScreeningSettings
from fastapi import FastAPI

from talent_ranker.api import app as ranking_app
from talent_ranker.config import SETTINGS as ranking_settings
from talent_ranker.external_evidence import EvidenceStore

from .agent_api import router as agent_router
from .agent_config import AgentSettings
from .drive_api import router as drive_router
from .drive_watch_api import router as drive_watch_router
from .evidence_api import router as evidence_router
from .indexing_store import IndexingStore
from .recruiter_auth_api import router as identity_router
from .recruiter_identity import IdentitySettings, RecruiterIdentity
from .resume_api import router as resume_router
from .source_api import router as source_router


def screening_settings(repo_root: Path) -> ScreeningSettings:
    """Load explicit screening settings for the combined API."""
    return ScreeningSettings(
        _env_file=[repo_root / "candidate-screening" / ".env", repo_root / ".env"]
    )


def require_combined_urls(settings: ScreeningSettings) -> None:
    required_urls = {
        "SCREENING_PUBLIC_BASE_URL": settings.public_base_url,
        "SCREENING_FRONTEND_BASE_URL": settings.frontend_base_url,
    }
    optional_urls = {
        "TALENT_RANKER_GOOGLE_WEB_REDIRECT_URI": ranking_settings.google_web_redirect_uri,
        "TALENT_RANKER_FRONTEND_BASE_URL": ranking_settings.frontend_base_url,
        "SCREENING_GMAIL_WEB_REDIRECT_URI": settings.gmail_web_redirect_uri,
    }
    missing = [name for name, value in required_urls.items() if not value]
    if missing:
        raise ValueError("Configure " + ", ".join(missing) + " before starting the combined API")
    for name, value in (required_urls | optional_urls).items():
        if not value:
            continue
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"{name} must be an HTTP(S) URL without embedded credentials")


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
        if ranking is ranking_app and screening is screening_app:
            require_combined_urls(app.state.screening_settings)
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

    app = FastAPI(title="Recruitment Agent API", lifespan=lifespan)
    app.state.screening_settings = getattr(screening.state, "settings", None)
    app.state.agent_settings = AgentSettings()
    identity_settings = IdentitySettings()
    if not identity_settings.database_url and app.state.screening_settings:
        identity_settings.database_url = getattr(app.state.screening_settings, "database_url", "")
    identity = RecruiterIdentity(identity_settings)
    app.state.recruiter_identity = identity
    ranking.state.recruiter_identity = identity
    screening.state.recruiter_identity = identity
    screening.state.ranking_workspace_id = app.state.agent_settings.workspace_id
    if ranking is ranking_app:
        ranking.state.ranking_workspace_id = app.state.agent_settings.workspace_id
    app.include_router(identity_router)
    app.include_router(agent_router)
    app.include_router(source_router)
    app.include_router(drive_router)
    app.include_router(drive_watch_router)
    app.include_router(resume_router)
    app.include_router(evidence_router)
    app.mount("/api/ranking", ranking)
    app.mount("/api", screening)
    return app


app = create_app()
