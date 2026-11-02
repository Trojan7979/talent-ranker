"""Bounded reads for persisted ranking runs."""

import json
from collections.abc import Sequence
from datetime import datetime

from .access import RecruiterScope


class SavedRunsRepositoryMixin:
    def save_run(
        self, job_id: str, profile_version_id: str, jd: str,
        models: dict, config: dict, results: Sequence, scope: RecruiterScope,
    ) -> str:
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ranking_runs
                   (job_id,job_profile_version_id,jd_text,model_versions,scoring_config,
                    workspace_id,actor_id)
                   VALUES (%s,%s::uuid,%s,%s::jsonb,%s::jsonb,%s,%s) RETURNING run_id""",
                (job_id, profile_version_id, jd, json.dumps(models), json.dumps(config),
                 scope.workspace_id, scope.actor_id),
            )
            run_id = str(cur.fetchone()[0])
            cur.executemany(
                """INSERT INTO ranking_results
                   (run_id,candidate_id,rank,score,score_components,evidence,reasoning,
                    requirement_evidence)
                   VALUES (%s::uuid,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb)""",
                [
                    (run_id, r.candidate_id, rank, r.score, json.dumps(r.components),
                     json.dumps(r.evidence), r.reasoning,
                     json.dumps(r.requirement_evidence))
                    for rank, r in enumerate(results, 1)
                ],
            )
        return run_id

    def get_linked_evidence(
        self, job_id: str, run_id: str, candidate_id: str, scope: RecruiterScope
    ) -> list[dict]:
        """Bounded external-source status for a candidate in an authorized saved run."""
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT e.url,e.kind,e.status,e.error_code,e.evidence
                   FROM ranking_results rr
                   JOIN ranking_runs r ON r.run_id=rr.run_id
                   JOIN candidates c ON c.candidate_id=rr.candidate_id
                   JOIN candidate_source_grants g ON g.candidate_id=c.candidate_id
                     AND g.workspace_id=%s AND g.actor_id=%s
                     AND g.source_uri=coalesce(nullif(c.metadata->>'client_source_uri',''),c.source_uri)
                   JOIN candidate_external_evidence e ON e.candidate_id=c.candidate_id
                     AND e.source_sha256=c.source_sha256
                   WHERE r.job_id=%s AND r.run_id=%s::uuid AND rr.candidate_id=%s
                     AND r.workspace_id=%s AND r.actor_id=%s
                     AND c.deleted_at IS NULL
                   ORDER BY e.created_at,e.url LIMIT 10""",
                (scope.workspace_id, scope.actor_id, job_id, run_id, candidate_id,
                 scope.workspace_id, scope.actor_id),
            )
            rows = cur.fetchall()
        return [
            {"url": url, "kind": kind, "status": status, "error_code": error_code,
             "title": evidence.get("title", "")[:250],
             "excerpt": evidence.get("text", "")[:1500], "untrusted": True,
             "ownership_verified": False}
            for url, kind, status, error_code, evidence in rows
        ]

    def get_ranked_candidate(
        self, job_id: str, run_id: str, candidate_id: str, scope: RecruiterScope
    ) -> dict | None:
        """Read a persisted score with its supporting passages, scoped to one job and run."""
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT rr.candidate_id,rr.rank,rr.score,rr.score_components,
                          rr.evidence,rr.reasoning,rr.requirement_evidence
                   FROM ranking_results rr
                   JOIN ranking_runs r ON r.run_id=rr.run_id
                   JOIN candidates c ON c.candidate_id=rr.candidate_id
                   JOIN candidate_source_grants g ON g.candidate_id=c.candidate_id
                     AND g.workspace_id=%s AND g.actor_id=%s
                     AND g.source_uri=coalesce(nullif(c.metadata->>'client_source_uri',''),c.source_uri)
                   WHERE r.job_id=%s AND r.run_id=%s::uuid AND rr.candidate_id=%s
                     AND r.workspace_id=%s AND r.actor_id=%s
                     AND c.deleted_at IS NULL""",
                (scope.workspace_id, scope.actor_id, job_id, run_id, candidate_id,
                 scope.workspace_id, scope.actor_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return dict(zip(
            ("candidate_id", "rank", "score", "score_components", "evidence", "reasoning", "requirement_evidence"),
            row,
            strict=True,
        ))

    def list_saved_runs(
        self,
        job_id: str | None,
        before_created_at: datetime | None,
        before_run_id: str | None,
        limit: int,
        allowed_job_ids: list[str] | None = None,
        workspace_id: str | None = None,
        actor_id: str | None = None,
    ) -> dict:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT r.run_id,r.job_id,r.job_profile_version_id,r.created_at,
                          (SELECT count(*) FROM ranking_results rr
                           JOIN candidates c ON c.candidate_id=rr.candidate_id
                           WHERE rr.run_id=r.run_id AND c.deleted_at IS NULL
                             AND (%s::text IS NULL OR EXISTS (
                               SELECT 1 FROM candidate_source_grants g
                               WHERE g.candidate_id=c.candidate_id
                                 AND g.workspace_id=%s AND g.actor_id=%s
                                 AND g.source_uri=coalesce(nullif(c.metadata->>'client_source_uri',''),c.source_uri)
                             ))) AS total_count
                   FROM ranking_runs r
                   WHERE (%s::text IS NULL OR r.job_id=%s)
                     AND (%s::text[] IS NULL OR r.job_id=ANY(%s::text[]))
                     AND (%s::text IS NULL OR r.workspace_id=%s)
                     AND (%s::text IS NULL OR r.actor_id=%s)
                     AND (%s::timestamptz IS NULL OR
                          (r.created_at,r.run_id) < (%s::timestamptz,%s::uuid))
                   ORDER BY r.created_at DESC,r.run_id DESC LIMIT %s""",
                (
                    workspace_id,
                    workspace_id,
                    actor_id,
                    job_id,
                    job_id,
                    allowed_job_ids,
                    allowed_job_ids,
                    workspace_id,
                    workspace_id,
                    actor_id,
                    actor_id,
                    before_created_at,
                    before_created_at,
                    before_run_id,
                    limit + 1,
                ),
            )
            rows = cur.fetchall()
        items = [
            {
                "run_id": str(row[0]),
                "job_id": row[1],
                "job_profile_version_id": str(row[2]) if row[2] else None,
                "created_at": row[3],
                "total_count": row[4],
            }
            for row in rows[:limit]
        ]
        last = items[-1] if len(rows) > limit else None
        return {
            "items": items,
            "next_before_created_at": last["created_at"] if last else None,
            "next_before_run_id": last["run_id"] if last else None,
        }

    def get_saved_run(
        self, run_id: str, after_rank: int, limit: int,
        workspace_id: str | None = None, actor_id: str | None = None,
    ) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT run_id,job_id,job_profile_version_id,created_at
                   FROM ranking_runs WHERE run_id=%s::uuid
                     AND (%s::text IS NULL OR workspace_id=%s)
                     AND (%s::text IS NULL OR actor_id=%s)""",
                (run_id, workspace_id, workspace_id, actor_id, actor_id),
            )
            run = cur.fetchone()
            if run is None:
                return None
            cur.execute(
                """SELECT count(*) FROM ranking_results rr
                   JOIN candidates c ON c.candidate_id=rr.candidate_id
                   WHERE rr.run_id=%s::uuid AND c.deleted_at IS NULL
                     AND (%s::text IS NULL OR EXISTS (
                       SELECT 1 FROM candidate_source_grants g
                       WHERE g.candidate_id=c.candidate_id
                         AND g.workspace_id=%s AND g.actor_id=%s
                         AND g.source_uri=coalesce(nullif(c.metadata->>'client_source_uri',''),c.source_uri)
                     ))""",
                (run_id, workspace_id, workspace_id, actor_id),
            )
            count = cur.fetchone()[0]
            cur.execute(
                """SELECT rr.candidate_id,rr.rank,rr.score,rr.score_components,
                          rr.evidence,rr.reasoning,rr.requirement_evidence
                   FROM ranking_results rr
                   JOIN candidates c ON c.candidate_id=rr.candidate_id
                   WHERE rr.run_id=%s::uuid AND rr.rank>%s AND c.deleted_at IS NULL
                     AND (%s::text IS NULL OR EXISTS (
                       SELECT 1 FROM candidate_source_grants g
                       WHERE g.candidate_id=c.candidate_id
                         AND g.workspace_id=%s AND g.actor_id=%s
                         AND g.source_uri=coalesce(nullif(c.metadata->>'client_source_uri',''),c.source_uri)
                     ))
                   ORDER BY rr.rank LIMIT %s""",
                (run_id, after_rank, workspace_id, workspace_id, actor_id, limit + 1),
            )
            rows = cur.fetchall()
        items = [
            {
                "candidate_id": row[0],
                "rank": row[1],
                "score": row[2],
                "score_components": row[3],
                "evidence": row[4],
                "reasoning": row[5],
                "requirement_evidence": row[6],
            }
            for row in rows[:limit]
        ]
        return {
            "run_id": str(run[0]),
            "job_id": run[1],
            "job_profile_version_id": str(run[2]) if run[2] else None,
            "created_at": run[3],
            "total_count": count,
            "items": items,
            "next_after_rank": items[-1]["rank"] if len(rows) > limit else None,
        }
