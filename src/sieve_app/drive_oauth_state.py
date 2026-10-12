"""One-use Google Drive OAuth state shared across API workers."""

from datetime import UTC, datetime, timedelta


class DriveOAuthStateMixin:
    def save_drive_oauth_state(
        self, state_hash: str, actor: str, verifier: str, nonce: str,
    ) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM drive_oauth_states WHERE expires_at < now()")
            cur.execute(
                """INSERT INTO drive_oauth_states
                   (state_hash,actor,code_verifier,nonce,expires_at)
                   VALUES (%s,%s,%s,%s,%s)""",
                (state_hash, actor, verifier, nonce, datetime.now(UTC) + timedelta(minutes=10)),
            )

    def consume_drive_oauth_state(self, state_hash: str) -> dict | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """DELETE FROM drive_oauth_states WHERE state_hash=%s AND expires_at>now()
                   RETURNING actor,code_verifier,nonce""",
                (state_hash,),
            )
            return cur.fetchone()
