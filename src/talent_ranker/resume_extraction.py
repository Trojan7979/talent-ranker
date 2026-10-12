"""Single-pass PDF/DOCX text and embedded-link extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from .resume_links import ResumeLink, extract_links


@dataclass(frozen=True)
class ExtractedResume:
    text: str
    links: tuple[ResumeLink, ...]


def _extract_pdf(path: Path) -> ExtractedResume:
    """Extract text from a digital PDF. Scanned PDFs should pass through OCR upstream."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(page for page in pages if page)
    if len(text) < 80:
        raise ValueError(f"{path} has too little extractable text; route it to OCR")
    hyperlinks = []
    for page in reader.pages:
        annotations = page.get("/Annots")
        if annotations is None:
            continue
        annotations = annotations.get_object()
        if not isinstance(annotations, list):
            continue
        for reference in annotations:
            annotation = reference.get_object()
            if not isinstance(annotation, dict):
                continue
            action = annotation.get("/A")
            if action is not None:
                action = action.get_object()
                if (isinstance(action, dict) and action.get("/S") == "/URI"
                        and isinstance(action.get("/URI"), str)):
                    hyperlinks.append(action["/URI"])
    text = normalize_text(text)
    return ExtractedResume(text, extract_links(text, tuple(hyperlinks)))


def _extract_docx(path: Path) -> ExtractedResume:
    """Read document-order text, including common table and header layouts."""
    from docx import Document

    with ZipFile(path) as archive:
        if (len(archive.infolist()) > 1000 or
                sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024):
            raise ValueError("DOCX archive exceeds extraction limits")
    document = Document(path)
    lines = []
    for section in document.sections:
        lines.extend(paragraph.text for paragraph in section.header.paragraphs)
    for block in document.iter_inner_content():
        if hasattr(block, "rows"):
            lines.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
        else:
            lines.append(block.text)
    text = normalize_text("\n".join(line for line in lines if line.strip()))
    if len(text) < 80:
        raise ValueError(f"{path} has too little extractable text")
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    hyperlinks = tuple(
        rel.target_ref
        for part in document.part.package.parts
        for rel in part.rels.values()
        if rel.reltype == RT.HYPERLINK and rel.is_external
    )
    return ExtractedResume(text, extract_links(text, hyperlinks))


def extract_pdf(path: Path) -> str:
    return _extract_pdf(path).text


def extract_docx(path: Path) -> str:
    return _extract_docx(path).text


def extract_resume(path: Path) -> str:
    return extract_resume_document(path).text


def extract_resume_document(path: Path) -> ExtractedResume:
    """Parse once, capturing visible and embedded links before privacy redaction."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    raise ValueError("resume must be a PDF or DOCX file")


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
