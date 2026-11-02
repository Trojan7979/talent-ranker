"""Transactional queue transition for repeat rankings in one conversation."""


class AgentRerankingStoreMixin:
    def queue_reranking(self, session: dict, top_k: int) -> int:
        with self.repository.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """SELECT p.profile_version_id,p.version FROM ranking_runs r
                   JOIN job_profile_versions p ON p.job_id=r.job_id
                     AND p.status='approved'
                   WHERE r.run_id=%s AND r.job_id=%s AND r.workspace_id=%s
                     AND r.actor_id=%s
                   ORDER BY p.version DESC LIMIT 1""",
                (session["ranking_run_id"], session["job_id"],
                 session["workspace_id"], session["actor_id"]),
            )
            profile = cur.fetchone()
            if profile is None:
                raise ValueError("The approved criteria for this run are unavailable")
            cur.execute(
                """UPDATE agent_sessions SET setup_stage='ranking',updated_at=now()
                   WHERE id=%s AND workspace_id=%s AND actor_id=%s
                     AND setup_stage='ranked' AND ranking_run_id=%s
                     AND campaign_id IS NULL AND question_draft IS NULL
                     AND question_config_id IS NULL RETURNING id""",
                (session["id"], session["workspace_id"], session["actor_id"],
                 session["ranking_run_id"]),
            )
            if cur.fetchone() is None:
                raise ValueError("This conversation is no longer ready for reranking")
            cur.execute(
                """INSERT INTO agent_ranking_jobs(session_id,profile_version_id,top_k)
                   VALUES (%s,%s,%s)
                   ON CONFLICT(session_id) DO UPDATE SET
                     profile_version_id=excluded.profile_version_id,
                     top_k=excluded.top_k,status='pending',attempts=0,
                     run_id=NULL,last_error=NULL,leased_until=NULL,
                     created_at=now(),updated_at=now()
                   WHERE agent_ranking_jobs.status='completed'
                   RETURNING session_id""",
                (session["id"], profile["profile_version_id"], top_k),
            )
            if cur.fetchone() is None:
                raise ValueError("A ranking job is already active for this conversation")
            return profile["version"]
