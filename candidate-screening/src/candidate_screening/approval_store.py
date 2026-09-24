import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

_CAMPAIGN_COLUMNS = """id,job_id,ranking_run_id,job_profile_version_id,config_id,
    selection_rule,proposed_candidate_ids,final_candidate_ids,message_template,
    expiry_hours,status,revision,approved_by,approved_at,created_at"""


class ApprovalStoreMixin:
    def approve_campaign(
        self, campaign_id: UUID, expected_revision: int, actor: str, public_base_url: str
    ) -> dict[str, Any] | None:
        """Freeze membership and queue initial mail in one transaction."""
        with self.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT * FROM screening_campaigns WHERE id=%s FOR UPDATE", (campaign_id,))
            campaign = cur.fetchone()
            if campaign is None:
                return None
            if campaign["status"] == "approved":
                cur.execute(
                    f"SELECT {_CAMPAIGN_COLUMNS} FROM screening_campaigns WHERE id=%s",
                    (campaign_id,),
                )
                return cur.fetchone()
            if campaign["status"] != "proposed" or campaign["revision"] != expected_revision:
                raise ValueError("campaign is no longer approvable at this revision")
            final_ids = campaign["final_candidate_ids"] or campaign["proposed_candidate_ids"]
            if not final_ids or len(final_ids) != len(set(final_ids)):
                raise ValueError("final candidate list must be nonempty and unique")
            if campaign["message_template"].count("{screening_link}") != 1:
                raise ValueError("message template must contain one {screening_link} placeholder")
            cur.execute(
                """SELECT rr.candidate_id,sc.email FROM ranking_results rr
                   JOIN candidates c ON c.candidate_id=rr.candidate_id
                   LEFT JOIN screening_contacts sc ON sc.candidate_id=c.candidate_id
                        AND sc.contactable
                   WHERE rr.run_id=%s AND rr.candidate_id=ANY(%s)
                     AND c.deleted_at IS NULL
                   FOR SHARE OF rr,c""",
                (campaign["ranking_run_id"], final_ids),
            )
            recipients = {row["candidate_id"]: row["email"] for row in cur.fetchall()}
            blocked = [
                candidate_id for candidate_id in final_ids if not recipients.get(candidate_id)
            ]
            if blocked:
                raise ValueError("candidates lack active contact: " + ", ".join(blocked))
            now = datetime.now(UTC)
            expires_at = now + timedelta(hours=campaign["expiry_hours"])
            for candidate_id in final_ids:
                token = secrets.token_urlsafe(32)
                cur.execute(
                    """INSERT INTO screening_invites
                       (campaign_id,candidate_id,token,expires_at)
                       VALUES (%s,%s,%s,%s) RETURNING id""",
                    (campaign_id, candidate_id, token, expires_at),
                )
                invite_id = cur.fetchone()["id"]
                link = public_base_url.rstrip("/") + "/" + token
                body = campaign["message_template"].replace("{screening_link}", link)
                cur.execute(
                    """INSERT INTO screening_delivery_outbox
                       (invite_id,recipient_email,subject,body)
                       VALUES (%s,%s,%s,%s)""",
                    (invite_id, recipients[candidate_id], "Your screening link", body),
                )
            cur.execute(
                f"""UPDATE screening_campaigns
                    SET final_candidate_ids=%s,status='approved',approved_by=%s,
                        approved_at=%s,revision=revision+1
                    WHERE id=%s RETURNING {_CAMPAIGN_COLUMNS}""",
                (final_ids, actor, now, campaign_id),
            )
            return cur.fetchone()
