from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import Settings
from .proposal_api import router as proposal_router
from .repository import PostgresRepository
from .schemas import HealthResponse


def create_app(repository=None, settings: Settings | None = None) -> FastAPI:
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
    app.include_router(proposal_router)

    @app.get("/health", response_model=HealthResponse, operation_id="screening_health")
    def health() -> HealthResponse:
        return HealthResponse()

    return app


app = create_app()
