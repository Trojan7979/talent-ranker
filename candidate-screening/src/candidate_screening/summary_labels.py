"""Human-facing wording for deterministic screening summary codes."""

from collections.abc import Mapping

OUTCOME_LABELS = {
    "proceed_to_interview": "Ready for interview",
    "needs_recruiter_review": "Needs recruiter review",
    "do_not_proceed": "Do not proceed",
}

FOLLOW_UP_LABELS = {
    "interest": "Interest needs clarification",
    "availability": "Start date needs clarification",
    "notice_period": "Notice period needs clarification",
    "salary": "Salary expectation needs clarification",
    "availability_after_target": "Start date is after the target date",
    "notice_exceeds_limit": "Notice period exceeds the job's limit",
    "availability_notice_conflict": "Start date and notice period may conflict",
    "salary_not_comparable": "Salary uses a different currency or pay period",
    "salary_above_budget": "Expected salary is above the job budget",
    "salary_partly_above_budget": "Expected range overlaps the job budget",
}


def _requirement(identifier: str, labels: Mapping[str, str]) -> str:
    return labels.get(identifier, identifier.replace("-", " ").replace("_", " ").title())


def _reported_requirement(label: str) -> str:
    if label.lower().startswith("experience "):
        return "Reports " + label[0].lower() + label[1:]
    if label.lower().startswith("strong understanding of "):
        return "Reports a " + label[0].lower() + label[1:]
    return f"Reports experience with {label}"


def readable_summary(
    confirmed: list[str], missing: list[str], verification: list[str],
    labels: Mapping[str, str],
) -> tuple[list[str], list[str], list[str]]:
    reported: list[str] = []
    unanswered: list[str] = []
    follow_up: list[str] = []
    for value in confirmed:
        if value.startswith("candidate_confirmed:"):
            name = value.removeprefix("candidate_confirmed:")
            reported.append("Interested in the role" if name == "interest"
                            else _reported_requirement(_requirement(name, labels)))
        elif value.startswith("candidate_reported:availability:"):
            reported.append(f"Earliest start: {value.rsplit(':', 1)[1]}")
        elif value.startswith("candidate_reported:notice_period_days:"):
            reported.append(f"Notice period: {value.rsplit(':', 1)[1]} days")
        elif value.startswith("candidate_reported:salary_expectation:"):
            reported.append("Expected salary: " + value.removeprefix(
                "candidate_reported:salary_expectation:"
            ))
        else:
            reported.append(value.replace("_", " "))
    for value in missing:
        if value.startswith("qualification:"):
            unanswered.append(f"{_requirement(value.split(':', 1)[1], labels)}: no answer")
        else:
            unanswered.append(value.replace("_", " ").capitalize() + ": no answer")
    for value in verification:
        if value.startswith("qualification:"):
            _, identifier, answer = value.split(":", 2)
            follow_up.append(f"{_requirement(identifier, labels)}: " + (
                "candidate said no" if answer == "no" else "candidate is unsure"
            ))
        else:
            follow_up.append(FOLLOW_UP_LABELS.get(value, value.replace("_", " ").capitalize()))
    return reported, unanswered, follow_up
