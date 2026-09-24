from fastapi import APIRouter, HTTPException, Request

from .candidate_schemas import (
    CandidateQuestions,
    CompletionResponse,
    DraftResponse,
    InviteView,
    SaveAnswersRequest,
)
from .questions import JobQuestions

router = APIRouter(prefix="/screening/invites", tags=["candidate screening"])


def _visible(row: dict | None) -> dict:
    if row is None:
        raise HTTPException(status_code=404, detail="screening link not found")
    if row["status"] == "expired":
        raise HTTPException(status_code=410, detail="screening link expired")
    if row["status"] is None:
        raise HTTPException(status_code=409, detail="screening link not yet sent")
    return row


def _view(row: dict) -> InviteView:
    return InviteView(
        id=row["id"],
        campaign_id=row["campaign_id"],
        job_id=row["job_id"],
        status=row["status"],
        expires_at=row["expires_at"],
        opened_at=row["opened_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        questions=CandidateQuestions.from_config(
            JobQuestions.model_validate(row["config_snapshot"])
        ),
    )


@router.get("/{token}", response_model=InviteView)
def read_invite(token: str, request: Request):
    return _view(_visible(request.app.state.repo.get_invite(token)))


def _event(token: str, target: str, request: Request) -> InviteView:
    try:
        row = request.app.state.repo.record_invite_event(token, target)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _view(_visible(row))


@router.post("/{token}/opened", response_model=InviteView)
def opened(token: str, request: Request):
    return _event(token, "opened", request)


@router.post("/{token}/started", response_model=InviteView)
def started(token: str, request: Request):
    return _event(token, "started", request)


@router.post("/{token}/decline", response_model=InviteView)
def declined(token: str, request: Request):
    return _event(token, "declined", request)


@router.put("/{token}/responses", response_model=DraftResponse)
def save_responses(token: str, details: SaveAnswersRequest, request: Request):
    try:
        result = request.app.state.repo.save_draft(
            token, details.answers, details.expected_revision
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="screening link not found")
    invite, draft = result
    _visible(invite)
    if draft is None:
        raise HTTPException(status_code=409, detail="screening is not started")
    return draft


@router.post("/{token}/complete", response_model=CompletionResponse)
def complete(token: str, details: SaveAnswersRequest, request: Request):
    try:
        result = request.app.state.repo.complete_invite(
            token, details.answers, details.expected_revision
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="screening link not found")
    invite, summary = result
    _visible(invite)
    if summary is None:
        raise HTTPException(status_code=409, detail="screening is not started")
    return summary
