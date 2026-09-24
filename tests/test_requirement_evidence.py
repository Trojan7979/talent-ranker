from talent_ranker.candidate_retrieval import retrieve_pool
from talent_ranker.evaluation import evaluate_run
from talent_ranker.metadata_evidence import assess_metadata
from talent_ranker.requirement_evidence import assess_requirements, summarize_requirements
from talent_ranker.schemas import HiringPriorities


def test_experience_evidence_without_skills_heading():
    priorities = HiringPriorities(must_have_skills=["Python", "SQL"])
    chunks = [
        {"ordinal": 0, "section": "experience", "content": "Built Python services."},
        {"ordinal": 1, "section": "summary", "content": "Engineering leader."},
    ]

    evidence, score, concerns = assess_requirements(priorities, chunks)

    assert evidence[0]["status"] == "experience_evidence"
    assert evidence[0]["section"] == "experience"
    assert evidence[0]["chunk_ordinal"] == 0
    assert evidence[1]["status"] == "not_evidenced"
    assert evidence[1]["passage"] is None
    assert score == 0.5
    assert concerns
    assert "Python: experience evidence" in summarize_requirements(evidence, concerns)
    assert "SQL: not evidenced" in summarize_requirements(evidence, concerns)


def test_skills_list_receives_less_credit_than_experience():
    priorities = HiringPriorities(must_have_skills=["Python"])
    chunks = [{"ordinal": 0, "section": "skills", "content": "Python, SQL"}]
    evidence, score, _ = assess_requirements(priorities, chunks)
    assert evidence[0]["status"] == "listed"
    assert score == 0.5


def test_retrieval_unions_requirement_queries_before_shortlist():
    class Encoder:
        def encode(self, texts, query=False):
            return [[0.0] for _ in texts]

    class Repo:
        def retrieve(self, query, vector, limit):
            cid = "A" if "Mandatory" in query else "B"
            return [cid], [], {cid: {"chunks": [query], "metadata": {}}}

    priorities = HiringPriorities(must_have_skills=["Python"])
    ordered, scores, records, trace = retrieve_pool(
        Repo(), Encoder(), "Mandatory skills: Python", priorities, 10, 60
    )
    assert ordered == ["A", "B"]
    assert set(scores) == set(records) == {"A", "B"}
    assert len(trace) == 2


def test_offline_evaluation_exposes_retrieval_miss():
    metrics = evaluate_run(
        {"A": True, "B": True},
        [{"dense_ids": ["A"], "lexical_ids": []}],
        ["A"],
        [{"candidate_id": "A", "requirement_evidence": []}],
        k=1,
    )
    assert metrics["union_recall"] == 0.5
    assert metrics["shortlist_recall"] == 0.5
    assert metrics["precision_at_k"] == 1.0


def test_metadata_unknown_does_not_become_mismatch():
    priorities = HiringPriorities(minimum_years_experience=5)
    evidence, earned, possible = assess_metadata(priorities, {})
    assert evidence[0]["status"] == "not_evidenced"
    assert (earned, possible) == (0, 0)


def test_compensation_requires_matching_units():
    priorities = HiringPriorities(
        compensation={"maximum": 100000, "currency": "USD", "period": "year"}
    )
    evidence, earned, possible = assess_metadata(
        priorities,
        {"expected_compensation": 90000, "compensation_currency": "INR"},
    )
    assert evidence[0]["status"] == "not_evidenced"
    assert (earned, possible) == (0, 0)
