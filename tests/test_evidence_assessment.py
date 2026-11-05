import json

import pytest

from talent_ranker.evidence_assessment import EvidenceAssessmentError, EvidenceAssessor


def _match(text="Built tenant-isolated SaaS platforms for customers."):
    return {
        "category": "must_have_requirements",
        "requirement": "Design multi-tenant SaaS platforms",
        "semantic_percentile": 0.8,
        "passages": [{
            "ordinal": 3, "section": "experience", "source_sha256": "abc",
            "content": text,
        }],
    }


def _response(rows):
    return {"choices": [{
        "finish_reason": "stop",
        "message": {"content": json.dumps({"assessments": rows})},
    }]}


def test_assessor_accepts_only_exact_resume_quotes_and_keeps_source_ids():
    captured = []

    def post(request, timeout):
        captured.append(json.loads(request.data))
        return _response([{
            "id": 0, "status": "supported", "evidence": [{
                "passage_id": "0.0", "quote": "Built tenant-isolated SaaS platforms",
            }],
        }])

    assessor = EvidenceAssessor(
        "https://models.example/v1/chat/completions", "secret", "deepseek-ai/DeepSeek-V4-Pro",
        post=post,
    )
    rows = assessor.assess([_match(
        "Contact me at applicant@example.com. Built tenant-isolated SaaS platforms for customers."
    )])

    assert rows[0]["status"] == "supported"
    assert rows[0]["passage"] == "Built tenant-isolated SaaS platforms"
    assert rows[0]["chunk_ordinal"] == 3
    assert rows[0]["source_sha256"] == "abc"
    assert captured[0]["enable_thinking"] is False
    assert "Design multi-tenant SaaS platforms" in captured[0]["messages"][1]["content"]
    assert "applicant@example.com" not in captured[0]["messages"][1]["content"]


def test_assessor_retries_invalid_quote_then_marks_criterion_unavailable():
    calls = []

    def post(request, timeout):
        calls.append(json.loads(request.data))
        return _response([{
            "id": 0, "status": "supported", "evidence": [{
                "passage_id": "0.0", "quote": "Led a 200-person engineering team",
            }],
        }])

    assessor = EvidenceAssessor("https://models.example", "secret", "deepseek", post=post)
    result = assessor.assess([_match()])

    assert len(calls) == 2
    assert "failed validation" in calls[1]["messages"][-1]["content"]
    assert result[0]["status"] == "unavailable"
    assert result[0]["citations"] == []


def test_assessor_salvages_valid_criteria_when_one_batch_quote_is_invalid():
    calls = []
    def post(request, timeout):
        calls.append(request)
        criteria = json.loads(json.loads(request.data)["messages"][1]["content"])["criteria"]
        if len(criteria) == 2:
            return _response([{"id": 0, "status": "supported", "evidence": [{
                "passage_id": "0.0", "quote": "Invented work experience",
            }]}, {"id": 1, "status": "not_evidenced", "evidence": []}])
        if criteria[0]["criterion"].startswith("Design multi-tenant"):
            return _response([{"id": 0, "status": "supported", "evidence": [{
                "passage_id": "0.0", "quote": "Invented work experience",
            }]}])
        return _response([{"id": 0, "status": "not_evidenced", "evidence": []}])

    assessor = EvidenceAssessor("https://models.example", "secret", "deepseek", post=post)
    other = _match("Developed Python APIs.")
    other["requirement"] = "Build Python APIs"
    result = assessor.assess([_match(), other])

    assert [item["status"] for item in result] == ["unavailable", "not_evidenced"]
    assert len(calls) == 1


def test_assessor_rejects_missing_criteria_and_cross_criterion_citations():
    assessor = EvidenceAssessor("https://models.example", "secret", "deepseek")
    matches = [_match(), _match("Developed Python APIs.")]
    passages = {
        "0.0": matches[0]["passages"][0],
        "1.0": matches[1]["passages"][0],
    }
    with pytest.raises(ValueError, match="no assessments"):
        assessor._validate({"assessments": []}, matches, passages)
    result = assessor._validate({"assessments": [
        {"id": 0, "status": "supported", "evidence": [{
            "passage_id": "1.0", "quote": "Developed Python APIs",
        }]},
        {"id": 1, "status": "not_evidenced", "evidence": []},
    ]}, matches, passages)
    assert [item["status"] for item in result] == ["unavailable", "not_evidenced"]


def test_assessor_preserves_exact_source_span_when_pdf_whitespace_differs():
    assessor = EvidenceAssessor("https://models.example", "secret", "deepseek")
    match = _match("Built scalable\nproduction APIs for customers.")
    rows = assessor._validate({"assessments": [{
        "id": 0, "status": "partial", "evidence": [{
            "passage_id": "0.0", "quote": "Built scalable production APIs",
        }],
    }]}, [match], {"0.0": match["passages"][0]})

    assert rows[0]["passage"] == "Built scalable\nproduction APIs"


def test_assessor_recovers_wrong_passage_id_only_with_same_criterion_quote():
    assessor = EvidenceAssessor("https://models.example", "secret", "deepseek")
    match = _match("Built secure Python APIs for customers.")
    rows = assessor._validate({"assessments": [{
        "id": 0, "status": "supported", "evidence": [{
            "passage_id": "9.9", "quote": "Built secure Python APIs",
        }],
    }]}, [match], {"0.0": match["passages"][0]})
    assert rows[0]["passage"] == "Built secure Python APIs"


def test_assessor_batches_long_criterion_lists_and_preserves_order():
    calls = []

    def post(request, timeout):
        criteria = json.loads(json.loads(request.data)["messages"][1]["content"])["criteria"]
        calls.append(len(criteria))
        return _response([{"id": item["id"], "status": "not_evidenced", "evidence": []}
                          for item in criteria])

    assessor = EvidenceAssessor("https://models.example", "secret", "deepseek", post=post)
    result = assessor.assess([_match() for _ in range(9)])

    assert calls == [4, 4, 1]
    assert len(result) == 9
    assert all(item["status"] == "not_evidenced" for item in result)
