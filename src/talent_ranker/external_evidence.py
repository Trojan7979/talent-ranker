"""Transactional link discovery and leased enrichment jobs.

No network calls occur inside database transactions. Completion is fenced with
a random lease token so a recovered or replaced job cannot publish stale data.
"""

from __future__ import annotations

from collections.abc import Sequence

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .resume_links import ResumeLink


def sync_resume_links(cur, candidate_id: str, source_sha256: str,
                      links: Sequence[ResumeLink]) -> None:
    """Called in the same transaction as the candidate/chunk upsert."""
    cur.execute(
        """DELETE FROM candidate_external_evidence WHERE candidate_id=%s
           AND (source_sha256<>%s OR NOT (url=ANY(%s::text[])))""",
        (candidate_id, source_sha256, [link.url for link in links]),
    )
    cur.executemany(
        """INSERT INTO candidate_external_evidence
           (candidate_id,source_sha256,url,kind,discovered_via,status)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT(candidate_id,url) DO UPDATE SET
             discovered_via=excluded.discovered_via,
             status='pending',attempts=0,next_attempt_at=now(),updated_at=now()
           WHERE candidate_external_evidence.status='completed'
             AND candidate_external_evidence.fetched_at<now()-interval '7 days'""",
        [(candidate_id, source_sha256, link.url, link.kind, link.discovered_via,
          'unsupported' if link.kind == 'unsupported' else 'pending') for link in links],
    )


class EvidenceStore:
    def __init__(self, database_url: str):
        self.pool = ConnectionPool(database_url, min_size=1, max_size=4,
                                   kwargs={"row_factory": dict_row})

    def close(self) -> None:
        self.pool.close()

    def claim_next(self) -> dict | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            # Exhausted crashed jobs must not remain 'running' indefinitely.
            cur.execute(
                """UPDATE candidate_external_evidence SET status='failed',
                   error_code='lease_exhausted',lease_token=NULL,leased_until=NULL,updated_at=now()
                   WHERE status='running' AND leased_until<now() AND attempts>=3"""
            )
            cur.execute(
                """WITH next_job AS (
                     SELECT e.id FROM candidate_external_evidence e
                     JOIN candidates c ON c.candidate_id=e.candidate_id
                     WHERE c.deleted_at IS NULL AND c.source_sha256=e.source_sha256
                       AND e.attempts<3 AND e.next_attempt_at<=now()
                       AND (e.status='pending' OR
                            (e.status='running' AND e.leased_until<now()))
                     ORDER BY e.next_attempt_at,e.created_at,e.id
                     LIMIT 1 FOR UPDATE OF e SKIP LOCKED
                   ) UPDATE candidate_external_evidence e SET status='running',
                     attempts=e.attempts+1,lease_token=gen_random_uuid(),
                     leased_until=now()+interval '3 minutes',updated_at=now()
                   FROM next_job WHERE e.id=next_job.id RETURNING e.*"""
            )
            return cur.fetchone()

    def complete(self, job: dict, evidence: dict) -> bool:
        return self._finish(job, 'completed', evidence, None, 0)

    def fail(self, job: dict, code: str, *, retryable: bool = False,
             blocked: bool = False, retry_after: int = 0) -> bool:
        retry = retryable and job['attempts'] < 3
        status = 'pending' if retry else ('blocked' if blocked else 'failed')
        delay = max(30 * 2 ** (job['attempts'] - 1), min(retry_after, 86400)) if retry else 0
        return self._finish(job, status, {}, code, delay)

    def _finish(self, job: dict, status: str, evidence: dict, code: str | None,
                delay: int) -> bool:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE candidate_external_evidence e SET status=%s,evidence=%s,error_code=%s,
                     fetched_at=CASE WHEN %s='completed' THEN now() ELSE NULL END,
                     next_attempt_at=now()+make_interval(secs=>%s),
                     leased_until=NULL,lease_token=NULL,updated_at=now()
                   WHERE e.id=%s AND e.lease_token=%s AND e.status='running'
                     AND e.leased_until>now() AND EXISTS (
                       SELECT 1 FROM candidates c WHERE c.candidate_id=e.candidate_id
                       AND c.deleted_at IS NULL AND c.source_sha256=e.source_sha256)
                   RETURNING e.id""",
                (status, Jsonb(evidence), code, status, delay, job['id'], job['lease_token']),
            )
            return cur.fetchone() is not None

    def get_for_candidates(self, candidate_ids: Sequence[str]) -> dict[str, list[dict]]:
        """Batch read for ranking/screening consumers; results remain untrusted evidence."""
        if len(candidate_ids) > 100:
            raise ValueError('at most 100 candidates per evidence read')
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT c.candidate_id,e.url,e.kind,e.discovered_via,e.source_sha256,
                          e.status,e.attempts,e.error_code,e.fetched_at,e.evidence
                   FROM candidates c LEFT JOIN candidate_external_evidence e
                     ON c.candidate_id=e.candidate_id AND c.source_sha256=e.source_sha256
                   WHERE c.deleted_at IS NULL AND c.candidate_id=ANY(%s::text[])
                   ORDER BY c.candidate_id,e.created_at,e.url""", (list(candidate_ids),),
            )
            results: dict[str, list[dict]] = {}
            for row in cur.fetchall():
                evidence = results.setdefault(row.pop('candidate_id'), [])
                if row['url'] is not None:
                    evidence.append(row)
            return results
