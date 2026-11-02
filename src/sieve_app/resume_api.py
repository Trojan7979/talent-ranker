"""Authenticated access to source originals; no document content is proxied."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from googleapiclient.errors import HttpError
from pydantic import BaseModel
from requests import HTTPError, RequestException

from talent_ranker.config import SETTINGS
from talent_ranker.drive_source import configured_drive_source
from talent_ranker.identifiers import validate_candidate_id
from talent_ranker.sharepoint import configured_sharepoint_source
from talent_ranker.storage import DriveConnectionError

from .drive_account import require_token
from .source_access import require_candidate_access
from .source_api import Actor, _configured

router = APIRouter(prefix="/api/sources", tags=["resume sources"])


class ResumeSource(BaseModel):
    file_name: str
    web_url: str
    modified_at: str
    source_status: Literal["unchanged", "changed", "unknown"]


@router.get("/candidates/{candidate_id}/resume", response_model=ResumeSource)
def get_resume_source(candidate_id: str, actor: Actor, request: Request,
                      response: Response) -> ResumeSource:
    try:
        candidate_id = validate_candidate_id(candidate_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    require_candidate_access(request, actor, [candidate_id])
    row = request.app.state.index_store.get_candidate_source(candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate resume not found")
    source_uri = row["source_uri"]
    if source_uri.startswith("sharepoint://"):
        _configured()
        source = configured_sharepoint_source(SETTINGS)
    elif source_uri.startswith("gdrive://"):
        try:
            source = configured_drive_source(interactive=False, token_file=require_token(actor))
        except DriveConnectionError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
    else:
        raise HTTPException(status_code=404, detail="No connected source is linked to this resume")
    try:
        file = source.get_file(source_uri)
        if not file.web_url:
            raise ValueError("No browser link")
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status in (403, 404, 410):
            raise HTTPException(
                status_code=404,
                detail="The source resume is unavailable or access was removed",
            ) from error
        raise HTTPException(status_code=502, detail="Could not reach the source; try again") from error
    except (RequestException, ValueError) as error:
        raise HTTPException(status_code=502, detail="Could not resolve the source resume") from error
    except HttpError as error:
        raise HTTPException(status_code=502, detail="Could not reach Google Drive") from error
    status = "unknown"
    if row.get("source_etag") and file.etag:
        status = "unchanged" if row["source_etag"] == file.etag else "changed"
    response.headers["Cache-Control"] = "no-store"
    return ResumeSource(file_name=file.name, web_url=file.web_url,
                        modified_at=file.modified_time, source_status=status)
