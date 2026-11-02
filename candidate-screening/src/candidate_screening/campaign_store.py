from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from .campaigns import CreateCampaignRequest, EditCampaignRequest
from .questions import JobQuestions, validate_against_approved_profile

_CAMPAIGN_COLUMNS = """id,job_id,ranking_run_id,job_profile_version_id,config_id,
    selection_rule,proposed_candidate_ids,final_candidate_ids,message_template,
    expiry_hours,status,revision,approved_by,approved_at,created_at"""

class CampaignStoreMixin:
    def create_job_config(
        self, job_id: str, profile_id: UUID, questions: JobQuestions, actor: str
    ) -> dict[str, Any] | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT priorities FROM job_profile_versions
                   WHERE job_id=%s AND profile_version_id=%s AND status='approved'""",
                (job_id, profile_id),
            )
            profile = cur.fetchone()
            if profile is None:
                return None
            validate_against_approved_profile(questions, profile["priorities"])
            cur.execute(
                """INSERT INTO screening_job_configs
                   (job_id,job_profile_version_id,version,questions,created_by)
                   SELECT p.job_id,p.profile_version_id,%s,%s,%s
                   FROM job_profile_versions p
                   WHERE p.job_id=%s AND p.profile_version_id=%s AND p.status='approved'
                   RETURNING id,job_id,job_profile_version_id,version,questions,
                             policy_version,created_by,created_at""",
                (
                    questions.version,
                    Jsonb(questions.model_dump(mode="json")),
                    actor,
                    job_id,
                    profile_id,
                ),
            )
            return cur.fetchone()

    def get_job_config(self, config_id: UUID) -> dict[str, Any] | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,job_id,job_profile_version_id,version,questions,
                          policy_version,created_by,created_at
                   FROM screening_job_configs WHERE id=%s""",
                (config_id,),
            )
            return cur.fetchone()

    def get_job_config_version(self, job_id: str, version: int) -> dict[str, Any] | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,job_id,job_profile_version_id,version,questions,
                          policy_version,created_by,created_at
                   FROM screening_job_configs WHERE job_id=%s AND version=%s""",
                (job_id, version),
            )
            return cur.fetchone()

    def create_campaign(
        self, request: CreateCampaignRequest, config: dict[str, Any], proposed: list[str]
    ) -> dict[str, Any]:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO screening_campaigns
                   (job_id,ranking_run_id,job_profile_version_id,config_id,
                    config_snapshot,selection_rule,proposed_candidate_ids,
                    message_template,expiry_hours)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING {_CAMPAIGN_COLUMNS}""",
                (
                    request.job_id,
                    request.ranking_run_id,
                    config["job_profile_version_id"],
                    request.config_id,
                    Jsonb(config["questions"]),
                    Jsonb(request.rule.model_dump()),
                    proposed,
                    request.message_template,
                    request.expiry_hours,
                ),
            )
            return cur.fetchone()

    def get_campaign(self, campaign_id: UUID) -> dict[str, Any] | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CAMPAIGN_COLUMNS} FROM screening_campaigns WHERE id=%s",
                (campaign_id,),
            )
            return cur.fetchone()

    def edit_campaign(
        self, campaign_id: UUID, request: EditCampaignRequest
    ) -> dict[str, Any] | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT ranking_run_id FROM screening_campaigns
                   WHERE id=%s AND status='proposed' AND revision=%s FOR UPDATE""",
                (campaign_id, request.expected_revision),
            )
            row = cur.fetchone()
            if row is None:
                return None
            if len(set(request.final_candidate_ids)) != len(request.final_candidate_ids):
                raise ValueError("final candidate IDs must be unique")
            cur.execute(
                """SELECT rr.candidate_id FROM ranking_results rr
                   JOIN candidates c ON c.candidate_id=rr.candidate_id
                   WHERE rr.run_id=%s AND rr.candidate_id=ANY(%s)
                     AND c.deleted_at IS NULL""",
                (row["ranking_run_id"], request.final_candidate_ids),
            )
            eligible = {item["candidate_id"] for item in cur.fetchall()}
            if eligible != set(request.final_candidate_ids):
                raise ValueError("final candidates must belong to the run and be active")
            cur.execute(
                f"""UPDATE screening_campaigns SET final_candidate_ids=%s,
                    message_template=%s,revision=revision+1 WHERE id=%s
                    RETURNING {_CAMPAIGN_COLUMNS}""",
                (request.final_candidate_ids, request.message_template, campaign_id),
            )
            return cur.fetchone()

    def reject_campaign(self, campaign_id: UUID, expected_revision: int) -> dict[str, Any] | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""UPDATE screening_campaigns SET status='rejected',revision=revision+1
                    WHERE id=%s AND status='proposed' AND revision=%s
                    RETURNING {_CAMPAIGN_COLUMNS}""",
                (campaign_id, expected_revision),
            )
            return cur.fetchone()