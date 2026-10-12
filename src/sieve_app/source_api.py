"""Recruiter-controlled SharePoint folder preview and durable indexing requests."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, model_validator
from requests import RequestException

from talent_ranker.config import SETTINGS
from talent_ranker.identifiers import validate_candidate_id
from talent_ranker.sharepoint import FolderLink, configured_sharepoint_source

router = APIRouter(prefix="/api/sources/sharepoint", tags=["resume sources"])
bearer = HTTPBearer(auto_error=False)


def recruiter_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    settings = getattr(request.app.state, "screening_settings", None)
    if credentials is None:
        raise HTTPException(status_code=401, detail="recruiter bearer token required")
    actor = settings.recruiter_tokens.get(credentials.credentials) if settings else None
    if not actor:
        raise HTTPException(status_code=403, detail="recruiter token not authorized")
    return actor


Actor = Annotated[str, Depends(recruiter_actor)]


class FolderRequest(BaseModel):
    folder_url: str = Field(min_length=12, max_length=2000)


class AnalyzeFolder(FolderRequest):
    request_id: UUID


class SourceFile(BaseModel):
    file_id: str
    name: str
    size: int | None
    modified_at: str
    web_url: str = ""


class FolderPreview(BaseModel):
    folder_url: str
    files: list[SourceFile]


class IndexEntry(BaseModel):
    candidate_id: str
    object_id: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_candidate(self):
        self.candidate_id = validate_candidate_id(self.candidate_id)
        return self


class StartIndexing(FolderRequest):
    request_id: UUID
    entries: list[IndexEntry] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_mapping(self):
        if len({item.candidate_id for item in self.entries}) != len(self.entries):
            raise ValueError("candidate IDs must be unique")
        if len({item.object_id for item in self.entries}) != len(self.entries):
            raise ValueError("SharePoint file IDs must be unique")
        return self


class IndexingJob(BaseModel):
    id: UUID
    status: str
    requested: int
    discovered: int
    indexed: int
    skipped: int
    failures: list[str]
    proposals: list[IdentityProposal] = Field(default_factory=list)


class IdentityProposal(BaseModel):
    object_id: str
    file_name: str
    name: str | None
    email: str | None
    candidate_id: str | None
    suggestion: Literal["existing", "new", "review"]
    analysis_error: str | None = None
    job_title: str | None = None
    web_url: str = ""


class ReviewDecision(BaseModel):
    object_id: str
    action: Literal["existing", "new", "skip"]
    candidate_id: str | None = None
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    job_title: str | None = Field(default=None, max_length=120)


class ApproveIndexing(BaseModel):
    decisions: list[ReviewDecision]


def _job(row: dict) -> IndexingJob:
    return IndexingJob(
        id=row["id"], status=row["status"], requested=len(row["entries"]),
        discovered=row["discovered"], indexed=row["indexed"], skipped=row["skipped"],
        failures=row["failures"],
        proposals=[IdentityProposal.model_validate(item) for item in row["entries"]]
        if row["status"] == "awaiting_review" else [],
    )


def _folder_url(raw: str) -> str:
    link = FolderLink.parse(raw)
    from urllib.parse import quote

    return f"https://{link.hostname}{quote(link.folder_path, safe='/')}"


def _configured() -> None:
    if not all((SETTINGS.sharepoint_tenant_id, SETTINGS.sharepoint_client_id,
                SETTINGS.sharepoint_client_secret)):
        raise HTTPException(status_code=503, detail="SharePoint source is not configured")


@router.post("/preview", response_model=FolderPreview)
def preview_folder(details: FolderRequest, actor: Actor) -> FolderPreview:
    _configured()
    try:
        folder_url = _folder_url(details.folder_url)
        files = configured_sharepoint_source(SETTINGS).list_resumes(folder_url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RequestException as error:
        raise HTTPException(status_code=502, detail="Could not read the SharePoint folder") from error
    if len(files) > 1000:
        raise HTTPException(status_code=409, detail="Folder has more than 1000 resumes")
    return FolderPreview(
        folder_url=folder_url,
        files=[SourceFile(file_id=item.file_id, name=item.name, size=item.size,
                          modified_at=item.modified_time, web_url=item.web_url) for item in files],
    )


@router.post("/jobs", response_model=IndexingJob, status_code=202)
def start_indexing(details: StartIndexing, actor: Actor, request: Request) -> IndexingJob:
    _configured()
    try:
        folder_url = _folder_url(details.folder_url)
        row = request.app.state.index_store.submit(
            details.request_id, folder_url,
            [item.model_dump() for item in details.entries], actor,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _job(row)


@router.post("/analyze", response_model=IndexingJob, status_code=202)
def analyze_folder(details: AnalyzeFolder, actor: Actor, request: Request) -> IndexingJob:
    _configured()
    try:
        folder_url = _folder_url(details.folder_url)
        row = request.app.state.index_store.submit_analysis(
            details.request_id, folder_url, actor,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _job(row)


@router.post("/jobs/{job_id}/approve", response_model=IndexingJob, status_code=202)
def approve_indexing(
    job_id: UUID, details: ApproveIndexing, actor: Actor, request: Request,
) -> IndexingJob:
    try:
        row = request.app.state.index_store.approve(
            job_id, actor, [item.model_dump() for item in details.decisions],
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _job(row)


@router.get("/jobs/{job_id}", response_model=IndexingJob)
def get_indexing_job(job_id: UUID, actor: Actor, request: Request) -> IndexingJob:
    row = request.app.state.index_store.get(job_id, actor)
    if row is None:
        raise HTTPException(status_code=404, detail="indexing job not found")
    return _job(row)
