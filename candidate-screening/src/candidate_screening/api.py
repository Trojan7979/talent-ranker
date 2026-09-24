from fastapi import FastAPI

from .schemas import HealthResponse


def create_app() -> FastAPI:
    app = FastAPI(title="Candidate Screening API", version="0.1.0")

    @app.get("/health", response_model=HealthResponse, operation_id="screening_health")
    def health() -> HealthResponse:
        return HealthResponse()

    return app


app = create_app()
