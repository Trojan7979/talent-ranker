import base64
import json
import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from sieve_app import recruiter_auth_api, recruiter_google, recruiter_identity, recruiter_microsoft
from sieve_app.evidence_api import router as evidence_router
from tests.auth_support import FakeRecruiterIdentity


def encoded(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


def test_provider_login_starts_on_callback_host():
    app = FastAPI()
    app.state.recruiter_identity = SimpleNamespace(settings=recruiter_identity.IdentitySettings(
        _env_file=None, public_base_url="http://127.0.0.1:8000",
        frontend_base_url="http://localhost:5173",
        google_client_id="client", google_client_secret="secret"))
    app.include_router(recruiter_auth_api.router)
    with TestClient(app) as client:
        response = client.get("/api/auth/providers")
    assert response.status_code == 200
    assert response.json()["login_urls"] == {
        "google": "http://127.0.0.1:8000/api/auth/login/google"}


def test_microsoft_token_requires_real_signature_audience_nonce_and_issuer(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_numbers()
    jwk = {"kid": "test-key", "kty": "RSA",
           "n": base64.urlsafe_b64encode(public.n.to_bytes(256, "big")).rstrip(b"=").decode(),
           "e": base64.urlsafe_b64encode(public.e.to_bytes(3, "big")).rstrip(b"=").decode()}
    monkeypatch.setattr(recruiter_microsoft.requests, "get", lambda *args, **kwargs:
                        SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"keys": [jwk]}))
    config = recruiter_microsoft.config(
        recruiter_identity.IdentitySettings(_env_file=None, microsoft_client_id="client"))

    def token(**changes):
        header = encoded({"alg": "RS256", "kid": "test-key"})
        payload = encoded({"iss": "https://login.microsoftonline.com/tenant-id/v2.0",
                           "tid": "tenant-id", "sub": "stable-subject",
                           "aud": "client", "nonce": "expected", "iat": int(time.time()),
                           "exp": int(time.time()) + 300} | changes)
        signed = f"{header}.{payload}".encode()
        signature = private.sign(signed, padding.PKCS1v15(), hashes.SHA256())
        return signed.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    assert recruiter_microsoft.verify(token(), config, "expected")["sub"] == "stable-subject"
    for changes in ({"aud": "other"}, {"nonce": "other"}, {"iss": "https://attacker.example"},
                    {"exp": int(time.time()) - 1}):
        with pytest.raises(HTTPException) as denied:
            recruiter_microsoft.verify(token(**changes), config, "expected")
        assert denied.value.status_code == 401
    with pytest.raises(HTTPException):
        recruiter_microsoft.verify(token()[:-2] + "AA", config, "expected")


def test_google_token_uses_google_verifier_and_checks_nonce(monkeypatch):
    calls = []
    claims = {"iss": "https://accounts.google.com", "sub": "google-subject", "nonce": "expected"}
    def verify(token, request, audience):
        calls.append((token, audience))
        return claims
    monkeypatch.setattr(recruiter_google.id_token, "verify_oauth2_token", verify)
    config = recruiter_google.config(
        recruiter_identity.IdentitySettings(_env_file=None, google_client_id="google-client"))
    assert recruiter_google.verify("provider-token", config["client_id"], "expected") == claims
    assert calls == [("provider-token", "google-client")]
    with pytest.raises(HTTPException) as denied:
        recruiter_google.verify("provider-token", config["client_id"], "wrong")
    assert denied.value.status_code == 401


def test_two_recruiter_sessions_do_not_share_candidate_evidence():
    app = FastAPI()
    app.state.recruiter_identity = FakeRecruiterIdentity({"account-a": "recruiter-a",
                                                         "account-b": "recruiter-b"})
    app.state.agent_settings = SimpleNamespace(workspace_id="workspace")
    app.state.ranking_service = SimpleNamespace(state=SimpleNamespace(pipeline=SimpleNamespace(
        repo=SimpleNamespace(accessible_candidate_ids=lambda ids, scope:
                             set(ids) if scope.actor_id == "recruiter-a" else set()))))
    app.state.evidence_store = SimpleNamespace(get_for_candidates=lambda ids: {ids[0]: []})
    app.include_router(evidence_router)
    url = "/api/sources/candidates/CAND_0001/evidence"
    with TestClient(app) as client:
        assert client.get(url).status_code == 401
        assert client.get(url, headers={"Cookie": "sieve_recruiter_session=account-a"}).status_code == 200
        assert client.get(url, headers={"Cookie": "sieve_recruiter_session=account-b"}).status_code == 404
