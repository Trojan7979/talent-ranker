"""Pure, bounded URL discovery. No network access or profile searching."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

MAX_LINKS = 25
MAX_URL_LENGTH = 2048
URL_PATTERN = re.compile(
    r"(?<![\w@./-])(?:(?:https?://|www\.)[^\s<>\[\]{}\"'|]+|"
    r"(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|me|app|ai|co|in|tech|site)"
    r"(?![a-z0-9.-])(?:/[^\s<>\[\]{}\"'|]*)?)", re.IGNORECASE,
)
UNSUPPORTED_HOSTS = {"linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com"}


@dataclass(frozen=True)
class ResumeLink:
    url: str
    kind: str
    discovered_via: str


def normalize_url(value: str) -> str | None:
    """Accept public web URL shapes; DNS/IP checks also run at fetch time.

    Queries/fragments are omitted deliberately: no tracking or signed credentials
    are persisted. Query-only pages are outside this first implementation.
    """
    if len(value) > MAX_URL_LENGTH:
        return None
    value = value.strip().rstrip(".,;:!?\u2022")
    extra_closings = max(0, value.count(")") - value.count("("))
    trim = min(extra_closings, len(value) - len(value.rstrip(")")))
    if trim:
        value = value[:-trim]
    if not value or len(value) > MAX_URL_LENGTH or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        return None
    if "://" not in value:
        value = "https://" + value
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        if (parts.scheme not in {"https", "http"} or parts.username is not None
                or parts.password is not None or not host or "." not in host
                or parts.port not in {None, 80 if parts.scheme == "http" else 443}
                or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host)
                or host.endswith((".local", ".localhost", ".internal", ".test", ".invalid"))):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        if host == "www.github.com":
            host = "github.com"
        path = parts.path or "/"
        if host == "github.com":
            path = path.rstrip("/")
            path = path.removesuffix(".git")
            path = path.lower() or "/"
        normalized = urlunsplit(("https" if host == "github.com" else parts.scheme, host, path, "", ""))
        return normalized if len(normalized) <= MAX_URL_LENGTH else None
    except (ValueError, UnicodeError):
        return None


def link_kind(url: str) -> str:
    host = urlsplit(url).hostname or ""
    if any(host == blocked or host.endswith("." + blocked) for blocked in UNSUPPORTED_HOSTS):
        return "unsupported"
    return "github" if host == "github.com" else "web"


def extract_links(text: str, hyperlinks: tuple[str, ...] = ()) -> tuple[ResumeLink, ...]:
    """Ordered hash-map deduplication: O(text + embedded URLs), capped output."""
    found: dict[str, ResumeLink] = {}
    for value in hyperlinks:
        url = normalize_url(value)
        if url and url not in found:
            found[url] = ResumeLink(url, link_kind(url), "hyperlink")
        if len(found) == MAX_LINKS:
            return tuple(found.values())
    for match in URL_PATTERN.finditer(text):
        url = normalize_url(match.group())
        if url and url not in found:
            found[url] = ResumeLink(url, link_kind(url), "text")
        if len(found) == MAX_LINKS:
            break
    return tuple(found.values())
