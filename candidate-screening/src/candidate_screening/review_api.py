from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .auth import recruiter_actor
from .review import ActivityPage, CompletedScreening, ReviewPage, ReviewQuery

router = APIRouter(prefix="/screening", tags=["recruiter review"])
Actor = Annotated[str, Depends(recruiter_actor)]


@router.get("/campaigns/{campaign_id}/invites", response_model=ActivityPage)
def campaign_invites(
    campaign_id: UUID,
    actor: Actor,
    request: Request,
    after: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    result = request.app.state.repo.list_invites(campaign_id, after, limit)
    if result is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return result


@router.get("/campaigns/{campaign_id}/results", response_model=ReviewPage)
def campaign_results(
    campaign_id: UUID, actor: Actor, request: Request, query: Annotated[ReviewQuery, Query()]
):
    try:
        result = request.app.state.repo.list_completed(campaign_id, query)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return result


@router.get("/summaries/{summary_id}", response_model=CompletedScreening)
def screening_summary(summary_id: UUID, actor: Actor, request: Request):
    result = request.app.state.repo.get_summary(summary_id)
    if result is None:
        raise HTTPException(status_code=404, detail="summary not found")
    return result
