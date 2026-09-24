from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class PostgresRepository:
    """Own a bounded pool; each use case borrows one connection."""

    def __init__(self, database_url: str, *, min_size: int = 1, max_size: int = 10):
        self.pool = ConnectionPool(
            database_url,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        self.pool.open()

    def close(self) -> None:
        self.pool.close()

    @contextmanager
    def connection(self) -> Iterator[Connection[dict[str, Any]]]:
        with self.pool.connection() as conn:
            yield conn

    def upsert_contact(
        self,
        candidate_id: str,
        email: str,
        source: str,
        source_reference: str | None,
        contactable: bool,
        updated_by: str,
    ) -> dict[str, Any] | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO screening_contacts
                   (candidate_id,email,source,source_reference,contactable,updated_by)
                   SELECT c.candidate_id,%s,%s,%s,%s,%s FROM candidates c
                   WHERE c.candidate_id=%s AND c.deleted_at IS NULL
                   ON CONFLICT(candidate_id) DO UPDATE SET
                       email=excluded.email, source=excluded.source,
                       source_reference=excluded.source_reference,
                       contactable=excluded.contactable, updated_by=excluded.updated_by,
                       updated_at=now()
                   RETURNING candidate_id,email,source,source_reference,contactable,
                             updated_by,updated_at""",
                (email, source, source_reference, contactable, updated_by, candidate_id),
            )
            return cur.fetchone()

    def resolve(self, candidate_id: str) -> str | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT sc.email FROM screening_contacts sc
                   JOIN candidates c ON c.candidate_id=sc.candidate_id
                   WHERE sc.candidate_id=%s AND sc.contactable AND c.deleted_at IS NULL""",
                (candidate_id,),
            )
            row = cur.fetchone()
            return row["email"] if row else None
