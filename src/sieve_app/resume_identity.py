"""Conservative contact extraction from a resume before ranking text is redacted."""

from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
NAME = re.compile(r"^[A-Za-z][A-Za-z .'-]{2,79}$")
JOB_TITLE = re.compile(
    r"^(?:job title|current role|current title|title|role)\s*:\s*(.{2,120})$",
    re.IGNORECASE,
)
NON_NAME_WORDS = {
    "resume", "curriculum", "vitae", "cv", "profile", "summary", "objective",
    "career", "professional", "experience", "education", "skills", "projects",
    "certifications", "engineer", "developer", "manager", "marketing", "sales",
    "challenging", "environment", "contact", "address", "email", "phone",
}


@dataclass(frozen=True)
class ResumeIdentity:
    name: str | None
    email: str | None
    job_title: str | None = None


def is_plausible_name(value: str) -> bool:
    """Reject headings and prose; uncertainty belongs in recruiter review."""
    words = value.split()
    return bool(
        NAME.fullmatch(value)
        and 2 <= len(words) <= 4
        and not value.endswith((".", "-", "'"))
        and all(word[0].isupper() for word in words)
        and not any(word.strip(".'-").casefold() in NON_NAME_WORDS for word in words)
    )


def corroborated_name(name: str, file_name: str, email: str | None) -> bool:
    """Require an independent filename or email clue for unattended legacy backfills."""
    if not is_plausible_name(name):
        return False
    words = [word.casefold() for word in re.findall(r"[A-Za-z]+", name)
             if word.casefold() not in {"dr", "mr", "ms", "mrs"}]
    if len(words) < 2:
        return False
    clues = [re.sub(r"[^a-z]", "", file_name.casefold())]
    if email:
        clues.append(re.sub(r"[^a-z]", "", email.partition("@")[0].casefold()))
    return any(all(word in clue for word in words) for clue in clues)


def extract_identity(text: str) -> ResumeIdentity:
    """Return only plausible header contact fields; never infer a match from a name."""
    header = text[:3000]
    emails = {match.group().casefold() for match in EMAIL.finditer(header)}
    email = next(iter(emails)) if len(emails) == 1 else None
    name = None
    for line in header.splitlines()[:12]:
        value = " ".join(line.strip().split())
        if is_plausible_name(value):
            name = value
            break
    job_title = next((match[1].strip() for line in header.splitlines()[:12]
                      if (match := JOB_TITLE.fullmatch(line.strip()))), None)
    return ResumeIdentity(name, email, job_title)
