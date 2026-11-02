import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from candidate_screening.config import Settings as ScreeningSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sieve_app.api import app, create_app, require_combined_urls, screening_settings
from talent_ranker.config import SETTINGS as ranking_settings


def test_combined_api_loads_screening_service_configuration(tmp_path: Path):
    service = tmp_path / "candidate-screening"
    service.mkdir()
    (service / ".env").write_text(
        "SCREENING_SENDER_BACKEND=fake\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "SCREENING_GMAIL_WEB_REDIRECT_URI=http://127.0.0.1:8000/api/screening/oauth/gmail/callback\n",
        encoding="utf-8",
    )
    settings = screening_settings(tmp_path)
    assert not hasattr(settings, "recruiter_tokens")
    assert settings.sender_backend == "fake"
    assert settings.gmail_web_redirect_uri == (
        "http://127.0.0.1:8000/api/screening/oauth/gmail/callback"
    )
    (tmp_path / ".env").write_text(
        "SCREENING_GMAIL_WEB_REDIRECT_URI=https://demo.example.test/api/screening/oauth/gmail/callback\n",
        encoding="utf-8",
    )
    assert screening_settings(tmp_path).gmail_web_redirect_uri.startswith("https://demo.example.test/")


def test_combined_api_does_not_require_source_oauth_to_start(monkeypatch):
    settings = ScreeningSettings(
        _env_file=None,
        public_base_url="https://example.test/s",
        gmail_web_redirect_uri="https://example.test/api/screening/oauth/gmail/callback",
        frontend_base_url="https://example.test",
    )
    monkeypatch.setattr(ranking_settings, "google_web_redirect_uri", "")
    require_combined_urls(settings)
    with pytest.raises(ValueError, match="SCREENING_PUBLIC_BASE_URL"):
        require_combined_urls(settings.model_copy(update={"public_base_url": ""}))


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
        assert client.get("/api/ranking/ranking-runs?limit=1").status_code == 401
        assert client.get(
            "/api/ranking/ranking-runs?limit=1",
            headers={"Authorization": "Bearer invalid"},
        ).status_code == 403
        token = next(iter(app.state.screening_settings.recruiter_tokens))
        assert client.get(
            "/api/ranking/ranking-runs?limit=1",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code == 200
        assert client.get("/api/screening/campaigns").status_code == 401


@pytest.mark.integration
def test_saved_rankings_are_scoped_to_recruiter_jobs():
    if not os.getenv("SIEVE_TEST_LOCAL_DATABASE"):
        pytest.skip("set SIEVE_TEST_LOCAL_DATABASE=1 for local combined-service test")
    settings = app.state.screening_settings
    agent_settings = app.state.agent_settings
    token = next(iter(settings.recruiter_tokens))
    other_token = f"test-{uuid4()}"
    other_actor = f"test-{uuid4()}"
    settings.recruiter_tokens[other_token] = other_actor
    agent_settings.allowed_jobs_by_actor[other_actor] = {"unassigned-test-job"}
    created_session_id = None
    try:
        with TestClient(app) as client:
            allowed = {"Authorization": f"Bearer {token}"}
            other = {"Authorization": f"Bearer {other_token}"}
            page = client.get("/api/ranking/ranking-runs?limit=1", headers=allowed)
            assert page.status_code == 200
            items = page.json()["items"]
            if not items:
                pytest.skip("no saved ranking run is available for the configured recruiter")
            run_id = items[0]["run_id"]
            agent_settings.allowed_jobs_by_actor[other_actor] = {items[0]["job_id"]}
            run = client.get(f"/api/ranking/ranking-runs/{run_id}", headers=allowed)
            assert run.status_code == 200
            assert client.get(f"/api/ranking/ranking-runs/{run_id}").status_code == 401
            assert client.get(f"/api/ranking/ranking-runs/{run_id}", headers=other).status_code == 404
            assert client.get("/api/ranking/ranking-runs", headers=other).json()["items"] == []
            session = client.post(
                "/api/agent/sessions", headers=allowed,
                json={"job_id": items[0]["job_id"], "ranking_run_id": run_id,
                      "use_saved_run": True},
            )
            assert session.status_code == 201
            created_session_id = session.json()["id"]
            own_threads = client.get("/api/agent/sessions", headers=allowed)
            assert own_threads.status_code == 200
            assert created_session_id in {item["id"] for item in own_threads.json()}
            other_threads = client.get("/api/agent/sessions", headers=other)
            assert other_threads.status_code == 200
            assert created_session_id not in {item["id"] for item in other_threads.json()}
            assert client.get(
                f"/api/agent/sessions/{created_session_id}", headers=other
            ).status_code == 404
            if run.json()["items"]:
                candidate_id = run.json()["items"][0]["candidate_id"]
                evidence_url = (
                    f"/api/ranking/ranking-runs/{run_id}/candidates/"
                    f"{candidate_id}/evidence"
                )
                assert client.get(evidence_url, headers=allowed).status_code == 200
                assert client.get(evidence_url).status_code == 401
                assert client.get(evidence_url, headers=other).status_code == 404
                source_evidence = f"/api/sources/candidates/{candidate_id}/evidence"
                source_resume = f"/api/sources/candidates/{candidate_id}/resume"
                assert client.get(source_evidence, headers=other).status_code == 404
                assert client.get(source_resume, headers=other).status_code == 404
    finally:
        if created_session_id is not None:
            with psycopg.connect(settings.database_url) as conn:
                conn.execute(
                    "DELETE FROM agent_sessions WHERE id=%s", (created_session_id,)
                )
        del settings.recruiter_tokens[other_token]
        del agent_settings.allowed_jobs_by_actor[other_actor]
