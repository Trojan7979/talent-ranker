from contextlib import ExitStack, asynccontextmanager

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
from .workflow_api import router as workflow_router


def create_app(repository=None, settings: Settings | None = None, gmail_web_oauth=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owned = repository is None
        if (owned or settings.workflow_enabled) and not settings.database_url:
            raise ValueError("Configure SCREENING_DATABASE_URL before starting screening")
        app.state.repo = repository or PostgresRepository(settings.database_url)
        with ExitStack() as stack:
            if settings.workflow_enabled:
                from langgraph.checkpoint.postgres import PostgresSaver
                from sieve_app.workflow import CampaignWorkflow

                checkpointer = stack.enter_context(PostgresSaver.from_conn_string(settings.database_url))
                checkpointer.setup()
                app.state.workflow = CampaignWorkflow(app.state.repo, checkpointer)
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
    app.include_router(workflow_router)

    @app.get("/health", response_model=HealthResponse, operation_id="screening_health")
    def health() -> HealthResponse:
        return HealthResponse()

    return app


app = create_app()
