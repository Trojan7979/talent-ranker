from types import SimpleNamespace
from uuid import uuid4

from sieve_app.agent_runtime import RecruitmentAgentRuntime
from sieve_app.agent_screening_workflow import AgentScreeningWorkflow


class DraftStore:
    def __init__(self):
        self.saved = None

    def save_question_draft(self, session_id, profile_id, top_n, questions):
        self.saved = (session_id, profile_id, top_n, questions)
        return {"id": session_id}


def test_chat_drafts_from_approved_criteria_without_creating_campaign():
    profile_id = uuid4()
    run_id = uuid4()
    repo = SimpleNamespace(
        resolve_run=lambda job, run: {
            "job_id": job, "run_id": run, "profile_status": "approved",
            "job_profile_version_id": profile_id,
        },
        approved_profile_priorities=lambda job, profile: {
            "must_have_skills": ["Python", "SQL"], "must_have_requirements": ["API design"],
        },
        latest_job_config=lambda job: {"version": 2},
    )
    store = DraftStore()
    workflow = AgentScreeningWorkflow(repo, store, 10)
    session = {"id": uuid4(), "job_id": "role-1", "ranking_run_id": run_id,
               "campaign_id": None, "question_config_id": None}

    assert workflow.is_draft_request("Draft screening questions for the top 10 candidates")
    reply = workflow.draft(session, "Draft screening questions for the top 10 candidates")

    assert "does not send email" in reply
    assert store.saved[:3] == (session["id"], profile_id, 10)
    assert store.saved[3].version == 3
    assert [question.text for question in store.saved[3].must_haves] == ["Python", "SQL", "API design"]


def test_draft_rejects_more_recipients_than_configured_limit():
    store = DraftStore()
    workflow = AgentScreeningWorkflow(None, store, 10)
    reply = workflow.draft({"campaign_id": None, "question_config_id": None},
                           "Create screening questions for top 11")
    assert "between 1 and 10" in reply
    assert store.saved is None


def test_pending_question_approval_blocks_campaign_creation_and_chat_approval():
    runtime = RecruitmentAgentRuntime(
        SimpleNamespace(), None, None, None, frozenset({"role-1"})
    )
    session = {"job_id": "role-1", "campaign_id": None, "workspace_id": "demo",
               "question_draft": {"must_haves": []}, "question_config_id": None}
    create_reply = runtime.invoke(session, "recruiter", [
        {"role": "user", "content": "Prepare a screening campaign for top 10"}
    ])
    approve_reply = runtime.invoke(session, "recruiter", [
        {"role": "user", "content": "I approve the questions"}
    ])
    assert "approve the pending screening questions first" in create_reply
    assert "Chat text alone does not approve" in approve_reply


def test_campaign_request_cannot_use_an_older_question_configuration():
    runtime = RecruitmentAgentRuntime(
        SimpleNamespace(), None, None, None, frozenset({"role-1"})
    )
    session = {"job_id": "role-1", "campaign_id": None, "workspace_id": "demo",
               "question_draft": None, "question_config_id": None}
    reply = runtime.invoke(session, "recruiter", [
        {"role": "user", "content": "Prepare a screening campaign for top 4"}
    ])
    assert "Draft screening questions" in reply
