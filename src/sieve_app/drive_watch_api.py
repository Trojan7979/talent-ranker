"""Recruiter-scoped Drive watch registration and persistent alert inbox."""

from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Request
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field

from talent_ranker.drive_source import configured_drive_source
from talent_ranker.storage import DriveConnectionError

from .agent_api import Actor
from .drive_account import require_token
from .drive_api import _drive_location
from .drive_watch import DriveWatchStore
from .drive_watch_schedule import next_scan_at

router = APIRouter(prefix="/api/agent/drive-watch", tags=["recruitment agent"])


class WatchFolder(BaseModel):
    folder_url: str = Field(min_length=12, max_length=2000)
    schedule: Literal["instant", "daily", "weekends"] = "instant"
    time_zone: str = Field(default="UTC", min_length=1, max_length=100)


def store(request: Request) -> DriveWatchStore:
    return DriveWatchStore(request.app.state.index_store.pool)


@router.post("/folders", status_code=201)
def watch_folder(details: WatchFolder, actor: Actor, request: Request):
    try:
        ZoneInfo(details.time_zone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Invalid time zone") from error
    token_path = require_token(actor)
    try:
        folder = _drive_location(details.folder_url)
        if "/folders/" not in folder:
            raise ValueError("Select a Google Drive folder, not one file")
        workspace = request.app.state.agent_settings.workspace_id
        now = datetime.now(UTC)
        next_due = now if details.schedule == "instant" else next_scan_at(
            details.schedule, details.time_zone, now,
        )
        watch_store = store(request)
        existing = watch_store.set_schedule(
            workspace, actor, folder, details.schedule, details.time_zone, next_due,
        )
        if existing:
            return existing
        files = configured_drive_source(interactive=False, token_file=token_path).list_resumes(folder)
    except DriveConnectionError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (HttpError, OSError) as error:
        raise HTTPException(status_code=502, detail="Could not read the Google Drive folder") from error
    if len(files) > 1000:
        raise HTTPException(status_code=409, detail="Folder has more than 1000 resumes")
    return watch_store.register(
        workspace, actor, folder, files, details.schedule, details.time_zone, next_due,
    )


@router.get("/inbox")
def watch_inbox(actor: Actor, request: Request):
    workspace = request.app.state.agent_settings.workspace_id
    return store(request).inbox(workspace, actor)


@router.post("/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: int, actor: Actor, request: Request):
    workspace = request.app.state.agent_settings.workspace_id
    if not store(request).dismiss(alert_id, workspace, actor):
        raise HTTPException(status_code=404, detail="alert not found")
    return {"dismissed": True}
