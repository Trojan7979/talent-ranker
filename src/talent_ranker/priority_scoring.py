from __future__ import annotations

import re


def _requirement_coverage(text: str, requirements: list[str]) -> float:
    resume_terms = set(re.findall(r"[a-z0-9+#.]+", text.lower()))
    scores = []
    for requirement in requirements:
        terms = {
            term for term in re.findall(r"[a-z0-9+#.]+", requirement.lower()) if len(term) >= 3
        }
        scores.append(len(terms & resume_terms) / len(terms) if terms else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def priority_alignment(text: str, priorities: dict, metadata: dict) -> tuple[float, list[str]]:
    """Score explicit recruiter priorities without inferring protected characteristics."""
    lowered = text.lower()
    weighted_scores: list[tuple[float, float]] = []
    concerns: list[str] = []

    must_requirements = priorities.get("must_have_requirements") or []
    if must_requirements:
        coverage = _requirement_coverage(text, must_requirements)
        weighted_scores.append((0.40, coverage))
        if coverage < 0.6:
            concerns.append("one or more must-have requirements lack resume evidence")

    must_have = priorities.get("must_have_skills") or []
    if must_have:
        coverage = sum(skill.lower() in lowered for skill in must_have) / len(must_have)
        weighted_scores.append((0.40, coverage))
        if coverage < 1:
            concerns.append("one or more must-have skills lack resume evidence")

    preferred_requirements = priorities.get("preferred_requirements") or []
    if preferred_requirements:
        weighted_scores.append((0.15, _requirement_coverage(text, preferred_requirements)))

    preferred = priorities.get("preferred_skills") or []
    if preferred:
        matched = sum(skill.lower() in lowered for skill in preferred)
        weighted_scores.append((0.15, matched / len(preferred)))

    minimum_years = priorities.get("minimum_years_experience")
    if minimum_years is not None:
        candidate_years = metadata.get("years_experience")
        if candidate_years is None:
            weighted_scores.append((0.15, 0.5))
            concerns.append("minimum experience needs verification")
        else:
            denominator = max(float(minimum_years), 1.0)
            weighted_scores.append((0.15, min(1.0, float(candidate_years) / denominator)))

    seniority = priorities.get("seniority")
    if seniority:
        candidate_seniority = str(metadata.get("seniority", "")).lower()
        score = 1.0 if seniority.lower() in (candidate_seniority or lowered) else 0.5
        weighted_scores.append((0.10, score))
        if score < 1:
            concerns.append("seniority needs verification")

    location = priorities.get("location") or {}
    locations = location.get("locations") or []
    if locations:
        candidate_location = str(metadata.get("location", "")).lower()
        score = 1.0 if any(item.lower() in candidate_location for item in locations) else 0.5
        weighted_scores.append((0.05, score))
        if score < 1:
            concerns.append("location requirement needs verification")

    availability = priorities.get("availability") or {}
    max_notice = availability.get("max_notice_period_days")
    if max_notice is not None:
        notice = metadata.get("notice_period_days")
        score = 0.5 if notice is None else float(float(notice) <= float(max_notice))
        weighted_scores.append((0.025, score))
        if score < 1:
            concerns.append("availability requirement needs verification")

    compensation = priorities.get("compensation") or {}
    if compensation.get("maximum") is not None:
        expected = metadata.get("expected_compensation")
        score = (
            0.5 if expected is None else float(float(expected) <= float(compensation["maximum"]))
        )
        weighted_scores.append((0.025, score))
        if score < 1:
            concerns.append("compensation expectation needs verification")

    total_weight = sum(weight for weight, _ in weighted_scores)
    if not total_weight:
        return 0.5, ["calibrated profile has no scorable priorities"]
    score = sum(weight * value for weight, value in weighted_scores) / total_weight
    return score, concerns
