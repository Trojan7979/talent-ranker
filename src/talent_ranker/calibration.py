from __future__ import annotations

import re

from .config import Settings
from .llm_priority_extraction import PROMPT_VERSION, LLMPriorityExtractor
from .priority_extraction import PriorityExtractor, RuleBasedPriorityExtractor
from .schemas import HiringPriorities, HiringPriorityOverrides

_SKILL_LABEL = re.compile(
    r"^(?:required|must-have|mandatory|essential|preferred|nice-to-have|desirable) skills?\s*[:\-]",
    re.IGNORECASE,
)
_STRUCTURED_CRITERION = re.compile(
    r"^(?:(?:required|must-have|mandatory|essential|preferred|nice-to-have|desirable) skills?\s*[:\-]"
    r"|(?:seniority|location|based in)\s*:"
    r"|(?:minimum(?: of)?|at least)\s+\d+(?:\.\d+)?\+?\s+years?\b"
    r"|(?:remote|hybrid|on-site|onsite)\s+role\b"
    r"|(?:notice period|join within|available within)\s*:?[ ]*\d+\s*(?:day|week|month)s?\b"
    r"|(?:USD|INR|EUR|GBP|AUD|CAD|[$₹€£])\s*[\d,.]+\s*(?:-|to)\s*[\d,.]+)",
    re.IGNORECASE,
)


def _rules_cover_jd(jd: str, priorities: HiringPriorities) -> bool:
    """Only skip the model when the JD uses fields the rules can account for."""
    if not priorities.must_have_skills and not priorities.preferred_skills:
        return False
    for index, line in enumerate(jd.splitlines()):
        value = line.strip(" \t-*•")
        if not value:
            continue
        if _STRUCTURED_CRITERION.match(value):
            skill_label = _SKILL_LABEL.match(value)
            if skill_label and re.search(
                r"\b(?:and|or)\b|\.\s+", value[skill_label.end():], re.IGNORECASE
            ):
                return False  # The rules split only comma/semicolon lists.
            continue
        if (index == 0 and len(value.split()) <= 6
                and not re.search(r"[:;]|\b(?:must|required|preferred|need|experience|skills?|with)\b", value, re.IGNORECASE)):
            continue  # A short role title is not itself an extractable criterion.
        return False
    return True


class HybridPriorityExtractor:
    """Use cheap, deterministic parsing for complete structured JDs; otherwise use the model."""

    def __init__(self, llm: LLMPriorityExtractor, metadata: dict):
        self.llm = llm
        self.metadata = metadata
        self.rules = RuleBasedPriorityExtractor()

    def extract(self, job_description: str) -> HiringPriorities:
        draft = self.rules.extract(job_description)
        if _rules_cover_jd(job_description, draft):
            self.metadata["method"] = "rules"
            return draft
        result = self.llm.extract(job_description)
        self.metadata["method"] = "llm"
        return result


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
    metadata = {
        "method": "llm" if settings.calibration_extractor == "llm" else "hybrid",
        "model": settings.calibration_model,
        "prompt_version": PROMPT_VERSION,
    }
    if settings.calibration_extractor == "hybrid":
        return HybridPriorityExtractor(extractor, metadata), metadata
    return extractor, metadata


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
