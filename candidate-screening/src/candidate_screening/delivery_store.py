from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID


class DeliveryStoreMixin:
    def claim_due(
        self,
        limit: int,
        lease_seconds: int = 60,
        max_attempts: int = 5,
        campaign_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        with self.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """UPDATE screening_delivery_outbox
                   SET status='unknown',leased_until=NULL,last_error='send_lease_expired'
                   WHERE status='processing' AND leased_until <= %s""",
                (now,),
            )
            cur.execute(
                """SELECT o.id FROM screening_delivery_outbox o
                   JOIN screening_invites i ON i.id=o.invite_id
                   JOIN candidates c ON c.candidate_id=i.candidate_id
                   JOIN screening_contacts sc ON sc.candidate_id=c.candidate_id
                   WHERE o.attempts < %s AND i.status IS NULL AND i.expires_at > %s
                     AND (%s::uuid IS NULL OR i.campaign_id=%s::uuid)
                     AND c.deleted_at IS NULL AND sc.contactable
                     AND o.status IN ('pending','failed') AND o.next_attempt_at <= %s
                   ORDER BY o.next_attempt_at,o.id LIMIT %s
                   FOR UPDATE OF o SKIP LOCKED""",
                (max_attempts, now, campaign_id, campaign_id, now, limit),
            )
            ids = [row["id"] for row in cur.fetchall()]
            if not ids:
                return []
            cur.execute(
                """UPDATE screening_delivery_outbox
                   SET status='processing',attempts=attempts+1,leased_until=%s
                   WHERE id=ANY(%s)
                   RETURNING id,invite_id,recipient_email,subject,body,attempts""",
                (now + timedelta(seconds=lease_seconds), ids),
            )
            return cur.fetchall()

    def delivery_still_valid(self, outbox_id: UUID) -> bool:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM screening_delivery_outbox o
                   JOIN screening_invites i ON i.id=o.invite_id
                   JOIN candidates c ON c.candidate_id=i.candidate_id
                   JOIN screening_contacts sc ON sc.candidate_id=i.candidate_id
                   WHERE o.id=%s AND o.status='processing' AND i.status IS NULL
                     AND i.expires_at > now() AND c.deleted_at IS NULL
                     AND sc.contactable""",
                (outbox_id,),
            )
            return cur.fetchone() is not None

    def mark_delivered(self, outbox_id: UUID, receipt: str) -> None:
        now = datetime.now(UTC)
        with self.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """UPDATE screening_delivery_outbox
                   SET status='sent',sent_at=%s,provider_receipt=%s,leased_until=NULL
                   WHERE id=%s AND status='processing' RETURNING invite_id""",
                (now, receipt, outbox_id),
            )
            row = cur.fetchone()
            if row is None:
                return
            cur.execute(
                """UPDATE screening_invites SET status='sent',sent_at=%s
                   WHERE id=%s AND status IS NULL AND expires_at>%s""",
                (now, row["invite_id"], now),
            )

    def mark_delivery_unknown(self, outbox_id: UUID, error_code: str) -> None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE screening_delivery_outbox
                   SET status='unknown',leased_until=NULL,last_error=%s
                   WHERE id=%s AND status='processing'""",
                (error_code[:100], outbox_id),
            )

    def cancel_delivery(self, outbox_id: UUID) -> None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE screening_delivery_outbox
                   SET status='cancelled',leased_until=NULL
                   WHERE id=%s AND status='processing'""",
                (outbox_id,),
            )
