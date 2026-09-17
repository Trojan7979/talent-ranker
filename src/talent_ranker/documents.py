from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from itertools import pairwise
from pathlib import Path

Tokenize = Callable[[str], list[int]]
Decode = Callable[[list[int]], str]


@dataclass(frozen=True)
class EvidenceUnit:
    ordinal: int
    section: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    parent_ordinal: int
    section: str
    content: str
    parent_content: str
    metadata: dict[str, str] = field(default_factory=dict)

    def embedding_text(self) -> str:
        context = " | ".join(f"{key}: {value}" for key, value in self.metadata.items())
        prefix = f"section: {self.section}"
        return f"{prefix} | {context}\n{self.content}" if context else f"{prefix}\n{self.content}"


SECTION_ALIASES = {
    "summary": {"summary", "profile", "professional summary", "about me", "objective"},
    "experience": {
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
        "work history",
        "career history",
    },
    "education": {"education", "academic background", "academic qualifications"},
    "skills": {"skills", "technical skills", "core competencies", "competencies"},
    "projects": {"projects", "selected projects", "personal projects", "key projects"},
    "certifications": {"certifications", "licenses and certifications", "credentials"},
    "achievements": {"achievements", "awards", "awards and achievements"},
}
ENTRY_SECTIONS = {"experience", "education", "projects", "certifications", "achievements"}
DATE_PATTERN = re.compile(
    r"\b(?:19|20)\d{2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
    re.IGNORECASE,
)


def extract_pdf(path: Path) -> str:
    """Extract text from a digital PDF. Scanned PDFs should pass through OCR upstream."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(page for page in pages if page)
    if len(text) < 80:
        raise ValueError(f"{path} has too little extractable text; route it to OCR")
    return normalize_text(text)


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def canonical_heading(line: str) -> str | None:
    normalized = re.sub(r"[^a-z ]", "", line.lower()).strip()
    if len(normalized.split()) > 4:
        return None
    return next(
        (section for section, aliases in SECTION_ALIASES.items() if normalized in aliases),
        None,
    )


def extract_evidence_units(text: str) -> list[EvidenceUnit]:
    sections: list[tuple[str, list[str]]] = [("profile", [])]
    for line in normalize_text(text).splitlines():
        heading = canonical_heading(line.strip())
        if heading:
            sections.append((heading, []))
        else:
            sections[-1][1].append(line)

    units: list[EvidenceUnit] = []
    for section, lines in sections:
        content = "\n".join(lines).strip()
        if not content:
            continue
        blocks = _evidence_blocks(content) if section in ENTRY_SECTIONS else [content]
        for block in blocks:
            metadata = _context_metadata(block) if section in ENTRY_SECTIONS else {}
            units.append(EvidenceUnit(len(units), section, block, metadata))
    return units


def _evidence_blocks(content: str) -> list[str]:
    paragraphs = [value.strip() for value in re.split(r"\n\s*\n", content) if value.strip()]
    if len(paragraphs) > 1:
        return _merge_short_blocks(paragraphs)
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    date_lines = [index for index, line in enumerate(lines) if DATE_PATTERN.search(line)]
    if len(date_lines) < 2:
        return [content.replace("\n", " ")]
    starts = {0, len(lines)}
    previous_date = date_lines[0]
    for date_line in date_lines[1:]:
        start = date_line
        lower_bound = max(previous_date + 1, date_line - 2)
        for index in range(date_line - 1, lower_bound - 1, -1):
            line = lines[index]
            is_heading = len(line.split()) <= 12 and not line.endswith((".", ";"))
            if not is_heading:
                break
            start = index
        starts.add(start)
        previous_date = date_line
    boundaries = sorted(starts)
    return [" ".join(lines[start:end]) for start, end in pairwise(boundaries) if end > start]


def _merge_short_blocks(blocks: list[str], minimum_words: int = 12) -> list[str]:
    merged: list[str] = []
    pending = ""
    for block in blocks:
        value = f"{pending}\n{block}".strip()
        if len(value.split()) < minimum_words:
            pending = value
            continue
        merged.append(value)
        pending = ""
    if pending:
        if merged:
            merged[-1] = f"{merged[-1]}\n{pending}"
        else:
            merged.append(pending)
    return merged


def _context_metadata(content: str) -> dict[str, str]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    metadata: dict[str, str] = {}
    if lines:
        metadata["heading"] = lines[0][:160]
    date_line = next((line for line in lines[:4] if DATE_PATTERN.search(line)), None)
    if date_line:
        metadata["dates"] = date_line[:120]
    return metadata


def chunk_resume(
    text: str,
    tokenize: Tokenize | None = None,
    decode: Decode | None = None,
    max_tokens: int = 300,
    overlap_tokens: int = 40,
) -> list[Chunk]:
    """Create token-aware child chunks while preserving their complete evidence parent."""
    if max_tokens <= 0 or not 0 <= overlap_tokens < max_tokens:
        raise ValueError("chunk sizes must satisfy 0 <= overlap_tokens < max_tokens")
    chunks: list[Chunk] = []
    for unit in extract_evidence_units(text):
        if tokenize is None or decode is None:
            words = unit.content.split()
            step = max_tokens - overlap_tokens
            children = [
                " ".join(words[start : start + max_tokens]) for start in range(0, len(words), step)
            ]
        else:
            token_ids = tokenize(unit.content)
            if len(token_ids) <= max_tokens:
                children = [unit.content]
            else:
                step = max_tokens - overlap_tokens
                children = [
                    decode(token_ids[start : start + max_tokens]).strip()
                    for start in range(0, len(token_ids), step)
                ]
        for child in children:
            if child:
                chunks.append(
                    Chunk(
                        len(chunks),
                        unit.ordinal,
                        unit.section,
                        child,
                        unit.content,
                        unit.metadata,
                    )
                )
    return chunks


def document_hash(data: bytes) -> str:
    return sha256(data).hexdigest()
