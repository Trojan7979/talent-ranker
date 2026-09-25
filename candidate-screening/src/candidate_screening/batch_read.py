"""Bounded read projections for preparing a recruiter-approved batch."""

from typing import Any


class BatchReadMixin:
    def latest_job_config(self, job_id: str) -> dict[str, Any] | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,job_id,job_profile_version_id,version,questions,
                          policy_version,created_by,created_at
                   FROM screening_job_configs WHERE job_id=%s
                   ORDER BY version DESC LIMIT 1""",
                (job_id,),
            )
            return cur.fetchone()

    def lookup_contacts(self, candidate_ids: list[str]) -> list[dict[str, Any]]:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT c.candidate_id,sc.email,coalesce(sc.contactable,false) AS contactable
                   FROM candidates c LEFT JOIN screening_contacts sc
                     ON sc.candidate_id=c.candidate_id
                   WHERE c.candidate_id=ANY(%s) AND c.deleted_at IS NULL""",
                (candidate_ids,),
            )
            by_id = {row["candidate_id"]: row for row in cur.fetchall()}
        return [by_id[candidate_id] for candidate_id in dict.fromkeys(candidate_ids) if candidate_id in by_id]
