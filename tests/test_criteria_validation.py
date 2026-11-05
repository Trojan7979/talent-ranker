import pytest

from talent_ranker.criteria_validation import GroundedCriteriaValidator


def fact(field, value, quote):
    return {"field": field, "value": value, "quote": quote}


def validate(jd, facts):
    return GroundedCriteriaValidator().validate({"facts": facts}, jd)


def test_free_form_candidate_expectation_does_not_require_a_keyword():
    jd = "For this role, fluent Python and ownership of production APIs matter."
    priorities, _ = validate(jd, [fact("must_have_skills", "Python", jd)])
    assert priorities.must_have_skills == ["Python"]


def test_narrative_fact_can_paraphrase_an_exact_jd_quote():
    jd = "Own production billing and subscription flows."
    priorities, _ = validate(jd, [fact(
        "role_responsibilities", "Build monetization capabilities", jd,
    )])
    assert priorities.role_responsibilities == ["Build monetization capabilities"]


def test_grounded_requirement_can_use_natural_wording_from_exact_jd_quote():
    jd = "We need a procurement analyst experienced in vendor negotiations and contract management."
    priorities, _ = validate(jd, [fact(
        "must_have_requirements", "experienced in contract management",
        "experienced in vendor negotiations and contract management",
    )])
    assert priorities.must_have_requirements == ["experienced in contract management"]


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


@pytest.mark.parametrize(("jd", "field", "value", "quote"), [
    (
        "The ideal candidate has led regulatory audits across multiple jurisdictions.",
        "must_have_requirements", "led regulatory audits across multiple jurisdictions",
        "The ideal candidate has led regulatory audits across multiple jurisdictions",
    ),
    (
        "We seek someone who has managed clinical trial operations.",
        "must_have_requirements", "managed clinical trial operations",
        "someone who has managed clinical trial operations",
    ),
    (
        "Experience with SAP would be useful in this procurement role.",
        "preferred_skills", "SAP", "Experience with SAP would be useful",
    ),
])
def test_unstructured_candidate_expectations_are_domain_neutral(
    jd, field, value, quote,
):
    priorities, _ = validate(jd, [fact(field, value, quote)])

    assert value in getattr(priorities, field)


def test_role_work_is_retained_without_promoting_it_to_must_have():
    jd = ("Our platform uses Go. You will build billing workflows for customers. "
          "Required: Python expertise.")
    priorities, evidence = validate(jd, [
        fact("role_responsibilities", "build billing workflows for customers",
             "You will build billing workflows for customers"),
        fact("must_have_requirements", "Python expertise", "Required: Python expertise"),
    ])

    assert priorities.role_responsibilities == ["build billing workflows for customers"]
    assert priorities.must_have_requirements == ["Python expertise"]
    assert evidence[0]["quote"] in jd


def test_experience_range_uses_lower_bound_as_minimum():
    jd = "Candidates with 2-3 years experience are suitable."
    priorities, _ = validate(jd, [fact("minimum_years_experience", 2, jd)])
    assert priorities.minimum_years_experience == 2

    with pytest.raises(ValueError, match="lower bound"):
        validate(jd, [fact("minimum_years_experience", 3, jd)])


def test_normalized_remote_policy_accepts_grounded_nonliteral_label():
    jd = "Work from Home."
    priorities, evidence = validate(jd, [fact("remote_policy", "remote", jd)])
    assert priorities.location.remote_policy == "remote"
    assert evidence[0]["quote"] == jd

    with pytest.raises(ValueError, match="exact JD quote"):
        validate(jd, [fact("remote_policy", "remote", "Work from anywhere")])

    with pytest.raises(ValueError, match="remote_policy"):
        validate(jd, [fact("remote_policy", "unknown", jd)])
