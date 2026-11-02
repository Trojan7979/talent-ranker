"""Recruiter access for the ranking HTTP API."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request


@dataclass(frozen=True)
class RecruiterScope:
    workspace_id: str
    actor_id: str
    allowed_jobs: frozenset[str]


def ranking_actor(
    request: Request,
) -> RecruiterScope:
    identity = getattr(request.app.state, "recruiter_identity", None)
    workspace_id = getattr(request.app.state, "ranking_workspace_id", None)
    if identity is None or not workspace_id:
        raise HTTPException(503, "ranking access is not configured")
    actor = identity.actor(request)
    return RecruiterScope(workspace_id, actor, identity.jobs(actor, workspace_id))


RankingActor = Annotated[RecruiterScope, Depends(ranking_actor)]


def require_job(job_id: str, access: RecruiterScope) -> None:
    if job_id not in access.allowed_jobs:
        raise HTTPException(404, "job not found")
