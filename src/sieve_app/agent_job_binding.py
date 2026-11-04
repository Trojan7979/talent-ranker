"""Bind an unassigned recruiter conversation to its first real role."""

from uuid import UUID, uuid4


class AgentJobBindingMixin:
    def bind_new_job(self, session_id: UUID):
        """Create and grant a role only when a recruiter supplies a usable JD."""
        with self.repository.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT * FROM agent_sessions WHERE id=%s FOR UPDATE", (session_id,))
            session = cur.fetchone()
            if session is None:
                raise LookupError("agent session not found")
            if session["job_id"] is not None:
                return session
            job_id = f"role-{uuid4().hex[:16]}"
            cur.execute("INSERT INTO jobs(job_id,job_description) VALUES (%s,'')", (job_id,))
            cur.execute(
                """INSERT INTO recruiter_job_grants(workspace_id,recruiter_id,job_id)
                   VALUES (%s,%s,%s)""",
                (session["workspace_id"], session["actor_id"], job_id),
            )
            cur.execute(
                """UPDATE agent_sessions SET job_id=%s,updated_at=now()
                   WHERE id=%s RETURNING *""",
                (job_id, session_id),
            )
            return cur.fetchone()
