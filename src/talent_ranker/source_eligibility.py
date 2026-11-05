"""Source provenance checks used before a document enters applicant ranking."""

EVALUATION_MARKER = "SYNTHETIC EVALUATION DOCUMENT"


def document_kind(text: str) -> str:
    """Honor an explicit source declaration that a document is not an application."""
    return "evaluation" if EVALUATION_MARKER in text.upper() else "resume"
