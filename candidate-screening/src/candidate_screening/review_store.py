from typing import Any
from uuid import UUID

from .review import ReviewQuery, decode_cursor, encode_cursor


class ReviewStoreMixin:
    def export_completed(self, campaign_id: UUID, candidate_ids: list[str]) -> list[dict] | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT config_snapshot FROM screening_campaigns WHERE id=%s", (campaign_id,))
            campaign = cur.fetchone()
            if campaign is None:
                return None
            cur.execute(
                """SELECT i.candidate_id,o.recipient_email,i.status,s.outcome,
                          s.confirmed,s.missing,s.needs_verification,r.interest,
                          r.earliest_start_date,r.notice_days,r.salary_minimum,
                          r.salary_maximum,r.salary_currency,r.salary_period,
                          r.salary_negotiable,i.completed_at
                   FROM screening_invites i
                   JOIN screening_summary s ON s.invite_id=i.id
                   JOIN screening_responses r ON r.invite_id=i.id
                   JOIN screening_delivery_outbox o ON o.invite_id=i.id
                   WHERE i.campaign_id=%s AND i.candidate_id=ANY(%s)
                   ORDER BY i.candidate_id""",
                (campaign_id, candidate_ids),
            )
            rows = cur.fetchall()
        labels = {
            item["id"]: item["text"]
            for item in campaign["config_snapshot"].get("must_haves", [])
        }
        for row in rows:
            row["question_labels"] = labels
        if {row["candidate_id"] for row in rows} != set(candidate_ids):
            raise ValueError("selected candidates must have completed this campaign")
        return rows

    def list_invites(self, campaign_id: UUID, after: str | None, limit: int) -> dict | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM screening_campaigns WHERE id=%s", (campaign_id,))
            if cur.fetchone() is None:
                return None
            cur.execute(
                """SELECT i.id AS invite_id,i.candidate_id,o.recipient_email,
                          o.status AS delivery_status,i.status,i.sent_at,i.opened_at,
                          i.started_at,i.completed_at,i.expires_at
                   FROM screening_invites i
                   JOIN screening_delivery_outbox o ON o.invite_id=i.id
                   WHERE i.campaign_id=%s AND (%s::text IS NULL OR i.candidate_id>%s)
                   ORDER BY i.candidate_id LIMIT %s""",
                (campaign_id, after, after, limit + 1),
            )
            rows = cur.fetchall()
        items = rows[:limit]
        return {
            "campaign_id": campaign_id,
            "items": items,
            "next_cursor": items[-1]["candidate_id"] if len(rows) > limit else None,
        }

    def list_completed(self, campaign_id: UUID, query: ReviewQuery) -> dict[str, Any] | None:
        cursor = decode_cursor(query.cursor, query.sort_by) if query.cursor else None
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM screening_campaigns WHERE id=%s", (campaign_id,))
            if cur.fetchone() is None:
                return None
            cur.execute(
                """SELECT s.outcome,count(*) AS count FROM screening_summary s
                   JOIN screening_invites i ON i.id=s.invite_id
                   WHERE i.campaign_id=%s GROUP BY s.outcome""",
                (campaign_id,),
            )
            counts = {row["outcome"]: row["count"] for row in cur.fetchall()}
            order = "priority,completed_at,id" if query.sort_by == "outcome" else "completed_at,id"
            if query.sort_by == "outcome":
                cursor_filter = "(%s::int IS NULL OR (priority,completed_at,id) > (%s,%s,%s))"
                cursor_params = (cursor[0], *cursor) if cursor else (None, 0, None, None)
            else:
                cursor_filter = "(%s::timestamptz IS NULL OR (completed_at,id) > (%s,%s))"
                cursor_params = (cursor[0], *cursor) if cursor else (None, None, None)
            cur.execute(
                f"""WITH matches AS (
                     SELECT s.id,s.invite_id,i.campaign_id,i.candidate_id,s.outcome,
                       s.confirmed,s.missing,s.needs_verification,s.reason_codes,
                       s.policy_version,s.config_version,i.completed_at,
                       CASE s.outcome WHEN 'needs_recruiter_review' THEN 0
                         WHEN 'proceed_to_interview' THEN 1 ELSE 2 END AS priority
                     FROM screening_summary s JOIN screening_invites i ON i.id=s.invite_id
                     WHERE i.campaign_id=%s AND (%s::text IS NULL OR s.outcome=%s)
                   ) SELECT * FROM matches WHERE {cursor_filter}
                   ORDER BY {order} LIMIT %s""",
                (campaign_id, query.outcome, query.outcome, *cursor_params, query.limit + 1),
            )
            rows = cur.fetchall()
        more = len(rows) > query.limit
        items = rows[: query.limit]
        return {
            "campaign_id": campaign_id,
            "counts": counts,
            "items": items,
            "next_cursor": encode_cursor(items[-1], query.sort_by) if more else None,
        }

    def get_summary(self, summary_id: UUID) -> dict[str, Any] | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT s.id,s.invite_id,i.campaign_id,i.candidate_id,s.outcome,
                          s.confirmed,s.missing,s.needs_verification,s.reason_codes,
                          s.policy_version,s.config_version,i.completed_at
                   FROM screening_summary s JOIN screening_invites i ON i.id=s.invite_id
                   WHERE s.id=%s""",
                (summary_id,),
            )
            return cur.fetchone()
