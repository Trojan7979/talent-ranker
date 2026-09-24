from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .auth import recruiter_actor
from .export import ExportRequest, build_workbook
from .review import ActivityPage, CompletedScreening, ReviewPage, ReviewQuery

router = APIRouter(prefix="/screening", tags=["recruiter review"])
Actor = Annotated[str, Depends(recruiter_actor)]


@router.post("/campaigns/{campaign_id}/exports")
def export_campaign_results(
    campaign_id: UUID, details: ExportRequest, actor: Actor, request: Request
) -> Response:
    try:
        rows = request.app.state.repo.export_completed(campaign_id, details.candidate_ids)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if rows is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return Response(
        content=build_workbook(rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="screening-{campaign_id}.xlsx"'},
    )


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
