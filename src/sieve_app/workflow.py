"""Read-only campaign coordination; domain tables remain the source of truth."""

from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class CampaignState(TypedDict):
    campaign_id: str
    status: str
    revision: int


class CampaignWorkflow:
    def __init__(self, repository, checkpointer):
        self.repository = repository
        builder = StateGraph(CampaignState)
        builder.add_node("inspect", self._inspect)
        builder.add_node("await_decision", self._await_decision)
        builder.add_edge(START, "inspect")
        builder.add_conditional_edges(
            "inspect", lambda state: "await_decision" if state["status"] == "proposed" else END
        )
        builder.add_edge("await_decision", "inspect")
        self.graph = builder.compile(checkpointer=checkpointer)

    def _inspect(self, state: CampaignState) -> dict:
        campaign = self.repository.get_campaign(UUID(state["campaign_id"]))
        if campaign is None:
            raise LookupError("campaign not found")
        return {"status": campaign["status"], "revision": campaign["revision"]}

    @staticmethod
    def _await_decision(state: CampaignState) -> dict:
        interrupt({"campaign_id": state["campaign_id"], "revision": state["revision"]})
        return {}

    def sync(self, campaign_id: UUID) -> dict:
        """Re-read the domain campaign when starting or resuming a checkpoint."""
        config = {"configurable": {"thread_id": f"campaign:{campaign_id}"}}
        snapshot = self.graph.get_state(config)
        if not snapshot.values:
            self.graph.invoke({"campaign_id": str(campaign_id)}, config)
        elif snapshot.next:
            self.graph.invoke(Command(resume=True), config)
        return self.status(campaign_id)

    def status(self, campaign_id: UUID) -> dict:
        snapshot = self.graph.get_state(
            {"configurable": {"thread_id": f"campaign:{campaign_id}"}}
        )
        if not snapshot.values:
            raise LookupError("workflow not started")
        return {
            "campaign_id": campaign_id,
            "campaign_status": snapshot.values["status"],
            "revision": snapshot.values["revision"],
            "workflow_status": "waiting_for_recruiter" if snapshot.next else "observed",
        }
