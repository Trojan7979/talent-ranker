"""Apply indexed-source grants to recruiter-facing candidate reads."""

from fastapi import HTTPException, Request

from talent_ranker.access import RecruiterScope


def require_candidate_access(request: Request, actor: str, candidate_ids: list[str]) -> None:
    ranking = getattr(request.app.state, "ranking_service", None)
    repo = getattr(getattr(ranking, "state", None), "pipeline", None)
    repo = getattr(repo, "repo", None)
    if repo is None:
        raise HTTPException(503, "candidate access is unavailable")
    workspace = request.app.state.agent_settings.workspace_id
    scope = RecruiterScope(workspace, actor, frozenset())
    if repo.accessible_candidate_ids(candidate_ids, scope) != set(candidate_ids):
        raise HTTPException(404, "candidate not found")
