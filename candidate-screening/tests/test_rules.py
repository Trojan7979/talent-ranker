from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from candidate_screening.lifecycle import transition
from candidate_screening.questions import (
    AvailabilityAnswer,
    JobQuestions,
    MustHave,
    NoticeAnswer,
    QualificationAnswer,
    SalaryAnswer,
    ScreeningAnswers,
)
from candidate_screening.summary import summarize

TODAY = date(2026, 9, 24)


def config(**changes) -> JobQuestions:
    return JobQuestions(
        version=1,
        must_haves=[MustHave(id="python", text="Python")],
        max_notice_days=30,
        salary_maximum=Decimal(150000),
        salary_currency="USD",
        salary_period="year",
        **changes,
    )


def complete_answers(**changes) -> ScreeningAnswers:
    values = {
        "qualifications": [QualificationAnswer(requirement_id="python", confirmation="yes")],
        "interest": "interested",
        "availability": AvailabilityAnswer(
            status="answered", earliest_start_date=TODAY + timedelta(days=30)
        ),
        "notice_period": NoticeAnswer(status="answered", days=30),
        "salary": SalaryAnswer(
            status="answered",
            minimum=Decimal(110000),
            maximum=Decimal(140000),
            currency="USD",
            period="year",
        ),
    }
    values.update(changes)
    return ScreeningAnswers(**values)


def test_complete_aligned_answers_pass_without_claiming_capability() -> None:
    result = summarize(config(), complete_answers(), TODAY)
    assert result.outcome == "proceed_to_interview"
    assert "candidate_confirmed:python" in result.confirmed
    assert result.needs_verification == []


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"salary": None}, "MISSING_REQUIRED_ANSWER"),
        ({"interest": "unsure"}, "INTEREST_UNCERTAIN"),
        ({"qualifications": []}, "MISSING_REQUIRED_ANSWER"),
        (
            {"qualifications": [QualificationAnswer(requirement_id="python", confirmation="no")]},
            "QUALIFICATION_UNCONFIRMED",
        ),
        ({"notice_period": NoticeAnswer(status="answered", days=60)}, "NOTICE_EXCEEDS_LIMIT"),
        (
            {"availability": AvailabilityAnswer(status="answered", earliest_start_date=TODAY)},
            "AVAILABILITY_NOTICE_CONFLICT",
        ),
        (
            {
                "salary": SalaryAnswer(
                    status="answered",
                    minimum=Decimal(110000),
                    maximum=Decimal(140000),
                    currency="EUR",
                    period="year",
                )
            },
            "SALARY_NOT_COMPARABLE",
        ),
        (
            {
                "salary": SalaryAnswer(
                    status="answered",
                    minimum=Decimal(140000),
                    maximum=Decimal(160000),
                    currency="USD",
                    period="year",
                )
            },
            "SALARY_RANGE_OVERLAPS_BUDGET",
        ),
    ],
)
def test_ambiguous_or_incomplete_answers_need_review(changes, reason) -> None:
    result = summarize(config(), complete_answers(**changes), TODAY)
    assert result.outcome == "needs_recruiter_review"
    assert reason in result.reason_codes


def test_no_interest_takes_precedence_over_missing_answers() -> None:
    result = summarize(config(), ScreeningAnswers(interest="not_interested"), TODAY)
    assert result.outcome == "do_not_proceed"
    assert "INTEREST_DECLINED" in result.reason_codes
    assert "MISSING_REQUIRED_ANSWER" in result.reason_codes


def test_hard_fail_requires_job_configuration() -> None:
    rules = config().model_copy(
        update={"must_haves": [MustHave(id="python", text="Python", hard_fail_on_no=True)]}
    )
    answer = complete_answers(
        qualifications=[QualificationAnswer(requirement_id="python", confirmation="no")]
    )
    assert summarize(rules, answer, TODAY).outcome == "do_not_proceed"


def test_unknown_or_duplicate_requirement_is_invalid() -> None:
    with pytest.raises(ValueError, match="unknown requirement"):
        summarize(
            config(),
            complete_answers(
                qualifications=[QualificationAnswer(requirement_id="rust", confirmation="yes")]
            ),
            TODAY,
        )
    with pytest.raises(ValidationError, match="unique"):
        ScreeningAnswers(
            qualifications=[
                QualificationAnswer(requirement_id="python", confirmation="yes"),
                QualificationAnswer(requirement_id="python", confirmation="no"),
            ]
        )


@pytest.mark.parametrize(
    "answer",
    [
        {"status": "answered", "minimum": 12, "maximum": 11, "currency": "USD", "period": "year"},
        {"status": "answered", "minimum": 12, "maximum": 13, "currency": "US", "period": "year"},
        {"status": "unsure", "minimum": 12},
    ],
)
def test_invalid_salary_input_rejected(answer) -> None:
    with pytest.raises(ValidationError):
        SalaryAnswer.model_validate(answer)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (None, "sent"),
        ("sent", "opened"),
        ("sent", "started"),
        ("opened", "started"),
        ("started", "completed"),
        ("started", "expired"),
    ],
)
def test_valid_transitions(current, target) -> None:
    assert transition(current, target) == target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (None, "started"),
        ("sent", "completed"),
        ("opened", "completed"),
        ("expired", "started"),
        ("completed", "expired"),
        ("declined", "opened"),
    ],
)
def test_invalid_transitions(current, target) -> None:
    with pytest.raises(ValueError, match="cannot transition"):
        transition(current, target)
