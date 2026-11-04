from uuid import UUID

from candidate_screening.questions import JobQuestions, validate_against_approved_profile
from psycopg.types.json import Jsonb

from .agent_job_binding import AgentJobBindingMixin
from .agent_reranking_store import AgentRerankingStoreMixin
from .agent_session_directory import AgentSessionDirectoryMixin
from .model_usage import AgentModelUsageMixin


class AgentStore(
    AgentJobBindingMixin, AgentSessionDirectoryMixin,
    AgentRerankingStoreMixin, AgentModelUsageMixin,
):
    """Conversation persistence over the application's existing PostgreSQL pool."""

    def __init__(self, repository):
        self.repository = repository

    def create_session(
        self, workspace_id: str, actor: str, job_id: str | None, run_id: UUID | None,
    ):
        with self.repository.connection() as conn, conn.cursor() as cur:
            if run_id is None and job_id is not None:
                cur.execute(
                    "INSERT INTO jobs(job_id,job_description) VALUES (%s,'') ON CONFLICT DO NOTHING",
                    (job_id,),
                )
            cur.execute(
                """INSERT INTO agent_sessions(workspace_id,actor_id,job_id,ranking_run_id,setup_stage)
                   VALUES (%s,%s,%s,%s,%s) RETURNING *""",
                (workspace_id, actor, job_id, run_id, "ranked" if run_id else "awaiting_jd"),
            )
            return cur.fetchone()

    def messages(self, session_id: UUID, limit: int = 50):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,role,content,created_at FROM agent_messages
                   WHERE session_id=%s ORDER BY id DESC LIMIT %s""",
                (session_id, limit),
            )
            return list(reversed(cur.fetchall()))

    def add_message(self, session_id: UUID, role: str, content: str):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_messages(session_id,role,content)
                   VALUES (%s,%s,%s) RETURNING id,role,content,created_at""",
                (session_id, role, content),
            )
            message = cur.fetchone()
            cur.execute("UPDATE agent_sessions SET updated_at=now() WHERE id=%s", (session_id,))
            return message

    def set_campaign(self, session_id: UUID, campaign_id: UUID):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE agent_sessions SET campaign_id=%s,updated_at=now()
                   WHERE id=%s AND campaign_id IS NULL RETURNING campaign_id""",
                (campaign_id, session_id),
            )
            return cur.fetchone()

    def campaign_for_question_config(self, config_id: UUID):
        """Recover a proposal created before its session update completed."""
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM screening_campaigns WHERE config_id=%s
                   ORDER BY created_at LIMIT 1""",
                (config_id,),
            )
            return cur.fetchone()

    def save_question_draft(self, session_id: UUID, profile_id: UUID, top_n: int, questions: JobQuestions):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE agent_sessions SET question_draft=%s,question_profile_version_id=%s,
                       question_top_n=%s,question_draft_revision=question_draft_revision+1,
                       updated_at=now()
                   WHERE id=%s AND setup_stage='ranked' AND campaign_id IS NULL
                     AND question_config_id IS NULL RETURNING *""",
                (Jsonb(questions.model_dump(mode="json")), profile_id, top_n, session_id),
            )
            return cur.fetchone()

    def approve_questions(self, session_id: UUID, expected_revision: int, actor: str):
        """Freeze a reviewed question draft and config in one transaction."""
        with self.repository.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT * FROM agent_sessions WHERE id=%s FOR UPDATE", (session_id,))
            session = cur.fetchone()
            if (session is None or session["question_draft"] is None
                    or session["question_draft_revision"] != expected_revision):
                raise ValueError("question draft is no longer approvable")
            if session["question_config_id"] is not None:
                return session["question_config_id"], session["question_top_n"]
            if session["campaign_id"] is not None:
                raise ValueError("question draft is no longer approvable")
            cur.execute(
                """SELECT priorities FROM job_profile_versions
                   WHERE profile_version_id=%s AND job_id=%s AND status='approved'""",
                (session["question_profile_version_id"], session["job_id"]),
            )
            profile = cur.fetchone()
            if profile is None:
                raise ValueError("approved hiring criteria are no longer available")
            questions = JobQuestions.model_validate(session["question_draft"])
            validate_against_approved_profile(questions, profile["priorities"])
            cur.execute(
                """INSERT INTO screening_job_configs
                   (job_id,job_profile_version_id,version,questions,created_by)
                   VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                (session["job_id"], session["question_profile_version_id"],
                 questions.version, Jsonb(questions.model_dump(mode="json")), actor),
            )
            config_id = cur.fetchone()["id"]
            cur.execute(
                """UPDATE agent_sessions SET question_config_id=%s,updated_at=now()
                   WHERE id=%s""", (config_id, session_id),
            )
            return config_id, session["question_top_n"]

    def advance_setup(self, session_id: UUID, expected_stage: str, next_stage: str, **values):
        allowed = {"draft_job_description", "draft_profile_version_id", "ranking_run_id"}
        if not set(values) <= allowed:
            raise ValueError("invalid setup update")
        assignments = ", ".join(f"{name}=%s" for name in values)
        if assignments:
            assignments += ", "
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""UPDATE agent_sessions SET {assignments}setup_stage=%s,updated_at=now()
                    WHERE id=%s AND setup_stage=%s RETURNING *""",
                (*values.values(), next_stage, session_id, expected_stage),
            )
            return cur.fetchone()

    def queue_ranking(self, session_id: UUID, profile_id: UUID, top_k: int):
        """Commit the approved ranking request and chat stage together."""
        with self.repository.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """UPDATE agent_sessions SET setup_stage='ranking',updated_at=now()
                   WHERE id=%s AND setup_stage='awaiting_criteria_approval'
                     AND draft_profile_version_id=%s RETURNING id""",
                (session_id, profile_id),
            )
            if cur.fetchone() is None:
                raise ValueError("ranking request is no longer available")
            cur.execute(
                """INSERT INTO agent_ranking_jobs(session_id,profile_version_id,top_k)
                   VALUES (%s,%s,%s)""",
                (session_id, profile_id, top_k),
            )

    def ranking_job(self, session_id: UUID):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status,last_error FROM agent_ranking_jobs WHERE session_id=%s",
                (session_id,),
            )
            return cur.fetchone()

    def ranking_session(self, session_id: UUID):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT workspace_id,actor_id,job_id FROM agent_sessions WHERE id=%s",
                (session_id,),
            )
            return cur.fetchone()

    def retry_ranking(self, session_id: UUID):
        with self.repository.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE agent_ranking_jobs SET status='pending',attempts=0,
                     last_error=NULL,leased_until=NULL,updated_at=now()
                   WHERE session_id=%s AND status='failed' RETURNING session_id""",
                (session_id,),
            )
            return cur.fetchone() is not None

    def claim_ranking(self):
        with self.repository.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """SELECT session_id FROM agent_ranking_jobs
                   WHERE status='pending' OR (status='running' AND leased_until<now())
                   ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"""
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                """UPDATE agent_ranking_jobs SET status='running',attempts=attempts+1,
                     leased_until=now()+interval '30 minutes',updated_at=now()
                   WHERE session_id=%s RETURNING *""",
                (row["session_id"],),
            )
            return cur.fetchone()

    def finish_ranking(self, job: dict, run_id: UUID, results: list):
        """Publish the saved run and the completion message as one visible change."""
        with self.repository.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """UPDATE agent_ranking_jobs SET status='completed',run_id=%s,
                     leased_until=NULL,updated_at=now()
                   WHERE session_id=%s AND status='running' AND attempts=%s
                   RETURNING session_id""",
                (run_id, job["session_id"], job["attempts"]),
            )
            if cur.fetchone() is None:
                raise RuntimeError("ranking lease was lost")
            cur.execute(
                """UPDATE agent_sessions SET setup_stage='ranked',ranking_run_id=%s,
                     updated_at=now() WHERE id=%s AND setup_stage='ranking'""",
                (run_id, job["session_id"]),
            )
            message = (
                f"Ranking finished. I saved {len(results)} candidates. Scores are relative ranking indexes, not probabilities of job fit.\n\nReview the candidate cards for names, scores, and evidence. Ask me to explain a candidate, compare candidates, or draft screening questions."
                if results else "Ranking finished, but no indexed candidates matched. Review resume intake before preparing screening."
            )
            cur.execute(
                "INSERT INTO agent_messages(session_id,role,content) VALUES (%s,'assistant',%s)",
                (job["session_id"], message[:20000]),
            )

    def fail_ranking(self, job: dict):
        with self.repository.connection() as conn, conn.transaction(), conn.cursor() as cur:
            retry = job["attempts"] < 3
            cur.execute(
                """UPDATE agent_ranking_jobs SET status=%s,leased_until=NULL,
                     last_error='Ranking could not complete; check worker logs',updated_at=now()
                   WHERE session_id=%s AND status='running' AND attempts=%s""",
                ("pending" if retry else "failed", job["session_id"], job["attempts"]),
            )
            if cur.rowcount == 1 and not retry:
                cur.execute(
                    """INSERT INTO agent_messages(session_id,role,content)
                       VALUES (%s,'assistant',%s)""",
                    (job["session_id"], "Ranking could not complete after three attempts. Ask an administrator to inspect the ranking worker; no shortlist was published."),
                )
