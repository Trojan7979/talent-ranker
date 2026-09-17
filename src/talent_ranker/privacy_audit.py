from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .privacy import detect_pii


@dataclass(frozen=True)
class PrivacyIssue:
    candidate_id: str
    field: str
    pii_types: tuple[str, ...]
    finding_count: int


@dataclass(frozen=True)
class PrivacyAuditReport:
    issues: tuple[PrivacyIssue, ...]

    @property
    def affected_candidates(self) -> int:
        return len({issue.candidate_id for issue in self.issues})

    @property
    def finding_count(self) -> int:
        return sum(issue.finding_count for issue in self.issues)


def audit_privacy(records: Iterable[tuple[str, str, str]]) -> PrivacyAuditReport:
    """Report PII types and locations without returning sensitive values."""
    issues = []
    for candidate_id, field, text in records:
        findings = detect_pii(text)
        if findings:
            issues.append(
                PrivacyIssue(
                    candidate_id,
                    field,
                    tuple(sorted({finding.kind for finding in findings})),
                    len(findings),
                )
            )
    return PrivacyAuditReport(tuple(issues))
