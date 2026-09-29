"""Recruiter-only control and status for the optional campaign observer."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .auth import recruiter_actor

router = APIRouter(prefix="/screening/campaigns", tags=["campaign workflow"])
Actor = Annotated[str, Depends(recruiter_actor)]


class WorkflowStatus(BaseModel):
    campaign_id: UUID
    campaign_status: str
    revision: int
    workflow_status: Literal["waiting_for_recruiter", "observed"]


def workflow(request: Request):
    coordinator = getattr(request.app.state, "workflow", None)
    if coordinator is None:
        raise HTTPException(status_code=503, detail="campaign workflow is disabled")
    return coordinator


@router.post("/{campaign_id}/workflow/sync", response_model=WorkflowStatus)
def sync_campaign(campaign_id: UUID, actor: Actor, request: Request):
    try:
        return workflow(request).sync(campaign_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/{campaign_id}/workflow", response_model=WorkflowStatus)
def campaign_workflow(campaign_id: UUID, actor: Actor, request: Request):
    if request.app.state.repo.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    try:
        return workflow(request).status(campaign_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
