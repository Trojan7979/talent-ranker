from __future__ import annotations

from .schemas import HiringPriorities


def assess_metadata(priorities: HiringPriorities, metadata: dict) -> tuple[list[dict], int, int]:
    """Assess only supplied, job-related metadata; missing values stay unknown."""
    checks: list[tuple[str, str, object, object]] = [
        (
            "minimum_years_experience",
            "minimum_years_experience",
            priorities.minimum_years_experience,
            metadata.get("years_experience"),
        ),
        ("seniority", "seniority", priorities.seniority, metadata.get("seniority")),
        (
            "availability",
            "max_notice_period_days",
            priorities.availability.max_notice_period_days,
            metadata.get("notice_period_days"),
        ),
        (
            "compensation",
            "maximum",
            priorities.compensation.maximum,
            metadata.get("expected_compensation"),
        ),
    ]
    locations = priorities.location.locations
    if locations:
        checks.append(("location", "locations", locations, metadata.get("location")))
    assessments: list[dict] = []
    earned = possible = 0
    for category, requirement, target, value in checks:
        if target is None:
            continue
        if category == "compensation" and (
            not priorities.compensation.currency
            or not priorities.compensation.period
            or metadata.get("compensation_currency") != priorities.compensation.currency
            or metadata.get("compensation_period") != priorities.compensation.period
        ):
            value = None
        supported = None
        if value is not None:
            try:
                if category in {"minimum_years_experience", "availability", "compensation"}:
                    number = float(value)
                    supported = (
                        number >= float(target)
                        if category == "minimum_years_experience"
                        else number <= float(target)
                    )
                elif category == "location":
                    supported = any(item.casefold() in str(value).casefold() for item in target)
                else:
                    supported = str(target).casefold() == str(value).casefold()
            except (TypeError, ValueError):
                supported = None
        status = (
            "not_evidenced"
            if supported is None
            else "reported_match"
            if supported
            else "reported_mismatch"
        )
        if supported is not None:
            possible += 1
            earned += int(supported)
        assessments.append(
            {
                "category": category,
                "requirement": {requirement: target},
                "status": status,
                "source": "candidate_metadata" if value is not None else None,
                "reported_value": value,
            }
        )
    return assessments, earned, possible
