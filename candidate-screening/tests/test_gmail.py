import base64
import sys
from email import message_from_bytes

import pytest

from candidate_screening.cli import main
from candidate_screening.gmail import (
    GMAIL_SEND_SCOPE,
    GMAIL_SEND_URL,
    GmailApiSender,
    authorize_gmail,
)


def test_gmail_sender_posts_mime_with_send_only_scope(monkeypatch, tmp_path):
    token_file = tmp_path / "sender.json"
    token_file.write_text("{}", encoding="utf-8")
    observed = {}

    class Credentials:
        valid = True
        refresh_token = "mock-refresh"
        token = "mock-access"

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "gmail-message-123"}

    class Session:
        def __init__(self, credentials):
            assert credentials is mock_credentials

        def post(self, url, json, timeout):
            observed["url"] = url
            observed["timeout"] = timeout
            observed["message"] = message_from_bytes(base64.urlsafe_b64decode(json["raw"]))
            return Response()

    mock_credentials = Credentials()
    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.from_authorized_user_file",
        lambda filename, scopes: mock_credentials if scopes == [GMAIL_SEND_SCOPE] else None,
    )
    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", Session)
    sender = GmailApiSender("sender@gmail.com", token_file)
    receipt = sender.send("candidate@outlook.com", "Screening", "Unique link", "outbox-1")
    assert receipt == "gmail-message-123"
    assert observed["url"] == GMAIL_SEND_URL
    assert observed["timeout"] == 15
    assert observed["message"]["From"] == "sender@gmail.com"
    assert observed["message"]["To"] == "candidate@outlook.com"
    assert observed["message"]["Message-ID"] == "<outbox-1@screening.local>"


def test_authorization_saves_sender_token_outside_repository(monkeypatch, tmp_path):
    observed = {}

    class MockCredentials:
        def to_json(self):
            return '{"token":"mock-only"}'

    class MockFlow:
        def run_local_server(self, port, prompt):
            observed["consent"] = (port, prompt)
            return MockCredentials()

    def from_file(filename, scopes):
        observed["client_file"] = filename
        observed["scopes"] = scopes
        return MockFlow()

    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file", from_file
    )
    token_file = tmp_path / ".tokens" / "gmail-sender.json"
    authorize_gmail(tmp_path / "client.json", token_file)
    assert token_file.read_text(encoding="utf-8") == '{"token":"mock-only"}'
    assert observed["scopes"] == [GMAIL_SEND_SCOPE]
    assert observed["consent"] == (0, "consent")


def test_gmail_dispatch_requires_explicit_campaign(monkeypatch):
    monkeypatch.setenv("SCREENING_SENDER_BACKEND", "gmail_api")
    monkeypatch.setenv("SCREENING_GMAIL_SENDER_EMAIL", "sender@gmail.com")
    monkeypatch.setattr(sys, "argv", ["candidate-screening", "dispatch", "--once"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
