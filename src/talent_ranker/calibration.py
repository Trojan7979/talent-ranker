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
_EXPERIENCE_DURATION = re.compile(
    r"\b(?:minimum(?:\s+of)?|at\s+least)?\s*\d+(?:\.\d+)?\+?\s*"
    r"(?:(?:-|–|to)\s*\d+(?:\.\d+)?\+?\s*)?years?\b(?:\s+of\s+experience|\s+experience)?",
    re.IGNORECASE,
)


def remove_experience_durations(text: str) -> str:
    """Keep role context while making numeric tenure informational to ranking."""
    return re.sub(r"\s+", " ", _EXPERIENCE_DURATION.sub(" ", text)).strip()


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
            self.metadata["criteria_evidence"] = self.rules.last_facts
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
        metadata = {"method": "rules", "prompt_version": PROMPT_VERSION}
        return RuleBasedPriorityExtractor(metadata), metadata
    key = settings.calibration_api_key
    metadata = {
        "method": "llm" if settings.calibration_extractor == "llm" else "hybrid",
        "model": settings.calibration_model,
        "prompt_version": PROMPT_VERSION,
    }
    extractor = LLMPriorityExtractor(
        settings.calibration_api_url,
        key.get_secret_value() if key else "",
        settings.calibration_model,
        settings.calibration_timeout_seconds,
        metadata=metadata,
    )
    if settings.calibration_extractor == "hybrid":
        return HybridPriorityExtractor(extractor, metadata), metadata
    return extractor, metadata


def build_calibrated_query(job_description: str, priorities: HiringPriorities) -> str:
    """Use concise qualifications for broad retrieval; search each criterion separately."""
    values = [
        *priorities.must_have_requirements,
        *priorities.must_have_skills,
        *priorities.preferred_requirements,
        *priorities.preferred_skills,
    ]
    if not values:
        values = priorities.role_responsibilities
    parts = []
    for value in filter(None, map(remove_experience_durations, values)):
        if len("; ".join([*parts, value])) > 400:
            break
        parts.append(value)
    return "; ".join(parts) if parts else remove_experience_durations(job_description)[:400]
