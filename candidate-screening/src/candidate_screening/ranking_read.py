from typing import Any
from uuid import UUID

from .selection import SelectionRule


class RankingReadMixin:
    def resolve_run(self, job_id: str, run_id: UUID | None) -> dict[str, Any] | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT r.run_id, r.job_id, r.job_profile_version_id,
                          p.status AS profile_status
                   FROM ranking_runs r
                   JOIN job_profile_versions p
                     ON p.profile_version_id=r.job_profile_version_id
                   WHERE r.job_id=%s AND (%s::uuid IS NULL OR r.run_id=%s::uuid)
                   ORDER BY r.created_at DESC, r.run_id DESC LIMIT 1""",
                (job_id, run_id, run_id),
            )
            return cur.fetchone()

    def select_ranked(self, run_id: UUID, rule: SelectionRule, limit: int) -> list[dict[str, Any]]:
        predicate = {
            "score_threshold": "rr.score >= %s",
            "top_n": "true",
            "rank_cutoff": "rr.rank <= %s",
        }[rule.kind]
        params = (run_id,) if rule.kind == "top_n" else (run_id, rule.value)
        count_limit = min(limit + 1, rule.value) if rule.kind == "top_n" else limit + 1
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""SELECT rr.candidate_id, rr.rank, rr.score,
                           (sc.email IS NOT NULL) AS has_contact
                    FROM ranking_results rr
                    JOIN candidates c ON c.candidate_id=rr.candidate_id
                    LEFT JOIN screening_contacts sc
                      ON sc.candidate_id=rr.candidate_id AND sc.contactable
                    WHERE rr.run_id=%s AND c.deleted_at IS NULL AND {predicate}
                    ORDER BY rr.rank, rr.candidate_id LIMIT %s""",
                (*params, count_limit),
            )
            return cur.fetchall()

    def eligible_ids(self, run_id: UUID, candidate_ids: list[str]) -> set[str]:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT rr.candidate_id FROM ranking_results rr
                   JOIN candidates c ON c.candidate_id=rr.candidate_id
                   WHERE rr.run_id=%s AND rr.candidate_id=ANY(%s)
                     AND c.deleted_at IS NULL""",
                (run_id, candidate_ids),
            )
            return {row["candidate_id"] for row in cur.fetchall()}
