import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

from .invite_store import _INVITE_QUERY, InviteStoreMixin
from .questions import JobQuestions, ScreeningAnswers
from .summary import summarize

_SUMMARY_COLUMNS = """id,invite_id,outcome,confirmed,missing,needs_verification,
    reason_codes,policy_version,config_version,generated_at"""


def _fingerprint(answers: ScreeningAnswers) -> str:
    payload = json.dumps(answers.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _answer_values(answers: ScreeningAnswers, fingerprint: str, submitted_at: datetime | None):
    availability, notice, salary = answers.availability, answers.notice_period, answers.salary
    return (
        Jsonb([item.model_dump(mode="json") for item in answers.qualifications]),
        answers.interest,
        availability.status if availability else None,
        availability.earliest_start_date if availability else None,
        notice.status if notice else None,
        notice.days if notice else None,
        salary.status if salary else None,
        salary.minimum if salary else None,
        salary.maximum if salary else None,
        salary.currency if salary else None,
        salary.period if salary else None,
        salary.negotiable if salary else False,
        fingerprint,
        submitted_at,
    )


def _write_response(cur, invite_id, answers, fingerprint, submitted_at):
    cur.execute(
        """INSERT INTO screening_responses
           (invite_id,qualifications,interest,availability_status,earliest_start_date,
            notice_status,notice_days,salary_status,salary_minimum,salary_maximum,
            salary_currency,salary_period,salary_negotiable,answer_fingerprint,submitted_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT(invite_id) DO UPDATE SET
             qualifications=excluded.qualifications,interest=excluded.interest,
             availability_status=excluded.availability_status,
             earliest_start_date=excluded.earliest_start_date,
             notice_status=excluded.notice_status,notice_days=excluded.notice_days,
             salary_status=excluded.salary_status,salary_minimum=excluded.salary_minimum,
             salary_maximum=excluded.salary_maximum,salary_currency=excluded.salary_currency,
             salary_period=excluded.salary_period,salary_negotiable=excluded.salary_negotiable,
             answer_fingerprint=excluded.answer_fingerprint,submitted_at=excluded.submitted_at,
             revision=screening_responses.revision+1,saved_at=now()
           RETURNING revision,saved_at""",
        (invite_id, *_answer_values(answers, fingerprint, submitted_at)),
    )
    return cur.fetchone()


class ResponseStoreMixin(InviteStoreMixin):
    def save_draft(
        self, token: str, answers: ScreeningAnswers, expected_revision: int
    ) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
        with self.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(_INVITE_QUERY + " FOR UPDATE OF i", (token,))
            invite = cur.fetchone()
            if invite is None:
                return None
            invite = self._expire_locked(cur, invite, datetime.now(UTC))
            if invite["status"] != "started":
                return invite, None
            config = JobQuestions.model_validate(invite["config_snapshot"])
            summarize(config, answers, datetime.now(UTC).date())  # checks requirement IDs
            cur.execute(
                "SELECT revision FROM screening_responses WHERE invite_id=%s FOR UPDATE",
                (invite["id"],),
            )
            existing = cur.fetchone()
            if (existing["revision"] if existing else 0) != expected_revision:
                raise ValueError("response revision conflict")
            result = _write_response(cur, invite["id"], answers, _fingerprint(answers), None)
            return invite, result

    def complete_invite(
        self, token: str, answers: ScreeningAnswers, expected_revision: int
    ) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
        with self.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(_INVITE_QUERY + " FOR UPDATE OF i", (token,))
            invite = cur.fetchone()
            if invite is None:
                return None
            now = datetime.now(UTC)
            invite = self._expire_locked(cur, invite, now)
            fingerprint = _fingerprint(answers)
            cur.execute(
                """SELECT revision,answer_fingerprint FROM screening_responses
                   WHERE invite_id=%s FOR UPDATE""",
                (invite["id"],),
            )
            existing = cur.fetchone()
            if invite["status"] == "completed":
                if not existing or existing["answer_fingerprint"] != fingerprint:
                    raise ValueError("completed answers cannot be changed")
                cur.execute(
                    f"SELECT {_SUMMARY_COLUMNS} FROM screening_summary WHERE invite_id=%s",
                    (invite["id"],),
                )
                return invite, cur.fetchone()
            if invite["status"] != "started":
                return invite, None
            if (existing["revision"] if existing else 0) != expected_revision:
                raise ValueError("response revision conflict")
            config = JobQuestions.model_validate(invite["config_snapshot"])
            result = summarize(config, answers, now.date())
            _write_response(cur, invite["id"], answers, fingerprint, now)
            cur.execute(
                "UPDATE screening_invites SET status='completed',completed_at=%s WHERE id=%s",
                (now, invite["id"]),
            )
            cur.execute(
                f"""INSERT INTO screening_summary
                   (invite_id,outcome,confirmed,missing,needs_verification,reason_codes,
                    policy_version,config_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING {_SUMMARY_COLUMNS}""",
                (
                    invite["id"],
                    result.outcome,
                    Jsonb(result.confirmed),
                    Jsonb(result.missing),
                    Jsonb(result.needs_verification),
                    Jsonb(result.reason_codes),
                    result.policy_version,
                    config.version,
                ),
            )
            invite["status"] = "completed"
            invite["completed_at"] = now
            return invite, cur.fetchone()
