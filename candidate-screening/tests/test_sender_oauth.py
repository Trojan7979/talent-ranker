import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import headers

from candidate_screening.gmail_web_oauth import GmailWebOAuth


class FakeOAuth:
    def __init__(self, token_file: Path):
        self.token_file = token_file
        self.completed = 0

    def authorization_url(self, state: str, verifier: str, nonce: str) -> str:
        assert verifier and nonce
        return f"https://accounts.google.test/authorize?state={state}"

    def complete(self, state: str, verifier: str, nonce: str, code: str) -> str:
        assert state and verifier and nonce and code == "mock-code"
        self.completed += 1
        self.token_file.write_text('{"refresh_token":"mock-refresh"}', encoding="utf-8")
        return "sender@example.test"


def test_frontend_connection_uses_one_time_state_and_never_returns_token(client, tmp_path):
    settings = client.app.state.settings
    settings.sender_backend = "gmail_api"
    settings.gmail_sender_email = "sender@example.test"
    settings.gmail_token_file = tmp_path / "gmail.json"
    client.app.state.gmail_web_oauth = FakeOAuth(settings.gmail_token_file)

    assert client.post("/screening/sender/gmail/connect", json={}).status_code == 401
    before = client.get("/screening/sender/gmail/status", headers=headers())
    assert before.json()["connected"] is False
    started = client.post("/screening/sender/gmail/connect", headers=headers(), json={})
    assert started.status_code == 200
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
    assert "refresh_token" not in started.text
    callback = client.get(
        "/screening/oauth/gmail/callback", params={"state": state, "code": "mock-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"].endswith("/ranking?gmail=connected")
    assert client.app.state.gmail_web_oauth.completed == 1
    assert client.get("/screening/sender/gmail/status", headers=headers()).json()["connected"]
    assert client.get("/screening/oauth/gmail/callback", params={"state": state, "code": "mock-code"}).status_code == 400
    assert client.get("/screening/oauth/gmail/callback", params={"state": "wrong", "code": "mock-code"}).status_code == 400


def test_web_oauth_rejects_another_google_account_before_saving(monkeypatch, tmp_path):
    from candidate_screening.config import Settings

    secret_file = tmp_path / "web.json"
    secret_file.write_text(json.dumps({"web": {"client_id": "client-id"}}), encoding="utf-8")
    token_file = tmp_path / "sender.json"
    oauth = GmailWebOAuth(Settings(
        gmail_web_client_secrets_file=secret_file, gmail_token_file=token_file,
        gmail_sender_email="expected@example.test",
    ))

    class Credentials:
        refresh_token = "refresh"
        id_token = "mock-id-token"

        def to_json(self):
            return '{"refresh_token":"refresh"}'

    class Flow:
        credentials = Credentials()

        def fetch_token(self, code):
            assert code == "mock-code"

    monkeypatch.setattr(GmailWebOAuth, "_flow", lambda self, verifier, state: Flow())
    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", lambda token, request, audience: {
        "email": "wrong@example.test", "email_verified": True, "nonce": "nonce",
    })
    with pytest.raises(ValueError, match="does not match"):
        oauth.complete("state", "verifier", "nonce", "mock-code")
    assert not token_file.exists()
    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", lambda token, request, audience: {
        "email": "expected@example.test", "email_verified": True, "nonce": "wrong-nonce",
    })
    with pytest.raises(ValueError, match="confirmation"):
        oauth.complete("state", "verifier", "nonce", "mock-code")
    assert not token_file.exists()
    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", lambda token, request, audience: {
        "email": "expected@example.test", "email_verified": True, "nonce": "nonce",
    })
    assert oauth.complete("state", "verifier", "nonce", "mock-code") == "expected@example.test"
    assert json.loads(token_file.read_text(encoding="utf-8"))["refresh_token"] == "refresh"


def test_web_authorization_url_uses_fixed_callback_state_and_pkce(tmp_path):
    from candidate_screening.config import Settings

    callback = "http://127.0.0.1:8001/screening/oauth/gmail/callback"
    path = tmp_path / "web.json"
    path.write_text(json.dumps({"web": {
        "client_id": "mock.apps.googleusercontent.com", "client_secret": "mock-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [callback],
    }}), encoding="utf-8")
    oauth = GmailWebOAuth(Settings(gmail_web_client_secrets_file=path,
                                  gmail_web_redirect_uri=callback))
    query = parse_qs(urlparse(oauth.authorization_url("fixed-state", "verifier", "nonce")).query)
    assert query["state"] == ["fixed-state"]
    assert query["redirect_uri"] == [callback]
    assert query["access_type"] == ["offline"]
    assert query["nonce"] == ["nonce"]
    assert query["code_challenge"]
