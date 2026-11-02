"""Locate the Google Drive connection owned by one recruiter."""

from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

from talent_ranker.config import SETTINGS


def token_file(actor: str) -> Path:
    return Path(SETTINGS.google_token_file).parent / "recruiter-drive" / f"{UUID(actor)}.json"


def require_token(actor: str) -> Path:
    path = token_file(actor)
    if not path.is_file():
        raise HTTPException(503, "Connect Google Drive for this recruiter account")
    return path
