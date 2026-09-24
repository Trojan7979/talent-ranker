import json

import pytest
from pydantic import SecretStr

from talent_ranker.calibration import configured_extractor
from talent_ranker.config import Settings
from talent_ranker.llm_priority_extraction import CalibrationError, LLMPriorityExtractor

JD = (
    "We need a senior data scientist who builds forecasting models in Python. "
    "Five years of experience is required. SQL is nice to have."
)


def response(facts):
    return {
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"facts": facts})}}]
    }


def fact(field, value, quote):
    return {"field": field, "value": value, "quote": quote}


def test_freeform_jd_uses_one_model_call_with_grounded_facts():
    requests = []
    facts = [
        fact("must_have_skills", "Python", "builds forecasting models in Python"),
        fact("preferred_skills", "SQL", "SQL is nice to have"),
        fact("minimum_years_experience", 5, "Five years of experience is required"),
        fact("seniority", "senior", "senior data scientist"),
    ]

    def post(request, timeout):
        requests.append(request)
        assert timeout == 12
        return response(facts)

    extractor = LLMPriorityExtractor(
        "https://example.test/v1/chat/completions", "secret", "model", 12, post
    )
    priorities = extractor.extract(JD)

    assert len(requests) == 1
    assert priorities.must_have_skills == ["Python"]
    assert priorities.preferred_skills == ["SQL"]
    assert priorities.minimum_years_experience == 5
    assert priorities.seniority == "senior"
    payload = json.loads(requests[0].data)
    assert payload["model"] == "model"
    assert payload["messages"][1]["content"].endswith(JD)


def test_ungrounded_quote_fails_without_creating_a_draft():
    extractor = LLMPriorityExtractor(
        "https://example.test",
        "secret",
        "model",
        post=lambda request, timeout: response([fact("must_have_skills", "Rust", "Rust required")]),
    )
    with pytest.raises(CalibrationError, match="invalid or ungrounded"):
        extractor.extract(JD)


def test_skill_must_appear_in_its_supporting_quote():
    extractor = LLMPriorityExtractor(
        "https://example.test",
        "secret",
        "model",
        post=lambda request, timeout: response(
            [fact("must_have_skills", "Rust", "builds forecasting models in Python")]
        ),
    )
    with pytest.raises(CalibrationError, match="invalid or ungrounded"):
        extractor.extract(JD)


def test_incomplete_response_fails_closed():
    extractor = LLMPriorityExtractor(
        "https://example.test",
        "secret",
        "model",
        post=lambda request, timeout: {
            "choices": [{"finish_reason": "length", "message": {"content": "{}"}}]
        },
    )
    with pytest.raises(CalibrationError, match="invalid or ungrounded"):
        extractor.extract(JD)


def test_empty_model_draft_is_not_silently_accepted():
    extractor = LLMPriorityExtractor(
        "https://example.test",
        "secret",
        "model",
        post=lambda request, timeout: response([]),
    )
    with pytest.raises(CalibrationError, match="invalid or ungrounded"):
        extractor.extract(JD)


def test_configured_extractor_records_model_without_exposing_key():
    settings = Settings(
        _env_file=None,
        calibration_extractor="llm",
        calibration_api_key=SecretStr("secret"),
        calibration_model="Qwen/Qwen3.8-27B",
    )
    extractor, metadata = configured_extractor(settings)
    assert isinstance(extractor, LLMPriorityExtractor)
    assert metadata["model"] == "Qwen/Qwen3.8-27B"
    assert "secret" not in str(metadata)


def test_llm_mode_requires_key():
    settings = Settings(_env_file=None, calibration_extractor="llm", calibration_api_key=None)
    with pytest.raises(CalibrationError, match="API key"):
        configured_extractor(settings)


def test_api_key_cannot_be_sent_over_plain_http():
    with pytest.raises(CalibrationError, match="HTTPS"):
        LLMPriorityExtractor("http://example.test", "secret", "model")


def test_missing_finish_reason_fails_closed():
    extractor = LLMPriorityExtractor(
        "https://example.test",
        "secret",
        "model",
        post=lambda request, timeout: {"choices": [{"message": {"content": "{}"}}]},
    )
    with pytest.raises(CalibrationError, match="invalid or ungrounded"):
        extractor.extract(JD)
