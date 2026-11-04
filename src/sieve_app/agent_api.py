import logging
from typing import Annotated
from uuid import UUID

from candidate_screening.campaigns import CreateCampaignRequest
from candidate_screening.delivery import InitialInviteDispatcher
from candidate_screening.pipeline import ScreeningPipeline
from candidate_screening.selection import TopN
from candidate_screening.sender_factory import create_sender
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from psycopg.errors import UniqueViolation

from .agent_config import AgentConfigurationError
from .agent_reranking import AgentRerankingWorkflow
from .agent_role_workflow import AgentRoleWorkflow
from .agent_runtime import RecruitmentAgentRuntime
from .agent_schemas import (
    AgentReply,
    AgentSession,
    AgentSessionSummary,
    ApproveAgentCampaign,
    ApproveAgentQuestions,
    CampaignAction,
    CreateAgentSession,
    DispatchAction,
    SendAgentMessage,
)
from .agent_screening_workflow import AgentScreeningWorkflow
from .agent_store import AgentStore
from .agent_views import campaign_view, view
from .recruiter_identity import actor_for

router = APIRouter(prefix="/api/agent", tags=["recruitment agent"])
logger = logging.getLogger(__name__)


def agent_actor(
    request: Request,
) -> str:
    return actor_for(request)


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


@router.get("/jobs")
def available_jobs(actor: Actor, request: Request) -> dict[str, list[str]]:
    settings, _, _, _ = services(request)
    return {"job_ids": sorted(request.app.state.recruiter_identity.jobs(actor, settings.workspace_id))}


@router.post("/sessions", response_model=AgentSession, status_code=201)
def create_session(details: CreateAgentSession, actor: Actor, request: Request):
    settings, screening_repo, ranking_repo, store = services(request)
    if details.use_saved_run and details.job_id is None:
        raise HTTPException(status_code=422, detail="choose a role to use a saved ranking run")
    if details.job_id is not None and details.job_id not in request.app.state.recruiter_identity.jobs(actor, settings.workspace_id):
        raise HTTPException(status_code=403, detail="job is not available to this recruiter")
    run = None
    if details.use_saved_run:
        run_id = details.ranking_run_id
        if run_id is None:
            runs = ranking_repo.list_saved_runs(
                details.job_id, None, None, 1, [details.job_id],
                settings.workspace_id, actor,
            )["items"]
            run_id = runs[0]["run_id"] if runs else None
        if run_id is None or ranking_repo.get_saved_run(
            str(run_id), 0, 1, settings.workspace_id, actor
        ) is None:
            raise HTTPException(status_code=404, detail="saved ranking run not found for recruiter")
        run = screening_repo.resolve_run(details.job_id, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="saved ranking run not found for job")
    row = store.create_session(settings.workspace_id, actor, details.job_id, run["run_id"] if run else None)
    if run is None:
        store.add_message(row["id"], "assistant", "Tell me about the role. Paste a job description and I'll extract hiring criteria for your review, or say 'Write a JD for...' with the role, responsibilities, and key requirements. Ranking starts only after you approve the criteria.")
        row = store.get_session(row["id"], settings.workspace_id, actor)
    return view(store, row, request.app.state.screening_settings)


@router.get("/sessions", response_model=list[AgentSessionSummary])
def list_sessions(actor: Actor, request: Request):
    settings, _, _, store = services(request)
    return store.list_sessions(settings.workspace_id, actor, sorted(request.app.state.recruiter_identity.jobs(actor, settings.workspace_id)))


@router.get("/sessions/{session_id}", response_model=AgentSession)
def get_session(session_id: UUID, actor: Actor, request: Request):
    settings, _, _, store = services(request)
    row = store.get_session(session_id, settings.workspace_id, actor)
    if row is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    if row["job_id"] is not None and row["job_id"] not in request.app.state.recruiter_identity.jobs(actor, settings.workspace_id):
        raise HTTPException(status_code=403, detail="job is not available to this recruiter")
    return view(store, row, request.app.state.screening_settings)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: UUID, actor: Actor, request: Request) -> None:
    settings, _, _, store = services(request)
    if not store.delete_session(session_id, settings.workspace_id, actor):
        raise HTTPException(status_code=404, detail="agent session not found")


@router.post("/sessions/{session_id}/messages", response_model=AgentReply)
def send_message(session_id: UUID, details: SendAgentMessage, actor: Actor, request: Request):
    settings, screening_repo, ranking_repo, store = services(request)
    row = store.get_session(session_id, settings.workspace_id, actor)
    if row is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    if row["job_id"] is not None and row["job_id"] not in request.app.state.recruiter_identity.jobs(actor, settings.workspace_id):
        raise HTTPException(status_code=403, detail="job is not available to this recruiter")
    store.add_message(session_id, "user", details.content.strip())
    history = [
        {"role": item["role"], "content": item["content"]} for item in store.messages(session_id)
    ]
    try:
        if row["setup_stage"] != "ranked":
            answer = AgentRoleWorkflow(
                settings, request.app.state.ranking_service.state.pipeline, store
            ).handle(row, actor, details.content)
        elif AgentRerankingWorkflow.is_request(details.content):
            answer = AgentRerankingWorkflow(store).handle(row, details.content)
        elif AgentScreeningWorkflow.is_draft_request(details.content):
            answer = AgentScreeningWorkflow(
                screening_repo, store, settings.max_recipients
            ).draft(row, details.content)
        else:
            answer = RecruitmentAgentRuntime(settings, screening_repo, ranking_repo, store, request.app.state.recruiter_identity.jobs(actor, settings.workspace_id)).invoke(
                row, actor, history
            )
    except (LookupError, ValueError) as error:
        store.add_message(session_id, "assistant", f"I could not complete that request: {error}")
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PermissionError as error:
        store.add_message(session_id, "assistant", "I cannot access that job or action with this account.")
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        logger.exception("Agent message failed in session %s", session_id)
        store.add_message(session_id, "assistant", "I could not complete that request. Your conversation is saved; please retry or ask for a narrower step.")
        raise HTTPException(status_code=503, detail="Agent request failed; conversation is saved") from error
    store.add_message(session_id, "assistant", answer)
    row = store.get_session(session_id, settings.workspace_id, actor)
    campaign = screening_repo.get_campaign(row["campaign_id"]) if row["campaign_id"] else None
    return AgentReply(
        session=view(store, row, request.app.state.screening_settings),
        answer=answer,
        campaign=campaign_view(screening_repo, campaign, request.app.state.screening_settings),
    )


@router.post("/sessions/{session_id}/questions/approve", response_model=AgentSession)
def approve_questions(
    session_id: UUID, details: ApproveAgentQuestions, actor: Actor, request: Request
):
    settings, screening_repo, _, store = services(request)
    row = store.get_session(session_id, settings.workspace_id, actor)
    if row is None or row["job_id"] not in request.app.state.recruiter_identity.jobs(actor, settings.workspace_id):
        raise HTTPException(status_code=404, detail="question draft not found")
    try:
        config_id, top_n = store.approve_questions(session_id, details.expected_revision, actor)
        if row["campaign_id"] is None:
            existing = store.campaign_for_question_config(config_id)
            if existing is None:
                campaign = ScreeningPipeline(screening_repo, settings.max_recipients).propose(
                    CreateCampaignRequest(
                        job_id=row["job_id"], ranking_run_id=row["ranking_run_id"],
                        config_id=config_id, rule=TopN(kind="top_n", value=top_n),
                        message_template="You have been invited to complete a screening form: {screening_link}",
                        expiry_hours=48,
                    )
                )
                store.set_campaign(session_id, campaign["id"])
            else:
                store.set_campaign(session_id, existing["id"])
            store.add_message(session_id, "assistant", "Questions approved. Review the proposed recipients, contact addresses, and questions before approving any invitations.")
    except UniqueViolation as error:
        raise HTTPException(status_code=409, detail="question version changed; draft again") from error
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return view(store, store.get_session(session_id, settings.workspace_id, actor), request.app.state.screening_settings)


@router.post("/sessions/{session_id}/approve", response_model=CampaignAction)
def approve_campaign(
    session_id: UUID, details: ApproveAgentCampaign, actor: Actor, request: Request
):
    settings, screening_repo, _, store = services(request)
    row = store.get_session(session_id, settings.workspace_id, actor)
    if row is None or row["campaign_id"] is None:
        raise HTTPException(status_code=404, detail="pending campaign not found")
    campaign = screening_repo.get_campaign(row["campaign_id"])
    if campaign is None or campaign["job_id"] not in request.app.state.recruiter_identity.jobs(actor, settings.workspace_id):
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


@router.post("/sessions/{session_id}/dispatch", response_model=DispatchAction, status_code=202)
def dispatch_campaign(
    session_id: UUID, background_tasks: BackgroundTasks, actor: Actor, request: Request
):
    settings, screening_repo, _, store = services(request)
    row = store.get_session(session_id, settings.workspace_id, actor)
    if row is None or row["campaign_id"] is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    campaign = screening_repo.get_campaign(row["campaign_id"])
    if campaign is None or campaign["job_id"] not in request.app.state.recruiter_identity.jobs(actor, settings.workspace_id):
        raise HTTPException(status_code=404, detail="campaign not found")
    if campaign["status"] != "approved":
        raise HTTPException(status_code=409, detail="campaign must be approved before dispatch")
    try:
        sender = create_sender(request.app.state.screening_settings)
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    dispatcher = InitialInviteDispatcher(screening_repo, sender)
    background_tasks.add_task(
        dispatcher.run_campaign,
        campaign["id"],
        request.app.state.screening_settings.max_campaign_size,
    )
    return DispatchAction(campaign_id=campaign["id"])
