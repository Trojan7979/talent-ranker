from uuid import UUID


class AgentStore:
    """Conversation persistence over the application's existing PostgreSQL pool."""

    def __init__(self, repository):
        self.repository = repository

    def create_session(self, workspace_id: str, actor: str, job_id: str, run_id: UUID | None):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_sessions(workspace_id,actor_id,job_id,ranking_run_id)
                   VALUES (%s,%s,%s,%s) RETURNING *""",
                (workspace_id, actor, job_id, run_id),
            )
            return cur.fetchone()

    def get_session(self, session_id: UUID, workspace_id: str, actor: str):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM agent_sessions
                   WHERE id=%s AND workspace_id=%s AND actor_id=%s""",
                (session_id, workspace_id, actor),
            )
            return cur.fetchone()

    def messages(self, session_id: UUID, limit: int = 50):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,role,content,created_at FROM agent_messages
                   WHERE session_id=%s ORDER BY id DESC LIMIT %s""",
                (session_id, limit),
            )
            return list(reversed(cur.fetchall()))

    def add_message(self, session_id: UUID, role: str, content: str):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_messages(session_id,role,content)
                   VALUES (%s,%s,%s) RETURNING id,role,content,created_at""",
                (session_id, role, content),
            )
            message = cur.fetchone()
            cur.execute("UPDATE agent_sessions SET updated_at=now() WHERE id=%s", (session_id,))
            return message

    def set_campaign(self, session_id: UUID, campaign_id: UUID):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE agent_sessions SET campaign_id=%s,updated_at=now()
                   WHERE id=%s AND campaign_id IS NULL RETURNING campaign_id""",
                (campaign_id, session_id),
            )
            return cur.fetchone()
