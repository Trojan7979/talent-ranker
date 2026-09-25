"""Recruiter-triggered, campaign-scoped initial email dispatch."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

from .auth import recruiter_actor
from .delivery import InitialInviteDispatcher
from .sender_factory import create_sender

router = APIRouter(prefix="/screening", tags=["screening delivery"])
Actor = Annotated[str, Depends(recruiter_actor)]


class DispatchAccepted(BaseModel):
    campaign_id: UUID
    status: Literal["scheduled"] = "scheduled"


@router.post("/campaigns/{campaign_id}/dispatch", response_model=DispatchAccepted, status_code=202)
def dispatch_campaign(
    campaign_id: UUID,
    background_tasks: BackgroundTasks,
    actor: Actor,
    request: Request,
) -> DispatchAccepted:
    campaign = request.app.state.repo.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    if campaign["status"] != "approved":
        raise HTTPException(status_code=409, detail="campaign must be approved before dispatch")
    try:
        sender = create_sender(request.app.state.settings)
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    dispatcher = InitialInviteDispatcher(request.app.state.repo, sender)
    background_tasks.add_task(
        dispatcher.run_campaign, campaign_id, request.app.state.settings.max_campaign_size
    )
    return DispatchAccepted(campaign_id=campaign_id)
