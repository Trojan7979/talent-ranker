"""Actor-scoped session lookups for the Recruitment Agent."""

from uuid import UUID


class AgentSessionDirectoryMixin:
    def get_session(self, session_id: UUID, workspace_id: str, actor: str):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM agent_sessions
                   WHERE id=%s AND workspace_id=%s AND actor_id=%s""",
                (session_id, workspace_id, actor),
            )
            return cur.fetchone()

    def list_sessions(self, workspace_id: str, actor: str, job_ids: list[str], limit: int = 30):
        if not job_ids:
            return []
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,job_id,setup_stage,ranking_run_id,created_at,updated_at
                   FROM agent_sessions
                   WHERE workspace_id=%s AND actor_id=%s AND job_id=ANY(%s)
                   ORDER BY updated_at DESC,id DESC LIMIT %s""",
                (workspace_id, actor, job_ids, limit),
            )
            return cur.fetchall()
