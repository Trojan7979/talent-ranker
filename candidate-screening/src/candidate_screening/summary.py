from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel

from .questions import JobQuestions, ScreeningAnswers

Outcome = Literal["proceed_to_interview", "needs_recruiter_review", "do_not_proceed"]


class ScreeningSummary(BaseModel):
    outcome: Outcome
    confirmed: list[str]
    missing: list[str]
    needs_verification: list[str]
    reason_codes: list[str]
    policy_version: Literal["screening-v1"] = "screening-v1"


def summarize(config: JobQuestions, answers: ScreeningAnswers, today: date) -> ScreeningSummary:
    """Evaluate self-reported answers using only approved, frozen job rules."""
    confirmed: list[str] = []
    missing: list[str] = []
    verification: list[str] = []
    reasons: list[str] = []
    hard_fail = False
    supplied = {item.requirement_id: item.confirmation for item in answers.qualifications}
    known = {item.id for item in config.must_haves}
    if unknown := set(supplied) - known:
        raise ValueError(f"unknown requirement IDs: {', '.join(sorted(unknown))}")

    for requirement in config.must_haves:
        answer = supplied.get(requirement.id)
        if answer is None:
            missing.append(f"qualification:{requirement.id}")
            reasons.append("MISSING_REQUIRED_ANSWER")
        elif answer == "yes":
            confirmed.append(f"candidate_confirmed:{requirement.id}")
        else:
            verification.append(f"qualification:{requirement.id}:{answer}")
            reasons.append("QUALIFICATION_UNCONFIRMED")
            if answer == "no" and requirement.hard_fail_on_no:
                hard_fail = True
                reasons.append("APPROVED_HARD_FAIL")

    if answers.interest is None:
        if config.require_interest:
            missing.append("interest")
            reasons.append("MISSING_REQUIRED_ANSWER")
    elif answers.interest == "not_interested":
        hard_fail = True
        reasons.append("INTEREST_DECLINED")
    elif answers.interest == "interested":
        confirmed.append("candidate_confirmed:interest")
    else:
        verification.append("interest")
        reasons.append("INTEREST_UNCERTAIN")

    availability = answers.availability
    if availability is None:
        if config.require_availability:
            missing.append("availability")
            reasons.append("MISSING_REQUIRED_ANSWER")
    elif availability.status != "answered":
        verification.append("availability")
        reasons.append("AVAILABILITY_UNCERTAIN")
    else:
        confirmed.append("candidate_reported:availability")
        if config.target_start_date and availability.earliest_start_date > config.target_start_date:
            verification.append("availability_after_target")
            reasons.append("AVAILABILITY_AFTER_TARGET")

    notice = answers.notice_period
    if notice is None:
        if config.require_notice_period:
            missing.append("notice_period")
            reasons.append("MISSING_REQUIRED_ANSWER")
    elif notice.status != "answered":
        verification.append("notice_period")
        reasons.append("NOTICE_UNCERTAIN")
    else:
        confirmed.append("candidate_reported:notice_period")
        if config.max_notice_days is not None and notice.days > config.max_notice_days:
            verification.append("notice_exceeds_limit")
            reasons.append("NOTICE_EXCEEDS_LIMIT")

    if (
        availability
        and notice
        and availability.status == notice.status == "answered"
        and availability.earliest_start_date < today + timedelta(days=notice.days)
    ):
        verification.append("availability_notice_conflict")
        reasons.append("AVAILABILITY_NOTICE_CONFLICT")

    salary = answers.salary
    if salary is None:
        if config.require_salary:
            missing.append("salary")
            reasons.append("MISSING_REQUIRED_ANSWER")
    elif salary.status != "answered":
        verification.append("salary")
        reasons.append("SALARY_UNCERTAIN")
    else:
        confirmed.append("candidate_reported:salary_expectation")
        if config.salary_maximum is not None:
            if salary.currency != config.salary_currency or salary.period != config.salary_period:
                verification.append("salary_not_comparable")
                reasons.append("SALARY_NOT_COMPARABLE")
            elif salary.minimum > config.salary_maximum:
                verification.append("salary_above_budget")
                reasons.append("SALARY_ABOVE_BUDGET")
            elif salary.maximum > config.salary_maximum:
                verification.append("salary_partly_above_budget")
                reasons.append("SALARY_RANGE_OVERLAPS_BUDGET")

    outcome: Outcome = (
        "do_not_proceed"
        if hard_fail
        else "needs_recruiter_review"
        if missing or verification
        else "proceed_to_interview"
    )
    return ScreeningSummary(
        outcome=outcome,
        confirmed=confirmed,
        missing=missing,
        needs_verification=verification,
        reason_codes=list(dict.fromkeys(reasons)),
    )
