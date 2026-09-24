from __future__ import annotations

import re
from typing import Protocol

from .schemas import (
    AvailabilityPriority,
    CompensationPriority,
    HiringPriorities,
    LocationPriority,
)

PREFERRED_MARKERS = ("preferred", "nice to have", "desirable", "a plus", "bonus")
MUST_MARKERS = ("must", "required", "requirement", "minimum", "essential")


class PriorityExtractor(Protocol):
    """Replaceable boundary for rule-based, customer-taxonomy, or LLM extraction."""

    def extract(self, job_description: str) -> HiringPriorities: ...


def _sentences(text: str) -> list[str]:
    return [
        part.strip(" \t\r\n•-*:") for part in re.split(r"\n+|(?<=[.!?])\s+", text) if part.strip()
    ]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _split_explicit_list(value: str) -> list[str]:
    return _unique(re.split(r"\s*[,;]\s*", value.strip(" .")))


def _labelled_values(text: str, labels: str) -> list[str]:
    pattern = rf"(?im)^\s*(?:{labels})\s*skills?\s*[:\-]\s*([^\n]+)$"
    return [item for value in re.findall(pattern, text) for item in _split_explicit_list(value)]


def _extract_requirements(text: str) -> tuple[list[str], list[str]]:
    must_have: list[str] = []
    preferred: list[str] = []
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if any(marker in lowered for marker in PREFERRED_MARKERS):
            preferred.append(sentence)
        elif any(marker in lowered for marker in MUST_MARKERS):
            must_have.append(sentence)
    return _unique(must_have), _unique(preferred)


def _extract_experience(text: str) -> float | None:
    values = [
        float(value)
        for value in re.findall(
            r"(?:minimum(?:\s+of)?|at\s+least)?\s*(\d+(?:\.\d+)?)\+?\s*years?",
            text,
            flags=re.IGNORECASE,
        )
    ]
    return max(values) if values else None


def _extract_label(text: str, label: str) -> str | None:
    match = re.search(rf"(?im)^\s*{label}\s*:\s*([^\n.;]+)", text)
    return match.group(1).strip() if match else None


def _extract_location(text: str) -> LocationPriority:
    lowered = text.lower()
    if "hybrid" in lowered:
        remote_policy = "hybrid"
    elif "remote" in lowered:
        remote_policy = "remote"
    elif "on-site" in lowered or "onsite" in lowered:
        remote_policy = "onsite"
    else:
        remote_policy = None
    value = _extract_label(text, "(?:location|based in)")
    locations = _split_explicit_list(value) if value else []
    return LocationPriority(locations=locations, remote_policy=remote_policy)


def _extract_availability(text: str) -> AvailabilityPriority:
    lowered = text.lower()
    if "immediate joiner" in lowered or "immediate start" in lowered:
        return AvailabilityPriority(max_notice_period_days=0)
    match = re.search(
        r"(?:notice period|join within|available within)\s*:?[ ]*(\d+)\s*(day|week|month)s?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return AvailabilityPriority()
    days = int(match.group(1)) * {"day": 1, "week": 7, "month": 30}[match.group(2).lower()]
    return AvailabilityPriority(max_notice_period_days=days)


def _extract_compensation(text: str) -> CompensationPriority:
    match = re.search(
        r"(USD|INR|EUR|GBP|AUD|CAD|[$₹€£])\s*([\d,.]+)\s*(?:-|to)\s*([\d,.]+)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return CompensationPriority()
    currency = {"$": "USD", "₹": "INR", "€": "EUR", "£": "GBP"}.get(
        match.group(1).upper(), match.group(1).upper()
    )
    tail = text[match.end() : match.end() + 30].lower()
    period = "hour" if "hour" in tail else "month" if "month" in tail else "year"
    return CompensationPriority(
        currency=currency,
        minimum=float(match.group(2).replace(",", "")),
        maximum=float(match.group(3).replace(",", "")),
        period=period,
    )


class RuleBasedPriorityExtractor:
    """Conservative, domain-neutral extraction for recruiter-reviewed drafts."""

    def extract(self, job_description: str) -> HiringPriorities:
        must_requirements, preferred_requirements = _extract_requirements(job_description)
        return HiringPriorities(
            must_have_skills=_labelled_values(
                job_description, "required|must-have|mandatory|essential"
            ),
            preferred_skills=_labelled_values(job_description, "preferred|nice-to-have|desirable"),
            must_have_requirements=must_requirements,
            preferred_requirements=preferred_requirements,
            minimum_years_experience=_extract_experience(job_description),
            seniority=_extract_label(job_description, "seniority"),
            location=_extract_location(job_description),
            availability=_extract_availability(job_description),
            compensation=_extract_compensation(job_description),
        )
