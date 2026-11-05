import logging

import numpy as np

from talent_ranker.access import RecruiterScope
from talent_ranker.criterion_matching import approved_criteria, match_criteria
from talent_ranker.embeddings import HostedReranker
from talent_ranker.evidence_assessment import EvidenceAssessmentError
from talent_ranker.pipeline import RankingPipeline
from talent_ranker.schemas import HiringPriorities
from talent_ranker.scoring_policy import CriterionRelevanceScoringPolicy


class Encoder:
    def encode(self, texts, query=False):
        return np.array([[1.0, 0.0] for _ in texts])


class Reranker:
    def __init__(self):
        self.queries = []

    def score_passages(self, query, passages):
        self.queries.append(query)
        return np.array([5.0 if "tenant-isolated" in text else -5.0 for text in passages])


class Assessor:
    def assess(self, matches):
        return [{"category": item["category"], "requirement": item["requirement"],
                 "status": "not_evidenced", "passage": None} for item in matches]


def _chunks():
    return {
        "A": [{"ordinal": 0, "section": "experience", "content": "Worked in retail sales.",
               "source_sha256": "a", "embedding": "[1,0]"}],
        "B": [{"ordinal": 0, "section": "experience",
               "content": "Built tenant-isolated applications for customers.",
               "source_sha256": "b", "embedding": "[1,0]"}],
    }


def test_criterion_passages_find_paraphrases_without_claiming_proof():
    priorities = HiringPriorities(
        must_have_requirements=["Experience designing multi-tenant SaaS architecture"],
    )
    reranker = Reranker()
    matches = match_criteria(approved_criteria(priorities), _chunks(), Encoder(), reranker)

    assert reranker.queries == ["Experience designing multi-tenant SaaS architecture"]
    assert matches["B"][0]["semantic_percentile"] == 1
    assert matches["A"][0]["semantic_percentile"] == 0


def test_role_work_can_be_retrieved_without_becoming_a_mandatory_score():
    priorities = HiringPriorities(role_responsibilities=["Build billing workflows"])
    criteria = approved_criteria(priorities)
    decision = CriterionRelevanceScoringPolicy().score([{
        "category": criteria[0].category, "semantic_percentile": 1.0,
    }])

    assert criteria[0].category == "role_responsibilities"
    assert decision.components["must_have_relevance"] == 0
    assert decision.components["role_relevance"] == 1

    explicit = HiringPriorities(
        must_have_skills=["Python"], role_responsibilities=["Build billing workflows"],
    )
    assert [item.category for item in approved_criteria(explicit)] == ["must_have_skills"]


def test_pipeline_uses_criterion_relevance_and_keeps_literal_evidence_separate(caplog):
    class Repo:
        def assert_embedding_ready(self, scope):
            pass

        def retrieve(self, query, vector, limit, scope):
            records = {cid: {"chunks": [row[0]["content"]], "metadata": {}}
                       for cid, row in _chunks().items()}
            return ["A", "B"], [], records

        def get_candidate_chunks(self, candidate_ids, scope):
            return _chunks()

        def save_run(self, *args):
            self.config = args[4]
            self.saved = getattr(self, "saved", 0) + 1
            return "run-1"

    pipeline = object.__new__(RankingPipeline)
    pipeline.repo, pipeline.encoder, pipeline.reranker = Repo(), Encoder(), Reranker()
    pipeline.scoring_policy = CriterionRelevanceScoringPolicy()
    pipeline.evidence_assessor = Assessor()
    pipeline.settings = type("Settings", (), {
        "retrieval_limit": 10, "rerank_limit": 10, "rrf_k": 60,
        "hosted_embedding_model": "embedding", "hosted_reranker_model": "reranker",
    })()
    priorities = HiringPriorities(
        must_have_requirements=["Experience designing multi-tenant SaaS architecture"],
    )
    with caplog.at_level(logging.INFO):
        _, results = pipeline.rank(
            "job-1", {"profile_version_id": "version-1", "job_description": "Company " * 2000,
                      "priorities": priorities.model_dump(mode="json")},
            scope=RecruiterScope("workspace", "actor", frozenset({"job-1"})),
        )

    assert [row.candidate_id for row in results] == ["B", "A"]
    assert results[0].requirement_evidence[0]["status"] == "not_evidenced"
    assert results[0].evidence == []
    assert pipeline.repo.config["evidence_assessment"] == "grounded_model_shadow"
    assert "Retrieval complete: 2 candidates found; 2 entering BGE reranking" in caplog.text
    assert "Cited resume evidence assessed for 2 candidates" in caplog.text

    class ReverseAssessor:
        def assess(self, matches):
            supported = "retail" in matches[0]["passages"][0]["content"]
            return [{"category": matches[0]["category"],
                     "requirement": matches[0]["requirement"],
                     "status": "supported" if supported else "not_evidenced",
                     "passage": "Worked in retail sales." if supported else None}]

    pipeline.evidence_assessor = ReverseAssessor()
    _, repeated = pipeline.rank(
        "job-1", {"profile_version_id": "version-1", "job_description": "Company " * 2000,
                  "priorities": priorities.model_dump(mode="json")},
        scope=RecruiterScope("workspace", "actor", frozenset({"job-1"})),
    )
    assert [row.candidate_id for row in repeated] == ["B", "A"]
    assert repeated[1].requirement_evidence[0]["status"] == "supported"

    class FailingAssessor:
        def assess(self, matches):
            raise EvidenceAssessmentError("invalid evidence")

    pipeline.evidence_assessor = FailingAssessor()
    _, recovered = pipeline.rank(
        "job-1", {"profile_version_id": "version-1", "job_description": "Company " * 2000,
                  "priorities": priorities.model_dump(mode="json")},
        scope=RecruiterScope("workspace", "actor", frozenset({"job-1"})),
    )
    assert [row.candidate_id for row in recovered] == ["B", "A"]
    assert recovered[0].requirement_evidence == []
    assert recovered[0].reasoning == "Evidence assessment was unavailable; review the resume."
    assert pipeline.repo.saved == 3


def test_reranker_fallback_bounds_a_passage_without_local_model_tokenizer():
    reranker = HostedReranker("https://models.example", "uncached-model")
    reranker.__dict__["tokenizer"] = None
    captured = []
    def score(query, passages):
        captured.extend(passages)
        return np.array([5.0 if "FINAL EVIDENCE" in text else 0.0 for text in passages])

    reranker.score = score

    scores, excerpts = reranker.score_passages_with_windows(
        "Python APIs", ["Built production APIs. " * 100 + " FINAL EVIDENCE"],
    )

    assert len(captured) > 1 and any("FINAL EVIDENCE" in value for value in captured)
    assert all(len(b"Python APIs" + value.encode()) <= 480 for value in captured)
    assert scores.tolist() == [5.0]
    assert "FINAL EVIDENCE" in excerpts[0]
