from fastapi import HTTPException, Request


async def recruiter_actor(
    request: Request,
) -> str:
    identity = getattr(request.app.state, "recruiter_identity", None)
    if identity is None:
        raise HTTPException(503, "Recruiter sign-in is not configured")
    actor = identity.actor(request)
    workspace = getattr(request.app.state, "ranking_workspace_id", "")
    if not workspace:
        raise HTTPException(503, "Recruiter workspace is not configured")
    params = request.path_params
    body = {}
    if request.method in ("POST", "PUT", "PATCH") and "application/json" in request.headers.get("content-type", ""):
        try:
            body = await request.json()
        except ValueError:
            pass
    job_id = params.get("job_id") or body.get("job_id")
    candidate_ids = []
    if params.get("candidate_id"):
        candidate_ids.append(params["candidate_id"])
    candidate_ids += body.get("candidate_ids", [])
    candidate_ids += body.get("final_candidate_ids", [])
    campaign_id = params.get("campaign_id") or body.get("campaign_id")
    run_id = body.get("ranking_run_id")
    if request.url.path.endswith("/screening/selections") and not run_id:
        raise HTTPException(422, "Select an owned ranking run")
    summary_id = params.get("summary_id")
    with identity.connect() as conn, conn.cursor() as cur:
        if job_id:
            cur.execute("SELECT 1 FROM recruiter_job_grants WHERE workspace_id=%s AND recruiter_id=%s AND job_id=%s",
                        (workspace, actor, job_id))
            if cur.fetchone() is None:
                raise HTTPException(404, "Job not found")
        for candidate_id in candidate_ids:
            cur.execute("SELECT 1 FROM candidate_source_grants WHERE workspace_id=%s AND actor_id=%s AND candidate_id=%s",
                        (workspace, actor, candidate_id))
            if cur.fetchone() is None:
                raise HTTPException(404, "Candidate not found")
        if run_id:
            cur.execute("SELECT 1 FROM ranking_runs r JOIN recruiter_job_grants g ON g.job_id=r.job_id "
                        "WHERE r.run_id=%s AND r.workspace_id=%s AND r.actor_id=%s "
                        "AND g.workspace_id=%s AND g.recruiter_id=%s",
                        (run_id, workspace, actor, workspace, actor))
            if cur.fetchone() is None:
                raise HTTPException(404, "Ranking run not found")
        if campaign_id:
            cur.execute("SELECT 1 FROM screening_campaigns c JOIN ranking_runs r ON r.run_id=c.ranking_run_id "
                        "JOIN recruiter_job_grants g ON g.job_id=c.job_id "
                        "WHERE c.id=%s AND r.workspace_id=%s AND r.actor_id=%s "
                        "AND g.workspace_id=%s AND g.recruiter_id=%s",
                        (campaign_id, workspace, actor, workspace, actor))
            if cur.fetchone() is None:
                raise HTTPException(404, "Campaign not found")
        if summary_id:
            cur.execute("SELECT 1 FROM screening_summary s JOIN screening_invites i ON i.id=s.invite_id "
                        "JOIN screening_campaigns c ON c.id=i.campaign_id JOIN ranking_runs r ON r.run_id=c.ranking_run_id "
                        "JOIN recruiter_job_grants g ON g.job_id=c.job_id "
                        "WHERE s.id=%s AND r.workspace_id=%s AND r.actor_id=%s "
                        "AND g.workspace_id=%s AND g.recruiter_id=%s",
                        (summary_id, workspace, actor, workspace, actor))
            if cur.fetchone() is None:
                raise HTTPException(404, "Summary not found")
    return actor
