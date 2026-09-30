import pytest
from conftest import PROFILE_ID, headers

from candidate_screening.questions import draft_questions, validate_against_approved_profile


def test_draft_covers_approved_criteria_without_duplicate_questions():
    priorities = {
        "must_have_skills": ["Python", " SQL "],
        "must_have_requirements": ["python", "Experience building APIs"],
        "availability": {"max_notice_period_days": 30},
        "compensation": {"maximum": 120000, "currency": "USD", "period": "year"},
    }
    draft = draft_questions(priorities)
    assert [item.text for item in draft.must_haves] == [
        "Python", "SQL", "Experience building APIs"
    ]
    assert draft.max_notice_days == 30
    assert draft.salary_maximum == 120000
    validate_against_approved_profile(draft, priorities)


@pytest.mark.integration
def test_recruiter_can_preview_question_draft_without_saving_configuration(client):
    url = f"/screening/jobs/job-1/profiles/{PROFILE_ID}/question-draft"
    assert client.get(url).status_code == 401
    response = client.get(url, headers=headers())
    assert response.status_code == 200, response.text
    assert response.json()["must_haves"] == [{
        "id": "requirement-1", "text": "Python", "hard_fail_on_no": False,
    }]
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS count FROM screening_job_configs")
        assert cur.fetchone()["count"] == 0
    saved = client.post(
        "/screening/jobs/job-1/configs", headers=headers(),
        json={"job_profile_version_id": str(PROFILE_ID), "questions": response.json()},
    )
    assert saved.status_code == 201, saved.text
