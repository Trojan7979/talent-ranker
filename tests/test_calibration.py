from talent_ranker.calibration import build_calibrated_query, calibrate_job_description
from talent_ranker.pipeline import RankingPipeline
from talent_ranker.priority_scoring import priority_alignment
from talent_ranker.ranking import final_score
from talent_ranker.schemas import HiringPriorities, HiringPriorityOverrides, LocationPriority


def test_calibration_extracts_must_have_and_preferred_skills():
    jd = (
        "Senior AI Engineer.\nRequired skills: Python, SQL\n"
        "Preferred skills: AWS, Kubernetes\nMinimum 5 years experience. Remote role.\n"
        "Seniority: Senior\n"
        "Location: Kolkata. Join within 4 weeks. INR 2000000-3000000 per year."
    )

    priorities = calibrate_job_description(jd)

    assert priorities.must_have_skills == ["Python", "SQL"]
    assert priorities.preferred_skills == ["AWS", "Kubernetes"]
    assert priorities.minimum_years_experience == 5
    assert priorities.seniority == "Senior"
    assert priorities.location.remote_policy == "remote"
    assert priorities.location.locations == ["Kolkata"]
    assert priorities.availability.max_notice_period_days == 28
    assert priorities.compensation.currency == "INR"
    assert priorities.compensation.maximum == 3_000_000


def test_calibration_is_domain_neutral_for_non_technical_roles():
    priorities = calibrate_job_description(
        "Chief Financial Officer\n"
        "Required skills: financial modeling, stakeholder management\n"
        "Preferred skills: board governance, mergers and acquisitions\n"
        "Seniority: C-suite\nMinimum 12 years experience."
    )

    assert priorities.must_have_skills == ["financial modeling", "stakeholder management"]
    assert priorities.preferred_skills == [
        "board governance",
        "mergers and acquisitions",
    ]
    assert priorities.seniority == "C-suite"


def test_recruiter_overrides_replace_heuristic_values():
    priorities = calibrate_job_description(
        "Senior engineer with Python required for a remote position.",
        HiringPriorityOverrides(
            must_have_skills=["Python", "FastAPI"],
            location=LocationPriority(locations=["Bengaluru"], remote_policy="hybrid"),
        ),
    )

    assert priorities.must_have_skills == ["Python", "FastAPI"]
    assert priorities.location.locations == ["Bengaluru"]
    assert priorities.location.remote_policy == "hybrid"


def test_calibrated_query_emphasizes_must_have_skills():
    priorities = HiringPriorities(
        must_have_skills=["Python"],
        preferred_skills=["AWS"],
        minimum_years_experience=5,
    )

    query = build_calibrated_query("Build ML systems.", priorities)

    assert query.count("Mandatory skills: Python") == 3
    assert "Preferred skills: AWS" in query
    assert "Minimum experience: 5 years" in query


def test_priority_alignment_scores_explicit_criteria():
    priorities = HiringPriorities(
        must_have_skills=["Python", "SQL"],
        preferred_skills=["AWS"],
        minimum_years_experience=5,
        seniority="senior",
    )

    score, concerns = priority_alignment(
        "Senior Python engineer who deployed services on AWS.",
        priorities.model_dump(mode="json"),
        {"years_experience": 6, "seniority": "senior"},
    )

    assert 0 < score < 1
    assert "one or more must-have skills lack resume evidence" in concerns


def test_final_score_includes_calibrated_priority_component():
    score, components, _ = final_score(0.01, 0.0, {}, calibrated_priority=0.8)

    assert 0 <= score <= 1
    assert components["calibrated_priority"] == 0.8


class FakeEncoder:
    def encode(self, texts, query=False):
        return [[0.0] * 384 for _ in texts]


class FakeReranker:
    def score(self, query, documents):
        return [0.0 for _ in documents]


class FakeRankingRepository:
    def __init__(self):
        self.query = ""
        self.saved_profile_version_id = ""

    def retrieve(self, query, embedding, limit):
        self.query = query
        return (
            ["CAND_0001"],
            ["CAND_0001"],
            {
                "CAND_0001": {
                    "chunks": ["Senior Python engineer with six years of experience."],
                    "metadata": {"years_experience": 6, "seniority": "senior"},
                }
            },
        )

    def get_candidate_chunks(self, candidate_ids):
        return {
            "CAND_0001": [
                {"ordinal": 0, "section": "experience", "content": "Built Python systems."}
            ]
        }

    def save_run(self, job_id, profile_version_id, jd, models, config, results):
        self.saved_profile_version_id = profile_version_id
        return "run-1"


def test_pipeline_ranks_with_and_records_approved_profile_version():
    pipeline = object.__new__(RankingPipeline)
    pipeline.encoder = FakeEncoder()
    pipeline.reranker = FakeReranker()
    pipeline.repo = FakeRankingRepository()
    pipeline.settings = type(
        "Settings",
        (),
        {
            "retrieval_limit": 10,
            "rerank_limit": 10,
            "rrf_k": 60,
            "embedding_model": "embedding",
            "reranker_model": "reranker",
        },
    )()
    job_profile = {
        "profile_version_id": "profile-1",
        "job_description": "Senior engineer for production systems.",
        "priorities": HiringPriorities(
            must_have_skills=["Python"],
            minimum_years_experience=5,
            seniority="senior",
        ).model_dump(mode="json"),
    }

    run_id, results = pipeline.rank("senior-ai-engineer", job_profile)

    assert run_id == "run-1"
    assert pipeline.repo.query == "Python"
    assert pipeline.repo.saved_profile_version_id == "profile-1"
    assert "calibrated_priority" in results[0].components
