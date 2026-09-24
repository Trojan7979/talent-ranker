"""Gmail OAuth sender for the initial screening invitation only."""

import base64
import os
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def _save_credentials(path: Path, serialized: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(serialized, encoding="utf-8")
    os.replace(temporary, path)


def authorize_gmail(client_secrets_file: Path, token_file: Path) -> None:
    """One-time, interactive consent by the sender account on the operator's machine."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets_file), scopes=[GMAIL_SEND_SCOPE]
    )
    credentials = flow.run_local_server(port=0, prompt="consent")
    _save_credentials(token_file, credentials.to_json())


@dataclass(frozen=True)
class GmailApiSender:
    sender_email: str
    token_file: Path

    def send(self, recipient: str, subject: str, body: str, message_id: str) -> str:
        from google.auth.exceptions import GoogleAuthError
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.credentials import Credentials
        from requests.exceptions import RequestException

        if not self.token_file.is_file():
            raise RuntimeError("Gmail sender is not authorized; run authorize-gmail")
        try:
            credentials = Credentials.from_authorized_user_file(
                str(self.token_file), scopes=[GMAIL_SEND_SCOPE]
            )
        except (ValueError, GoogleAuthError) as error:
            raise RuntimeError("Gmail sender token file is invalid") from error
        if not credentials.valid and not credentials.refresh_token:
            raise RuntimeError("Gmail sender authorization has expired")
        token_before_send = credentials.token

        message = EmailMessage()
        message["From"] = self.sender_email
        message["To"] = recipient
        message["Subject"] = subject
        message["Message-ID"] = f"<{message_id}@screening.local>"
        message.set_content(body)
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        try:
            response = AuthorizedSession(credentials).post(
                GMAIL_SEND_URL, json={"raw": encoded}, timeout=15
            )
            response.raise_for_status()
        except (GoogleAuthError, RequestException) as error:
            raise RuntimeError(f"Gmail send failed: {type(error).__name__}") from error
        try:
            receipt = response.json().get("id")
        except ValueError as error:
            raise RuntimeError("Gmail returned an invalid response") from error
        if not isinstance(receipt, str) or not receipt:
            raise RuntimeError("Gmail did not return a message ID")
        if credentials.refresh_token and credentials.token != token_before_send:
            _save_credentials(self.token_file, credentials.to_json())
        return receipt
