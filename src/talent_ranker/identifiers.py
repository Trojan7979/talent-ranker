from __future__ import annotations

import re


CANDIDATE_ID_PATTERN = re.compile(r"^CAND_([0-9]{4})$")
MIN_CANDIDATE_NUMBER = 1
MAX_CANDIDATE_NUMBER = 9_000


def format_candidate_id(candidate_number: int) -> str:
    """Return the stable external ID used by the 9,000-candidate pilot."""
    if not MIN_CANDIDATE_NUMBER <= candidate_number <= MAX_CANDIDATE_NUMBER:
        raise ValueError(
            f"candidate number must be between {MIN_CANDIDATE_NUMBER} "
            f"and {MAX_CANDIDATE_NUMBER}"
        )
    return f"CAND_{candidate_number:04d}"


def validate_candidate_id(candidate_id: str) -> str:
    """Validate and return a normalized pilot candidate ID."""
    normalized = candidate_id.strip().upper()
    match = CANDIDATE_ID_PATTERN.fullmatch(normalized)
    if match is None:
        raise ValueError("candidate ID must use the format CAND_0001")
    candidate_number = int(match.group(1))
    if not MIN_CANDIDATE_NUMBER <= candidate_number <= MAX_CANDIDATE_NUMBER:
        raise ValueError("candidate ID must be between CAND_0001 and CAND_9000")
    return normalized