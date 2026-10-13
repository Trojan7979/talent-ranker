import json
from uuid import UUID

from candidate_screening.campaigns import CreateCampaignRequest
from candidate_screening.pipeline import ScreeningPipeline
from candidate_screening.selection import SelectionRequest, TopN
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from .agent_config import AgentSettings

SYSTEM_PROMPT = """You are the Recruitment Agent. Use tools for every claim about jobs,
candidates, ranking runs, or campaigns. Work only within the supplied job context. For a request
to screen candidates, preview the requested number, then prepare a campaign. Preparing creates a
draft only: clearly state that recruiter approval is required before invitations are queued.
Never claim an email was sent from a proposed or merely approved campaign. Keep answers concise."""


class RecruitmentAgentRuntime:
    def __init__(self, settings: AgentSettings, screening_repo, ranking_repo, store):
        self.settings = settings
        self.screening_repo = screening_repo
        self.ranking_repo = ranking_repo
        self.store = store

    def invoke(self, session: dict, actor: str, history: list[dict]) -> str:
        allowed = self.settings.allowed_job_ids(actor)
        job_id = session["job_id"]
        if job_id not in allowed:
            raise PermissionError("job is not available to this recruiter")

        def ensure_job(requested: str) -> None:
            if requested != job_id or requested not in allowed:
                raise ValueError("tool request is outside the active job")

        @tool
        def list_saved_runs(requested_job_id: str) -> str:
            """List recent saved ranking runs for the active job."""
            ensure_job(requested_job_id)
            result = self.ranking_repo.list_saved_runs(requested_job_id, None, None, 10)
            return json.dumps(result, default=str)

        @tool
        def preview_candidates(requested_job_id: str, ranking_run_id: str, top_n: int) -> str:
            """Preview the top N candidates from a saved ranking run without changing data."""
            ensure_job(requested_job_id)
            top_n = min(max(top_n, 1), self.settings.max_recipients)
            result = ScreeningPipeline(self.screening_repo, self.settings.max_recipients).preview(
                SelectionRequest(
                    job_id=requested_job_id,
                    ranking_run_id=UUID(ranking_run_id),
                    rule=TopN(kind="top_n", value=top_n),
                )
            )
            return result.model_dump_json()

        @tool
        def prepare_screening_campaign(
            requested_job_id: str, ranking_run_id: str, top_n: int
        ) -> str:
            """Create one draft screening campaign for top candidates; never approves or sends."""
            ensure_job(requested_job_id)
            if session.get("campaign_id"):
                campaign = self.screening_repo.get_campaign(session["campaign_id"])
                return json.dumps(campaign, default=str)
            top_n = min(max(top_n, 1), self.settings.max_recipients)
            config = self.screening_repo.latest_job_config(requested_job_id)
            if config is None:
                raise ValueError("screening configuration is missing for this job")
            campaign = ScreeningPipeline(self.screening_repo, self.settings.max_recipients).propose(
                CreateCampaignRequest(
                    job_id=requested_job_id,
                    ranking_run_id=UUID(ranking_run_id),
                    config_id=config["id"],
                    rule=TopN(kind="top_n", value=top_n),
                    message_template=(
                        "You have been invited to complete a screening form: {screening_link}"
                    ),
                    expiry_hours=48,
                )
            )
            self.store.set_campaign(session["id"], campaign["id"])
            session["campaign_id"] = campaign["id"]
            return json.dumps(campaign, default=str)

        @tool
        def get_campaign_status(campaign_id: str) -> str:
            """Read the current campaign and invitation delivery states."""
            campaign = self.screening_repo.get_campaign(UUID(campaign_id))
            if campaign is None:
                raise ValueError("campaign not found")
            ensure_job(campaign["job_id"])
            activity = self.screening_repo.list_invites(UUID(campaign_id), None, 100)
            return json.dumps({"campaign": campaign, "activity": activity}, default=str)

        model = ChatOpenAI(
            model=self.settings.model,
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
            timeout=self.settings.model_timeout_seconds,
            max_retries=self.settings.max_retries,
            temperature=0,
        )
        agent = create_agent(
            model,
            [list_saved_runs, preview_candidates, prepare_screening_campaign, get_campaign_status],
            system_prompt=SYSTEM_PROMPT
            + f"\nActive job_id: {job_id}. Preferred saved run: {session.get('ranking_run_id')}.",
        )
        result = agent.invoke({"messages": history})
        content = result["messages"][-1].content
        if isinstance(content, str):
            return content.strip()
        return json.dumps(content, default=str)
