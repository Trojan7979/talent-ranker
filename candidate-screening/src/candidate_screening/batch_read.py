"""Bounded read projections for preparing a recruiter-approved batch."""

from typing import Any
from uuid import UUID


class BatchReadMixin:
    def set_candidate_name(self, candidate_id: str, display_name: str) -> dict | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO candidate_names(candidate_id,display_name,source)
                   SELECT c.candidate_id,%s,'recruiter_verified' FROM candidates c
                   WHERE c.candidate_id=%s AND c.deleted_at IS NULL
                   ON CONFLICT(candidate_id) DO UPDATE SET
                     display_name=excluded.display_name,source=excluded.source,
                     updated_at=now()
                   RETURNING candidate_id,display_name""",
                (display_name, candidate_id),
            )
            return cur.fetchone()

    def approved_profile_priorities(self, job_id: str, profile_id: UUID) -> dict | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT priorities FROM job_profile_versions
                   WHERE job_id=%s AND profile_version_id=%s AND status='approved'""",
                (job_id, profile_id),
            )
            row = cur.fetchone()
            return row["priorities"] if row else None

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
                """SELECT c.candidate_id,cn.display_name,cn.source AS name_source,sc.email,
                          coalesce(sc.contactable,false) AS contactable
                   FROM candidates c LEFT JOIN screening_contacts sc
                     ON sc.candidate_id=c.candidate_id
                   LEFT JOIN candidate_names cn ON cn.candidate_id=c.candidate_id
                   WHERE c.candidate_id=ANY(%s) AND c.deleted_at IS NULL""",
                (candidate_ids,),
            )
            by_id = {row["candidate_id"]: row for row in cur.fetchall()}
        return [by_id[candidate_id] for candidate_id in dict.fromkeys(candidate_ids) if candidate_id in by_id]
