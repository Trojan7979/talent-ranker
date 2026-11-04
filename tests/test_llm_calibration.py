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
        fact("must_have_skills", "Python", "We need a senior data scientist who builds forecasting models in Python"),
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


def test_deepseek_criteria_extraction_disables_extended_reasoning():
    requests = []
    extractor = LLMPriorityExtractor(
        "https://example.test/v1/chat/completions", "secret",
        "deepseek-ai/DeepSeek-V4-Pro",
        post=lambda request, timeout: (requests.append(request) or response([
            fact("must_have_skills", "Python", "We need a senior data scientist who builds forecasting models in Python")
        ])),
    )

    extractor.extract(JD)

    assert json.loads(requests[0].data)["enable_thinking"] is False


def test_fenced_json_is_parsed_but_facts_still_require_jd_quotes():
    wrapped = "```json\n" + json.dumps({"facts": [
        fact("must_have_skills", "Python", "We need a senior data scientist who builds forecasting models in Python")
    ]}) + "\n```"
    extractor = LLMPriorityExtractor(
        "https://example.test", "secret", "model",
        post=lambda request, timeout: {
            "choices": [{"finish_reason": "stop", "message": {"content": wrapped}}]
        },
    )

    assert extractor.extract(JD).must_have_skills == ["Python"]


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
        calibration_api_url="https://example.test/v1/chat/completions",
        calibration_model="Qwen/Qwen3.8-27B",
    )
    extractor, metadata = configured_extractor(settings)
    assert isinstance(extractor, LLMPriorityExtractor)
    assert metadata["model"] == "Qwen/Qwen3.8-27B"
    assert "secret" not in str(metadata)


def test_hybrid_uses_rules_for_structured_lists_without_model_call():
    settings = Settings(_env_file=None, calibration_extractor="hybrid", calibration_api_key=SecretStr("secret"), calibration_api_url="https://example.test/v1/chat/completions", calibration_model="test-model")
    extractor, metadata = configured_extractor(settings)
    extractor.llm.extract = lambda jd: pytest.fail("structured JD must not call model")
    result = extractor.extract("Engineer\nRequired skills: Python, FastAPI\nPreferred skills: AWS")
    assert result.must_have_skills == ["Python", "FastAPI"]
    assert result.preferred_skills == ["AWS"]
    assert metadata["method"] == "rules"


def test_hybrid_calls_model_for_freeform_requirement_even_with_other_skills():
    settings = Settings(_env_file=None, calibration_extractor="hybrid", calibration_api_key=SecretStr("secret"), calibration_api_url="https://example.test/v1/chat/completions", calibration_model="test-model")
    extractor, metadata = configured_extractor(settings)
    calls = []

    def model(jd):
        calls.append(jd)
        return LLMPriorityExtractor(
            "https://example.test", "secret", "model",
            post=lambda request, timeout: response([
                fact("must_have_skills", "FastAPI", "Must have FastAPI"),
            ]),
        ).extract(jd)

    extractor.llm.extract = model
    result = extractor.extract("Engineer\nPreferred skills: AWS\nMust have FastAPI")
    assert result.must_have_skills == ["FastAPI"]
    assert len(calls) == 1
    assert metadata["method"] == "llm"


def test_hybrid_does_not_treat_conjoined_skill_list_as_complete():
    settings = Settings(_env_file=None, calibration_extractor="hybrid", calibration_api_key=SecretStr("secret"), calibration_api_url="https://example.test/v1/chat/completions", calibration_model="test-model")
    extractor, _ = configured_extractor(settings)
    def unavailable(jd):
        raise CalibrationError("model unavailable")

    extractor.llm.extract = unavailable
    with pytest.raises(CalibrationError, match="model unavailable"):
        extractor.extract("Required skills: Python and FastAPI")


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


def test_grounded_facts_are_added_to_calibration_metadata():
    settings = Settings(
        _env_file=None, calibration_extractor="llm",
        calibration_api_key=SecretStr("secret"),
        calibration_api_url="https://example.test/v1/chat/completions",
        calibration_model="model",
    )
    extractor, metadata = configured_extractor(settings)
    extractor.post = lambda request, timeout: response([
        fact(
            "must_have_skills", "Python",
            "We need a senior data scientist who builds forecasting models in Python",
        )
    ])

    extractor.extract(JD)

    assert metadata["criteria_evidence"] == [{
        "field": "must_have_skills",
        "value": "Python",
        "quote": "We need a senior data scientist who builds forecasting models in Python",
    }]
