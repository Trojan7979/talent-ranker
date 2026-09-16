from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    section: str
    content: str


HEADINGS = {
    "summary", "profile", "experience", "work experience", "employment",
    "education", "skills", "projects", "certifications", "achievements",
}


def extract_pdf(path: Path) -> str:
    """Extract text from a digital PDF. Scanned PDFs should pass through OCR upstream."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(p for p in pages if p)
    if len(text) < 80:
        raise ValueError(f"{path} has too little extractable text; route it to OCR")
    return normalize_text(text)


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_resume(text: str, target_words: int = 180, overlap_words: int = 35) -> list[Chunk]:
    """Section-aware chunks preserve career evidence better than blind token windows."""
    lines = [line.strip() for line in normalize_text(text).splitlines() if line.strip()]
    sections: list[tuple[str, list[str]]] = [("profile", [])]
    for line in lines:
        key = re.sub(r"[^a-z ]", "", line.lower()).strip()
        if key in HEADINGS and len(line.split()) <= 4:
            sections.append((key, []))
        else:
            sections[-1][1].append(line)

    chunks: list[Chunk] = []
    for section, section_lines in sections:
        words = "\n".join(section_lines).split()
        if not words:
            continue
        start = 0
        while start < len(words):
            end = min(start + target_words, len(words))
            chunks.append(Chunk(len(chunks), section, " ".join(words[start:end])))
            if end == len(words):
                break
            start = max(start + 1, end - overlap_words)
    return chunks


def document_hash(data: bytes) -> str:
    return sha256(data).hexdigest()
