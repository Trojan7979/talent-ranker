"""Bounded reads for persisted ranking runs."""


class SavedRunsRepositoryMixin:
    def get_saved_run(self, run_id: str, after_rank: int, limit: int) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT run_id,job_id,job_profile_version_id,created_at
                   FROM ranking_runs WHERE run_id=%s::uuid""",
                (run_id,),
            )
            run = cur.fetchone()
            if run is None:
                return None
            cur.execute(
                """SELECT count(*) FROM ranking_results rr
                   JOIN candidates c ON c.candidate_id=rr.candidate_id
                   WHERE rr.run_id=%s::uuid AND c.deleted_at IS NULL""",
                (run_id,),
            )
            count = cur.fetchone()[0]
            cur.execute(
                """SELECT rr.candidate_id,rr.rank,rr.score,rr.score_components,
                          rr.evidence,rr.reasoning,rr.requirement_evidence
                   FROM ranking_results rr
                   JOIN candidates c ON c.candidate_id=rr.candidate_id
                   WHERE rr.run_id=%s::uuid AND rr.rank>%s AND c.deleted_at IS NULL
                   ORDER BY rr.rank LIMIT %s""",
                (run_id, after_rank, limit + 1),
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
