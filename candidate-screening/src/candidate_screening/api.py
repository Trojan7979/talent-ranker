from contextlib import asynccontextmanager

from fastapi import FastAPI

from .batch_api import router as batch_router
from .candidate_api import router as candidate_router
from .config import Settings
from .dispatch_api import router as dispatch_router
from .gmail_web_oauth import GmailWebOAuth
from .proposal_api import router as proposal_router
from .repository import PostgresRepository
from .review_api import router as review_router
from .schemas import HealthResponse
from .sender_oauth_api import router as sender_oauth_router


def create_app(repository=None, settings: Settings | None = None, gmail_web_oauth=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owned = repository is None
        app.state.repo = repository or PostgresRepository(settings.database_url)
        try:
            yield
        finally:
            if owned:
                app.state.repo.close()

    app = FastAPI(title="Candidate Screening API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.gmail_web_oauth = gmail_web_oauth or GmailWebOAuth(settings)
    app.include_router(proposal_router)
    app.include_router(candidate_router)
    app.include_router(review_router)
    app.include_router(dispatch_router)
    app.include_router(batch_router)
    app.include_router(sender_oauth_router)

    @app.get("/health", response_model=HealthResponse, operation_id="screening_health")
    def health() -> HealthResponse:
        return HealthResponse()

    return app


app = create_app()
