"""Durable, idempotent SharePoint ingestion work queue."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .drive_oauth_state import DriveOAuthStateMixin
from .identity_approval import IdentityApprovalMixin


class IndexingStore(DriveOAuthStateMixin, IdentityApprovalMixin):
    def __init__(self, database_url: str):
        self.pool = ConnectionPool(
            database_url, min_size=1, max_size=4, kwargs={"row_factory": dict_row}, open=True
        )

    def close(self) -> None:
        self.pool.close()

    def get_candidate_source(self, candidate_id: str) -> dict[str, Any] | None:
        """Read the active resume's client reference, including legacy copied records."""
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT coalesce(nullif(metadata->>'client_source_uri',''),source_uri)
                            AS source_uri, metadata->>'source_etag' AS source_etag
                   FROM candidates WHERE candidate_id=%s AND deleted_at IS NULL""",
                (candidate_id,),
            )
            return cur.fetchone()

    def submit(
        self, request_id: UUID, folder_url: str, entries: list[dict[str, str]], actor: str
    ) -> dict[str, Any]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO sharepoint_ingestion_jobs
                   (request_id,folder_url,entries,created_by)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT(request_id) DO NOTHING RETURNING id""",
                (request_id, folder_url, Jsonb(entries), actor),
            )
            created = cur.fetchone()
            cur.execute(
                "SELECT * FROM sharepoint_ingestion_jobs WHERE request_id=%s",
                (request_id,),
            )
            job = cur.fetchone()
            if not created and (job["folder_url"] != folder_url
                                or job["entries"] != entries or job["created_by"] != actor):
                raise ValueError("request ID was already used for a different indexing job")
            return job

    def submit_analysis(self, request_id: UUID, folder_url: str, actor: str) -> dict[str, Any]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO sharepoint_ingestion_jobs
                   (request_id,folder_url,entries,created_by,phase)
                   VALUES (%s,%s,'[]'::jsonb,%s,'analyze')
                   ON CONFLICT(request_id) DO NOTHING""",
                (request_id, folder_url, actor),
            )
            cur.execute("SELECT * FROM sharepoint_ingestion_jobs WHERE request_id=%s", (request_id,))
            job = cur.fetchone()
            if (job["folder_url"] != folder_url or job["created_by"] != actor
                    or job["phase"] != "analyze"):
                raise ValueError("request ID was already used for a different indexing job")
            return job

    def match_candidates(self, drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Match only stable source IDs, exact bytes, or an existing unique email."""
        uris = [item["source_uri"] for item in drafts]
        hashes = [item["sha256"] for item in drafts]
        emails = [item["email"] for item in drafts if item.get("email")]
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT source_uri,candidate_id FROM sharepoint_candidate_files WHERE source_uri=ANY(%s)",
                (uris,),
            )
            by_source = {row["source_uri"]: row["candidate_id"] for row in cur.fetchall()}
            cur.execute(
                """SELECT source_sha256,candidate_id FROM candidates
                   WHERE source_sha256=ANY(%s) AND deleted_at IS NULL""", (hashes,),
            )
            by_hash = {row["source_sha256"]: row["candidate_id"] for row in cur.fetchall()}
            cur.execute(
                """SELECT lower(email) AS email,array_agg(candidate_id) AS candidate_ids
                   FROM screening_contacts WHERE lower(email)=ANY(%s)
                   GROUP BY lower(email)""", (emails,),
            )
            by_email = {row["email"]: row["candidate_ids"] for row in cur.fetchall()}
        for item in drafts:
            fixed = set(filter(None, (by_source.get(item["source_uri"]),
                                      by_hash.get(item["sha256"]))))
            matches = set(fixed)
            matches.update(by_email.get(item.get("email"), []))
            item["locked_candidate_id"] = next(iter(fixed)) if len(fixed) == 1 else None
            item["locked_conflict"] = len(fixed) > 1
            item["candidate_id"] = (
                next(iter(matches)) if len(matches) == 1 else item["locked_candidate_id"]
            )
            item["suggestion"] = (
                "review" if item.get("analysis_error") or len(matches) > 1
                else "existing" if len(matches) == 1
                else "new"
            )
        seen_emails: set[str] = set()
        seen_hashes: set[str] = set()
        for item in drafts:
            if item["suggestion"] != "new":
                continue
            email = item.get("email")
            digest = item.get("sha256")
            if (email and email in seen_emails) or (digest and digest in seen_hashes):
                item["suggestion"] = "review"
            if email:
                seen_emails.add(email)
            if digest:
                seen_hashes.add(digest)
        return drafts

    def save_analysis(self, job_id: UUID, attempt: int, drafts: list[dict[str, Any]]) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE sharepoint_ingestion_jobs SET entries=%s,status='awaiting_review',
                      discovered=%s,leased_until=NULL,updated_at=now()
                   WHERE id=%s AND phase='analyze' AND status='running' AND attempts=%s""",
                (Jsonb(drafts), len(drafts), job_id, attempt),
            )
            if cur.rowcount != 1:
                raise RuntimeError("analysis lease was lost")

    def record_identity(
        self, job_id: UUID, attempt: int, candidate_id: str, source_uri: str,
        name: str, email: str, actor: str, source_kind: str = "sharepoint",
    ) -> None:
        with self.pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM sharepoint_ingestion_jobs
                   WHERE id=%s AND attempts=%s AND status='running' FOR UPDATE""",
                (job_id, attempt),
            )
            if cur.fetchone() is None:
                raise RuntimeError("indexing lease was lost")
            cur.execute(
                """INSERT INTO sharepoint_candidate_files(source_uri,candidate_id)
                   VALUES (%s,%s) ON CONFLICT(source_uri) DO UPDATE SET
                   updated_at=now() WHERE sharepoint_candidate_files.candidate_id=excluded.candidate_id""",
                (source_uri, candidate_id),
            )
            if cur.rowcount != 1:
                raise ValueError("Source file is already linked to a different candidate")
            if name:
                cur.execute(
                    """INSERT INTO candidate_names(candidate_id,display_name,source)
                       VALUES (%s,%s,%s) ON CONFLICT(candidate_id) DO UPDATE SET
                       display_name=excluded.display_name,updated_at=now()
                       WHERE candidate_names.source=excluded.source""",
                    (candidate_id, name, source_kind),
                )
            if email:
                cur.execute(
                    """INSERT INTO screening_contacts
                       (candidate_id,email,source,source_reference,contactable,updated_by)
                       VALUES (%s,%s,%s,%s,false,%s)
                       ON CONFLICT(candidate_id) DO NOTHING""",
                    (candidate_id, email, source_kind, source_uri, actor),
                )

    def get(self, job_id: UUID, actor: str) -> dict[str, Any] | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM sharepoint_ingestion_jobs WHERE id=%s AND created_by=%s",
                (job_id, actor),
            )
            return cur.fetchone()

    def claim_next(self, actor_id: str | None = None) -> dict[str, Any] | None:
        with self.pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM sharepoint_ingestion_jobs
                   WHERE (status='pending' OR (status='running' AND leased_until<now()))
                     AND (%s::text IS NULL OR created_by=%s)
                     AND (folder_url NOT LIKE 'https://drive.google.com/%%'
                          OR created_by ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
                   ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1""",
                (actor_id, actor_id),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                """UPDATE sharepoint_ingestion_jobs SET status='running', attempts=attempts+1,
                      discovered=0,indexed=0,skipped=0,failures='[]'::jsonb,
                      leased_until=now()+interval '30 minutes',updated_at=now()
                   WHERE id=%s RETURNING *""",
                (row["id"],),
            )
            return cur.fetchone()

    def record_result(self, job_id: UUID, attempt: int, failure: str | None) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE sharepoint_ingestion_jobs SET
                      indexed=indexed+%s,
                      failures=failures || %s::jsonb,
                      leased_until=now()+interval '30 minutes',updated_at=now()
                   WHERE id=%s AND status='running' AND attempts=%s""",
                (int(failure is None), Jsonb([failure] if failure else []), job_id, attempt),
            )
            if cur.rowcount != 1:
                raise RuntimeError("indexing lease was lost")

    def finish(self, job_id: UUID, attempt: int, discovered: int, skipped: int) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE sharepoint_ingestion_jobs SET
                      discovered=%s,skipped=%s,
                      status=CASE WHEN jsonb_array_length(failures)=0
                           THEN 'completed' ELSE 'completed_with_errors' END,
                      entries=(SELECT coalesce(jsonb_agg(
                        jsonb_build_object('candidate_id',item->>'candidate_id',
                                           'object_id',item->>'object_id')),'[]'::jsonb)
                        FROM jsonb_array_elements(entries) AS item),
                      leased_until=NULL,updated_at=now(),finished_at=now()
                   WHERE id=%s AND status='running' AND attempts=%s""",
                (discovered, skipped, job_id, attempt),
            )
            if cur.rowcount != 1:
                raise RuntimeError("indexing lease was lost")

    def fail(self, job_id: UUID, attempt: int, reason: str) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE sharepoint_ingestion_jobs SET
                      status='failed',failures=failures || %s::jsonb,
                      entries=(SELECT coalesce(jsonb_agg(
                        jsonb_build_object('candidate_id',item->>'candidate_id',
                                           'object_id',item->>'object_id')),'[]'::jsonb)
                        FROM jsonb_array_elements(entries) AS item),
                      leased_until=NULL,updated_at=now(),finished_at=now()
                   WHERE id=%s AND status='running' AND attempts=%s""",
                (Jsonb([reason]), job_id, attempt),
            )
