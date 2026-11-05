"""Persist explicit outcomes for each resume processed by an indexing worker."""

from __future__ import annotations

from uuid import UUID

from psycopg.types.json import Jsonb

from talent_ranker.batch_ingestion import IngestionOutcome


class IndexingProgressMixin:
    def record_result(
        self, job_id: UUID, attempt: int, failure: str | None,
        outcome: IngestionOutcome | None = None,
    ) -> None:
        # Successful legacy callers performed an embed; workers now report no-ops explicitly.
        if failure is None and outcome is None:
            outcome = IngestionOutcome.EMBEDDED
        embedded = int(failure is None and outcome == IngestionOutcome.EMBEDDED)
        unchanged = int(failure is None and outcome == IngestionOutcome.UNCHANGED)
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE sharepoint_ingestion_jobs SET
                      indexed=indexed+%s,embedded=embedded+%s,unchanged=unchanged+%s,
                      failures=failures || %s::jsonb,
                      leased_until=now()+interval '30 minutes',updated_at=now()
                   WHERE id=%s AND status='running' AND attempts=%s""",
                (embedded, embedded, unchanged, Jsonb([failure] if failure else []),
                 job_id, attempt),
            )
            if cur.rowcount != 1:
                raise RuntimeError("indexing lease was lost")
