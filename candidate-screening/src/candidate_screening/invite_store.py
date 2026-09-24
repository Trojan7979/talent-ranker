from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from .lifecycle import InviteStatus, transition

_INVITE_QUERY = """SELECT i.*,c.config_snapshot,c.job_id,c.id AS campaign_id
    FROM screening_invites i JOIN screening_campaigns c ON c.id=i.campaign_id
    JOIN candidates ca ON ca.candidate_id=i.candidate_id
    WHERE i.token=%s AND ca.deleted_at IS NULL"""

_TIMESTAMPS = {"opened": "opened_at", "started": "started_at", "declined": "declined_at"}


class InviteStoreMixin:
    @staticmethod
    def _expire_locked(cur, invite: dict[str, Any], now: datetime) -> dict[str, Any]:
        if invite["status"] in (None, "sent", "opened", "started") and now >= invite["expires_at"]:
            cur.execute(
                "UPDATE screening_invites SET status='expired',expired_at=%s WHERE id=%s",
                (now, invite["id"]),
            )
            cur.execute(
                """UPDATE screening_delivery_outbox SET status='cancelled',leased_until=NULL
                   WHERE invite_id=%s AND status IN ('pending','failed','processing')""",
                (invite["id"],),
            )
            invite["status"] = "expired"
            invite["expired_at"] = now
        return invite

    def get_invite(self, token: str) -> dict[str, Any] | None:
        with self.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(_INVITE_QUERY + " FOR UPDATE OF i", (token,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._expire_locked(cur, row, datetime.now(UTC))

    def record_invite_event(self, token: str, target: InviteStatus) -> dict[str, Any] | None:
        if target not in ("opened", "started", "declined"):
            raise ValueError("unsupported candidate event")
        with self.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(_INVITE_QUERY + " FOR UPDATE OF i", (token,))
            invite = cur.fetchone()
            if invite is None:
                return None
            now = datetime.now(UTC)
            invite = self._expire_locked(cur, invite, now)
            current = invite["status"]
            if current == "expired":
                return invite
            if current == target or (target == "opened" and current == "started"):
                return invite
            transition(current, target)
            column = _TIMESTAMPS[target]
            cur.execute(
                f"UPDATE screening_invites SET status=%s,{column}=%s WHERE id=%s",
                (target, now, invite["id"]),
            )
            invite["status"] = target
            invite[column] = now
            return invite

    def expire_due(self, limit: int = 1000) -> int:
        with self.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM screening_invites
                   WHERE expires_at <= now() AND
                     (status IS NULL OR status IN ('sent','opened','started'))
                   ORDER BY expires_at,id LIMIT %s FOR UPDATE SKIP LOCKED""",
                (limit,),
            )
            ids: list[UUID] = [row["id"] for row in cur.fetchall()]
            if not ids:
                return 0
            cur.execute(
                "UPDATE screening_invites SET status='expired',expired_at=now() WHERE id=ANY(%s)",
                (ids,),
            )
            cur.execute(
                """UPDATE screening_delivery_outbox
                   SET status='cancelled',leased_until=NULL
                   WHERE invite_id=ANY(%s) AND status IN ('pending','failed','processing')""",
                (ids,),
            )
            return len(ids)
