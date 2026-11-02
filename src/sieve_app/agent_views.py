"""Read models for recruiter agent sessions and screening drafts."""

from .agent_schemas import AgentSession
from .agent_store import AgentStore


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
    ranking = store.ranking_job(row["id"]) if row["setup_stage"] == "ranking" else None
    return AgentSession.model_validate(
        {
            **row,
            "ranking_status": ranking["status"] if ranking else None,
            "messages": store.messages(row["id"]),
            "campaign": campaign_view(store.repository, campaign, screening_settings),
        }
    )
