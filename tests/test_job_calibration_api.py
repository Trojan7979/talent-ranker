from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from talent_ranker.api import app, approve_job_profile, calibrate_job, rank_candidates
from talent_ranker.llm_priority_extraction import CalibrationError
from talent_ranker.schemas import ApproveJobProfileRequest, CalibrateJobRequest, RankRequest

PROFILE_ID = UUID("33333333-3333-3333-3333-333333333333")


def profile(status: str = "draft") -> dict:
    return {
        "profile_version_id": str(PROFILE_ID),
        "job_id": "senior-ai-engineer",
        "version": 1,
        "status": status,
        "job_description": "Senior engineer. Python is required for this role.",
        "priorities": {
            "must_have_skills": ["Python"],
            "preferred_skills": [],
            "minimum_years_experience": None,
            "seniority": "senior",
            "location": {"locations": [], "remote_policy": None},
            "availability": {"max_notice_period_days": None, "target_start_date": None},
            "compensation": {
                "currency": None,
                "minimum": None,
                "maximum": None,
                "period": None,
            },
        },
        "created_at": datetime(2026, 9, 22, tzinfo=UTC),
        "approved_at": None,
        "approved_by": None,
    }


class FakeJobRepository:
    def __init__(self, stored_profile: dict | None = None):
        self.stored_profile = stored_profile

    def create_job_profile(
        self,
        job_id: str,
        job_description: str,
        priorities: dict,
        calibration_metadata: dict | None = None,
    ):
        created = profile()
        created["job_id"] = job_id
        created["job_description"] = job_description
        created["priorities"] = priorities
        created["calibration_metadata"] = calibration_metadata or {}
        self.stored_profile = created
        return created

    def get_job_profile(self, profile_version_id: str):
        assert profile_version_id == str(PROFILE_ID)
        return self.stored_profile

    def approve_job_profile(self, profile_version_id: str, approved_by: str):
        assert profile_version_id == str(PROFILE_ID)
        approved = {**self.stored_profile, "status": "approved", "approved_by": approved_by}
        self.stored_profile = approved
        return approved


def test_calibration_endpoint_creates_recruiter_reviewable_draft():
    repository = FakeJobRepository()
    app.state.pipeline = SimpleNamespace(repo=repository)

    response = calibrate_job(
        CalibrateJobRequest(
            job_id="senior-ai-engineer",
            job_description="Senior engineer. Python is required for this role.",
        )
    )

    assert response.status == "draft"
    assert response.priorities.must_have_skills == []
    assert response.priorities.must_have_requirements == ["Python is required for this role."]
    assert response.calibration_metadata == {"method": "rules"}


def test_failed_llm_draft_does_not_create_profile(monkeypatch):
    class FailingExtractor:
        def extract(self, job_description):
            raise CalibrationError("calibration model request failed")

    repository = FakeJobRepository()
    app.state.pipeline = SimpleNamespace(repo=repository)
    monkeypatch.setattr(
        "talent_ranker.api.configured_extractor",
        lambda settings: (FailingExtractor(), {"method": "llm"}),
    )

    with pytest.raises(HTTPException) as error:
        calibrate_job(
            CalibrateJobRequest(job_id="job", job_description="A role with Python required.")
        )

    assert error.value.status_code == 502
    assert repository.stored_profile is None


def test_approval_records_recruiter_identity():
    repository = FakeJobRepository(profile())
    app.state.pipeline = SimpleNamespace(repo=repository)

    response = approve_job_profile(PROFILE_ID, ApproveJobProfileRequest(approved_by="alex"))

    assert response.status == "approved"
    assert response.approved_by == "alex"


def test_ranking_rejects_unapproved_profile():
    app.state.pipeline = SimpleNamespace(repo=FakeJobRepository(profile()))

    with pytest.raises(HTTPException) as error:
        rank_candidates(
            RankRequest(
                job_id="senior-ai-engineer",
                job_profile_version_id=PROFILE_ID,
                top_k=10,
            )
        )

    assert error.value.status_code == 409
