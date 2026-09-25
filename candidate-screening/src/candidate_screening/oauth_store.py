"""One-use OAuth state shared across API workers."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID


class OAuthStateStoreMixin:
    def save_oauth_state(
        self, state_hash: str, actor: str, verifier: str, nonce: str, campaign_id: UUID | None
    ) -> None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM screening_gmail_oauth_states WHERE expires_at < now()")
            cur.execute(
                """INSERT INTO screening_gmail_oauth_states
                   (state_hash,actor,code_verifier,nonce,campaign_id,expires_at)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (state_hash, actor, verifier, nonce, campaign_id,
                 datetime.now(UTC) + timedelta(minutes=10)),
            )

    def consume_oauth_state(self, state_hash: str) -> dict[str, Any] | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """DELETE FROM screening_gmail_oauth_states
                   WHERE state_hash=%s AND expires_at>now()
                   RETURNING actor,code_verifier,nonce,campaign_id""",
                (state_hash,),
            )
            return cur.fetchone()
