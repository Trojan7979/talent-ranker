from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .agent_config import AgentConfigurationError
from .agent_runtime import RecruitmentAgentRuntime
from .agent_schemas import (
    AgentReply,
    AgentSession,
    ApproveAgentCampaign,
    CampaignAction,
    CreateAgentSession,
    SendAgentMessage,
)
from .agent_store import AgentStore

router = APIRouter(prefix="/api/agent", tags=["recruitment agent"])
bearer = HTTPBearer(auto_error=False)


def agent_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="recruiter bearer token required")
    settings = request.app.state.screening_settings
    actor = settings.recruiter_tokens.get(credentials.credentials) if settings else None
    if not actor:
        raise HTTPException(status_code=403, detail="recruiter token not authorized")
    return actor


Actor = Annotated[str, Depends(agent_actor)]


def services(request: Request):
    settings = request.app.state.agent_settings
    try:
        settings.require_ready()
    except AgentConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    screening_repo = request.app.state.screening_service.state.repo
    ranking_repo = request.app.state.ranking_service.state.pipeline.repo
    return settings, screening_repo, ranking_repo, AgentStore(screening_repo)


def campaign_view(repository, campaign: dict | None, screening_settings) -> dict | None:
    if campaign is None:
        return None
    candidate_ids = campaign["final_candidate_ids"] or campaign["proposed_candidate_ids"]
    config = repository.get_job_config(campaign["config_id"])
    activity = repository.list_invites(campaign["id"], None, 100)
    delivery_counts: dict[str, int] = {}
    for item in (activity or {}).get("items", []):
        status = item["delivery_status"]
        delivery_counts[status] = delivery_counts.get(status, 0) + 1
    return {
        **campaign,
        "recipients": repository.lookup_contacts(candidate_ids),
        "questions": config["questions"] if config else None,
        "sender": {
            "backend": screening_settings.sender_backend,
            "email": screening_settings.gmail_sender_email or screening_settings.smtp_from_email,
        },
        "delivery": {
            "counts": delivery_counts,
            "items": (activity or {}).get("items", []),
        },
    }


def view(store: AgentStore, row: dict, screening_settings) -> AgentSession:
    campaign = store.repository.get_campaign(row["campaign_id"]) if row["campaign_id"] else None
    return AgentSession.model_validate(
        {
            **row,
            "messages": store.messages(row["id"]),
            "campaign": campaign_view(store.repository, campaign, screening_settings),
        }
    )


@router.post("/sessions", response_model=AgentSession, status_code=201)
def create_session(details: CreateAgentSession, actor: Actor, request: Request):
    settings, screening_repo, _, store = services(request)
    if details.job_id not in settings.allowed_job_ids(actor):
        raise HTTPException(status_code=403, detail="job is not available to this recruiter")
    run = screening_repo.resolve_run(details.job_id, details.ranking_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="saved ranking run not found for job")
    row = store.create_session(settings.workspace_id, actor, details.job_id, run["run_id"])
    return view(store, row, request.app.state.screening_settings)


@router.get("/sessions/{session_id}", response_model=AgentSession)
def get_session(session_id: UUID, actor: Actor, request: Request):
    settings, _, _, store = services(request)
    row = store.get_session(session_id, settings.workspace_id, actor)
    if row is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    return view(store, row, request.app.state.screening_settings)


@router.post("/sessions/{session_id}/messages", response_model=AgentReply)
def send_message(session_id: UUID, details: SendAgentMessage, actor: Actor, request: Request):
    settings, screening_repo, ranking_repo, store = services(request)
    row = store.get_session(session_id, settings.workspace_id, actor)
    if row is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    store.add_message(session_id, "user", details.content.strip())
    history = [
        {"role": item["role"], "content": item["content"]} for item in store.messages(session_id)
    ]
    try:
        answer = RecruitmentAgentRuntime(settings, screening_repo, ranking_repo, store).invoke(
            row, actor, history
        )
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    store.add_message(session_id, "assistant", answer)
    row = store.get_session(session_id, settings.workspace_id, actor)
    campaign = screening_repo.get_campaign(row["campaign_id"]) if row["campaign_id"] else None
    return AgentReply(
        session=view(store, row, request.app.state.screening_settings),
        answer=answer,
        campaign=campaign_view(screening_repo, campaign, request.app.state.screening_settings),
    )


@router.post("/sessions/{session_id}/approve", response_model=CampaignAction)
def approve_campaign(
    session_id: UUID, details: ApproveAgentCampaign, actor: Actor, request: Request
):
    settings, screening_repo, _, store = services(request)
    row = store.get_session(session_id, settings.workspace_id, actor)
    if row is None or row["campaign_id"] is None:
        raise HTTPException(status_code=404, detail="pending campaign not found")
    campaign = screening_repo.get_campaign(row["campaign_id"])
    if campaign is None or campaign["job_id"] not in settings.allowed_job_ids(actor):
        raise HTTPException(status_code=404, detail="pending campaign not found")
    try:
        approved = screening_repo.approve_campaign(
            campaign["id"],
            details.expected_revision,
            actor,
            request.app.state.screening_settings.public_base_url,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return CampaignAction(
        campaign=campaign_view(screening_repo, approved, request.app.state.screening_settings)
    )
