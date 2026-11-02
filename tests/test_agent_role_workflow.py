import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sieve_app.agent_role_workflow import AgentRoleWorkflow
from sieve_app.agent_runtime import RecruitmentAgentRuntime
from talent_ranker.llm_priority_extraction import CalibrationError


class SetupStore:
    def __init__(self, session):
        self.session = session

    def advance_setup(self, session_id, expected_stage, next_stage, **values):
        assert session_id == self.session["id"]
        assert self.session["setup_stage"] == expected_stage
        self.session.update(values)
        self.session["setup_stage"] = next_stage
        return self.session

    def queue_ranking(self, session_id, profile_id, top_k):
        assert session_id == self.session["id"]
        assert profile_id == self.session["draft_profile_version_id"]
        self.session["setup_stage"] = "ranking"
        self.session["queued_top_k"] = top_k

    def ranking_job(self, session_id):
        return {"status": self.session.get("ranking_status", "pending")}

    def retry_ranking(self, session_id):
        if self.session.get("ranking_status") != "failed":
            return False
        self.session["ranking_status"] = "pending"
        return True


class SetupRepository:
    def __init__(self):
        self.profile = None

    def create_job_profile(self, job_id, jd, priorities, metadata):
        self.profile = {
            "profile_version_id": str(uuid4()), "job_id": job_id, "version": 1,
            "status": "draft", "job_description": jd, "priorities": priorities,
        }
        return self.profile

    def get_job_profile(self, profile_id):
        return self.profile if self.profile and self.profile["profile_version_id"] == profile_id else None

    def update_job_profile(self, profile_id, priorities):
        assert profile_id == self.profile["profile_version_id"]
        self.profile["priorities"] = priorities
        return self.profile

    def approve_job_profile(self, profile_id, actor):
        assert profile_id == self.profile["profile_version_id"]
        self.profile["status"] = "approved"
        self.profile["approved_by"] = actor
        return self.profile


class SetupPipeline:
    def __init__(self):
        self.settings = SimpleNamespace(calibration_extractor="rules")
        self.repo = SetupRepository()
        self.rank_calls = []

    def rank(self, job_id, profile, top_k):
        self.rank_calls.append((job_id, profile["status"], top_k))
        return str(uuid4()), [SimpleNamespace(candidate_id="CAND_001", score=0.82, reasoning="Python experience evidenced")]


def test_pasted_jd_extracts_criteria_and_requires_ranking_approval():
    session = {"id": uuid4(), "job_id": "senior-engineer", "setup_stage": "awaiting_jd"}
    pipeline = SetupPipeline()
    workflow = AgentRoleWorkflow(SimpleNamespace(), pipeline, SetupStore(session))

    assert "Paste the job description" in workflow.handle(session, "recruiter", "Top 10")
    assert session["setup_stage"] == "awaiting_jd"
    assert "Draft hiring criteria" in workflow.handle(
        session, "recruiter", "Senior Python engineer building APIs with SQL and mentoring engineers."
    )
    assert session["setup_stage"] == "awaiting_criteria_approval"
    assert "Senior Python engineer" in workflow.handle(session, "recruiter", "Show JD")
    assert pipeline.repo.profile["status"] == "draft"
    assert "explicit approval" in workflow.handle(session, "recruiter", "Rank top 10 candidates")
    assert pipeline.rank_calls == []

    revised = workflow.handle(session, "recruiter", "Change must-have skills to Python, SQL")
    assert "Python" in revised and "SQL" in revised
    result = workflow.handle(session, "recruiter", "I approve these criteria; rank top 10 candidates")
    assert "background" in result
    assert pipeline.rank_calls == []
    assert session["setup_stage"] == "ranking"
    assert session["queued_top_k"] == 10
    assert "Ranking is running" in workflow.handle(session, "recruiter", "Is it ready?")


def test_unstructured_jd_without_skill_sections_still_produces_reviewable_criteria():
    session = {"id": uuid4(), "job_id": "operations-lead", "setup_stage": "awaiting_jd"}
    pipeline = SetupPipeline()
    reply = AgentRoleWorkflow(SimpleNamespace(), pipeline, SetupStore(session)).handle(
        session, "recruiter",
        "Lead the regional operations team, coordinate suppliers and improve delivery times. "
        "Experience with budgeting and cross-functional planning is important.",
    )

    assert "Draft hiring criteria" in reply
    assert "Experience with budgeting" in reply
    assert session["setup_stage"] == "awaiting_criteria_approval"
    assert pipeline.repo.profile["status"] == "draft"
    assert pipeline.repo.profile["job_description"].startswith("Lead the regional")


def test_failed_ranking_can_be_retried_from_chat():
    session = {"id": uuid4(), "job_id": "role-1", "setup_stage": "ranking",
               "ranking_status": "failed"}
    workflow = AgentRoleWorkflow(SimpleNamespace(), SetupPipeline(), SetupStore(session))
    assert "stopped" in workflow.handle(session, "recruiter", "Is it ready?")
    assert "queued again" in workflow.handle(session, "recruiter", "Retry ranking")
    assert session["ranking_status"] == "pending"


def test_incomplete_calibration_uses_grounded_rules_fallback(monkeypatch):
    session = {"id": uuid4(), "job_id": "role-1", "setup_stage": "awaiting_jd_approval",
               "draft_job_description": "Senior engineer with Python and SQL experience."}
    pipeline = SetupPipeline()
    pipeline.settings.calibration_model = "test-model"
    store = SetupStore(session)
    usage = {"completion_tokens": 4096,
             "completion_tokens_details": {"reasoning_tokens": 4096}}
    extractor = SimpleNamespace(last_usage=usage)
    recorded = []
    store.record_model_usage = lambda *args: recorded.append(args)
    monkeypatch.setattr("sieve_app.agent_role_workflow.configured_extractor",
                        lambda settings: (extractor, {}))
    def fail(*args, **kwargs):
        raise CalibrationError("incomplete model output")
    monkeypatch.setattr("sieve_app.agent_role_workflow.calibrate_job_description", fail)

    reply = AgentRoleWorkflow(SimpleNamespace(), pipeline, store).handle(
        session, "recruiter", "I approve this JD"
    )

    assert "Draft hiring criteria" in reply
    assert "Python and SQL experience" in reply
    assert session["setup_stage"] == "awaiting_criteria_approval"
    assert pipeline.repo.profile is not None
    assert pipeline.repo.profile["status"] == "draft"
    assert len(recorded) == 1


def test_every_setup_prompt_has_a_valid_stage_reply():
    """Keep frontend suggestions aligned with the server's actual conversation states."""
    source = (Path(__file__).resolve().parents[1] / "frontend/src/agentPrompts.ts").read_text(
        encoding="utf-8"
    )
    for group, stage in (
        ("jd", "awaiting_jd"),
        ("jdReview", "awaiting_jd_approval"),
        ("criteria", "awaiting_criteria_approval"),
    ):
        block = re.search(rf"const {group}: Prompt\[\] = \[(.*?)\];", source, re.DOTALL)
        assert block is not None
        prompts = re.findall(r'prompt: "([^"]+)"', block.group(1))
        assert prompts
        for prompt in prompts:
            session = {"id": uuid4(), "job_id": "test-job", "setup_stage": stage}
            pipeline = SetupPipeline()
            if stage == "awaiting_jd_approval":
                session["draft_job_description"] = "Senior Python engineer building APIs and mentoring engineers."
            if stage == "awaiting_criteria_approval":
                profile = pipeline.repo.create_job_profile(
                    "test-job", "Senior Python engineer building APIs and mentoring engineers.", {}, {}
                )
                session["draft_profile_version_id"] = profile["profile_version_id"]
            workflow = AgentRoleWorkflow(SimpleNamespace(), pipeline, SetupStore(session))
            workflow._draft_jd = lambda notes, session_id: "Senior Python engineer building APIs and mentoring engineers."
            assert len(workflow.handle(session, "recruiter", prompt)) > 20, prompt


def test_campaign_status_without_campaign_is_explicit_and_read_only():
    settings = SimpleNamespace(allowed_job_ids=lambda actor: {"test-job"})
    runtime = RecruitmentAgentRuntime(settings, None, None, None, frozenset({"test-job"}))
    session = {"job_id": "test-job", "campaign_id": None, "workspace_id": "demo"}
    reply = runtime.invoke(session, "recruiter", [
        {"role": "user", "content": "Check the current screening campaign status."}
    ])
    assert "No screening campaign exists" in reply
