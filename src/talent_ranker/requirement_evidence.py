from __future__ import annotations

import re
from collections.abc import Sequence

from .privacy import redact_pii
from .schemas import HiringPriorities


def _terms(value: str) -> list[str]:
    return re.findall(r"[\w+#.]+", value.casefold())


def _passage(content: str, terms: list[str], limit: int = 240) -> str:
    words = content.split()
    index = next((i for i, word in enumerate(words) if _terms(word)[:1] == terms[:1]), 0)
    start = max(0, index - 12)
    return redact_pii(" ".join(words[start : start + 40]))[:limit].strip()


def assess_requirements(
    priorities: HiringPriorities, chunks: Sequence[dict]
) -> tuple[list[dict], float, list[str]]:
    """Match literal requirements across every section; related text is not proof."""
    groups = (
        ("must_have_skills", priorities.must_have_skills, 2),
        ("preferred_skills", priorities.preferred_skills, 1),
        ("must_have_requirements", priorities.must_have_requirements, 2),
        ("preferred_requirements", priorities.preferred_requirements, 1),
    )
    assessments: list[dict] = []
    earned = possible = 0.0
    missing_must = False
    for category, values, weight in groups:
        for value in values:
            terms = _terms(value)
            # A complete phrase is defensible evidence; token overlap alone is not.
            matches = [
                chunk
                for chunk in chunks
                if terms and " ".join(terms) in " ".join(_terms(chunk["content"]))
            ]
            matches.sort(
                key=lambda chunk: (
                    chunk["section"] not in {"experience", "projects"},
                    chunk["section"] == "skills",
                    chunk["ordinal"],
                )
            )
            best = matches[0] if matches else None
            status = (
                "experience_evidence"
                if best and best["section"] in {"experience", "projects"}
                else "listed"
                if best and best["section"] == "skills"
                else "mentioned"
                if best
                else "not_evidenced"
            )
            possible += weight
            earned += weight * (0.5 if status == "listed" else float(best is not None))
            if category.startswith("must_have") and best is None:
                missing_must = True
            assessments.append(
                {
                    "category": category,
                    "requirement": value,
                    "status": status,
                    "section": best["section"] if best else None,
                    "chunk_ordinal": best["ordinal"] if best else None,
                    "source_sha256": best.get("source_sha256") if best else None,
                    "passage": _passage(best["content"], terms) if best else None,
                }
            )
    concerns = ["one or more must-have requirements are not evidenced"] if missing_must else []
    if not possible:
        concerns.append("approved profile has no explicit textual requirements")
    return assessments, earned / possible if possible else 0.5, concerns


def summarize_requirements(assessments: Sequence[dict], concerns: Sequence[str]) -> str:
    """Keep the benchmark CSV explanation aligned with persisted assessments."""
    summary = [
        f"{item['requirement'] if isinstance(item['requirement'], str) else item['category']}: "
        f"{item['status'].replace('_', ' ')}"
        for item in assessments[:6]
    ]
    if len(assessments) > 6:
        summary.append(f"{len(assessments) - 6} more requirements in structured evidence")
    if concerns:
        summary.append(f"Review: {concerns[0]}")
    return "; ".join(summary) or "No explicit requirements; review score components."
