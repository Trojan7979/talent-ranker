import pytest

from talent_ranker.criteria_validation import GroundedCriteriaValidator


def fact(field, value, quote):
    return {"field": field, "value": value, "quote": quote}


def validate(jd, facts):
    return GroundedCriteriaValidator().validate({"facts": facts}, jd)


def test_must_have_requires_explicit_requirement_language():
    jd = "We build forecasting models in Python."
    with pytest.raises(ValueError, match="requirement language"):
        validate(jd, [fact("must_have_skills", "Python", jd)])


def test_requirement_value_cannot_be_an_ungrounded_paraphrase():
    jd = "Five years of experience is required."
    with pytest.raises(ValueError, match="not present"):
        validate(jd, [fact(
            "must_have_requirements", "Production machine learning expertise", jd,
        )])


def test_conflicting_importance_fails_closed():
    jd = "Required: Python. Python is also nice to have."
    with pytest.raises(ValueError, match="conflicting importance"):
        validate(jd, [
            fact("must_have_skills", "Python", "Required: Python"),
            fact("preferred_skills", "Python", "Python is also nice to have"),
        ])


def test_alternative_skills_remain_a_grouped_requirement():
    jd = "Required qualifications: Python or Java."
    priorities, evidence = validate(jd, [
        fact("must_have_skills", "Python", jd),
        fact("must_have_skills", "Java", jd),
    ])

    assert priorities.must_have_skills == []
    assert priorities.must_have_requirements == [jd]
    assert len(evidence) == 1


def test_section_heading_can_classify_following_requirement():
    jd = "Required qualifications:\nPython\nPreferred qualifications:\nAWS"
    priorities, _ = validate(jd, [
        fact("must_have_skills", "Python", "Python"),
        fact("preferred_skills", "AWS", "AWS"),
    ])

    assert priorities.must_have_skills == ["Python"]
    assert priorities.preferred_skills == ["AWS"]


def test_duplicate_model_facts_are_retained_once():
    jd = "We need an engineer who builds forecasting models in Python."
    priorities, evidence = validate(jd, [
        fact("must_have_skills", "Python", jd),
        fact("must_have_skills", "Python", jd),
    ])
    assert priorities.must_have_skills == ["Python"]
    assert len(evidence) == 1


def test_company_technology_stack_is_not_a_grounded_must_have():
    jd = "Our product platform uses Python, React, and PostgreSQL."
    with pytest.raises(ValueError, match="requirement language"):
        validate(jd, [fact("must_have_skills", "Python", jd)])


def test_skill_is_not_counted_twice_when_same_quote_is_a_requirement():
    jd = "Preferred: Experience with Redis and event-driven architectures."
    priorities, evidence = validate(jd, [
        fact("preferred_skills", "Redis", jd),
        fact("preferred_requirements", "Experience with Redis and event-driven architectures", jd),
    ])

    assert priorities.preferred_skills == []
    assert priorities.preferred_requirements == [
        "Experience with Redis and event-driven architectures"
    ]
    assert len(evidence) == 1
