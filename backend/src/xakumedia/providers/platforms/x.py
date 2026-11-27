"""X / Twitter discovery provider for profiles, statuses, images, and multi-quality videos."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
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
from ..gallerydl import X_HOSTS, GalleryDlProvider, _DiscoveryState

logger = get_logger("providers.x")

_X_RESERVED_PATHS = {
    "i",
    "home",
    "explore",
    "search",
    "notifications",
    "messages",
    "settings",
    "compose",
    "hashtag",
    "intent",
    "share",
    "login",
    "signup",
    "tos",
    "privacy",
    "following",
    "followers",
}
_PROFILE_SCOPES = {"profile", "likes", "highlights", "articles", "with_replies", "replies"}
_X_VID_DIM_RE = re.compile(r"/vid/(?:[a-z0-9]+/)?(\d+)x(\d+)/", re.IGNORECASE)


@dataclass(frozen=True)
class XTarget:
    """Normalized representation of an X / Twitter URL and requested scope."""

    scope: str  # profile | status | likes | highlights | articles | gallery
    canonical_url: str
    username: str | None = None
    tweet_id: str | None = None


def _parse_x_url(url: str) -> XTarget:
    """Classify an X / Twitter URL into profile, status, tab, or gallery scope."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return XTarget(scope="gallery", canonical_url=url)

    segments = [seg for seg in parts.path.split("/") if seg]
    if not segments:
        return XTarget(scope="gallery", canonical_url=url)

    # /i/status/<id>, /i/web/status/<id>, /<user>/status/<id>
    for idx, seg in enumerate(segments):
        if seg.lower() == "status" and idx + 1 < len(segments) and segments[idx + 1].isdigit():
            tweet_id = segments[idx + 1]
            owner = segments[0] if segments[0].lower() not in _X_RESERVED_PATHS else None
            canonical = (
                f"https://x.com/{owner}/status/{tweet_id}"
                if owner
                else f"https://x.com/i/status/{tweet_id}"
            )
            return XTarget(
                scope="status",
                canonical_url=canonical,
                username=owner,
                tweet_id=tweet_id,
            )

    first = segments[0].lower()
    if first in _X_RESERVED_PATHS:
        return XTarget(scope="gallery", canonical_url=url)

    user = segments[0].lstrip("@")
    if len(segments) == 1 or segments[1].lower() in ("media", "tweets", "posts"):
        return XTarget(
            scope="profile",
            canonical_url=f"https://x.com/{user}",
            username=user,
        )

    tab = segments[1].lower()
    if tab in ("likes", "highlights", "articles", "with_replies", "replies"):
        return XTarget(scope=tab, canonical_url=url, username=user)

    return XTarget(scope="gallery", canonical_url=url, username=user)


def _unwrap_tweet(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("__typename") == "TweetWithVisibilityResults" and isinstance(raw.get("tweet"), dict):
        return raw["tweet"]
    return raw


def _tweet_author_handle(tweet: dict[str, Any], fallback: str | None = None) -> str:
    core = tweet.get("core") if isinstance(tweet.get("core"), dict) else {}
    user_res = ((core.get("user_results") or {}).get("result")) or {}
    if isinstance(user_res, dict):
        handle = (
            (user_res.get("core") or {}).get("screen_name")
            or (user_res.get("legacy") or {}).get("screen_name")
        )
        if handle:
            return str(handle)
    author = tweet.get("author")
    if isinstance(author, dict) and author.get("name"):
        return str(author["name"])
    return fallback or "x"


def _parse_tweet_timestamp(raw_tweet: dict[str, Any], legacy: dict[str, Any]) -> float | None:
    raw_date = legacy.get("created_at") or raw_tweet.get("created_at")
    if isinstance(raw_date, str) and raw_date.strip():
        try:
            dt = parsedate_to_datetime(raw_date.strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.timestamp()
        except Exception:
            pass
    return extract_published_timestamp(legacy)


def _original_x_image_url(raw_url: str) -> tuple[str, str]:
    if len(raw_url) > 4 and raw_url[-4] == ".":
        base, _, fmt = raw_url.rpartition(".")
        ext = fmt.lower()
        return f"{base}?format={fmt}&name=orig", ext
    if "format=" in raw_url:
        ext_part = raw_url.split("format=", 1)[1].split("&", 1)[0].lower() or "jpg"
        base = raw_url.rpartition("=")[0] + "="
        return f"{base}orig", ext_part
    return raw_url, "jpg"


def _extract_article_image_urls(tweet: dict[str, Any]) -> list[str]:
    article = tweet.get("article")
    if not isinstance(article, dict):
        return []
    art_res = (article.get("article_results") or {}).get("result") or article
    if not isinstance(art_res, dict):
        return []

    urls: list[str] = []
    seen: set[str] = set()

    def _add(candidate: Any) -> None:
        if isinstance(candidate, str) and candidate.startswith("http") and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)

    cover = (art_res.get("cover_media") or {}).get("media_info") or {}
    if isinstance(cover, dict):
        _add(cover.get("original_img_url"))

    for ent in art_res.get("media_entities") or ():
        if not isinstance(ent, dict):
            continue
        info = ent.get("media_info") or {}
        if isinstance(info, dict):
            _add(info.get("original_img_url"))

    return urls


class XProvider(GalleryDlProvider):
    """Dedicated provider for X (x.com) and Twitter (twitter.com) media."""

    platform_name = "x"
    label = "X / Twitter (gallery-dl)"

    @classmethod
    def match(cls, url: str) -> bool:
        return host_of(url) in X_HOSTS

    def _cookie_candidate_urls(self, url: str) -> tuple[str, ...]:
        return (url, "https://x.com/", "https://twitter.com/")

    def capabilities_for(self, url: str) -> ProviderCapabilities:
        target = _parse_x_url(url)
        has_cookies = lookup_cookie_profile(self._cookie_candidate_urls(url)) is not None
        is_profile = target.scope in _PROFILE_SCOPES
        return ProviderCapabilities(
            provider=self.name,
            label=self.label,
            source_type="profile" if is_profile else "gallery",
            profile_bulk=is_profile,
            individual_posts=True,
            albums=True,
            images=True,
            videos=True,
            pagination=is_profile,
            requires_auth=is_profile and not has_cookies,
            has_cookies=has_cookies,
            notes=(
                "X profile scans combine media and original timelines with pinned tweets, cards, "
                "all MP4 resolutions, and strict creator filtering."
                if is_profile
                else f"X {target.scope} extractor."
            ),
        )

    def classify(self, url: str) -> ClassifiedUrl:
        target = _parse_x_url(url)
        parts = urlsplit(target.canonical_url)
        is_profile = target.scope in _PROFILE_SCOPES
        category = (
            UrlCategory.CHANNEL
            if is_profile
            else (UrlCategory.SOCIAL_POST if target.scope == "status" else UrlCategory.GALLERY)
        )
        return ClassifiedUrl(
            raw_url=url,
            normalized_url=target.canonical_url,
            category=category,
            platform="twitter",
            domain=parts.netloc or "x.com",
            author_hint=target.username,
            title_hint=(
                f"@{target.username}"
                if target.username
                else (target.tweet_id or "X")
            ),
            is_supported=True,
            requires_auth=is_profile,
            metadata_extra={"provider": self.name, "x_scope": target.scope},
        )

    def _prepare_extractor(self, safe_url: str):
        gdl_config.set(("extractor", "twitter"), "pinned", True)
        gdl_config.set(("extractor", "twitter"), "cards", True)
        gdl_config.set(("extractor", "twitter"), "previews", True)
        gdl_config.set(("extractor", "twitter"), "retweets", False)
        gdl_config.set(("extractor", "twitter"), "sleep-request", (0.5, 1.0))
        return super()._prepare_extractor(safe_url)

    def _build_post_from_tweet(
        self,
        raw_tweet: dict[str, Any],
        *,
        source_url: str,
        target_handle: str | None,
        strict_author: bool,
        options: ScanOptions,
    ) -> Post | None:
        tweet = _unwrap_tweet(raw_tweet)
        legacy = tweet.get("legacy") if isinstance(tweet.get("legacy"), dict) else tweet
        if not isinstance(legacy, dict):
            return None

        tweet_id = str(tweet.get("rest_id") or legacy.get("id_str") or "")
        if not tweet_id:
            return None

        # Never mix other creators' retweets into profile scans.
        if legacy.get("retweeted_status_id_str") or legacy.get("retweeted_status_result"):
            return None

        author = _tweet_author_handle(tweet, fallback=target_handle)
        if strict_author and target_handle and author.lower() != target_handle.lower():
            return None

        note_res = ((tweet.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result")
        raw_text = (
            note_res.get("text")
            if isinstance(note_res, dict) and note_res.get("text")
            else (legacy.get("full_text") or legacy.get("text") or "")
        )
        title = str(raw_text).strip()[:240] or None

        pub_ts = _parse_tweet_timestamp(tweet, legacy)
        created_at = datetime.fromtimestamp(pub_ts, tz=UTC) if pub_ts is not None else None
        post_url = f"https://x.com/{author}/status/{tweet_id}"
        post_key = f"tweet_id:{tweet_id}"

        media_entities = ((legacy.get("extended_entities") or {}).get("media")) or []
        media_items = []

        for idx, entity in enumerate(media_entities):
            if not isinstance(entity, dict):
                continue
            ext_avail = entity.get("ext_media_availability") or {}
            if isinstance(ext_avail, dict) and ext_avail.get("status") == "Unavailable":
                continue

            media_id = str(entity.get("id_str") or f"{tweet_id}:{idx}")
            raw_orig = entity.get("original_info")
            orig_info = raw_orig if isinstance(raw_orig, dict) else {}
            orig_w = int(orig_info["width"]) if isinstance(orig_info.get("width"), int) else None
            orig_h = int(orig_info["height"]) if isinstance(orig_info.get("height"), int) else None

            if "video_info" in entity:
                if not options.include_videos:
                    continue
                video_info = entity["video_info"] or {}
                raw_variants = [
                    v
                    for v in (video_info.get("variants") or ())
                    if isinstance(v, dict)
                    and v.get("url")
                    and (
                        v.get("content_type") == "video/mp4"
                        or ".mp4" in str(v.get("url")).split("?", 1)[0].lower()
                    )
                ]
                if not raw_variants:
                    continue

                parsed_variants: list[tuple[tuple[int, int, int], MediaFormatInfo]] = []
                is_gif = entity.get("type") == "animated_gif"
                seen_urls: set[str] = set()
                seen_ids: set[str] = set()

                for v in raw_variants:
                    v_url = str(v["url"])
                    if v_url in seen_urls:
                        continue
                    seen_urls.add(v_url)
                    bitrate = int(v.get("bitrate") or 0)
                    dim_match = _X_VID_DIM_RE.search(v_url)
                    vw = int(dim_match.group(1)) if dim_match else orig_w
                    vh = int(dim_match.group(2)) if dim_match else orig_h
                    tier = min(vw, vh) if vw and vh else vh
                    base_id = f"{tier}p" if tier else f"{bitrate // 1000}kbps"
                    fmt_id = base_id
                    if fmt_id in seen_ids:
                        fmt_id = f"{base_id}-{bitrate // 1000}k"
                    if fmt_id in seen_ids:
                        fmt_id = f"{fmt_id}-{len(seen_ids) + 1}"
                    seen_ids.add(fmt_id)
                    fmt = MediaFormatInfo(
                        format_id=fmt_id,
                        container="mp4",
                        resolution=f"{vw}x{vh}" if vw and vh else None,
                        video_codec="h264",
                        audio_codec=None if is_gif else "aac",
                        width=vw,
                        height=vh,
                        is_direct_stream=True,
                        url=v_url,
                        requires_merge=False,
                        format_note=f"{tier}p ({bitrate // 1000}kbps)" if tier else "mp4",
                    )
                    parsed_variants.append(((bitrate, vh or 0, vw or 0), fmt))

                parsed_variants.sort(key=lambda pair: pair[0], reverse=True)
                formats = [fmt for _, fmt in parsed_variants]
                best = formats[0]
                dur_ms = video_info.get("duration_millis")
                duration = (
                    round(float(dur_ms) / 1000.0, 3)
                    if isinstance(dur_ms, (int, float)) and dur_ms > 0
                    else None
                )

                item_meta: dict[str, Any] = {"post_key": post_key, "extractor": "twitter"}
                if pub_ts is not None:
                    item_meta["published_timestamp"] = pub_ts
                item = make_media_item(
                    provider=self.name,
                    source_url=source_url,
                    media_url=best.url,
                    media_type=MediaType.VIDEO,
                    post_id="",
                    title=title,
                    author=author,
                    thumbnail_url=entity.get("media_url_https"),
                    duration_seconds=duration,
                    width=best.width or orig_w,
                    height=best.height or orig_h,
                    extension="mp4",
                    mime_type="video/mp4",
                    format_info=None,
                    provider_media_id=media_id,
                    post_url=post_url,
                    attachment_index=len(media_items),
                    metadata_extra=item_meta,
                )
                item.available_formats = formats
                media_items.append(item)

            elif entity.get("media_url_https"):
                if not options.include_images:
                    continue
                img_url, ext = _original_x_image_url(str(entity["media_url_https"]))
                fmt = MediaFormatInfo(
                    format_id="original",
                    container=ext,
                    resolution=f"{orig_w}x{orig_h}" if orig_w and orig_h else None,
                    width=orig_w,
                    height=orig_h,
                    is_direct_stream=True,
                    url=img_url,
                    requires_merge=False,
                    format_note="original",
                )
                item_meta = {"post_key": post_key, "extractor": "twitter"}
                if pub_ts is not None:
                    item_meta["published_timestamp"] = pub_ts
                item = make_media_item(
                    provider=self.name,
                    source_url=source_url,
                    media_url=img_url,
                    media_type=MediaType.IMAGE,
                    post_id="",
                    title=title,
                    author=author,
                    thumbnail_url=img_url,
                    width=orig_w,
                    height=orig_h,
                    extension=ext,
                    mime_type=f"image/{ext}",
                    format_info=fmt,
                    provider_media_id=media_id,
                    post_url=post_url,
                    attachment_index=len(media_items),
                    metadata_extra=item_meta,
                )
                media_items.append(item)

        if options.include_images:
            existing_urls = {item.original_url for item in media_items}
            for art_idx, art_url in enumerate(_extract_article_image_urls(tweet)):
                orig_url, ext = _original_x_image_url(art_url)
                if orig_url in existing_urls:
                    continue
                existing_urls.add(orig_url)
                fmt = MediaFormatInfo(
                    format_id="original",
                    container=ext,
                    is_direct_stream=True,
                    url=orig_url,
                    requires_merge=False,
                    format_note="original",
                )
                item_meta = {"post_key": post_key, "extractor": "twitter"}
                if pub_ts is not None:
                    item_meta["published_timestamp"] = pub_ts
                media_items.append(
                    make_media_item(
                        provider=self.name,
                        source_url=source_url,
                        media_url=orig_url,
                        media_type=MediaType.IMAGE,
                        post_id="",
                        title=title,
                        author=author,
                        thumbnail_url=orig_url,
                        extension=ext,
                        mime_type=f"image/{ext}",
                        format_info=fmt,
                        provider_media_id=f"{tweet_id}:art:{art_idx}",
                        post_url=post_url,
                        attachment_index=len(media_items),
                        metadata_extra=item_meta,
                    )
                )

        if not media_items:
            return None

        return make_post(
            provider=self.name,
            source_url=source_url,
            post_key=post_key,
            provider_post_id=tweet_id,
            author=author,
            title=title,
            media_items=media_items,
            post_url=post_url,
            created_at=created_at,
            metadata_extra={
                "extractor": "twitter",
                "tweet_id": tweet_id,
                "group_key": post_key,
            },
        )

    def _consume_tweet_stream(
        self,
        tweets: Iterator[dict[str, Any]],
        *,
        source_url: str,
        target_handle: str | None,
        strict_author: bool,
        options: ScanOptions,
        cancel_event: threading.Event,
        on_page: PageCallback | None,
        state: _DiscoveryState,
        seen_tweet_ids: set[str],
    ) -> Iterator[Post]:
        page = state.media_count // 20
        for index, raw_tweet in enumerate(tweets, 1):
            if cancel_event.is_set() or state.limit_reached():
                return
            if not isinstance(raw_tweet, dict):
                continue
            unwrapped = _unwrap_tweet(raw_tweet)
            raw_legacy = unwrapped.get("legacy")
            legacy = raw_legacy if isinstance(raw_legacy, dict) else unwrapped
            tid = str(
                unwrapped.get("rest_id")
                or (legacy.get("id_str") if isinstance(legacy, dict) else "")
                or ""
            )
            if not tid or tid in seen_tweet_ids:
                continue
            seen_tweet_ids.add(tid)

            if index % 20 == 1 and on_page is not None:
                page += 1
                on_page(page)
                state.page_reported = True

            post = self._build_post_from_tweet(
                raw_tweet,
                source_url=source_url,
                target_handle=target_handle,
                strict_author=strict_author,
                options=options,
            )
            if post is None:
                continue
            state.posts_emitted += 1
            state.media_count += len(post.media_items)
            yield post

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
        target = _parse_x_url(safe_url)
        state = _DiscoveryState(options=options)
        seen_tweet_ids: set[str] = set()

        if on_total is not None and target.scope not in _PROFILE_SCOPES:
            on_total(1, None)

        try:
            if target.scope == "profile" and target.username:
                extractor = self._prepare_extractor(f"https://x.com/{target.username}/media")
                # Resolve user existence upfront so invalid handles fail fast.
                extractor.api.user_by_screen_name(target.username)

                # Pass 1: Photo + Video media timelines.
                try:
                    yield from self._consume_tweet_stream(
                        extractor.api.user_media(target.username),
                        source_url=target.canonical_url,
                        target_handle=target.username,
                        strict_author=True,
                        options=options,
                        cancel_event=cancel_event,
                        on_page=on_page,
                        state=state,
                        seen_tweet_ids=seen_tweet_ids,
                    )
                except (AuthenticationError, AuthorizationError):
                    raise
                except Exception as exc:
                    if state.posts_emitted == 0:
                        raise
                    warn(f"X media tab ended early for @{target.username}: {exc}")

                # Pass 2: Original timeline catches pinned/omitted media tweets and articles.
                if not cancel_event.is_set() and not state.limit_reached():
                    try:
                        yield from self._consume_tweet_stream(
                            extractor.api.user_original_timeline(target.username),
                            source_url=target.canonical_url,
                            target_handle=target.username,
                            strict_author=True,
                            options=options,
                            cancel_event=cancel_event,
                            on_page=on_page,
                            state=state,
                            seen_tweet_ids=seen_tweet_ids,
                        )
                    except (AuthenticationError, AuthorizationError):
                        if state.posts_emitted == 0:
                            raise
                        warn(
                            f"X timeline supplement stopped due to auth/rate limit "
                            f"for @{target.username}."
                        )
                    except Exception as exc:
                        if state.posts_emitted == 0:
                            raise
                        warn(f"X timeline supplement ended early for @{target.username}: {exc}")

            elif target.scope == "status" and target.tweet_id:
                extractor = self._prepare_extractor(target.canonical_url)
                matched = False
                for raw_tweet in extractor.api.tweet_detail(target.tweet_id):
                    if not isinstance(raw_tweet, dict):
                        continue
                    unwrapped = _unwrap_tweet(raw_tweet)
                    raw_legacy = unwrapped.get("legacy")
                    legacy = raw_legacy if isinstance(raw_legacy, dict) else {}
                    tid = str(unwrapped.get("rest_id") or legacy.get("id_str") or "")
                    if tid != target.tweet_id:
                        continue
                    post = self._build_post_from_tweet(
                        raw_tweet,
                        source_url=target.canonical_url,
                        target_handle=None,
                        strict_author=False,
                        options=options,
                    )
                    if post is not None:
                        matched = True
                        state.posts_emitted += 1
                        state.media_count += len(post.media_items)
                        yield post
                        break
                if not matched:
                    yield from super()._discover(
                        target.canonical_url, cancel_event, warn, on_page, state, depth=0
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
