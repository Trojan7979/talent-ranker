import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sieve_app.api import app, create_app, screening_settings


def test_combined_api_loads_screening_service_configuration(tmp_path: Path):
    service = tmp_path / "candidate-screening"
    service.mkdir()
    (service / ".env").write_text(
        'SCREENING_RECRUITER_TOKENS={"demo-token":"demo-recruiter"}\n'
        "SCREENING_SENDER_BACKEND=fake\n",
        encoding="utf-8",
    )
    settings = screening_settings(tmp_path)
    assert settings.recruiter_tokens == {"demo-token": "demo-recruiter"}
    assert settings.sender_backend == "fake"


def test_combined_api_routes_requests_and_runs_both_lifespans():
    events: list[str] = []

    def service(name: str) -> FastAPI:
        @asynccontextmanager
        async def lifespan(_: FastAPI):
            events.append(f"start:{name}")
            try:
                yield
            finally:
                events.append(f"stop:{name}")

        app = FastAPI(lifespan=lifespan)

        @app.get("/health")
        def health():
            return {"service": name}

        return app

    app = create_app(service("ranking"), service("screening"))
    with TestClient(app) as client:
        assert client.get("/api/ranking/health").json() == {"service": "ranking"}
        assert client.get("/api/health").json() == {"service": "screening"}
        assert events == ["start:ranking", "start:screening"]
    assert events == ["start:ranking", "start:screening", "stop:screening", "stop:ranking"]


@pytest.mark.integration
def test_combined_api_starts_real_services_and_preserves_screening_auth():
    if not os.getenv("SIEVE_TEST_LOCAL_DATABASE"):
        pytest.skip("set SIEVE_TEST_LOCAL_DATABASE=1 for local combined-service test")
    with TestClient(app) as client:
        assert client.get("/api/ranking/health").status_code == 200
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/ranking/ranking-runs?limit=1").status_code == 200
        assert client.get("/api/screening/campaigns").status_code == 401
