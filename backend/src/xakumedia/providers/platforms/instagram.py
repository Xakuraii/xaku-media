"""Instagram discovery provider adapter for profiles, posts, reels, stories, and highlights."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from gallery_dl import config as gdl_config
from gallery_dl.exception import (
    AuthenticationError,
    AuthorizationError,
    HttpError,
    NoExtractorError,
    NotFoundError,
)

from ...core.logging import get_logger
from ...exceptions.base import ExtractionError
from ...extractors.gallery import parse_gallery_dl_error
from ...models.media import MediaFormatInfo, MediaType
from ...models.post import Post, ProviderCapabilities, ScanOptions
from ...models.url import ClassifiedUrl, UrlCategory
from ...utils.security import validate_url_security
from ..base import (
    PageCallback,
    TotalCallback,
    WarningCallback,
    extract_published_timestamp,
    host_of,
    lookup_cookie_profile,
    make_media_item,
    make_post,
)
from ..dash import parse_dash_mpd
from ..gallerydl import GalleryDlProvider, _DiscoveryState

logger = get_logger("providers.instagram")

INSTAGRAM_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
    "instagr.am",
}

_RESERVED_IG_PATHS = {
    "explore",
    "accounts",
    "direct",
    "stories",
    "reels",
    "reel",
    "p",
    "tv",
    "tags",
    "locations",
    "audio",
    "share",
    "api",
    "graphql",
    "static",
    "about",
    "legal",
    "developer",
}

_STATIC_FRAMERATE_RE = re.compile(r'frameRate="(\d+)/(\d+)"')
_PROFILE_SCOPES = {"profile", "reels", "stories", "highlights", "highlight", "tagged", "reposts"}


@dataclass(frozen=True)
class InstagramTarget:
    """Normalized representation of an Instagram URL and requested scope."""

    # profile | reels | stories | highlights | highlight | tagged | reposts | post | gallery
    scope: str
    canonical_url: str
    username: str | None = None
    shortcode: str | None = None
    highlight_id: str | None = None


def _parse_instagram_url(url: str) -> InstagramTarget:
    """Classify an Instagram URL into its canonical scope and identifier."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return InstagramTarget(scope="gallery", canonical_url=url)

    segments = [seg for seg in parts.path.split("/") if seg]
    if not segments:
        return InstagramTarget(scope="gallery", canonical_url=url)

    first = segments[0].lower()

    # /p/<code>, /reel/<code>, /reels/<code>, /tv/<code>
    if first in ("p", "reel", "reels", "tv") and len(segments) >= 2:
        code = segments[1]
        kind = "reel" if first in ("reel", "reels") else ("tv" if first == "tv" else "p")
        return InstagramTarget(
            scope="post",
            canonical_url=f"https://www.instagram.com/{kind}/{code}/",
            shortcode=code,
        )

    # /<user>/p/<code>, /<user>/reel/<code>, /<user>/reels/<code>, /<user>/tv/<code>
    if (
        len(segments) >= 3
        and first not in _RESERVED_IG_PATHS
        and segments[1].lower() in ("p", "reel", "reels", "tv")
    ):
        code = segments[2]
        kind = "reel" if segments[1].lower() in ("reel", "reels") else "p"
        return InstagramTarget(
            scope="post",
            canonical_url=f"https://www.instagram.com/{kind}/{code}/",
            username=segments[0],
            shortcode=code,
        )

    # /stories/highlights/<id>/
    if first == "stories" and len(segments) >= 3 and segments[1].lower() == "highlights":
        hid = segments[2]
        return InstagramTarget(
            scope="highlight",
            canonical_url=f"https://www.instagram.com/stories/highlights/{hid}/",
            highlight_id=hid,
        )

    # /stories/<user>/...
    if first == "stories" and len(segments) >= 2 and segments[1].lower() != "me":
        user = segments[1]
        return InstagramTarget(
            scope="stories",
            canonical_url=f"https://www.instagram.com/stories/{user}/",
            username=user,
        )

    if first in _RESERVED_IG_PATHS:
        return InstagramTarget(scope="gallery", canonical_url=url)

    user = segments[0]
    if len(segments) == 1 or segments[1].lower() in ("posts", "photos"):
        return InstagramTarget(
            scope="profile",
            canonical_url=f"https://www.instagram.com/{user}/",
            username=user,
        )

    tab = segments[1].lower()
    if tab == "reels":
        return InstagramTarget(
            scope="reels",
            canonical_url=f"https://www.instagram.com/{user}/reels/",
            username=user,
        )
    if tab == "stories":
        return InstagramTarget(
            scope="stories",
            canonical_url=f"https://www.instagram.com/stories/{user}/",
            username=user,
        )
    if tab == "highlights":
        return InstagramTarget(
            scope="highlights",
            canonical_url=f"https://www.instagram.com/{user}/highlights/",
            username=user,
        )
    if tab == "tagged":
        return InstagramTarget(
            scope="tagged",
            canonical_url=f"https://www.instagram.com/{user}/tagged/",
            username=user,
        )
    if tab == "reposts":
        return InstagramTarget(
            scope="reposts",
            canonical_url=f"https://www.instagram.com/{user}/reposts/",
            username=user,
        )

    return InstagramTarget(scope="gallery", canonical_url=url, username=user)


def _infer_image_extension(image_url: str) -> str:
    path = image_url.split("?", 1)[0].rsplit("/", 1)[-1]
    if "." in path:
        ext = path.rsplit(".", 1)[-1].lower()
        if ext in ("jpg", "jpeg", "png", "webp", "gif", "avif", "heic"):
            return ext
    return "jpg"


def _best_instagram_image(item: dict[str, Any]) -> tuple[str | None, int | None, int | None]:
    candidates = ((item.get("image_versions2") or {}).get("candidates")) or []
    best_url: str | None = None
    best_w: int | None = None
    best_h: int | None = None
    best_area = -1
    for cand in candidates:
        if not isinstance(cand, dict) or not cand.get("url"):
            continue
        w = int(cand["width"]) if isinstance(cand.get("width"), (int, float)) else None
        h = int(cand["height"]) if isinstance(cand.get("height"), (int, float)) else None
        area = (w or 0) * (h or 0)
        if area > best_area:
            best_area = area
            best_url = str(cand["url"])
            best_w = w
            best_h = h
    return best_url, best_w, best_h


def _is_static_music_photo(item: dict[str, Any]) -> bool:
    """Return True when a 1fps music-backed image wears a dummy video manifest."""
    manifest = item.get("video_dash_manifest")
    if not isinstance(manifest, str) or not manifest:
        return False
    match = _STATIC_FRAMERATE_RE.search(manifest)
    if not match:
        return False
    return match.group(1) == match.group(2)


def _extract_instagram_video_formats(
    item: dict[str, Any],
) -> tuple[list[MediaFormatInfo], float | None]:
    """Return all DASH (up to 1080p) and progressive MP4 streams for one IG video slide."""
    if _is_static_music_photo(item):
        return [], None

    formats: list[MediaFormatInfo] = []
    duration: float | None = None

    mpd_xml = item.get("video_dash_manifest")
    if isinstance(mpd_xml, str) and "<MPD" in mpd_xml:
        formats, duration = parse_dash_mpd(mpd_xml)

    raw_versions = [
        v for v in (item.get("video_versions") or []) if isinstance(v, dict) and v.get("url")
    ]
    raw_versions.sort(
        key=lambda v: (
            int(v.get("height") or 0),
            int(v.get("width") or 0),
            int(v.get("bandwidth") or 0),
        ),
        reverse=True,
    )

    seen_urls = {f.url for f in formats}
    seen_ids = {f.format_id for f in formats}
    for v in raw_versions:
        v_url = str(v["url"])
        if v_url in seen_urls:
            continue
        w = int(v["width"]) if isinstance(v.get("width"), (int, float)) else None
        h = int(v["height"]) if isinstance(v.get("height"), (int, float)) else None
        res_label = f"{w}x{h}" if w and h else None
        tier = min(w, h) if w and h else h
        base_id = f"{tier}p-progressive" if tier else "progressive"
        fmt_id = base_id
        if fmt_id in seen_ids:
            fmt_id = f"{base_id}-{len(seen_ids) + 1}"
        seen_urls.add(v_url)
        seen_ids.add(fmt_id)
        formats.append(
            MediaFormatInfo(
                format_id=fmt_id,
                container="mp4",
                resolution=res_label,
                video_codec="h264",
                audio_codec="aac",
                width=w,
                height=h,
                is_direct_stream=True,
                url=v_url,
                requires_merge=False,
                format_note=f"progressive {tier}p" if tier else "progressive",
            )
        )

    if duration is None:
        raw_dur = item.get("video_duration")
        if isinstance(raw_dur, (int, float)) and raw_dur > 0:
            duration = float(raw_dur)

    return formats, duration


class InstagramProvider(GalleryDlProvider):
    """Dedicated provider for Instagram profiles, posts, reels, stories, and highlights."""

    platform_name = "instagram"
    label = "Instagram (gallery-dl)"

    @classmethod
    def match(cls, url: str) -> bool:
        return host_of(url) in INSTAGRAM_HOSTS

    def _cookie_candidate_urls(self, url: str) -> tuple[str, ...]:
        return (url, "https://www.instagram.com/")

    def capabilities_for(self, url: str) -> ProviderCapabilities:
        target = _parse_instagram_url(url)
        has_cookies = lookup_cookie_profile(self._cookie_candidate_urls(url)) is not None
        is_profile = target.scope in _PROFILE_SCOPES
        return ProviderCapabilities(
            provider=self.name,
            label=self.label,
            source_type="profile" if is_profile else "gallery",
            profile_bulk=is_profile,
            individual_posts=True,
            albums=True,
            images=target.scope != "reels",
            videos=True,
            pagination=is_profile,
            requires_auth=not has_cookies,
            has_cookies=has_cookies,
            notes=(
                "Instagram profile scans discover Posts, Reels, active Stories, and Highlights."
                if is_profile
                else f"Instagram {target.scope} extractor."
            )
            + (
                " This site usually requires authorized session cookies."
                if not has_cookies
                else ""
            ),
        )

    def classify(self, url: str) -> ClassifiedUrl:
        target = _parse_instagram_url(url)
        parts = urlsplit(target.canonical_url)
        is_profile = target.scope in _PROFILE_SCOPES
        category = (
            UrlCategory.CHANNEL
            if is_profile
            else (UrlCategory.SOCIAL_POST if target.scope == "post" else UrlCategory.GALLERY)
        )
        return ClassifiedUrl(
            raw_url=url,
            normalized_url=target.canonical_url,
            category=category,
            platform="instagram",
            domain=parts.netloc or "www.instagram.com",
            author_hint=target.username,
            title_hint=(
                f"@{target.username}"
                if target.username
                else (target.shortcode or target.highlight_id or "Instagram")
            ),
            is_supported=True,
            requires_auth=False,
            metadata_extra={"provider": self.name, "instagram_scope": target.scope},
        )

    def _prepare_extractor(self, safe_url: str):
        # Keep request pacing fast enough for large reel/post scans while staying polite.
        gdl_config.set(("extractor", "instagram"), "sleep-request", (0.8, 1.5))
        return super()._prepare_extractor(safe_url)

    def _build_post_from_ig_media(
        self,
        post_dict: dict[str, Any],
        *,
        source_url: str,
        fallback_author: str,
        options: ScanOptions,
        post_url_override: str | None = None,
        title_fallback: str | None = None,
    ) -> Post | None:
        raw_pk = str(post_dict.get("pk") or post_dict.get("id") or "")
        post_pk = raw_pk.split("_", 1)[0]
        shortcode = str(post_dict.get("code") or "")
        post_identity = post_pk or shortcode
        if not post_identity:
            return None

        user_obj = post_dict.get("user") if isinstance(post_dict.get("user"), dict) else {}
        author = str(user_obj.get("username") or fallback_author or "instagram")
        caption_obj = post_dict.get("caption")
        caption: str | None = None
        if isinstance(caption_obj, dict) and isinstance(caption_obj.get("text"), str):
            caption = caption_obj["text"].strip() or None
        elif isinstance(caption_obj, str) and caption_obj.strip():
            caption = caption_obj.strip()
        if not caption and title_fallback:
            caption = title_fallback

        raw_ts = post_dict.get("taken_at") or post_dict.get("created_at")
        pub_ts = extract_published_timestamp({"timestamp": raw_ts}) if raw_ts else None
        created_at = datetime.fromtimestamp(pub_ts, tz=UTC) if pub_ts is not None else None

        product_type = str(post_dict.get("product_type") or "")
        if post_url_override:
            post_url = post_url_override
        elif shortcode:
            kind = "reel" if product_type == "clips" else "p"
            post_url = f"https://www.instagram.com/{kind}/{shortcode}/"
        else:
            post_url = source_url

        slides = post_dict.get("carousel_media") or [post_dict]
        post_key = f"post_id:{post_identity}"
        media_items = []

        for idx, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            slide_pk = str(slide.get("pk") or slide.get("id") or "").split("_", 1)[0]
            slide_id = (
                slide_pk
                if (slide_pk and (len(slides) > 1 or slide_pk != post_identity))
                else post_identity
            )
            if slide_id == post_identity and len(slides) > 1:
                slide_id = f"{post_identity}:{idx + 1}"

            slide_ts_raw = slide.get("taken_at") or raw_ts
            slide_ts = (
                extract_published_timestamp({"timestamp": slide_ts_raw})
                if slide_ts_raw
                else pub_ts
            )
            thumb_url, thumb_w, thumb_h = _best_instagram_image(slide)
            video_formats, duration = _extract_instagram_video_formats(slide)

            if video_formats:
                if not options.include_videos:
                    continue
                best_muxed = next(
                    (
                        f
                        for f in video_formats
                        if f.video_codec and f.audio_codec and not f.requires_merge
                    ),
                    None,
                )
                best_video = next((f for f in video_formats if f.video_codec), video_formats[0])
                preview_url = (best_muxed.url if best_muxed and best_muxed.url else None) or (
                    best_video.url or ""
                )
                item_meta: dict[str, Any] = {
                    "post_key": post_key,
                    "extractor": "instagram",
                }
                if slide_ts is not None:
                    item_meta["published_timestamp"] = slide_ts
                item = make_media_item(
                    provider=self.name,
                    source_url=source_url,
                    media_url=preview_url,
                    media_type=MediaType.VIDEO,
                    post_id="",
                    title=caption,
                    author=author,
                    thumbnail_url=thumb_url,
                    duration_seconds=duration,
                    width=slide.get("original_width") or best_video.width or thumb_w,
                    height=slide.get("original_height") or best_video.height or thumb_h,
                    extension="mp4",
                    mime_type="video/mp4",
                    format_info=None,
                    provider_media_id=slide_id,
                    post_url=post_url,
                    attachment_index=len(media_items),
                    metadata_extra=item_meta,
                )
                item.available_formats = video_formats
                media_items.append(item)
            else:
                if not options.include_images or not thumb_url:
                    continue
                ext = _infer_image_extension(thumb_url)
                w = slide.get("original_width") or thumb_w
                h = slide.get("original_height") or thumb_h
                img_fmt = MediaFormatInfo(
                    format_id="original",
                    container=ext,
                    resolution=f"{w}x{h}" if w and h else None,
                    width=w,
                    height=h,
                    is_direct_stream=True,
                    url=thumb_url,
                    requires_merge=False,
                    format_note="original",
                )
                item_meta = {
                    "post_key": post_key,
                    "extractor": "instagram",
                }
                if slide_ts is not None:
                    item_meta["published_timestamp"] = slide_ts
                item = make_media_item(
                    provider=self.name,
                    source_url=source_url,
                    media_url=thumb_url,
                    media_type=MediaType.IMAGE,
                    post_id="",
                    title=caption,
                    author=author,
                    thumbnail_url=thumb_url,
                    width=w,
                    height=h,
                    extension=ext,
                    mime_type=f"image/{ext}",
                    format_info=img_fmt,
                    provider_media_id=slide_id,
                    post_url=post_url,
                    attachment_index=len(media_items),
                    metadata_extra=item_meta,
                )
                media_items.append(item)

        if not media_items:
            return None

        return make_post(
            provider=self.name,
            source_url=source_url,
            post_key=post_key,
            provider_post_id=post_identity,
            author=author,
            title=caption,
            media_items=media_items,
            post_url=post_url,
            created_at=created_at,
            metadata_extra={
                "extractor": "instagram",
                "shortcode": shortcode,
                "product_type": product_type,
                "group_key": post_key,
            },
        )

    def _hydrate_ig_media_by_code(
        self,
        extractor: Any,
        code: str,
    ) -> dict[str, Any] | None:
        """Fetch full /v1/media/<id>/info/ payload with 1 transient retry."""
        for attempt in range(2):
            try:
                items = list(extractor.api.media(code))
                if items and isinstance(items[0], dict):
                    return items[0]
                return None
            except (AuthenticationError, AuthorizationError):
                raise
            except Exception:
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                raise
        return None

    def _iter_profile_posts_tab(
        self,
        extractor: Any,
        username: str,
        *,
        source_url: str,
        options: ScanOptions,
        cancel_event: threading.Event,
        warn: WarningCallback,
        on_page: PageCallback | None,
        state: _DiscoveryState,
        seen_pks: set[str],
        seen_codes: set[str],
    ) -> Iterator[Post]:
        page = 0
        try:
            for index, raw_post in enumerate(extractor.api.user_feed(username), 1):
                if cancel_event.is_set() or state.limit_reached():
                    return
                if not isinstance(raw_post, dict):
                    continue
                if index % 12 == 1 and on_page is not None:
                    page += 1
                    on_page(page)
                    state.page_reported = True
                pk = str(raw_post.get("pk") or raw_post.get("id") or "").split("_", 1)[0]
                code = str(raw_post.get("code") or "")
                if (pk and pk in seen_pks) or (code and code in seen_codes):
                    continue
                if pk:
                    seen_pks.add(pk)
                if code:
                    seen_codes.add(code)
                post = self._build_post_from_ig_media(
                    raw_post,
                    source_url=source_url,
                    fallback_author=username,
                    options=options,
                )
                if post is None:
                    continue
                state.posts_emitted += 1
                state.media_count += len(post.media_items)
                yield post
        except (AuthenticationError, AuthorizationError):
            raise
        except Exception as exc:
            if state.posts_emitted == 0 and not options.include_videos:
                raise
            warn(f"Instagram Posts tab ended early for @{username}: {exc}")

    def _iter_profile_reels_tab(
        self,
        extractor: Any,
        username: str,
        *,
        source_url: str,
        options: ScanOptions,
        cancel_event: threading.Event,
        warn: WarningCallback,
        on_page: PageCallback | None,
        state: _DiscoveryState,
        seen_pks: set[str],
        seen_codes: set[str],
    ) -> Iterator[Post]:
        if not options.include_videos or cancel_event.is_set() or state.limit_reached():
            return
        page = 0
        try:
            for index, reel in enumerate(extractor.api.user_reels(username), 1):
                if cancel_event.is_set() or state.limit_reached():
                    return
                if index % 12 == 1 and on_page is not None:
                    page += 1
                    on_page(page)
                    state.page_reported = True
                media = (reel.get("media") if isinstance(reel, dict) else None) or {}
                if not isinstance(media, dict):
                    continue
                pk = str(media.get("pk") or media.get("id") or "").split("_", 1)[0]
                code = str(media.get("code") or "")
                if (pk and pk in seen_pks) or (code and code in seen_codes):
                    continue
                if pk:
                    seen_pks.add(pk)
                if code:
                    seen_codes.add(code)

                hydrated: dict[str, Any] | None = None
                if media.get("video_versions") or media.get("video_dash_manifest"):
                    hydrated = media
                elif code:
                    try:
                        hydrated = self._hydrate_ig_media_by_code(extractor, code)
                    except (AuthenticationError, AuthorizationError):
                        raise
                    except Exception as exc:
                        warn(f"Skipped Instagram reel {code}: {exc}")
                        continue
                if hydrated is None:
                    hydrated = media

                post_url = f"https://www.instagram.com/reel/{code}/" if code else source_url
                post = self._build_post_from_ig_media(
                    hydrated,
                    source_url=source_url,
                    fallback_author=username,
                    options=options,
                    post_url_override=post_url,
                )
                if post is None:
                    continue
                state.posts_emitted += 1
                state.media_count += len(post.media_items)
                yield post
        except (AuthenticationError, AuthorizationError):
            raise
        except Exception as exc:
            if state.posts_emitted == 0:
                raise
            warn(f"Instagram Reels tab ended early for @{username}: {exc}")

    def _iter_profile_stories(
        self,
        extractor: Any,
        username: str,
        *,
        source_url: str,
        options: ScanOptions,
        cancel_event: threading.Event,
        warn: WarningCallback,
        state: _DiscoveryState,
        seen_pks: set[str],
        best_effort: bool,
    ) -> Iterator[Post]:
        if cancel_event.is_set() or state.limit_reached():
            return
        try:
            user = extractor.api.user(username)
            user_id = str(user["id"])
            reels = extractor.api.reels_media([user_id]) or []
        except (AuthenticationError, AuthorizationError):
            if not best_effort:
                raise
            return
        except Exception as exc:
            if not best_effort and state.posts_emitted == 0:
                raise
            if not best_effort:
                warn(f"Could not fetch Instagram stories for @{username}: {exc}")
            return

        for reel in reels:
            if not isinstance(reel, dict):
                continue
            for item in reel.get("items") or ():
                if cancel_event.is_set() or state.limit_reached():
                    return
                if not isinstance(item, dict):
                    continue
                pk = str(item.get("pk") or item.get("id") or "").split("_", 1)[0]
                if not pk or pk in seen_pks:
                    continue
                seen_pks.add(pk)
                post = self._build_post_from_ig_media(
                    item,
                    source_url=source_url,
                    fallback_author=username,
                    options=options,
                    post_url_override=f"https://www.instagram.com/stories/{username}/{pk}/",
                )
                if post is None:
                    continue
                state.posts_emitted += 1
                state.media_count += len(post.media_items)
                yield post

    def _iter_highlights_by_ids(
        self,
        extractor: Any,
        reel_ids: list[str],
        *,
        username: str,
        source_url: str,
        options: ScanOptions,
        cancel_event: threading.Event,
        warn: WarningCallback,
        state: _DiscoveryState,
        seen_pks: set[str],
        best_effort: bool,
    ) -> Iterator[Post]:
        for start in range(0, len(reel_ids), 10):
            if cancel_event.is_set() or state.limit_reached():
                return
            chunk = reel_ids[start : start + 10]
            try:
                reels = extractor.api.reels_media(chunk) or []
            except (AuthenticationError, AuthorizationError):
                if not best_effort:
                    raise
                return
            except Exception as exc:
                if not best_effort and state.posts_emitted == 0:
                    raise
                warn(f"Skipped Instagram highlights batch: {exc}")
                continue
            for reel in reels:
                if not isinstance(reel, dict):
                    continue
                hl_id = str(reel.get("id") or "").removeprefix("highlight:")
                hl_title = str(reel.get("title") or "").strip() or None
                hl_url = (
                    f"https://www.instagram.com/stories/highlights/{hl_id}/"
                    if hl_id
                    else source_url
                )
                for item in reel.get("items") or ():
                    if cancel_event.is_set() or state.limit_reached():
                        return
                    if not isinstance(item, dict):
                        continue
                    pk = str(item.get("pk") or item.get("id") or "").split("_", 1)[0]
                    if not pk or pk in seen_pks:
                        continue
                    seen_pks.add(pk)
                    post = self._build_post_from_ig_media(
                        item,
                        source_url=source_url,
                        fallback_author=username,
                        options=options,
                        post_url_override=hl_url,
                        title_fallback=hl_title,
                    )
                    if post is None:
                        continue
                    state.posts_emitted += 1
                    state.media_count += len(post.media_items)
                    yield post

    def _iter_profile_highlights(
        self,
        extractor: Any,
        username: str,
        *,
        source_url: str,
        options: ScanOptions,
        cancel_event: threading.Event,
        warn: WarningCallback,
        state: _DiscoveryState,
        seen_pks: set[str],
        best_effort: bool,
    ) -> Iterator[Post]:
        if cancel_event.is_set() or state.limit_reached():
            return
        try:
            tray = list(extractor.api.highlights_tray(username) or ())
        except (AuthenticationError, AuthorizationError):
            if not best_effort:
                raise
            return
        except Exception as exc:
            if not best_effort and state.posts_emitted == 0:
                raise
            if not best_effort:
                warn(f"Could not fetch Instagram highlights for @{username}: {exc}")
            return

        reel_ids = [str(hl["id"]) for hl in tray if isinstance(hl, dict) and hl.get("id")]
        if not reel_ids:
            return
        yield from self._iter_highlights_by_ids(
            extractor,
            reel_ids,
            username=username,
            source_url=source_url,
            options=options,
            cancel_event=cancel_event,
            warn=warn,
            state=state,
            seen_pks=seen_pks,
            best_effort=best_effort,
        )

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
        target = _parse_instagram_url(safe_url)
        state = _DiscoveryState(options=options)
        seen_pks: set[str] = set()
        seen_codes: set[str] = set()

        if on_total is not None and target.scope not in _PROFILE_SCOPES:
            on_total(1, None)

        try:
            if target.scope == "post" and target.shortcode:
                extractor = self._prepare_extractor(target.canonical_url)
                raw = self._hydrate_ig_media_by_code(extractor, target.shortcode)
                if raw is not None:
                    post = self._build_post_from_ig_media(
                        raw,
                        source_url=target.canonical_url,
                        fallback_author=target.username or "instagram",
                        options=options,
                    )
                    if post is not None:
                        state.posts_emitted += 1
                        state.media_count += len(post.media_items)
                        yield post
                        return
                yield from super()._discover(
                    target.canonical_url, cancel_event, warn, on_page, state, depth=0
                )

            elif target.scope == "profile" and target.username:
                extractor = self._prepare_extractor(f"{target.canonical_url}posts/")
                # Warm user resolution cleanly before iterating tabs.
                extractor.api.user(target.username)

                yield from self._iter_profile_posts_tab(
                    extractor,
                    target.username,
                    source_url=target.canonical_url,
                    options=options,
                    cancel_event=cancel_event,
                    warn=warn,
                    on_page=on_page,
                    state=state,
                    seen_pks=seen_pks,
                    seen_codes=seen_codes,
                )
                if (
                    options.include_videos
                    and not cancel_event.is_set()
                    and not state.limit_reached()
                ):
                    yield from self._iter_profile_reels_tab(
                        extractor,
                        target.username,
                        source_url=target.canonical_url,
                        options=options,
                        cancel_event=cancel_event,
                        warn=warn,
                        on_page=on_page,
                        state=state,
                        seen_pks=seen_pks,
                        seen_codes=seen_codes,
                    )
                if not cancel_event.is_set() and not state.limit_reached():
                    yield from self._iter_profile_stories(
                        extractor,
                        target.username,
                        source_url=target.canonical_url,
                        options=options,
                        cancel_event=cancel_event,
                        warn=warn,
                        state=state,
                        seen_pks=seen_pks,
                        best_effort=True,
                    )
                if not cancel_event.is_set() and not state.limit_reached():
                    yield from self._iter_profile_highlights(
                        extractor,
                        target.username,
                        source_url=target.canonical_url,
                        options=options,
                        cancel_event=cancel_event,
                        warn=warn,
                        state=state,
                        seen_pks=seen_pks,
                        best_effort=True,
                    )

            elif target.scope == "reels" and target.username:
                extractor = self._prepare_extractor(target.canonical_url)
                yield from self._iter_profile_reels_tab(
                    extractor,
                    target.username,
                    source_url=target.canonical_url,
                    options=options,
                    cancel_event=cancel_event,
                    warn=warn,
                    on_page=on_page,
                    state=state,
                    seen_pks=seen_pks,
                    seen_codes=seen_codes,
                )

            elif target.scope == "stories" and target.username:
                extractor = self._prepare_extractor(target.canonical_url)
                yield from self._iter_profile_stories(
                    extractor,
                    target.username,
                    source_url=target.canonical_url,
                    options=options,
                    cancel_event=cancel_event,
                    warn=warn,
                    state=state,
                    seen_pks=seen_pks,
                    best_effort=False,
                )

            elif target.scope == "highlights" and target.username:
                extractor = self._prepare_extractor(target.canonical_url)
                yield from self._iter_profile_highlights(
                    extractor,
                    target.username,
                    source_url=target.canonical_url,
                    options=options,
                    cancel_event=cancel_event,
                    warn=warn,
                    state=state,
                    seen_pks=seen_pks,
                    best_effort=False,
                )

            elif target.scope == "highlight" and target.highlight_id:
                extractor = self._prepare_extractor(target.canonical_url)
                yield from self._iter_highlights_by_ids(
                    extractor,
                    [f"highlight:{target.highlight_id}"],
                    username="instagram",
                    source_url=target.canonical_url,
                    options=options,
                    cancel_event=cancel_event,
                    warn=warn,
                    state=state,
                    seen_pks=seen_pks,
                    best_effort=False,
                )

            else:
                yield from super()._discover(
                    target.canonical_url, cancel_event, warn, on_page, state, depth=0
                )

        except (AuthenticationError, AuthorizationError) as exc:
            raise self._explain(parse_gallery_dl_error(exc, safe_url), safe_url) from exc
        except (NotFoundError, HttpError, NoExtractorError) as exc:
            raise self._explain(parse_gallery_dl_error(exc, safe_url), safe_url) from exc
        except ExtractionError:
            raise
        except Exception as exc:
            raise self._explain(parse_gallery_dl_error(exc, safe_url), safe_url) from exc

        if state.posts_emitted == 0:
            raise self._no_media_error(safe_url)
