"""Resolve a recruiter scope for local CLI operations."""

from sieve_app.agent_config import AgentSettings
from sieve_app.recruiter_identity import IdentitySettings, RecruiterIdentity

from .access import RecruiterScope


def cli_scope(actor_id: str | None) -> RecruiterScope:
    settings = AgentSettings()
    if actor_id is None:
        raise ValueError("specify --actor-id with a signed-in recruiter ID")
    jobs = RecruiterIdentity(IdentitySettings()).jobs(actor_id, settings.workspace_id)
    if not jobs:
        raise ValueError("recruiter has no job grants in the agent workspace")
    return RecruiterScope(
        settings.workspace_id, actor_id, jobs
    )
