"""Google OpenID Connect configuration and ID-token verification."""

from fastapi import HTTPException
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

from .recruiter_identity import IdentitySettings


def config(settings: IdentitySettings) -> dict[str, str]:
    return {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret.get_secret_value()
        if settings.google_client_secret else "",
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
    }


def verify(token: str, client_id: str, nonce: str) -> dict:
    try:
        claims = id_token.verify_oauth2_token(token, GoogleRequest(), client_id)
        if claims.get("nonce") != nonce or not claims.get("sub"):
            raise ValueError("Nonce or subject mismatch")
        return claims
    except Exception as error:
        raise HTTPException(401, "Identity token verification failed") from error
