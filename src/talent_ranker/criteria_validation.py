"""Deterministic validation and mapping for model-extracted JD criteria."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .schemas import HiringPriorities

FieldName = Literal[
    "must_have_skills", "preferred_skills", "must_have_requirements",
    "preferred_requirements", "minimum_years_experience", "seniority",
    "location", "remote_policy", "max_notice_period_days", "target_start_date",
    "compensation_currency", "compensation_minimum", "compensation_maximum",
    "compensation_period",
]


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: FieldName
    value: str | float
    quote: str = Field(min_length=1)


class ExtractedFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[ExtractedFact] = Field(max_length=50)


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


class GroundedCriteriaValidator:
    """Fail closed when model facts are ungrounded, ambiguous, or conflicting."""

    _must_cues = re.compile(
        r"\b(?:must|required|mandatory|essential|minimum|requirements?|qualifications?|"
        r"what you (?:bring|need)|we (?:need|require|seek)|looking for)\b",
        re.IGNORECASE,
    )
    _preferred_cues = re.compile(
        r"\b(?:preferred|nice to have|desirable|a plus|bonus|optional)\b",
        re.IGNORECASE,
    )
    _text_fields = {
        "must_have_skills", "preferred_skills", "must_have_requirements",
        "preferred_requirements", "seniority", "location", "remote_policy",
        "compensation_currency",
    }
    _criteria_fields = {
        "must_have_skills", "preferred_skills",
        "must_have_requirements", "preferred_requirements",
    }

    def validate(self, raw: object, job_description: str) -> tuple[HiringPriorities, list[dict]]:
        facts = self._remove_redundant_skills(self._deduplicate([
            self._group_alternative_skills(fact)
            for fact in ExtractedFacts.model_validate(raw).facts
        ]))
        if not facts:
            raise ValueError("no criteria extracted")
        for fact in facts:
            self._validate_fact(fact, job_description)
        priorities = self._to_priorities(facts)
        return priorities, [fact.model_dump(mode="json") for fact in facts]

    def _validate_fact(self, fact: ExtractedFact, job_description: str) -> None:
        if len(str(fact.value)) > 500 or len(fact.quote) > 800:
            raise ValueError("criterion or supporting quote is too long")
        if _normalized(fact.quote) not in _normalized(job_description):
            raise ValueError("model fact has no exact JD quote")
        if fact.field in self._text_fields and (
            _normalized(str(fact.value)) not in _normalized(fact.quote)
        ):
            raise ValueError("model value is not present in supporting quote")
        if fact.field.startswith("must_have_"):
            self._require_active_cue(
                fact, job_description, self._must_cues, self._preferred_cues, "requirement"
            )
        if fact.field.startswith("preferred_"):
            self._require_active_cue(
                fact, job_description, self._preferred_cues, self._must_cues, "optional"
            )

    @staticmethod
    def _require_active_cue(
        fact: ExtractedFact, job_description: str, expected: re.Pattern,
        opposing: re.Pattern, label: str,
    ) -> None:
        quote = _normalized(fact.quote)
        jd = _normalized(job_description)
        quote_at = jd.rfind(quote)
        context = jd[:quote_at + len(quote)]
        context = re.sub(
            r"\b(?:preferred|desirable|optional|nice to have)\s+"
            r"(?:requirements?|qualifications?)\b",
            "preferred",
            context,
            flags=re.IGNORECASE,
        )
        expected_at = max((match.start() for match in expected.finditer(context)), default=-1)
        opposing_at = max((match.start() for match in opposing.finditer(context)), default=-1)
        if expected_at < opposing_at or expected_at < 0:
            raise ValueError(f"criterion lacks nearby {label} language")

    @staticmethod
    def _group_alternative_skills(fact: ExtractedFact) -> ExtractedFact:
        if not fact.field.endswith("_skills") or not re.search(
            r"\bor\b", fact.quote, re.IGNORECASE
        ):
            return fact
        field = (
            "must_have_requirements"
            if fact.field == "must_have_skills"
            else "preferred_requirements"
        )
        return ExtractedFact(field=field, value=fact.quote, quote=fact.quote)

    @staticmethod
    def _deduplicate(facts: list[ExtractedFact]) -> list[ExtractedFact]:
        unique: dict[tuple[str, str], ExtractedFact] = {}
        for fact in facts:
            unique.setdefault((fact.field, _normalized(str(fact.value))), fact)
        return list(unique.values())

    @staticmethod
    def _remove_redundant_skills(facts: list[ExtractedFact]) -> list[ExtractedFact]:
        requirement_quotes = {
            ("must" if fact.field.startswith("must_have") else "preferred",
             _normalized(fact.quote))
            for fact in facts
            if fact.field.endswith("_requirements")
        }
        return [
            fact for fact in facts
            if not fact.field.endswith("_skills") or (
                "must" if fact.field.startswith("must_have") else "preferred",
                _normalized(fact.quote),
            ) not in requirement_quotes
        ]

    def _to_priorities(self, facts: list[ExtractedFact]) -> HiringPriorities:
        values: dict = {
            "must_have_skills": [], "preferred_skills": [],
            "must_have_requirements": [], "preferred_requirements": [],
            "location": {"locations": []}, "availability": {}, "compensation": {},
        }
        repeatable = self._criteria_fields | {"location"}
        scalar_fields: set[str] = set()
        classified: dict[tuple[str, str], str] = {}
        for fact in facts:
            field, value = fact.field, fact.value
            if field not in repeatable:
                if field in scalar_fields:
                    raise ValueError(f"conflicting values for {field}")
                scalar_fields.add(field)
            if isinstance(value, str) and not value.strip():
                raise ValueError("empty extracted value")
            if field in self._criteria_fields:
                kind = "skills" if field.endswith("skills") else "requirements"
                key = kind, _normalized(str(value))
                importance = "must" if field.startswith("must_have") else "preferred"
                if key in classified and classified[key] != importance:
                    raise ValueError("criterion has conflicting importance")
                classified[key] = importance
                values[field].append(str(value).strip())
            elif field == "location":
                values["location"]["locations"].append(str(value).strip())
            elif field == "remote_policy":
                values["location"]["remote_policy"] = str(value).lower()
            elif field == "max_notice_period_days":
                number = float(value)
                if not number.is_integer():
                    raise ValueError("notice period must be whole days")
                values["availability"][field] = int(number)
            elif field == "target_start_date":
                values["availability"][field] = str(value)
            elif field.startswith("compensation_"):
                name = field.removeprefix("compensation_")
                values["compensation"][name] = (
                    float(value) if name in {"minimum", "maximum"}
                    else str(value).upper() if name == "currency" else str(value).lower()
                )
            else:
                values[field] = (
                    float(value) if field == "minimum_years_experience" else str(value)
                )
        return HiringPriorities.model_validate(values)
