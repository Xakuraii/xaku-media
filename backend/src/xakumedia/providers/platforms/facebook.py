"""Facebook discovery provider adapter for profiles, photos, albums, videos, and reels."""

from __future__ import annotations

import concurrent.futures
import html as html_lib
import json
import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from ...core.logging import get_logger
from ...exceptions.base import ExtractionError, XakuMediaError
from ...models.media import MediaFormatInfo, MediaType
from ...models.post import Post, ProviderCapabilities, ScanOptions
from ...models.url import ClassifiedUrl, UrlCategory
from ...utils.security import validate_url_security
from ..base import (
    PageCallback,
    TotalCallback,
    WarningCallback,
    host_of,
    make_media_item,
    make_post,
)
from ..dash import parse_dash_mpd
from ..gallerydl import (
    FACEBOOK_CATEGORY,
    GalleryDlProvider,
    _DiscoveryState,
    _facebook_video_ids,
)

logger = get_logger("providers.facebook")

FACEBOOK_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "fb.com",
    "www.fb.com",
    "fb.watch",
}

REELS_PAGINATION_QUERY_NAME = "ProfileCometAppCollectionReelsRendererPaginationQuery"
REELS_PAGINATION_DEFAULT_DOC_ID = "29259931620295125"

VIDEOS_PAGINATION_QUERY_NAME = "PagesCometChannelTabAllVideosCardImplPaginationQuery"
VIDEOS_PAGINATION_DEFAULT_DOC_ID = "29643863005208862"

TIMELINE_ROOT_QUERY_NAME = "ProfileCometTimelineListViewRootQuery"
TIMELINE_ROOT_DEFAULT_DOC_ID = "29875146502090540"

TILES_PAGINATION_QUERY_NAME = "ProfileCometTilesFeedPaginationQuery"
TILES_PAGINATION_DEFAULT_DOC_ID = "28137111635965845"

STORIES_CONTENT_QUERY_NAME = "StoriesSuspenseContentPaneRootWithEntryPointQuery"
STORIES_CONTENT_DEFAULT_DOC_ID = "29556157090686900"

_DOC_ID_CACHE: dict[str, str] = {
    REELS_PAGINATION_QUERY_NAME: REELS_PAGINATION_DEFAULT_DOC_ID,
    VIDEOS_PAGINATION_QUERY_NAME: VIDEOS_PAGINATION_DEFAULT_DOC_ID,
    TIMELINE_ROOT_QUERY_NAME: TIMELINE_ROOT_DEFAULT_DOC_ID,
    TILES_PAGINATION_QUERY_NAME: TILES_PAGINATION_DEFAULT_DOC_ID,
    STORIES_CONTENT_QUERY_NAME: STORIES_CONTENT_DEFAULT_DOC_ID,
}

_RE_NON_PROFILE_SEGMENTS = {
    "reel",
    "reels",
    "watch",
    "photo",
    "photo.php",
    "media",
    "permalink.php",
    "story.php",
    "video.php",
    "video",
    "groups",
    "events",
    "share",
    "login",
    "hashtag",
    "marketplace",
    "gaming",
    "plugins",
}

_RE_SINGLE_VIDEO_ID = re.compile(r"/(?:reel|videos?|watch)/(\d+)|[?&](?:v|video_id)=(\d+)")

parse_facebook_dash_mpd = parse_dash_mpd


@dataclass(frozen=True)
class FacebookTarget:
    """Normalized representation of a Facebook URL and its requested scope."""

    # "profile" | "reels" | "videos" | "photos" | "video" | "stories" | "gallery"
    scope: str
    profile_base: str | None
    canonical_gallery_url: str
    video_id: str | None = None


def _decode_js_escaped_url(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if "\\u" in text or "\\/" in text:
        try:
            text = json.loads(f'"{text}"')
        except Exception:
            text = text.replace("\\/", "/")
    return html_lib.unescape(text)


def _extract_json_object_after(clean_html: str, key: str) -> dict[str, Any] | None:
    """Decode the JSON object immediately following ``"<key>":`` in SSR HTML."""
    decoder = json.JSONDecoder()
    marker = f'"{key}":'
    start = 0
    while True:
        idx = clean_html.find(marker, start)
        if idx < 0:
            return None
        brace = clean_html.find("{", idx + len(marker))
        if brace < 0 or brace - (idx + len(marker)) > 8:
            start = idx + len(marker)
            continue
        try:
            obj, _ = decoder.raw_decode(clean_html, brace)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        start = idx + len(marker)


def _extract_connection_info(
    clean_html: str,
    field_name: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Extract a Relay connection dict (edges + page_info) and its enclosing node id.

    Works regardless of JSON key ordering inside ``page_info`` or ``edges``.
    """
    marker = f'"{field_name}":'
    decoder = json.JSONDecoder()
    idx = 0
    while True:
        pos = clean_html.find(marker, idx)
        if pos < 0:
            return None, None
        brace = clean_html.find("{", pos + len(marker))
        if brace < 0 or brace - (pos + len(marker)) > 8:
            idx = pos + len(marker)
            continue
        try:
            conn, end_pos = decoder.raw_decode(clean_html, brace)
            if isinstance(conn, dict) and "page_info" in conn:
                tail = clean_html[end_pos : end_pos + 200]
                m_id = re.search(r'"id":"([^"]+)"', tail)
                return conn, (m_id.group(1) if m_id else None)
        except Exception:
            # Fallback if truncated/non-JSON before full block closes: find page_info object nearby.
            window = clean_html[brace : brace + 20000]
            pinfo = _extract_json_object_after(window, "page_info")
            if pinfo is not None:
                m_id = re.search(r'\},"id":"([^"]+)"', window)
                return {"edges": [], "page_info": pinfo}, (m_id.group(1) if m_id else None)
        idx = pos + len(marker)


def _parse_facebook_url(url: str) -> FacebookTarget:
    """Classify any Facebook URL into a normalized scope + profile base."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return FacebookTarget(scope="gallery", profile_base=None, canonical_gallery_url=url)

    host = (parts.hostname or "").lower()
    if host == "fb.watch":
        return FacebookTarget(scope="video", profile_base=None, canonical_gallery_url=url)

    path = parts.path.strip("/")
    segments = [seg for seg in path.split("/") if seg]
    query = parse_qs(parts.query)

    # /profile.php?id=<NUM>[&sk=...]
    if segments and segments[0].lower() == "profile.php":
        pid = (query.get("id") or [""])[0].strip()
        if pid:
            base = f"https://www.facebook.com/{pid}"
            sk = (query.get("sk") or [""])[0].strip().lower()
            if sk in ("reels_tab", "reels"):
                return FacebookTarget(
                    scope="reels",
                    profile_base=base,
                    canonical_gallery_url=f"{base}/reels",
                )
            if sk in ("videos", "videos_by"):
                return FacebookTarget(
                    scope="videos",
                    profile_base=base,
                    canonical_gallery_url=f"{base}/videos",
                )
            if sk in ("photos", "photos_by", "photos_albums", "photos_all", "photos_of"):
                tab = (
                    "photos_albums"
                    if sk == "photos_albums"
                    else ("photos_by" if sk == "photos_by" else "photos")
                )
                return FacebookTarget(
                    scope="photos",
                    profile_base=base,
                    canonical_gallery_url=f"{base}/{tab}",
                )
            return FacebookTarget(
                scope="profile",
                profile_base=base,
                canonical_gallery_url=base,
            )

    # /people/<slug>/<NUM>
    if len(segments) >= 3 and segments[0].lower() == "people" and segments[2].isdigit():
        base = f"https://www.facebook.com/{segments[2]}"
        return FacebookTarget(scope="profile", profile_base=base, canonical_gallery_url=base)

    # Story / Highlight bucket URLs: /stories/<bucket_id>[/<story_id>] or /stories/highlights/<id>
    if (
        len(segments) >= 2
        and segments[0].lower() == "stories"
        and segments[1].lower() not in ("archive", "settings", "create")
    ):
        if segments[1].lower() == "highlights":
            if len(segments) < 3:
                return FacebookTarget(scope="gallery", profile_base=None, canonical_gallery_url=url)
            bucket_id = segments[2]
        else:
            bucket_id = segments[1]
        return FacebookTarget(
            scope="stories",
            profile_base=None,
            canonical_gallery_url=f"https://www.facebook.com/stories/{bucket_id}",
            video_id=bucket_id,
        )

    # Single video/reel/watch/share URLs
    vid_match = _RE_SINGLE_VIDEO_ID.search(url)
    if (
        (segments and segments[0].lower() in ("reel", "watch", "video.php"))
        or (len(segments) >= 2 and segments[1].lower() == "videos" and len(segments) >= 3)
        or (
            len(segments) >= 2
            and segments[0].lower() == "share"
            and segments[1].lower() in ("r", "v")
        )
    ):
        vid = None
        if vid_match:
            vid = vid_match.group(1) or vid_match.group(2)
        return FacebookTarget(
            scope="video",
            profile_base=None,
            canonical_gallery_url=url,
            video_id=vid,
        )

    # Non-profile gallery/photo/post/group URLs
    if (
        not segments
        or segments[0].lower() in _RE_NON_PROFILE_SEGMENTS
        or (len(segments) >= 2 and segments[1].lower() in ("posts", "permalink"))
        or "fbid" in query
        or "set" in query
    ):
        # Single photo with photo/... sub-path is gallery
        return FacebookTarget(scope="gallery", profile_base=None, canonical_gallery_url=url)

    # Profile + optional tab
    owner = segments[0]
    base = f"https://www.facebook.com/{owner}"
    if len(segments) == 1:
        return FacebookTarget(scope="profile", profile_base=base, canonical_gallery_url=base)

    tab = segments[1].lower()
    if tab in ("reels", "reels_tab"):
        return FacebookTarget(
            scope="reels",
            profile_base=base,
            canonical_gallery_url=f"{base}/reels",
        )
    if tab in ("videos", "videos_by"):
        return FacebookTarget(
            scope="videos",
            profile_base=base,
            canonical_gallery_url=f"{base}/videos",
        )
    if tab in ("photos", "photos_by", "photos_albums", "photos_of"):
        return FacebookTarget(
            scope="photos",
            profile_base=base,
            canonical_gallery_url=f"{base}/{tab}",
        )

    return FacebookTarget(scope="gallery", profile_base=None, canonical_gallery_url=url)


def _extract_tokens_and_preload_vars(
    html_text: str,
) -> tuple[str | None, str | None, dict[str, Any]]:
    clean = html_text.replace("\\/", "/")
    dtsg_match = re.search(r'"DTSGInitialData",\[\],\{"token":"([^"]+)"', clean)
    lsd_match = re.search(r'"LSD",\[\],\{"token":"([^"]+)"', clean)
    preload_vars: dict[str, Any] = {}
    for m in re.finditer(r'"variables":(\{"collectionToken"[^}]+\})', clean):
        try:
            preload_vars = json.loads(m.group(1))
            break
        except Exception:
            continue
    return (
        dtsg_match.group(1) if dtsg_match else None,
        lsd_match.group(1) if lsd_match else None,
        preload_vars,
    )


def _resolve_doc_id_from_bundles(
    html_text: str, query_name: str, force_refresh: bool = False
) -> str:
    if not force_refresh and query_name in _DOC_ID_CACHE:
        return _DOC_ID_CACHE[query_name]

    marker = f"{query_name}_facebookRelayOperation"
    clean = html_text.replace("\\/", "/")
    js_urls = sorted(
        set(
            re.findall(
                r'https://static\.xx\.fbcdn\.net/rsrc\.php/[^"\'\s<>)]+?\.js[^"\'\s<>)]*',
                clean,
            )
        )
    )
    if js_urls:
        pattern = re.compile(
            rf'__d\("{re.escape(marker)}",\[\],\(function\([^)]*\)\{{[a-zA-Z0-9_.]+\s*=\s*"(\d+)"'
        )
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:

            def _probe(url: str) -> str | None:
                try:
                    resp = client.get(url)
                    if resp.status_code == 200 and marker in resp.text:
                        match = pattern.search(resp.text)
                        if match:
                            return match.group(1)
                except Exception:
                    return None
                return None

            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                for found in pool.map(_probe, js_urls[:120]):
                    if found:
                        _DOC_ID_CACHE[query_name] = found
                        return found

    return _DOC_ID_CACHE.get(
        query_name,
        REELS_PAGINATION_DEFAULT_DOC_ID
        if query_name == REELS_PAGINATION_QUERY_NAME
        else VIDEOS_PAGINATION_DEFAULT_DOC_ID,
    )


def _parse_ndjson_chunks(text: str) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict) and ("data" in obj or "result" in obj):
            chunks.append(obj)
    return chunks


def _parse_ndjson_primary(text: str) -> dict[str, Any] | None:
    chunks = _parse_ndjson_chunks(text)
    return next((c for c in chunks if "data" in c), None)


def _extract_highlight_bucket_ids(
    html_text: str,
    payloads: list[Any] | None = None,
    *,
    exclude_ids: set[str] | None = None,
) -> list[str]:
    """Collect Story / Featured Highlight bucket IDs from SSR HTML and GraphQL payloads."""
    blocked = set(exclude_ids or ())
    seen: set[str] = set()
    ordered: list[str] = []

    def _record(candidate: Any) -> None:
        if not isinstance(candidate, (str, int)):
            return
        val = str(candidate).strip()
        if not val or not val.isdigit() or val in blocked or val in seen:
            return
        seen.add(val)
        ordered.append(val)

    bucket_keys = {
        "story_bucket",
        "story_buckets",
        "featured_highlights",
        "highlight_units_section",
        "highlight_units",
        "highlight_buckets",
        "profile_intro_card",
        "bucket",
        "buckets",
    }

    def _walk_highlight_node(obj: Any, *, inside_bucket: bool, record) -> None:
        if isinstance(obj, list):
            for entry in obj:
                _walk_highlight_node(entry, inside_bucket=inside_bucket, record=record)
            return
        if not isinstance(obj, dict):
            return
        typename = str(obj.get("__typename") or "")
        now_inside = (
            inside_bucket
            or "__isStoryBucket" in obj
            or any(tag in typename for tag in ("Bucket", "Highlight", "Featured"))
        )
        if now_inside:
            _record(obj.get("id"))
            _record(obj.get("bucket_id"))
        raw_url = obj.get("url")
        if isinstance(raw_url, str):
            m_url = re.search(r"/stories/(?:highlights/)?(\d+)", raw_url)
            if m_url:
                _record(m_url.group(1))
        for k, v in obj.items():
            if k in ("story_bucket_owner", "owner", "actors", "delegate_page"):
                continue
            _walk_highlight_node(
                v,
                inside_bucket=now_inside or (k in bucket_keys),
                record=record,
            )

    clean = html_text.replace("\\/", "/") if html_text else ""
    if clean:
        for match in re.findall(r'"/stories/(?:highlights/)?(\d+)"', clean):
            _record(match)
        for key in ("story_bucket", "featured_highlights", "highlight_units_section"):
            for m in re.finditer(rf'"{key}":', clean):
                obj = _extract_json_object_after(clean[m.start() :], key)
                if obj is not None:
                    _walk_highlight_node(obj, inside_bucket=True, record=_record)

    for payload in payloads or ():
        _walk_highlight_node(payload, inside_bucket=False, record=_record)

    return ordered


def _collect_story_nodes_from_payloads(
    payloads: list[Any],
    *,
    target_bucket_id: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Collect unified story card nodes and bucket owner name from Relay payloads."""
    stories: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    owner_name: str | None = None

    def _is_other_bucket(obj: dict[str, Any]) -> bool:
        if not target_bucket_id:
            return False
        bid = obj.get("id")
        if not isinstance(bid, (str, int)) or not str(bid):
            return False
        typename = str(obj.get("__typename") or "")
        is_bucket = (
            "__isStoryBucket" in obj
            or "Bucket" in typename
            or "story_bucket_owner" in obj
        )
        return is_bucket and str(bid) != target_bucket_id

    def _walk(obj: Any) -> None:
        nonlocal owner_name
        if isinstance(obj, list):
            for entry in obj:
                _walk(entry)
            return
        if not isinstance(obj, dict) or _is_other_bucket(obj):
            return
        bucket_owner = obj.get("story_bucket_owner")
        if isinstance(bucket_owner, dict) and not owner_name:
            name = bucket_owner.get("name") or bucket_owner.get("short_name")
            if isinstance(name, str) and name.strip():
                owner_name = name.strip()

        for conn_key in ("unified_stories", "unified_stories_with_notes"):
            conn = obj.get(conn_key)
            if isinstance(conn, dict):
                for edge in conn.get("edges") or ():
                    node = edge.get("node") if isinstance(edge, dict) else None
                    if not isinstance(node, dict):
                        continue
                    nid = str(node.get("id") or len(stories))
                    if nid in seen_ids:
                        continue
                    seen_ids.add(nid)
                    stories.append(node)

        for v in obj.values():
            _walk(v)

    for payload in payloads:
        _walk(payload)
    return stories, owner_name


def _extract_caption_and_timestamp(
    story: dict[str, Any], media: dict[str, Any]
) -> tuple[str | None, float | None]:
    caption: str | None = None
    msg = story.get("message") or media.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("text"), str):
        caption = msg["text"].strip() or None
    elif isinstance(msg, str) and msg.strip():
        caption = msg.strip()

    ts: float | None = None
    tracking_raw = story.get("tracking")
    if isinstance(tracking_raw, str) and "publish_time" in tracking_raw:
        m = re.search(r'"publish_time":(\d+)', tracking_raw)
        if m:
            ts = float(m.group(1))
    if ts is None:
        for candidate in (
            media.get("created_time"),
            media.get("publish_time"),
            story.get("publish_time"),
        ):
            if isinstance(candidate, (int, float)) and candidate > 0:
                ts = float(candidate)
                break
    return caption, ts


def _extract_thumbnail_from_media(media: dict[str, Any]) -> str | None:
    pref = media.get("preferred_thumbnail")
    if isinstance(pref, dict):
        img = pref.get("image")
        if isinstance(img, dict) and img.get("uri"):
            return str(img["uri"])
    for key in ("first_frame_thumbnail",):
        val = media.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    img_obj = media.get("thumbnailImage") or media.get("image")
    if isinstance(img_obj, dict) and img_obj.get("uri"):
        return str(img_obj["uri"])
    return None


def _extract_owner_name(story: dict[str, Any], media: dict[str, Any], fallback: str) -> str:
    owner = (
        media.get("owner") or story.get("actors", [{}])[0]
        if isinstance(story.get("actors"), list) and story.get("actors")
        else media.get("owner")
    )
    if isinstance(owner, dict):
        name = owner.get("name") or owner.get("username")
        if name:
            return str(name)
    return fallback


class FacebookProvider(GalleryDlProvider):
    """Dedicated provider for Facebook profiles, photos, albums, videos, and reels."""

    platform_name = "facebook"
    label = "Facebook (gallery-dl)"

    @classmethod
    def match(cls, url: str) -> bool:
        return host_of(url) in FACEBOOK_HOSTS

    def _cookie_candidate_urls(self, url: str) -> tuple[str, ...]:
        return (url, "https://www.facebook.com/")

    def capabilities_for(self, url: str) -> ProviderCapabilities:
        target = _parse_facebook_url(url)
        has_cookies = super().capabilities_for("https://www.facebook.com/").has_cookies
        if target.scope == "stories":
            caps = super().capabilities_for("https://www.facebook.com/")
            return ProviderCapabilities(
                provider=self.name,
                label=self.label,
                source_type="gallery",
                profile_bulk=False,
                individual_posts=True,
                albums=True,
                images=True,
                videos=True,
                pagination=False,
                requires_auth=not has_cookies,
                has_cookies=has_cookies,
                notes="Facebook Stories and Featured Highlights video/photo extractor.",
            )
        if target.scope in ("profile", "reels", "videos", "photos"):
            return ProviderCapabilities(
                provider=self.name,
                label=self.label,
                source_type="profile",
                profile_bulk=True,
                individual_posts=True,
                albums=target.scope in ("profile", "photos"),
                images=target.scope in ("profile", "photos"),
                videos=target.scope in ("profile", "reels", "videos"),
                pagination=True,
                requires_auth=not has_cookies,
                has_cookies=has_cookies,
                notes=(
                    "Facebook discovery enumerates paginated Reels/Videos via GraphQL "
                    "alongside profile Highlights/Stories, photos, and albums."
                ),
            )
        caps = super().capabilities_for(target.canonical_gallery_url)
        if target.scope == "video":
            caps.source_type = "video"
            caps.videos = True
            caps.images = False
            caps.requires_auth = False if has_cookies else caps.requires_auth
        return caps

    def classify(self, url: str) -> ClassifiedUrl:
        target = _parse_facebook_url(url)
        if target.scope in ("profile", "reels", "videos", "photos"):
            parts = urlsplit(target.canonical_gallery_url)
            return ClassifiedUrl(
                raw_url=url,
                normalized_url=target.canonical_gallery_url,
                category=UrlCategory.CHANNEL,
                platform="facebook",
                domain=parts.netloc or "www.facebook.com",
                author_hint=(target.profile_base or "").rsplit("/", 1)[-1] or None,
                title_hint=(f"{(target.profile_base or '').rsplit('/', 1)[-1]} ({target.scope})"),
                is_supported=True,
                requires_auth=False,
                metadata_extra={"provider": self.name, "facebook_scope": target.scope},
            )
        if target.scope == "video":
            parts = urlsplit(url)
            return ClassifiedUrl(
                raw_url=url,
                normalized_url=url,
                category=UrlCategory.VIDEO_POST,
                platform="facebook",
                domain=parts.netloc or "www.facebook.com",
                author_hint=None,
                title_hint=target.video_id or "Facebook Video",
                is_supported=True,
                requires_auth=False,
                metadata_extra={"provider": self.name, "facebook_scope": "video"},
            )
        return super().classify(target.canonical_gallery_url)

    def _warm_facebook_session(self, profile_base: str):
        extractor = self._prepare_extractor(f"{profile_base}/photos")
        try:
            extractor.request(f"{profile_base}/photos_by", fatal=False)
        except Exception:
            pass
        return extractor

    def _build_video_post_from_formats(
        self,
        *,
        video_id: str,
        source_url: str,
        post_url: str,
        author: str,
        title: str | None,
        thumbnail_url: str | None,
        formats: list[MediaFormatInfo],
        duration_seconds: float | None = None,
        published_ts: float | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> Post | None:
        video_fmts = [
            fmt for fmt in formats if fmt.url and (fmt.video_codec or "none").lower() != "none"
        ]
        if not video_fmts:
            return None

        best_video = video_fmts[0]
        item_width = width or best_video.width
        item_height = height or best_video.height
        created_at = (
            datetime.fromtimestamp(published_ts, tz=UTC) if published_ts is not None else None
        )
        item_meta: dict[str, Any] = {
            "post_key": f"facebook:video:{video_id}",
            "extractor": FACEBOOK_CATEGORY,
        }
        if published_ts is not None:
            item_meta["published_timestamp"] = published_ts

        item = make_media_item(
            provider=self.name,
            source_url=source_url,
            media_url=best_video.url,
            media_type=MediaType.VIDEO,
            post_id="",
            title=title or f"Facebook Video {video_id}",
            author=author or "facebook",
            thumbnail_url=thumbnail_url,
            duration_seconds=duration_seconds,
            width=item_width,
            height=item_height,
            extension=best_video.container or "mp4",
            mime_type=f"video/{best_video.container or 'mp4'}",
            format_info=None,
            provider_media_id=video_id,
            post_url=post_url,
            attachment_index=0,
            metadata_extra=item_meta,
        )
        item.available_formats = formats

        return make_post(
            provider=self.name,
            source_url=source_url,
            post_key=f"facebook:video:{video_id}",
            provider_post_id=video_id,
            author=author or "facebook",
            title=title or f"Facebook Video {video_id}",
            media_items=[item],
            post_url=post_url,
            created_at=created_at,
            metadata_extra={
                "extractor": FACEBOOK_CATEGORY,
                "group_key": f"facebook:video:{video_id}",
            },
        )

    def _graphql_post_raw(
        self,
        extractor: Any,
        *,
        fb_dtsg: str,
        lsd: str,
        friendly_name: str,
        doc_id: str,
        variables: dict[str, Any],
        referer: str,
    ) -> str | None:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-FB-LSD": lsd,
            "X-ASBD-ID": "129477",
            "X-FB-Friendly-Name": friendly_name,
            "Referer": referer,
            "Origin": "https://www.facebook.com",
        }
        payload = {
            "fb_dtsg": fb_dtsg,
            "lsd": lsd,
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": friendly_name,
            "variables": json.dumps(variables),
            "server_timestamps": "true",
            "doc_id": doc_id,
        }
        for attempt in range(2):
            try:
                resp = extractor.request(
                    "https://www.facebook.com/api/graphql/",
                    method="POST",
                    headers=headers,
                    data=payload,
                    fatal=False,
                )
            except Exception:
                if attempt == 0:
                    time.sleep(0.8)
                    continue
                return None
            status = getattr(resp, "status_code", 200)
            if status in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(0.8)
                continue
            if status >= 400:
                return None
            text = getattr(resp, "text", "") or ""
            if text or attempt == 1:
                return text
            time.sleep(0.5)
        return None

    def _graphql_post(
        self,
        extractor: Any,
        *,
        fb_dtsg: str,
        lsd: str,
        friendly_name: str,
        doc_id: str,
        variables: dict[str, Any],
        referer: str,
    ) -> dict[str, Any] | None:
        raw = self._graphql_post_raw(
            extractor,
            fb_dtsg=fb_dtsg,
            lsd=lsd,
            friendly_name=friendly_name,
            doc_id=doc_id,
            variables=variables,
            referer=referer,
        )
        return _parse_ndjson_primary(raw) if raw else None

    def _extract_formats_from_media_dict(
        self,
        media: dict[str, Any],
    ) -> tuple[list[MediaFormatInfo], float | None]:
        formats: list[MediaFormatInfo] = []
        duration: float | None = None

        vdl = media.get("videoDeliveryLegacyFields") or {}
        mpd_xml = vdl.get("dash_manifest_xml_string") or media.get("dash_manifest")
        if isinstance(mpd_xml, str) and "<MPD" in mpd_xml:
            formats, duration = parse_facebook_dash_mpd(mpd_xml)

        # Also check progressive HD/SD URLs as fallback / muxed alternatives
        progressive_candidates: list[tuple[str, int, str | None]] = []
        for key, label, height in (
            ("browser_native_hd_url", "hd", 720),
            ("playable_url_quality_hd", "hd", 720),
            ("browser_native_sd_url", "sd", 360),
            ("playable_url", "sd", 360),
        ):
            raw_url = media.get(key) or vdl.get(key)
            if isinstance(raw_url, str) and raw_url.startswith("http"):
                progressive_candidates.append((label, height, raw_url))

        vdr = (media.get("videoDeliveryResponseFragment") or {}).get(
            "videoDeliveryResponseResult"
        ) or {}
        for item in vdr.get("progressive_urls") or []:
            if not isinstance(item, dict):
                continue
            p_url = item.get("progressive_url")
            if isinstance(p_url, str) and p_url.startswith("http"):
                meta = item.get("metadata") or {}
                q = str(meta.get("quality") or "").lower()
                is_hd = q == "hd"
                progressive_candidates.append(
                    ("hd" if is_hd else "sd", 720 if is_hd else 360, p_url)
                )

        existing_ids = {f.format_id for f in formats}
        existing_urls = {f.url for f in formats}
        for label, height, p_url in progressive_candidates:
            if p_url in existing_urls:
                continue
            fmt_id = label if label not in existing_ids else f"progressive-{label}"
            if fmt_id in existing_ids:
                continue
            existing_ids.add(fmt_id)
            existing_urls.add(p_url)
            formats.append(
                MediaFormatInfo(
                    format_id=fmt_id,
                    container="mp4",
                    resolution=f"{height}p",
                    video_codec="h264",
                    audio_codec="aac",
                    height=height,
                    is_direct_stream=True,
                    url=p_url,
                    requires_merge=False,
                    format_note=f"progressive {label}",
                )
            )

        if duration is None:
            ms = media.get("playable_duration_in_ms")
            if isinstance(ms, (int, float)) and ms > 0:
                duration = round(float(ms) / 1000.0, 3)

        return formats, duration

    def _extract_single_facebook_video(
        self,
        video_url: str,
        extractor: Any,
        *,
        fallback_author: str = "facebook",
        warn: WarningCallback | None = None,
    ) -> list[Post]:
        """Extract all streams/resolutions for one Facebook reel/video URL."""
        try:
            resp = extractor.request(video_url, fatal=False)
            html_text = getattr(resp, "text", "") or ""
            final_url = getattr(resp, "url", video_url) or video_url
        except Exception as exc:
            html_text = ""
            final_url = video_url
            logger.debug("Direct Facebook video fetch failed for %s: %s", video_url, exc)

        formats: list[MediaFormatInfo] = []
        duration: float | None = None
        published_ts: float | None = None
        title: str | None = None
        author = fallback_author
        thumbnail_url: str | None = None

        vid_match = _RE_SINGLE_VIDEO_ID.search(final_url) or _RE_SINGLE_VIDEO_ID.search(video_url)
        video_id = (vid_match.group(1) or vid_match.group(2)) if vid_match else None

        if html_text:
            clean = html_text.replace("\\/", "/")
            if not video_id:
                m_vid = re.search(r'"video_id":"(\d+)"', clean)
                if m_vid:
                    video_id = m_vid.group(1)

            # Prefer structured dash_manifest_xml_string when present
            for m_mpd in re.finditer(r'"dash_manifest_xml_string":"(<\?xml[^"]+)"', html_text):
                try:
                    xml_str = json.loads(f'"{m_mpd.group(1)}"')
                except Exception:
                    continue
                parsed_fmts, parsed_dur = parse_facebook_dash_mpd(xml_str)
                if parsed_fmts:
                    formats = parsed_fmts
                    duration = parsed_dur
                    break

            # Fallback: raw <MPD>...</MPD> embedded anywhere in JS/HTML payload
            if not formats:
                for m_raw_mpd in re.finditer(r"(<MPD[\s\S]{50,25000}?</MPD>)", html_text):
                    raw_block = m_raw_mpd.group(1)
                    if "\\u003C" in raw_block or '\\"' in raw_block or "\\/" in raw_block:
                        try:
                            raw_block = json.loads(f'"{raw_block}"')
                        except Exception:
                            raw_block = (
                                raw_block.replace("\\u003C", "<")
                                .replace('\\"', '"')
                                .replace("\\/", "/")
                            )
                    parsed_fmts, parsed_dur = parse_facebook_dash_mpd(raw_block)
                    if parsed_fmts:
                        formats = parsed_fmts
                        duration = parsed_dur
                        break

            # Add progressive browser_native_hd_url / sd_url fallbacks
            existing_urls = {f.url for f in formats}
            existing_ids = {f.format_id for f in formats}
            for key, label, h in (
                ("browser_native_hd_url", "hd", 720),
                ("playable_url_quality_hd", "hd", 720),
                ("browser_native_sd_url", "sd", 360),
                ("playable_url", "sd", 360),
            ):
                m_prog = re.search(rf'"{key}":"([^"]+)"', html_text)
                if m_prog:
                    p_url = _decode_js_escaped_url(m_prog.group(1))
                    if p_url.startswith("http") and p_url not in existing_urls:
                        fmt_id = label if label not in existing_ids else f"progressive-{label}"
                        existing_urls.add(p_url)
                        existing_ids.add(fmt_id)
                        formats.append(
                            MediaFormatInfo(
                                format_id=fmt_id,
                                container="mp4",
                                resolution=f"{h}p",
                                video_codec="h264",
                                audio_codec="aac",
                                height=h,
                                is_direct_stream=True,
                                url=p_url,
                                requires_merge=False,
                                format_note=f"progressive {label}",
                            )
                        )

            m_ts = re.search(r'"publish_time":(\d+)|"created_time":(\d+)', clean)
            if m_ts:
                published_ts = float(m_ts.group(1) or m_ts.group(2))

            m_thumb = re.search(
                r'"(?:first_frame_thumbnail|thumbnailImage)":(?:\{"uri":)?\s*"(https://[^"]+)"',
                clean,
            ) or re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html_text)
            if m_thumb:
                thumbnail_url = html_lib.unescape(m_thumb.group(1))

            m_title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html_text)
            if m_title:
                title = html_lib.unescape(m_title.group(1)).strip() or None

            m_owner = re.search(
                r'"video_owner":\{"__typename":"(?:User|Page)","name":"([^"]+)"', clean
            )
            if m_owner:
                try:
                    author = json.loads(f'"{m_owner.group(1)}"')
                except Exception:
                    author = m_owner.group(1)

        if video_id and formats:
            post = self._build_video_post_from_formats(
                video_id=video_id,
                source_url=video_url,
                post_url=f"https://www.facebook.com/reel/{video_id}"
                if "/reel/" in video_url
                else video_url,
                author=author,
                title=title,
                thumbnail_url=thumbnail_url,
                formats=formats,
                duration_seconds=duration,
                published_ts=published_ts,
            )
            if post is not None:
                return [post]

        # Fallback to yt-dlp for watch/?v=, share links, or unusual embed pages
        try:
            from ..ytdlp import YtDlpProvider

            yt_posts = list(
                YtDlpProvider().iter_posts(
                    video_url,
                    ScanOptions(include_videos=True, include_images=False, max_posts=5),
                    threading.Event(),
                )
            )
            if yt_posts:
                for p_obj in yt_posts:
                    p_obj.provider = self.name
                    for it in p_obj.media_items:
                        it.provider = self.name
                        it.metadata_extra["extractor"] = FACEBOOK_CATEGORY
                return yt_posts
        except Exception as exc:
            if warn:
                logger.debug("yt-dlp Facebook fallback skipped for %s: %s", video_url, exc)

        # Last-resort gallery-dl single-video extractor
        try:
            state = _DiscoveryState(
                options=ScanOptions(include_videos=True, include_images=False, max_posts=5)
            )
            return list(
                super()._discover(
                    video_url,
                    threading.Event(),
                    warn or (lambda _m: None),
                    None,
                    state,
                    depth=1,
                )
            )
        except Exception:
            return []

    def _iter_paginated_reels(
        self,
        profile_base: str,
        extractor: Any,
        cancel_event: threading.Event,
        warn: WarningCallback,
        on_page: PageCallback | None,
        state: _DiscoveryState,
        seen_video_ids: set[str],
    ) -> Iterator[Post]:
        """Discover all Reels from a Facebook profile via GraphQL pagination."""
        reels_url = f"{profile_base}/reels"
        try:
            resp = extractor.request(reels_url, fatal=False)
        except Exception as exc:
            warn(f"Could not fetch Facebook reels page: {exc}")
            return
        if getattr(resp, "status_code", 200) >= 400:
            warn(f"Facebook reels page returned HTTP {resp.status_code}.")
            return

        html_text = getattr(resp, "text", "") or ""
        clean = html_text.replace("\\/", "/")
        dtsg, lsd, preload_vars = _extract_tokens_and_preload_vars(clean)

        shorts_conn, col_id = _extract_connection_info(clean, "aggregated_fb_shorts")

        # Author hint from profile HTML
        author_fallback = profile_base.rsplit("/", 1)[-1]
        m_title = re.search(r"<title>([^<|]+)", html_text)
        if m_title:
            candidate = html_lib.unescape(m_title.group(1)).strip()
            if candidate and candidate.lower() != "facebook":
                author_fallback = candidate

        if dtsg and lsd and shorts_conn is not None and col_id:
            doc_id = _resolve_doc_id_from_bundles(clean, REELS_PAGINATION_QUERY_NAME)
            base_vars = {
                k: v for k, v in preload_vars.items() if k.startswith("__relay_internal__pv__")
            }
            base_vars.update(
                {
                    "count": 20,
                    "id": col_id,
                    "scale": 1,
                    "useDefaultActor": False,
                    "renderLocation": "TIMELINE",
                }
            )
            cursor: str | None = None
            has_next = True
            page_index = 0
            retried_doc_lookup = False

            while has_next and not cancel_event.is_set() and not state.limit_reached():
                page_index += 1
                variables = {**base_vars, "cursor": cursor}
                payload = self._graphql_post(
                    extractor,
                    fb_dtsg=dtsg,
                    lsd=lsd,
                    friendly_name=REELS_PAGINATION_QUERY_NAME,
                    doc_id=doc_id,
                    variables=variables,
                    referer=reels_url,
                )
                if payload is None or not ((payload.get("data") or {}).get("node") or {}).get(
                    "aggregated_fb_shorts"
                ):
                    if not retried_doc_lookup:
                        retried_doc_lookup = True
                        doc_id = _resolve_doc_id_from_bundles(
                            clean, REELS_PAGINATION_QUERY_NAME, force_refresh=True
                        )
                        continue
                    break

                shorts = payload["data"]["node"]["aggregated_fb_shorts"]
                edges = shorts.get("edges") or []
                if on_page is not None:
                    on_page(page_index)
                    state.page_reported = True

                for edge in edges:
                    if cancel_event.is_set() or state.limit_reached():
                        return
                    story = (edge.get("profile_reel_node") or {}).get("node") or {}
                    attachments = story.get("attachments") or []
                    media = (
                        attachments[0].get("media")
                        if attachments and isinstance(attachments[0], dict)
                        else {}
                    )
                    if not isinstance(media, dict):
                        media = {}

                    vid = str(media.get("id") or "")
                    if not vid or vid in seen_video_ids:
                        continue
                    seen_video_ids.add(vid)

                    permalink = str(
                        media.get("permalink_url") or f"https://www.facebook.com/reel/{vid}"
                    )
                    formats, duration = self._extract_formats_from_media_dict(media)
                    caption, pub_ts = _extract_caption_and_timestamp(story, media)
                    thumb = _extract_thumbnail_from_media(media)
                    owner_name = _extract_owner_name(story, media, author_fallback)

                    post = None
                    if formats:
                        post = self._build_video_post_from_formats(
                            video_id=vid,
                            source_url=reels_url,
                            post_url=permalink,
                            author=owner_name,
                            title=caption,
                            thumbnail_url=thumb,
                            formats=formats,
                            duration_seconds=duration,
                            published_ts=pub_ts,
                            width=media.get("width")
                            if isinstance(media.get("width"), int)
                            else None,
                            height=media.get("height")
                            if isinstance(media.get("height"), int)
                            else None,
                        )
                    if post is None:
                        fallback_posts = self._extract_single_facebook_video(
                            permalink,
                            extractor,
                            fallback_author=owner_name,
                            warn=warn,
                        )
                        if fallback_posts:
                            post = fallback_posts[0]
                    if post is not None:
                        state.posts_emitted += 1
                        state.media_count += len(post.media_items)
                        yield post

                pinfo = shorts.get("page_info") or {}
                next_cursor = pinfo.get("end_cursor")
                has_next = (
                    bool(pinfo.get("has_next_page")) and bool(next_cursor) and next_cursor != cursor
                )
                cursor = next_cursor
            return

        # Fallback: initial SSR HTML video IDs (for Page layouts without aggregated_fb_shorts)
        for vid in _facebook_video_ids([html_text]):
            if cancel_event.is_set() or state.limit_reached():
                return
            if vid in seen_video_ids:
                continue
            seen_video_ids.add(vid)
            for post in self._extract_single_facebook_video(
                f"https://www.facebook.com/reel/{vid}",
                extractor,
                fallback_author=author_fallback,
                warn=warn,
            ):
                state.posts_emitted += 1
                state.media_count += len(post.media_items)
                yield post

    def _iter_paginated_videos(
        self,
        profile_base: str,
        extractor: Any,
        cancel_event: threading.Event,
        warn: WarningCallback,
        on_page: PageCallback | None,
        state: _DiscoveryState,
        seen_video_ids: set[str],
    ) -> Iterator[Post]:
        """Discover all videos from a Facebook profile/page Videos tab via GraphQL pagination."""
        videos_url = f"{profile_base}/videos"
        try:
            resp = extractor.request(videos_url, fatal=False)
        except Exception as exc:
            warn(f"Could not fetch Facebook videos page: {exc}")
            return
        if getattr(resp, "status_code", 200) >= 400:
            warn(f"Facebook videos page returned HTTP {resp.status_code}.")
            return

        html_text = getattr(resp, "text", "") or ""
        clean = html_text.replace("\\/", "/")
        dtsg, lsd, _ = _extract_tokens_and_preload_vars(clean)

        author_fallback = profile_base.rsplit("/", 1)[-1]
        ordered_ids: list[str] = []
        seen_in_tab: set[str] = set()

        def _record_vid(vid: str) -> None:
            if vid and vid not in seen_in_tab and vid not in seen_video_ids:
                seen_in_tab.add(vid)
                ordered_ids.append(vid)

        for vid in _facebook_video_ids([html_text]):
            _record_vid(vid)

        all_videos_conn, page_id = _extract_connection_info(clean, "all_videos")
        if all_videos_conn and page_id:
            for edge in all_videos_conn.get("edges") or []:
                node = (edge.get("node") if isinstance(edge, dict) else None) or {}
                if isinstance(node, dict) and node.get("id"):
                    _record_vid(str(node["id"]))

            pinfo_init = all_videos_conn.get("page_info") or {}
            cursor: str | None = pinfo_init.get("end_cursor")
            has_next = bool(pinfo_init.get("has_next_page")) and bool(cursor)

            if has_next and dtsg and lsd:
                doc_id = _resolve_doc_id_from_bundles(clean, VIDEOS_PAGINATION_QUERY_NAME)
                retried_doc_lookup = False
                page_index = 1
                while has_next and not cancel_event.is_set():
                    page_index += 1
                    payload = self._graphql_post(
                        extractor,
                        fb_dtsg=dtsg,
                        lsd=lsd,
                        friendly_name=VIDEOS_PAGINATION_QUERY_NAME,
                        doc_id=doc_id,
                        variables={
                            "alwaysIncludeAudioRooms": False,
                            "count": 20,
                            "cursor": cursor,
                            "id": page_id,
                            "scale": 1,
                        },
                        referer=videos_url,
                    )
                    if payload is None or not ((payload.get("data") or {}).get("node") or {}).get(
                        "all_videos"
                    ):
                        if not retried_doc_lookup:
                            retried_doc_lookup = True
                            doc_id = _resolve_doc_id_from_bundles(
                                clean, VIDEOS_PAGINATION_QUERY_NAME, force_refresh=True
                            )
                            continue
                        break

                    all_videos = payload["data"]["node"]["all_videos"]
                    for edge in all_videos.get("edges") or []:
                        node = edge.get("node") or {}
                        if (
                            isinstance(node, dict)
                            and node.get("__typename") == "Video"
                            and node.get("id")
                        ):
                            _record_vid(str(node["id"]))

                    if on_page is not None:
                        on_page(page_index)
                        state.page_reported = True

                    pinfo = all_videos.get("page_info") or {}
                    next_cursor = pinfo.get("end_cursor")
                    has_next = (
                        bool(pinfo.get("has_next_page"))
                        and bool(next_cursor)
                        and next_cursor != cursor
                    )
                    cursor = next_cursor
                    if (
                        state.options.max_posts
                        and len(seen_video_ids) + len(ordered_ids) >= state.options.max_posts
                    ):
                        break
        else:
            # Personal profiles may expose videos under /videos_by instead of /videos.
            try:
                vb_resp = extractor.request(f"{profile_base}/videos_by", fatal=False)
                if getattr(vb_resp, "status_code", 200) < 400:
                    for vid in _facebook_video_ids([getattr(vb_resp, "text", "") or ""]):
                        _record_vid(vid)
            except Exception:
                pass

        for vid in ordered_ids:
            if cancel_event.is_set() or state.limit_reached():
                return
            if vid in seen_video_ids:
                continue
            seen_video_ids.add(vid)
            posts = self._extract_single_facebook_video(
                f"https://www.facebook.com/watch/?v={vid}",
                extractor,
                fallback_author=author_fallback,
                warn=warn,
            )
            if not posts:
                posts = self._extract_single_facebook_video(
                    f"https://www.facebook.com/reel/{vid}",
                    extractor,
                    fallback_author=author_fallback,
                    warn=warn,
                )
            for post in posts:
                state.posts_emitted += 1
                state.media_count += len(post.media_items)
                yield post

    def _build_story_image_post(
        self,
        *,
        photo_id: str,
        image_url: str,
        source_url: str,
        post_url: str,
        author: str,
        title: str | None = None,
        published_ts: float | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> Post:
        path = image_url.split("?", 1)[0].rsplit("/", 1)[-1]
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else "jpg"
        if ext not in ("jpg", "jpeg", "png", "webp", "gif", "avif"):
            ext = "jpg"
        created_at = (
            datetime.fromtimestamp(published_ts, tz=UTC) if published_ts is not None else None
        )
        fmt = MediaFormatInfo(
            format_id="original",
            container=ext,
            resolution=f"{width}x{height}" if width and height else None,
            width=width,
            height=height,
            is_direct_stream=True,
            url=image_url,
            requires_merge=False,
            format_note="original",
        )
        item_meta: dict[str, Any] = {
            "post_key": f"facebook:story:{photo_id}",
            "extractor": FACEBOOK_CATEGORY,
        }
        if published_ts is not None:
            item_meta["published_timestamp"] = published_ts
        item = make_media_item(
            provider=self.name,
            source_url=source_url,
            media_url=image_url,
            media_type=MediaType.IMAGE,
            post_id="",
            title=title or f"Facebook Story {photo_id}",
            author=author or "facebook",
            thumbnail_url=image_url,
            width=width,
            height=height,
            extension=ext,
            mime_type=f"image/{ext}",
            format_info=fmt,
            provider_media_id=photo_id,
            post_url=post_url,
            attachment_index=0,
            metadata_extra=item_meta,
        )
        return make_post(
            provider=self.name,
            source_url=source_url,
            post_key=f"facebook:story:{photo_id}",
            provider_post_id=photo_id,
            author=author or "facebook",
            title=title or f"Facebook Story {photo_id}",
            media_items=[item],
            post_url=post_url,
            created_at=created_at,
            metadata_extra={
                "extractor": FACEBOOK_CATEGORY,
                "group_key": f"facebook:story:{photo_id}",
            },
        )

    def _iter_story_bucket_posts(
        self,
        bucket_id: str,
        extractor: Any,
        *,
        source_url: str,
        fallback_author: str,
        options: ScanOptions,
        cancel_event: threading.Event,
        warn: WarningCallback,
        state: _DiscoveryState,
        seen_video_ids: set[str],
        seen_story_photo_ids: set[str],
    ) -> Iterator[Post]:
        """Extract all video and image cards from one Facebook Story / Highlight bucket."""
        story_bucket_url = f"https://www.facebook.com/stories/{bucket_id}"
        try:
            resp = extractor.request(story_bucket_url, fatal=False)
        except Exception as exc:
            warn(f"Could not open Facebook story highlight {bucket_id}: {exc}")
            return
        if getattr(resp, "status_code", 200) >= 400:
            return

        html_text = getattr(resp, "text", "") or ""
        clean = html_text.replace("\\/", "/")
        dtsg, lsd, _ = _extract_tokens_and_preload_vars(clean)
        payloads: list[Any] = []

        # Collect preloaded Relay JSON embedded directly inside /stories/<bucket_id> HTML.
        for script_body in re.findall(
            r'<script[^>]+type="application/json"[^>]*>(.*?)</script>',
            html_text,
            re.DOTALL,
        ):
            if "unified_stories" not in script_body and "story_bucket_owner" not in script_body:
                continue
            try:
                payloads.append(json.loads(script_body))
            except Exception:
                continue

        # Fetch full Stories bucket payload if SSR HTML lacked attachments or had only nav stubs.
        initial_stories, bucket_owner = _collect_story_nodes_from_payloads(
            payloads, target_bucket_id=bucket_id
        )
        needs_gql = not initial_stories or any(
            not (s.get("attachments") or s.get("media")) for s in initial_stories
        )
        if needs_gql and dtsg and lsd:
            m_pre = re.search(
                r'"adp_StoriesSuspenseContentPaneRootWithEntryPointQueryRelayPreloader_[^"]+",'
                r'"queryID":"(\d+)","variables":(\{.*?\}),'
                r'"queryName":"StoriesSuspenseContentPaneRootWithEntryPointQuery"',
                clean,
            )
            if m_pre:
                doc_id = m_pre.group(1)
                try:
                    variables = json.loads(m_pre.group(2))
                except Exception:
                    variables = {}
            else:
                doc_id = _resolve_doc_id_from_bundles(clean, STORIES_CONTENT_QUERY_NAME)
                variables = {
                    "blur": 10,
                    "bucketID": bucket_id,
                    "feedbackSource": 65,
                    "feedLocation": "COMET_MEDIA_VIEWER",
                    "focusCommentID": None,
                    "initialBucketID": bucket_id,
                    "initialLoad": True,
                    "isFbNotesIncluded": True,
                    "isStoriesArchive": False,
                    "scale": 1,
                    "shouldDeferLoad": False,
                    "shouldEnableArmadilloStoryReply": True,
                    "shouldEnableLiveInStories": True,
                }
            raw_gql = self._graphql_post_raw(
                extractor,
                fb_dtsg=dtsg,
                lsd=lsd,
                friendly_name=STORIES_CONTENT_QUERY_NAME,
                doc_id=doc_id,
                variables=variables,
                referer=story_bucket_url,
            )
            if raw_gql:
                payloads.extend(_parse_ndjson_chunks(raw_gql))
            initial_stories, owner_after = _collect_story_nodes_from_payloads(
                payloads, target_bucket_id=bucket_id
            )
            bucket_owner = bucket_owner or owner_after

        author = bucket_owner or fallback_author
        for story in initial_stories:
            if cancel_event.is_set() or state.limit_reached():
                return
            story_id = str(story.get("id") or "")
            attachments = story.get("attachments") or []
            media_candidates: list[dict[str, Any]] = []
            for att in attachments:
                if isinstance(att, dict) and isinstance(att.get("media"), dict):
                    media_candidates.append(att["media"])
            if not media_candidates and isinstance(story.get("media"), dict):
                media_candidates.append(story["media"])

            for media in media_candidates:
                if cancel_event.is_set() or state.limit_reached():
                    return
                typename = str(media.get("__typename") or "")
                formats, duration = self._extract_formats_from_media_dict(media)
                is_video = bool(formats) or typename == "Video"
                caption, pub_ts = _extract_caption_and_timestamp(story, media)
                thumb = _extract_thumbnail_from_media(media)
                owner_name = _extract_owner_name(story, media, author)

                if is_video:
                    if not options.include_videos:
                        continue
                    vid = str(media.get("id") or story_id)
                    if not vid or vid in seen_video_ids:
                        continue
                    seen_video_ids.add(vid)
                    card_url = str(
                        media.get("permalink_url")
                        or f"https://www.facebook.com/stories/{bucket_id}/{vid}"
                    )
                    post = None
                    if formats:
                        post = self._build_video_post_from_formats(
                            video_id=vid,
                            source_url=source_url,
                            post_url=card_url,
                            author=owner_name,
                            title=caption,
                            thumbnail_url=thumb,
                            formats=formats,
                            duration_seconds=duration,
                            published_ts=pub_ts,
                            width=media.get("width")
                            if isinstance(media.get("width"), int)
                            else None,
                            height=media.get("height")
                            if isinstance(media.get("height"), int)
                            else None,
                        )
                    if post is None and vid.isdigit():
                        fallback_posts = self._extract_single_facebook_video(
                            f"https://www.facebook.com/watch/?v={vid}",
                            extractor,
                            fallback_author=owner_name,
                            warn=warn,
                        )
                        if fallback_posts:
                            post = fallback_posts[0]
                    if post is not None:
                        state.posts_emitted += 1
                        state.media_count += len(post.media_items)
                        yield post
                elif options.include_images:
                    img_url = None
                    img_w = None
                    img_h = None
                    for key in ("image", "photo_image", "previewImage", "large_share_image"):
                        val = media.get(key)
                        if isinstance(val, dict) and isinstance(val.get("uri"), str):
                            img_url = val["uri"]
                            img_w = val.get("width") if isinstance(val.get("width"), int) else None
                            img_h = (
                                val.get("height") if isinstance(val.get("height"), int) else None
                            )
                            break
                        if isinstance(val, str) and val.startswith("http"):
                            img_url = val
                            break
                    if not img_url:
                        img_url = thumb
                    pid = str(media.get("id") or story_id)
                    if not img_url or not pid or pid in seen_story_photo_ids:
                        continue
                    seen_story_photo_ids.add(pid)
                    card_url = f"https://www.facebook.com/stories/{bucket_id}/{pid}"
                    post = self._build_story_image_post(
                        photo_id=pid,
                        image_url=img_url,
                        source_url=source_url,
                        post_url=card_url,
                        author=owner_name,
                        title=caption,
                        published_ts=pub_ts,
                        width=img_w,
                        height=img_h,
                    )
                    state.posts_emitted += 1
                    state.media_count += len(post.media_items)
                    yield post

    def _iter_profile_highlights(
        self,
        profile_base: str,
        extractor: Any,
        *,
        options: ScanOptions,
        cancel_event: threading.Event,
        warn: WarningCallback,
        on_page: PageCallback | None,
        state: _DiscoveryState,
        seen_video_ids: set[str],
    ) -> Iterator[Post]:
        """Discover Facebook profile Featured Highlights and active Story buckets."""
        try:
            resp = extractor.request(profile_base, fatal=False)
        except Exception:
            return
        if getattr(resp, "status_code", 200) >= 400:
            return

        html_text = getattr(resp, "text", "") or ""
        clean = html_text.replace("\\/", "/")
        dtsg, lsd, _ = _extract_tokens_and_preload_vars(clean)

        author_fallback = profile_base.rsplit("/", 1)[-1]
        m_title = re.search(r"<title>([^<|]+)", html_text)
        if m_title:
            candidate = html_lib.unescape(m_title.group(1)).strip()
            if candidate and candidate.lower() != "facebook":
                author_fallback = candidate

        exclude_ids: set[str] = set()
        if author_fallback.isdigit():
            exclude_ids.add(author_fallback)
        tail_seg = profile_base.rsplit("/", 1)[-1]
        if tail_seg.isdigit():
            exclude_ids.add(tail_seg)
        id_pat = r'"(?:userID|delegate_page)":\s*(?:\{"[^}]*"id":)?\s*"(\d+)"'
        for m_uid in re.findall(id_pat, clean):
            exclude_ids.add(m_uid)

        payloads: list[Any] = []
        m_pre = re.search(
            r'"adp_ProfileCometTimelineListViewRootQueryRelayPreloader_[^"]+",'
            r'"queryID":"(\d+)","variables":(\{.*?\}),'
            r'"queryName":"ProfileCometTimelineListViewRootQuery"',
            clean,
        )
        if m_pre and dtsg and lsd:
            try:
                variables = json.loads(m_pre.group(2))
                raw_gql = self._graphql_post_raw(
                    extractor,
                    fb_dtsg=dtsg,
                    lsd=lsd,
                    friendly_name=TIMELINE_ROOT_QUERY_NAME,
                    doc_id=m_pre.group(1),
                    variables=variables,
                    referer=profile_base,
                )
                if raw_gql:
                    tl_chunks = _parse_ndjson_chunks(raw_gql)
                    payloads.extend(tl_chunks)
                    # Paginate profile_tile_sections when Featured Highlights sit past tile 2.
                    target_uid = str(variables.get("userID") or "")

                    def _tile_page_info(
                        chunks: list[Any], root_key: str
                    ) -> tuple[bool, str | None, str | None]:
                        for ch in chunks:
                            if not isinstance(ch, dict):
                                continue
                            holder = (ch.get("data") or {}).get(root_key)
                            if not isinstance(holder, dict):
                                continue
                            pts = holder.get("profile_tile_sections")
                            pinfo = pts.get("page_info") if isinstance(pts, dict) else None
                            if isinstance(pinfo, dict):
                                hid = str(holder.get("id") or "") or None
                                return (
                                    bool(pinfo.get("has_next_page")),
                                    pinfo.get("end_cursor"),
                                    hid,
                                )
                        return False, None, None

                    has_next, cursor, found_uid = _tile_page_info(tl_chunks, "user")
                    target_uid = found_uid or target_uid
                    tiles_doc_id = _resolve_doc_id_from_bundles(clean, TILES_PAGINATION_QUERY_NAME)
                    for _ in range(6):
                        if not has_next or not cursor or not target_uid or cancel_event.is_set():
                            break
                        tile_raw = self._graphql_post_raw(
                            extractor,
                            fb_dtsg=dtsg,
                            lsd=lsd,
                            friendly_name=TILES_PAGINATION_QUERY_NAME,
                            doc_id=tiles_doc_id,
                            variables={
                                "count": 4,
                                "cursor": cursor,
                                "id": target_uid,
                                "previousProfileId": None,
                                "renderLocation": "timeline",
                                "scale": 1,
                            },
                            referer=profile_base,
                        )
                        if not tile_raw:
                            break
                        tile_chunks = _parse_ndjson_chunks(tile_raw)
                        payloads.extend(tile_chunks)
                        next_has, next_cursor, _ = _tile_page_info(tile_chunks, "node")
                        if not next_cursor or next_cursor == cursor:
                            break
                        cursor = next_cursor
                        has_next = next_has
            except Exception:
                pass

        bucket_ids = _extract_highlight_bucket_ids(
            html_text,
            payloads,
            exclude_ids=exclude_ids,
        )
        if not bucket_ids:
            return

        seen_story_photo_ids: set[str] = set()
        for idx, bucket_id in enumerate(bucket_ids, 1):
            if cancel_event.is_set() or state.limit_reached():
                return
            if on_page is not None:
                on_page(idx, len(bucket_ids))
                state.page_reported = True
            yield from self._iter_story_bucket_posts(
                bucket_id,
                extractor,
                source_url=profile_base,
                fallback_author=author_fallback,
                options=options,
                cancel_event=cancel_event,
                warn=warn,
                state=state,
                seen_video_ids=seen_video_ids,
                seen_story_photo_ids=seen_story_photo_ids,
            )

    def _iter_profile_photos_and_albums(
        self,
        profile_base: str,
        *,
        include_photos_tab: bool,
        include_albums_tab: bool,
        include_avatar: bool,
        cancel_event: threading.Event,
        warn: WarningCallback,
        on_page: PageCallback | None,
        state: _DiscoveryState,
    ) -> Iterator[Post]:
        """Discover profile photos, albums, and avatars without losing one tab if another fails."""
        tab_urls: list[str] = []
        if include_photos_tab:
            tab_urls.append(f"{profile_base}/photos")
        if include_albums_tab:
            tab_urls.append(f"{profile_base}/photos_albums")
        if include_avatar:
            tab_urls.append(f"{profile_base}/avatar")

        seen_photo_keys: set[str] = set()
        for tab_url in tab_urls:
            if cancel_event.is_set() or state.limit_reached():
                return
            try:
                for post in super()._discover(
                    tab_url,
                    cancel_event,
                    warn,
                    on_page,
                    state,
                    depth=0,
                ):
                    unique_items = []
                    for item in post.media_items:
                        key = str(item.provider_media_id or item.original_url)
                        if key in seen_photo_keys:
                            continue
                        seen_photo_keys.add(key)
                        unique_items.append(item)
                    if not unique_items:
                        state.posts_emitted = max(0, state.posts_emitted - 1)
                        state.media_count = max(0, state.media_count - len(post.media_items))
                        continue
                    if len(unique_items) < len(post.media_items):
                        dropped = len(post.media_items) - len(unique_items)
                        state.media_count = max(0, state.media_count - dropped)
                        post.media_items = unique_items
                        post.post_type = Post.infer_type(unique_items)
                    yield post
            except XakuMediaError as exc:
                warn(f"Facebook {tab_url.rsplit('/', 1)[-1]} discovery ended early: {exc.message}")
            except Exception as exc:
                warn(f"Facebook {tab_url.rsplit('/', 1)[-1]} discovery ended early: {exc}")

    def iter_posts(
        self,
        url: str,
        options: ScanOptions,
        cancel_event: threading.Event,
        on_page: PageCallback | None = None,
        on_warning: WarningCallback | None = None,
        on_total: TotalCallback | None = None,
    ) -> Iterator[Post]:
        safe_url = validate_url_security(url)
        warn = on_warning or (lambda _msg: None)
        target = _parse_facebook_url(safe_url)
        state = _DiscoveryState(options=options)
        seen_video_ids: set[str] = set()

        if target.scope == "video":
            if not options.include_videos:
                return
            if on_total is not None:
                on_total(1, None)
            extractor = self._prepare_extractor("https://www.facebook.com/reel/0")
            posts = self._extract_single_facebook_video(safe_url, extractor, warn=warn)
            if not posts:
                raise self._no_media_error(safe_url)
            for post in posts:
                yield post
            return

        if target.scope == "stories" and target.video_id:
            extractor = self._prepare_extractor("https://www.facebook.com/reel/0")
            seen_story_photo_ids: set[str] = set()
            yield from self._iter_story_bucket_posts(
                target.video_id,
                extractor,
                source_url=safe_url,
                fallback_author="facebook",
                options=options,
                cancel_event=cancel_event,
                warn=warn,
                state=state,
                seen_video_ids=seen_video_ids,
                seen_story_photo_ids=seen_story_photo_ids,
            )
            if state.posts_emitted == 0:
                raise self._no_media_error(safe_url)
            return

        if target.scope in ("reels", "videos", "profile") and target.profile_base:
            extractor = self._warm_facebook_session(target.profile_base)

            if options.include_videos:
                if target.scope in ("reels", "profile"):
                    yield from self._iter_paginated_reels(
                        target.profile_base,
                        extractor,
                        cancel_event,
                        warn,
                        on_page,
                        state,
                        seen_video_ids,
                    )
                if target.scope in ("videos", "profile") and not state.limit_reached():
                    yield from self._iter_paginated_videos(
                        target.profile_base,
                        extractor,
                        cancel_event,
                        warn,
                        on_page,
                        state,
                        seen_video_ids,
                    )

            if (
                target.scope == "profile"
                and not cancel_event.is_set()
                and not state.limit_reached()
            ):
                try:
                    yield from self._iter_profile_highlights(
                        target.profile_base,
                        extractor,
                        options=options,
                        cancel_event=cancel_event,
                        warn=warn,
                        on_page=on_page,
                        state=state,
                        seen_video_ids=seen_video_ids,
                    )
                except Exception as exc:
                    logger.debug("Facebook highlights skipped for %s: %s", target.profile_base, exc)

            if target.scope == "profile" and options.include_images and not state.limit_reached():
                yield from self._iter_profile_photos_and_albums(
                    target.profile_base,
                    include_photos_tab=True,
                    include_albums_tab=True,
                    include_avatar=True,
                    cancel_event=cancel_event,
                    warn=warn,
                    on_page=on_page,
                    state=state,
                )

            if state.posts_emitted == 0:
                raise self._no_media_error(safe_url)
            return

        if target.scope == "photos" and target.profile_base and options.include_images:
            albums_only = target.canonical_gallery_url.rstrip("/").endswith("/photos_albums")
            yield from self._iter_profile_photos_and_albums(
                target.profile_base,
                include_photos_tab=not albums_only,
                include_albums_tab=True,
                include_avatar=False,
                cancel_event=cancel_event,
                warn=warn,
                on_page=on_page,
                state=state,
            )
            if state.posts_emitted == 0:
                raise self._no_media_error(safe_url)
            return

        # "gallery" (album/set/photo/post/group)
        try:
            yield from super()._discover(
                target.canonical_gallery_url,
                cancel_event,
                warn,
                on_page,
                state,
                depth=0,
            )
        except Exception as exc:
            # Post URLs (/posts/..., /permalink.php) often embed video that gallery-dl misses
            if target.scope == "gallery" and options.include_videos and state.posts_emitted == 0:
                extractor = self._prepare_extractor("https://www.facebook.com/reel/0")
                posts = self._extract_single_facebook_video(safe_url, extractor, warn=warn)
                if posts:
                    for post in posts:
                        yield post
                    return
            if isinstance(exc, ExtractionError):
                raise
            raise

        if state.posts_emitted == 0 and target.scope == "gallery" and options.include_videos:
            extractor = self._prepare_extractor("https://www.facebook.com/reel/0")
            posts = self._extract_single_facebook_video(safe_url, extractor, warn=warn)
            for post in posts:
                state.posts_emitted += 1
                yield post

        if state.posts_emitted == 0:
            raise self._no_media_error(safe_url)
