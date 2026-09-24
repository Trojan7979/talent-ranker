from __future__ import annotations

import json
from typing import Any


class JobProfileRepositoryMixin:
    """Persistence operations for versioned, recruiter-approved job profiles."""

    conn: Any

    @staticmethod
    def _job_profile(row) -> dict | None:
        if row is None:
            return None
        return {
            "profile_version_id": str(row[0]),
            "job_id": row[1],
            "version": row[2],
            "status": row[3],
            "job_description": row[4],
            "priorities": row[5],
            "created_at": row[6],
            "approved_at": row[7],
            "approved_by": row[8],
            "calibration_metadata": row[9],
        }

    def create_job_profile(
        self,
        job_id: str,
        job_description: str,
        priorities: dict,
        calibration_metadata: dict | None = None,
    ) -> dict:
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO jobs(job_id, job_description)
                   VALUES (%s, %s)
                   ON CONFLICT(job_id) DO UPDATE SET
                     job_description = excluded.job_description, updated_at = now()""",
                (job_id, job_description),
            )
            cur.execute("SELECT 1 FROM jobs WHERE job_id = %s FOR UPDATE", (job_id,))
            cur.execute(
                """INSERT INTO job_profile_versions
                   (job_id, version, job_description, priorities, calibration_metadata)
                   SELECT %s, coalesce(max(version), 0) + 1, %s, %s::jsonb, %s::jsonb
                   FROM job_profile_versions WHERE job_id = %s
                   RETURNING profile_version_id""",
                (
                    job_id,
                    job_description,
                    json.dumps(priorities),
                    json.dumps(calibration_metadata or {}),
                    job_id,
                ),
            )
            profile_version_id = str(cur.fetchone()[0])
        profile = self.get_job_profile(profile_version_id)
        if profile is None:  # pragma: no cover - database invariant
            raise RuntimeError("created job profile could not be loaded")
        return profile

    def get_job_profile(self, profile_version_id: str) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT p.profile_version_id, p.job_id, p.version, p.status,
                          p.job_description, p.priorities, p.created_at, p.approved_at,
                          p.approved_by, p.calibration_metadata
                   FROM job_profile_versions p
                   WHERE p.profile_version_id = %s::uuid""",
                (profile_version_id,),
            )
            return self._job_profile(cur.fetchone())

    def update_job_profile(self, profile_version_id: str, priorities: dict) -> dict | None:
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                """UPDATE job_profile_versions SET priorities = %s::jsonb
                   WHERE profile_version_id = %s::uuid AND status = 'draft'
                   RETURNING profile_version_id""",
                (json.dumps(priorities), profile_version_id),
            )
            updated = cur.fetchone()
        return self.get_job_profile(profile_version_id) if updated else None

    def approve_job_profile(self, profile_version_id: str, approved_by: str) -> dict | None:
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                """SELECT job_id FROM job_profile_versions
                   WHERE profile_version_id = %s::uuid AND status = 'draft'
                   FOR UPDATE""",
                (profile_version_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            job_id = row[0]
            cur.execute("SELECT 1 FROM jobs WHERE job_id = %s FOR UPDATE", (job_id,))
            cur.execute(
                """UPDATE job_profile_versions SET status = 'superseded'
                   WHERE job_id = %s AND status = 'approved'""",
                (job_id,),
            )
            cur.execute(
                """UPDATE job_profile_versions
                   SET status = 'approved', approved_at = now(), approved_by = %s
                   WHERE profile_version_id = %s::uuid""",
                (approved_by, profile_version_id),
            )
        return self.get_job_profile(profile_version_id)
