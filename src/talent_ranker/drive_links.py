"""Resolve Google Drive browser links to stable file and folder IDs."""

import re
from urllib.parse import urlparse


def drive_id(value: str, kind: str) -> str:
    value = value.strip()
    if "://" not in value:
        return value
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "drive.google.com":
        raise ValueError("expected a Google Drive HTTPS link")
    parts = parsed.path.strip("/").split("/")
    expected = ["file", "d"] if kind == "file" else ["drive", "folders"]
    if parts[:2] != expected or len(parts) < 3 or not parts[2]:
        raise ValueError(f"expected a Google Drive {kind} link")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", parts[2]):
        raise ValueError("invalid Google Drive file or folder ID")
    return parts[2]
