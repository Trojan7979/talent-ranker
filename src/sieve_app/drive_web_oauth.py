"""Server-side Google Drive consent for the local recruiter workspace."""

import json
import os
import tempfile
from pathlib import Path

from talent_ranker.config import Settings
from talent_ranker.storage import DRIVE_READONLY_SCOPE

SCOPES = [*DRIVE_READONLY_SCOPE, "openid", "email"]


class DriveWebOAuth:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _client_id(self) -> str:
        path = Path(self.settings.google_web_credentials_file)
        if not path.is_file():
            raise ValueError("Google Web application OAuth client JSON is not configured")
        try:
            client_id = json.loads(path.read_text(encoding="utf-8"))["web"]["client_id"]
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError("Expected a Google Web application OAuth client JSON") from error
        if not isinstance(client_id, str) or not client_id:
            raise ValueError("Google Web application client ID is missing")
        return client_id

    def _flow(self, state: str, verifier: str):
        from google_auth_oauthlib.flow import Flow

        return Flow.from_client_secrets_file(
            self.settings.google_web_credentials_file, scopes=SCOPES,
            state=state, code_verifier=verifier,
            redirect_uri=self.settings.google_web_redirect_uri,
        )

    def authorization_url(self, state: str, verifier: str, nonce: str) -> str:
        self._client_id()
        url, _ = self._flow(state, verifier).authorization_url(
            access_type="offline", prompt="consent", nonce=nonce,
        )
        return url

    def complete(self, state: str, verifier: str, nonce: str, code: str,
                 token_file: Path) -> str:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token

        client_id = self._client_id()
        flow = self._flow(state, verifier)
        try:
            flow.fetch_token(code=code)
        except Warning as warning:
            token = getattr(warning, "token", None)
            granted = token.get("scope", ()) if isinstance(token, dict) else ()
            if isinstance(granted, str):
                granted = granted.split()
            if DRIVE_READONLY_SCOPE[0] not in granted:
                raise ValueError("Google did not grant Drive read access") from warning
            flow.oauth2session.token = dict(token)
        except Exception as error:
            raise ValueError("Google Drive authorization could not be completed") from error
        credentials = flow.credentials
        if credentials.granted_scopes and DRIVE_READONLY_SCOPE[0] not in credentials.granted_scopes:
            raise ValueError("Google did not grant Drive read access")
        if not credentials.refresh_token or not credentials.id_token:
            raise ValueError("Google did not grant offline Drive access")
        try:
            claims = id_token.verify_oauth2_token(credentials.id_token, GoogleRequest(), client_id)
        except Exception as error:
            raise ValueError("Google account confirmation failed") from error
        if not claims.get("email_verified") or claims.get("nonce") != nonce:
            raise ValueError("Google account confirmation did not match this request")
        self._save_token(token_file, credentials.to_json())
        return str(claims["email"])

    @staticmethod
    def _save_token(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False,
        ) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
