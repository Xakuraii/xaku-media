"""Source link normalization and bounded short-link resolution.

Users paste links in every form a site's share sheet produces: bare domains,
``vm.tiktok.com`` codes, ``fb.watch`` codes, and ``/share/`` paths. Providers
only understand canonical URLs, so normalize before classification instead of
rejecting a link that a browser opens fine.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

import httpx

from ..auth.headers import DEFAULT_USER_AGENT
from .security import validate_url_security

# Hosts whose whole purpose is redirecting to a canonical post/profile URL.
SHORT_LINK_HOSTS = {
    "vm.tiktok.com",
    "vt.tiktok.com",
    "fb.watch",
    "fb.me",
    "pin.it",
    "t.co",
}

# Share-sheet paths that redirect (or expose a canonical URL) on the full site.
SHARE_PATH_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "instagram.com",
    "www.instagram.com",
}

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_CANONICAL_META = re.compile(
    r"<meta[^>]+(?:property|name)=[\"'](?:og:url|twitter:url)[\"'][^>]*>",
    re.IGNORECASE,
)
_CANONICAL_LINK = re.compile(
    r"<link[^>]+rel=[\"']canonical[\"'][^>]*>",
    re.IGNORECASE,
)
_CONTENT_ATTR = re.compile(r"content=[\"']([^\"']+)[\"']", re.IGNORECASE)
_HREF_ATTR = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)

_READ_LIMIT = 200_000
_MAX_REDIRECTS = 6


def ensure_scheme(raw: str) -> str:
    """Add ``https://`` to scheme-less input while leaving valid URLs alone."""
    value = raw.strip().strip("<>\"'")
    if not value:
        return value
    if value.startswith("//"):
        return f"https:{value}"
    if _SCHEME.match(value):
        return value
    return f"https://{value}"


def _normalized_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def needs_resolution(url: str) -> bool:
    """Return True when this URL is a shortener or a known share-sheet path."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in SHORT_LINK_HOSTS:
        return True
    bare = _normalized_host(url)
    return bare in SHARE_PATH_HOSTS and parts.path.lower().startswith("/share/")


def _canonical_from_html(html: str) -> str | None:
    for tag in _CANONICAL_META.findall(html):
        match = _CONTENT_ATTR.search(tag)
        if match:
            return match.group(1).strip()
    for tag in _CANONICAL_LINK.findall(html):
        match = _HREF_ATTR.search(tag)
        if match:
            return match.group(1).strip()
    return None


def _read_prefix(response: httpx.Response, limit: int = _READ_LIMIT) -> str:
    """Read only enough of a response to find its canonical URL."""
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= limit:
            break
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


def resolve_source_url(url: str, timeout: float = 10.0) -> str:
    """Follow known short/share links to a canonical provider URL.

    Resolution is intentionally limited to known hosts and bounded to a few
    redirects. Any failure returns the last safe URL so a network hiccup never
    blocks a scan that might still work with the original link.
    """
    if not needs_resolution(url):
        return url

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    current = url
    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=timeout,
            headers=headers,
        ) as client:
            for _ in range(_MAX_REDIRECTS):
                try:
                    with client.stream("GET", current) as response:
                        location = response.headers.get("location")
                        if response.is_redirect and location:
                            candidate = urljoin(current, location)
                            current = validate_url_security(candidate)
                            if not needs_resolution(current):
                                break
                            continue
                        if not needs_resolution(current):
                            break
                        canonical = _canonical_from_html(_read_prefix(response))
                except Exception:
                    return current
                if not canonical:
                    break
                candidate = urljoin(current, canonical)
                if candidate == current:
                    break
                try:
                    current = validate_url_security(candidate)
                except Exception:
                    break
    except Exception:
        return current
    return current


__all__ = [
    "SHORT_LINK_HOSTS",
    "ensure_scheme",
    "needs_resolution",
    "resolve_source_url",
]
