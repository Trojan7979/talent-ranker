"""Paginated recruiter reads for saved screening campaigns."""

from datetime import datetime
from uuid import UUID


class CampaignDirectoryMixin:
    def list_campaigns(
        self,
        job_id: str | None,
        before_created_at: datetime | None,
        before_id: UUID | None,
        limit: int,
        allowed_jobs: list[str] | None = None,
        workspace_id: str | None = None,
        actor_id: str | None = None,
    ) -> dict:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,job_id,ranking_run_id,status,created_at,
                          cardinality(COALESCE(final_candidate_ids,proposed_candidate_ids))
                          AS candidate_count
                   FROM screening_campaigns
                   WHERE (%s::text IS NULL OR job_id=%s)
                     AND (%s::text[] IS NULL OR job_id=ANY(%s::text[]))
                     AND (%s::text IS NULL OR EXISTS (
                       SELECT 1 FROM ranking_runs r WHERE r.run_id=screening_campaigns.ranking_run_id
                         AND r.workspace_id=%s AND r.actor_id=%s))
                     AND (%s::timestamptz IS NULL OR
                          (created_at,id) < (%s::timestamptz,%s::uuid))
                   ORDER BY created_at DESC,id DESC LIMIT %s""",
                (job_id, job_id, allowed_jobs, allowed_jobs,
                 workspace_id, workspace_id, actor_id,
                 before_created_at, before_created_at, before_id, limit + 1),
            )
            rows = cur.fetchall()
        items = [
            {
                "id": row["id"],
                "job_id": row["job_id"],
                "ranking_run_id": row["ranking_run_id"],
                "status": row["status"],
                "created_at": row["created_at"],
                "candidate_count": row["candidate_count"],
            }
            for row in rows[:limit]
        ]
        last = items[-1] if len(rows) > limit else None
        return {
            "items": items,
            "next_before_created_at": last["created_at"] if last else None,
            "next_before_id": last["id"] if last else None,
        }
