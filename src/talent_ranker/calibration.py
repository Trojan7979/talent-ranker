from __future__ import annotations

from .config import Settings
from .llm_priority_extraction import PROMPT_VERSION, LLMPriorityExtractor
from .priority_extraction import PriorityExtractor, RuleBasedPriorityExtractor
from .schemas import HiringPriorities, HiringPriorityOverrides


def _merge(base: HiringPriorities, overrides: HiringPriorityOverrides | None) -> HiringPriorities:
    if overrides is None:
        return base
    values = base.model_dump()
    values.update(overrides.model_dump(exclude_none=True))
    return HiringPriorities.model_validate(values)


def calibrate_job_description(
    job_description: str,
    overrides: HiringPriorityOverrides | None = None,
    extractor: PriorityExtractor | None = None,
) -> HiringPriorities:
    """Create an editable draft; extraction never constitutes recruiter approval."""
    draft = (extractor or RuleBasedPriorityExtractor()).extract(job_description)
    return _merge(draft, overrides)


def configured_extractor(settings: Settings) -> tuple[PriorityExtractor, dict]:
    if settings.calibration_extractor == "rules":
        return RuleBasedPriorityExtractor(), {"method": "rules"}
    key = settings.calibration_api_key
    extractor = LLMPriorityExtractor(
        settings.calibration_api_url,
        key.get_secret_value() if key else "",
        settings.calibration_model,
        settings.calibration_timeout_seconds,
    )
    return extractor, {
        "method": "llm",
        "model": settings.calibration_model,
        "prompt_version": PROMPT_VERSION,
    }


def build_calibrated_query(job_description: str, priorities: HiringPriorities) -> str:
    """Create a weighted textual query consumed by dense and lexical retrieval."""
    parts = [job_description.strip()]
    if priorities.must_have_requirements:
        required = "\n".join(priorities.must_have_requirements)
        parts.extend([f"Mandatory requirements:\n{required}"] * 2)
    if priorities.must_have_skills:
        must = ", ".join(priorities.must_have_skills)
        parts.extend([f"Mandatory skills: {must}"] * 3)
    if priorities.preferred_requirements:
        preferred = "\n".join(priorities.preferred_requirements)
        parts.append(f"Preferred requirements:\n{preferred}")
    if priorities.preferred_skills:
        parts.append(f"Preferred skills: {', '.join(priorities.preferred_skills)}")
    if priorities.minimum_years_experience is not None:
        parts.append(f"Minimum experience: {priorities.minimum_years_experience:g} years")
    if priorities.seniority:
        parts.append(f"Seniority: {priorities.seniority}")
    if priorities.location.locations:
        parts.append(f"Locations: {', '.join(priorities.location.locations)}")
    if priorities.location.remote_policy:
        parts.append(f"Work arrangement: {priorities.location.remote_policy}")
    if priorities.availability.max_notice_period_days is not None:
        parts.append(
            f"Maximum notice period: {priorities.availability.max_notice_period_days} days"
        )
    compensation = priorities.compensation
    if compensation.minimum is not None or compensation.maximum is not None:
        value = (
            f"{compensation.currency or ''} {compensation.minimum or ''}-"
            f"{compensation.maximum or ''} {compensation.period or ''}"
        )
        parts.append(f"Compensation: {value.strip()}")
    return "\n".join(parts)
