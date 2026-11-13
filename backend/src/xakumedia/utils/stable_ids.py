"""Deterministic identifiers for sources, posts, and media assets.

Stable IDs make rescans idempotent: the same provider asset always maps to the
same database row, so duplicate detection does not depend on filenames or on a
freshly generated UUID per scan.
"""

import hashlib
import uuid
from urllib.parse import urlsplit, urlunsplit

_NAMESPACE = uuid.UUID("4c1f0e2a-5a4e-4f26-9a5c-2b8f3d6f7a10")


def stable_id(kind: str, *parts: str) -> str:
    """Build a deterministic UUID from a kind and ordered identity parts."""
    payload = ":".join([kind, *[str(part) for part in parts]])
    return str(uuid.uuid5(_NAMESPACE, payload))


def canonical_media_url(url: str) -> str:
    """Normalize a media URL for fingerprinting without dropping query identity.

    Many CDNs use query parameters to identify the asset itself
    (for example ``?format=jpg&name=orig``), so the query string is kept.
    Fragments and the default ports are not significant.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()

    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parts.path or "/"
    return urlunsplit((scheme, host, path, parts.query, ""))


def url_fingerprint(url: str) -> str:
    """Stable short fingerprint for a URL used when providers expose no ID."""
    return hashlib.sha1(canonical_media_url(url).encode("utf-8")).hexdigest()
