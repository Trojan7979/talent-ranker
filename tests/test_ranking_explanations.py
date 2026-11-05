import json

from talent_ranker.ranking_explanations import RankingExplanationGenerator
from talent_ranker.source_eligibility import document_kind


def _evidence():
    return [{
        "category": "must_have_requirements",
        "requirement": "Build secure backend APIs",
        "status": "supported",
        "citations": [{"quote": "Built secure Python APIs for paying customers."}],
    }]


def _response(bullets):
    return {"choices": [{"finish_reason": "stop",
                         "message": {"content": json.dumps({"bullets": bullets})}}]}


def test_qwen_explanation_uses_validated_resume_quote():
    requests = []

    def post(request, timeout):
        requests.append(json.loads(request.data))
        return _response([{
            "text": "Built secure Python APIs for a customer-facing product.",
            "criterion_ids": [0],
            "quote": "Built secure Python APIs for paying customers.",
        }])

    generator = RankingExplanationGenerator(
        "https://models.example/v1/chat/completions", "secret", "Qwen/test", post=post,
    )
    result = generator.explain(_evidence())

    assert result == "- Built secure Python APIs for a customer-facing product."
    assert requests[0]["model"] == "Qwen/test"
    assert requests[0]["enable_thinking"] is False
    assert "Built secure Python APIs" in requests[0]["messages"][1]["content"]


def test_qwen_explanation_rejects_unquoted_claim_and_omits_empty_evidence():
    calls = []

    def post(request, timeout):
        calls.append(request)
        return _response([{
            "text": "Led a large engineering team for ten years.",
            "criterion_ids": [0], "quote": "Led a large engineering team",
        }])

    generator = RankingExplanationGenerator("https://models.example", "secret", "Qwen/test", post=post)
    assert generator.explain(_evidence()) == ""
    assert len(calls) == 2
    assert generator.explain([{"status": "not_evidenced", "citations": []}]) == ""
    assert len(calls) == 2


def test_qwen_explanation_rejects_invented_years():
    generator = RankingExplanationGenerator("https://models.example", "secret", "Qwen/test")
    facts = [{"quotes": ["Built secure Python APIs for paying customers."]}]
    raw = {"bullets": [{"text": "Built secure Python APIs for 8 years.",
                        "criterion_ids": [0],
                        "quote": "Built secure Python APIs for paying customers."}]}
    try:
        generator._validate(raw, facts)
    except ValueError as error:
        assert "numeric claim" in str(error)
    else:
        raise AssertionError("invented experience duration was accepted")


def test_qwen_explanation_keeps_valid_bullet_when_another_claim_is_unsupported():
    generator = RankingExplanationGenerator("https://models.example", "secret", "Qwen/test")
    valid = {"text": "Built secure Python APIs for paying customers.",
             "criterion_ids": [0], "quote": "Built secure Python APIs for paying customers."}
    unsupported = {"text": "Built secure Python APIs for 8 years.",
                   "criterion_ids": [0], "quote": valid["quote"]}
    facts = [{"quotes": [valid["quote"]]}]

    assert generator._validated_bullets({"bullets": [valid, unsupported]}, facts) == [valid["text"]]


def test_only_explicit_evaluation_documents_are_excluded_from_ranking():
    assert document_kind("SYNTHETIC EVALUATION DOCUMENT — NOT A JOB APPLICATION") == "evaluation"
    assert document_kind("Built Python APIs and managed cloud deployments") == "resume"
