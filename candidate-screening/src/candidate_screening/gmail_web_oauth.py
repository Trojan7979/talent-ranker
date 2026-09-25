"""Server-side Google consent; the browser never receives Gmail credentials."""

import json
from dataclasses import dataclass

from .config import Settings
from .gmail import GMAIL_SEND_SCOPE, _save_credentials

SCOPES = [GMAIL_SEND_SCOPE, "openid", "email"]


@dataclass(frozen=True)
class GmailWebOAuth:
    settings: Settings

    def _client_id(self) -> str:
        path = self.settings.gmail_web_client_secrets_file
        if not path.is_file():
            raise ValueError("Gmail web OAuth client JSON is not configured")
        try:
            client_id = json.loads(path.read_text(encoding="utf-8"))["web"]["client_id"]
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError("Expected a Google Web application OAuth client JSON") from error
        if not isinstance(client_id, str) or not client_id:
            raise ValueError("Google Web application client ID is missing")
        return client_id

    def _flow(self, verifier: str, state: str):
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_secrets_file(
            str(self.settings.gmail_web_client_secrets_file),
            scopes=SCOPES,
            state=state,
            code_verifier=verifier,
            redirect_uri=self.settings.gmail_web_redirect_uri,
        )
        return flow

    def authorization_url(self, state: str, verifier: str, nonce: str) -> str:
        self._client_id()
        flow = self._flow(verifier, state)
        url, _ = flow.authorization_url(
            access_type="offline", prompt="consent", include_granted_scopes="true", nonce=nonce
        )
        return url

    def complete(self, state: str, verifier: str, nonce: str, code: str) -> str:
        from google.auth.exceptions import GoogleAuthError
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token
        from oauthlib.oauth2 import OAuth2Error
        from requests.exceptions import RequestException

        client_id = self._client_id()
        flow = self._flow(verifier, state)
        try:
            flow.fetch_token(code=code)
        except (OAuth2Error, RequestException, GoogleAuthError) as error:
            raise ValueError("Google authorization could not be completed") from error
        credentials = flow.credentials
        if not credentials.refresh_token or not credentials.id_token:
            raise ValueError("Google did not grant offline sender access")
        try:
            claims = id_token.verify_oauth2_token(credentials.id_token, GoogleRequest(), client_id)
        except (ValueError, RequestException, GoogleAuthError) as error:
            raise ValueError("Google account confirmation failed") from error
        expected = (self.settings.gmail_sender_email or "").casefold()
        email = str(claims.get("email", "")).casefold()
        if not claims.get("email_verified") or not expected or email != expected:
            raise ValueError("Connected Google account does not match the configured sender")
        if claims.get("nonce") != nonce:
            raise ValueError("Google account confirmation did not match this connection request")
        _save_credentials(self.settings.gmail_token_file, credentials.to_json())
        return email
