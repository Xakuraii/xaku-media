"""Incremental rescan service and differential media discovery for saved sources."""

import html
import re
import threading
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx
from gallery_dl import extractor as gdl_extractor

from ..auth.headers import DEFAULT_USER_AGENT
from ..core.logging import get_logger
from ..db import default_repository
from ..db.connection import get_db_session
from ..db.repository import MediaRepository
from ..downloader.library import canonical_single_post_key, url_asset_tokens
from ..exceptions.base import (
    MediaUnavailableError,
    NetworkTimeoutError,
    UnsupportedSourceError,
)
from ..extractors.gallery import extract_gallery_info
from ..extractors.video import extract_video_info
from ..models.media import MediaItem
from ..models.post import ScanOptions
from ..models.source import IncrementalScanResult, RescanAllSummary, SavedSource
from ..models.url import ClassifiedUrl
from ..providers.registry import resolve_provider
from ..scanners.direct import classify_direct_url
from ..utils.security import validate_url_security

logger = get_logger("sources.rescan")

_HOST_PLATFORM_LABELS = {
    "youtube.com": "Youtube",
    "youtu.be": "Youtube",
    "tiktok.com": "Tiktok",
    "instagram.com": "Instagram",
    "instagr.am": "Instagram",
    "facebook.com": "Facebook",
    "fb.com": "Facebook",
    "fb.watch": "Facebook",
    "x.com": "X",
    "twitter.com": "X",
}

_META_IMAGE_PATTERNS = (
    re.compile(
        r'<meta[^>]+(?:property|name)=["\']'
        r'(?:og:image(?::secure_url)?|twitter:image(?::src)?)["\']'
        r'[^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']'
        r'(?:og:image(?::secure_url)?|twitter:image(?::src)?)["\']',
        re.IGNORECASE,
    ),
)


_BAD_AVATAR_PATH_RE = re.compile(
    r"/(?:avatar|posts|photos|videos|reels|likes|reposts)/?$",
    re.IGNORECASE,
)


def _is_usable_avatar_url(url: str | None) -> bool:
    """Return True when ``url`` is an actual image/media asset rather than a web page."""
    if not url or not isinstance(url, str):
        return False
    stripped = url.strip()
    if not stripped:
        return False
    if stripped.startswith(("media-loader://", "data:image/")):
        return True
    try:
        parts = urlsplit(stripped)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    path = (parts.path or "").rstrip("/")
    if not path:
        return False
    if _BAD_AVATAR_PATH_RE.search(path) or re.match(r"^/@[^/]+$", path):
        return False
    host = (parts.hostname or "").lower()
    if host.endswith(
        ("tiktok.com", "instagram.com", "facebook.com", "fb.com", "x.com", "twitter.com")
    ):
        # Bare user/page routes on main site hosts are HTML pages, not CDN image assets.
        if not parts.query and "." not in path.rsplit("/", 1)[-1]:
            return False
    return not path.lower().endswith((".html", ".htm", ".php"))


def _clean_author(author: str | None, fallback: str | None = None) -> str | None:
    if isinstance(author, str):
        stripped = author.strip().lstrip("@")
        if stripped and stripped.lower() not in ("gallery", "unknown", "none", "user"):
            return stripped
    return fallback


def infer_source_identity(url: str) -> tuple[str | None, str | None]:
    """Infer ``(platform, author)`` from a source URL without network calls."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None, None

    host = (parts.hostname or "").lower()
    for prefix in ("www.", "m.", "mobile."):
        if host.startswith(prefix):
            host = host[len(prefix) :]

    platform: str | None = None
    for domain, label in _HOST_PLATFORM_LABELS.items():
        if host == domain or host.endswith(f".{domain}"):
            platform = label
            break
    if platform is None and host:
        platform = host.split(".", 1)[0].capitalize()

    segments = [seg for seg in parts.path.split("/") if seg]
    author: str | None = None
    if segments:
        first = segments[0]
        if first.startswith("@"):
            author = first.lstrip("@")
        elif first in ("channel", "c", "user") and len(segments) > 1:
            author = segments[1].lstrip("@")
        elif first not in (
            "watch",
            "playlist",
            "shorts",
            "reel",
            "reels",
            "p",
            "explore",
            "share",
            "photo",
            "video",
        ):
            author = first.lstrip("@")
    return platform, author or None


def _lookup_cached_avatar(repo: MediaRepository, url: str, author: str | None) -> str | None:
    """Return a known thumbnail/avatar URL from local SQLite history when available."""
    try:
        with get_db_session(repo.db_path) as conn:
            rows = conn.execute(
                """
                SELECT thumbnail_url,
                       CASE WHEN media_type = 'image' THEN original_url ELSE NULL END AS img_url
                FROM media_items
                WHERE (source_url = ? OR post_url = ?)
                  AND (
                    (thumbnail_url IS NOT NULL AND thumbnail_url != '')
                    OR (
                      media_type = 'image'
                      AND original_url IS NOT NULL
                      AND original_url != ''
                    )
                  )
                ORDER BY created_at DESC LIMIT 25
                """,
                (url, url),
            ).fetchall()
            for row in rows:
                for candidate in (row["thumbnail_url"], row["img_url"]):
                    if _is_usable_avatar_url(candidate):
                        return str(candidate)
            if author:
                rows = conn.execute(
                    """
                    SELECT thumbnail_url,
                           CASE WHEN media_type = 'image' THEN original_url ELSE NULL END AS img_url
                    FROM media_items
                    WHERE LOWER(author) = LOWER(?)
                      AND (
                        (thumbnail_url IS NOT NULL AND thumbnail_url != '')
                        OR (
                          media_type = 'image'
                          AND original_url IS NOT NULL
                          AND original_url != ''
                        )
                      )
                    ORDER BY created_at DESC LIMIT 25
                    """,
                    (author,),
                ).fetchall()
                for row in rows:
                    for candidate in (row["thumbnail_url"], row["img_url"]):
                        if _is_usable_avatar_url(candidate):
                            return str(candidate)
    except Exception:
        pass
    return None


def _fetch_page_avatar(url: str) -> str | None:
    """Best-effort SSRF-safe fetch of og:image / profile avatar for a saved URL."""
    try:
        safe_url = validate_url_security(url)
    except Exception:
        return None
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=4.0,
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        ) as client:
            resp = client.get(safe_url)
            if resp.status_code >= 400:
                return None
            ctype = (resp.headers.get("content-type") or "").lower()
            if "text/html" not in ctype and "application/xhtml" not in ctype:
                return None
            snippet = resp.text[:120_000]
            for pattern in _META_IMAGE_PATTERNS:
                match = pattern.search(snippet)
                if match:
                    candidate = html.unescape(match.group(1).strip())
                    if candidate:
                        return urljoin(str(resp.url), candidate)
    except Exception:
        return None
    return None


def enrich_source_metadata(
    source: SavedSource,
    repository: MediaRepository | None = None,
    *,
    fetch_remote: bool = True,
) -> SavedSource:
    """Fill missing platform, author, and profile picture on a SavedSource."""
    repo = repository or default_repository
    inferred_platform, inferred_author = infer_source_identity(source.url)
    if not source.platform and inferred_platform:
        source.platform = inferred_platform

    cleaned_author = _clean_author(source.author, inferred_author)
    if cleaned_author:
        source.author = cleaned_author

    generic_titles = {source.url, "", "facebook.com", "tiktok.com", "instagram.com", "x.com"}
    if ((source.title or "").strip().lower() in generic_titles) and source.author:
        source.title = f"@{source.author}" if not source.author.startswith("@") else source.author

    if not _is_usable_avatar_url(source.thumbnail_url):
        source.thumbnail_url = None

    if not source.thumbnail_url:
        cached = _lookup_cached_avatar(repo, source.url, source.author)
        if cached:
            source.thumbnail_url = cached
        elif fetch_remote:
            remote = _fetch_page_avatar(source.url)
            if remote and _is_usable_avatar_url(remote):
                source.thumbnail_url = remote
    return source


def scan_source_url(url: str) -> tuple[ClassifiedUrl | None, list[MediaItem]]:
    """Scan and extract media items from a URL via unified providers or fallbacks."""
    classified: ClassifiedUrl | None = None
    media_items: list[MediaItem] = []

    # 1. Unified provider registry (routes TikTok, YouTube, Instagram, Facebook, X, direct, etc.)
    try:
        provider = resolve_provider(url)
        classified = provider.classify(url)
        posts = list(
            provider.iter_posts(
                url,
                ScanOptions(max_posts=60, include_images=True, include_videos=True),
                threading.Event(),
            )
        )
        media_items = [item for post in posts for item in post.media_items]
        if media_items:
            return classified, media_items
    except UnsupportedSourceError:
        pass
    except Exception as exc:
        logger.warning(f"Provider rescan failed for {url}: {exc}")

    # 2. Probe for direct media URL fallback
    try:
        classified, direct_item = classify_direct_url(url)
        if direct_item is not None:
            media_items = [direct_item]
    except (UnsupportedSourceError, MediaUnavailableError, NetworkTimeoutError):
        pass

    # 3. Check legacy gallery-dl extractor (skip TikTok profiles handled by yt-dlp)
    if not media_items and "tiktok.com" not in url.lower():
        try:
            if gdl_extractor.find(url):
                classified, media_items = extract_gallery_info(url)
        except Exception:
            pass

    # 4. Check legacy single-video yt-dlp fallback
    if not media_items:
        try:
            classified, video_item = extract_video_info(url)
            if video_item is not None:
                media_items = [video_item]
        except Exception as exc:
            logger.warning(f"Video extraction failed for {url}: {exc}")

    return classified, media_items


def incremental_rescan_source(
    source_or_id: str | SavedSource,
    repository: MediaRepository | None = None,
) -> IncrementalScanResult:
    """Perform an incremental rescan of a saved source, distinguishing newly found items."""
    repo = repository or default_repository

    if isinstance(source_or_id, SavedSource):
        source = source_or_id
    else:
        found = repo.get_source(source_or_id)
        if not found:
            raise ValueError(f"Saved source not found: {source_or_id}")
        source = found

    logger.info(f"Starting incremental rescan for source '{source.title}' ({source.url})...")

    # Retrieve already known item URLs for this source
    known_urls = repo.get_known_item_urls_for_source(source.url)
    classified, discovered_items = scan_source_url(source.url)

    from ..downloader.library import annotate_items

    annotate_items(discovered_items)

    now = datetime.now(UTC).isoformat()
    new_items: list[MediaItem] = []
    existing_items: list[MediaItem] = []

    known_tokens: set[str] = set()
    known_post_keys: set[str] = set()
    for known in known_urls:
        known_tokens.update(url_asset_tokens(known))
        pk = canonical_single_post_key(known)
        if pk:
            known_post_keys.add(pk)

    source_root = source.url.rstrip("/")
    for item in discovered_items:
        item_source = (item.source_url or "").rstrip("/")
        item_post = (item.post_url or "").rstrip("/")
        item_tokens = url_asset_tokens(item.original_url)
        item_pk = canonical_single_post_key(item.post_url)
        is_known = (
            item.original_url in known_urls
            or (bool(item_source) and item_source != source_root and item.source_url in known_urls)
            or (bool(item_post) and item_post != source_root and item.post_url in known_urls)
            or bool(item_tokens & known_tokens)
            or (item_pk is not None and item_pk in known_post_keys)
            or item.library_status in ("downloaded", "skipped")
        )
        if is_known:
            existing_items.append(item)
        else:
            new_items.append(item)

    # Persist scan history event
    if classified and discovered_items:
        try:
            repo.save_scan_result(classified, discovered_items)
        except Exception as exc:
            logger.warning(f"Could not persist scan history during rescan: {exc}")

    # Update source statistics and fill missing profile picture/author metadata.
    first_thumb = next(
        (item.thumbnail_url for item in discovered_items if item.thumbnail_url),
        None,
    )
    first_author = next(
        (item.author for item in discovered_items if item.author and item.author != "media"),
        None,
    )
    if (
        (not source.thumbnail_url and first_thumb)
        or (not source.author and first_author)
        or (not source.platform and classified and classified.platform)
    ):
        if not source.thumbnail_url and first_thumb:
            source.thumbnail_url = first_thumb
        if not source.author and first_author:
            source.author = first_author
        if not source.platform and classified and classified.platform:
            source.platform = classified.platform
        try:
            repo.save_source(source)
        except Exception:
            pass

    repo.update_source_scan_stats(source.id, len(discovered_items), now)
    updated_source = repo.get_source(source.id) or source

    logger.info(
        f"Incremental rescan complete for '{source.title}': "
        f"{len(discovered_items)} total found, {len(new_items)} new items."
    )

    return IncrementalScanResult(
        source=updated_source,
        total_found=len(discovered_items),
        new_items=new_items,
        existing_items=existing_items,
        new_item_count=len(new_items),
        scanned_at=now,
    )


def rescan_all_sources(
    repository: MediaRepository | None = None,
    tag: str | None = None,
) -> RescanAllSummary:
    """Perform incremental rescan across all saved sources."""
    repo = repository or default_repository
    sources = repo.list_saved_sources(tag=tag)

    summary = RescanAllSummary(sources_checked=len(sources))

    for src in sources:
        try:
            res = incremental_rescan_source(src, repository=repo)
            summary.results.append(res)
            summary.total_items_found += res.total_found
            summary.total_new_items += res.new_item_count
        except Exception as exc:
            logger.error(f"Error rescanning source {src.id} ({src.url}): {exc}")
            summary.errors[src.id] = str(exc)

    return summary
