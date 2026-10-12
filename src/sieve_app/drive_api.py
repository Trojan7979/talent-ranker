"""Recruiter-controlled Google Drive resume preview and indexing requests."""

import hashlib
import json
import secrets
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field

from talent_ranker.config import SETTINGS
from talent_ranker.drive_links import drive_id
from talent_ranker.drive_source import configured_drive_source

from .drive_web_oauth import DriveWebOAuth
from .source_api import (
    Actor,
    ApproveIndexing,
    FolderPreview,
    IndexingJob,
    SourceFile,
    _job,
    approve_indexing,
    get_indexing_job,
)

router = APIRouter(prefix="/api/sources/drive", tags=["resume sources"])
COOKIE = "sieve_drive_oauth"


class DriveRequest(BaseModel):
    location: str = Field(min_length=12, max_length=2000)


class AnalyzeDrive(DriveRequest):
    request_id: UUID


def _drive_location(value: str) -> str:
    kind = "file" if "/file/d/" in value else "folder"
    file_id = drive_id(value, kind)
    return (f"https://drive.google.com/file/d/{file_id}/view" if kind == "file" else
            f"https://drive.google.com/drive/folders/{file_id}")


def _drive_ready() -> None:
    if not Path(SETTINGS.google_token_file).is_file():
        raise HTTPException(status_code=503, detail="Connect Google Drive on this page first")


@router.get("/connection")
def drive_connection(actor: Actor) -> dict[str, bool]:
    try:
        token = json.loads(Path(SETTINGS.google_token_file).read_text(encoding="utf-8"))
        connected = bool(token.get("refresh_token"))
    except (OSError, ValueError, AttributeError):
        connected = False
    return {"connected": connected}


@router.post("/connect")
def connect_drive(actor: Actor, request: Request, response: Response) -> dict[str, str]:
    state, verifier, nonce = (secrets.token_urlsafe(size) for size in (32, 64, 32))
    try:
        url = DriveWebOAuth(SETTINGS).authorization_url(state, verifier, nonce)
    except (ValueError, ImportError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    request.app.state.index_store.save_drive_oauth_state(
        hashlib.sha256(state.encode()).hexdigest(), actor, verifier, nonce,
    )
    response.set_cookie(
        COOKIE, state, max_age=600, httponly=True, samesite="lax",
        secure=SETTINGS.google_web_redirect_uri.startswith("https://"),
        path="/api/sources/drive/oauth",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authorization_url": url}


@router.get("/oauth/callback")
def drive_callback(request: Request, state: str, code: str | None = None,
                   error: str | None = None):
    if not secrets.compare_digest(request.cookies.get(COOKIE, ""), state):
        raise HTTPException(status_code=400, detail="Drive connection did not match this browser")
    saved = request.app.state.index_store.consume_drive_oauth_state(
        hashlib.sha256(state.encode()).hexdigest(),
    )
    if saved is None:
        raise HTTPException(status_code=400, detail="Drive connection link was already used or expired; start again")
    if error:
        raise HTTPException(status_code=400, detail="Google did not grant Drive access; start again")
    if not code:
        raise HTTPException(status_code=400, detail="Google returned without an authorization code; start again")
    try:
        DriveWebOAuth(SETTINGS).complete(state, saved["code_verifier"], saved["nonce"], code)
    except (ValueError, OSError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    url = f"{SETTINGS.frontend_base_url.rstrip('/')}/sources?source=drive&drive=connected"
    response = RedirectResponse(url, status_code=303, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
    })
    response.delete_cookie(COOKIE, path="/api/sources/drive/oauth")
    return response


@router.post("/preview", response_model=FolderPreview)
def preview_drive(details: DriveRequest, actor: Actor) -> FolderPreview:
    _drive_ready()
    try:
        location = _drive_location(details.location)
        files = configured_drive_source().list_resumes(location)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except HttpError as error:
        raise HTTPException(status_code=502, detail="Could not read the Google Drive location") from error
    if len(files) > 1000:
        raise HTTPException(status_code=409, detail="Location has more than 1000 resumes")
    return FolderPreview(folder_url=location, files=[
        SourceFile(file_id=item.file_id, name=item.name, size=item.size,
                   modified_at=item.modified_time, web_url=item.web_url) for item in files
    ])


@router.post("/analyze", response_model=IndexingJob, status_code=202)
def analyze_drive(details: AnalyzeDrive, actor: Actor, request: Request) -> IndexingJob:
    _drive_ready()
    try:
        row = request.app.state.index_store.submit_analysis(
            details.request_id, _drive_location(details.location), actor,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _job(row)


@router.post("/jobs/{job_id}/approve", response_model=IndexingJob, status_code=202)
def approve_drive(job_id: UUID, details: ApproveIndexing, actor: Actor,
                  request: Request) -> IndexingJob:
    return approve_indexing(job_id, details, actor, request)


@router.get("/jobs/{job_id}", response_model=IndexingJob)
def get_drive_job(job_id: UUID, actor: Actor, request: Request) -> IndexingJob:
    return get_indexing_job(job_id, actor, request)
