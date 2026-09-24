from __future__ import annotations

import re
from dataclasses import dataclass

@dataclass(frozen=True)
class PiiFinding:
    kind: str
    start: int
    end: int

_EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+",
    re.IGNORECASE,
)
_PROFILE_URL_PATTERN = re.compile(
    r"(?:https?://|www\.|linkedin\.com/in/)[^\s<>()]+[^\s<>().,;:!?]",
    re.IGNORECASE,
)
_PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[\s.-])?(?:\(\d{2,5}\)[\s.-]?)?"
    r"\d{3,5}[\s.-]\d{3,5}(?:[\s.-]\d{3,5})?(?!\w)"
    r"|(?<!\w)\+?\d{10,15}(?!\w)"
)
_PATTERNS = (
    ("email", _EMAIL_PATTERN, "[REDACTED_EMAIL]"),
    ("profile_url", _PROFILE_URL_PATTERN, "[REDACTED_PROFILE_URL]"),
    ("phone", _PHONE_PATTERN, "[REDACTED_PHONE]"),
)

def detect_pii(text: str) -> list[PiiFinding]:
    """Locate supported contact identifiers without retaining their values."""
    findings = [
        PiiFinding(kind, match.start(), match.end())
        for kind, pattern, _ in _PATTERNS
        for match in pattern.finditer(text)
    ]
    return sorted(findings, key=lambda finding: (finding.start, finding.end))

def redact_pii(text: str) -> str:
    """Replace supported contact identifiers with explicit, non-sensitive labels."""
    redacted = text
    for _, pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted