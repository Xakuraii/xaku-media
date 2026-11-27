"""Shared DASH MPD manifest parser for adaptive video and audio streams."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..models.media import MediaFormatInfo

_CODEC_ALIASES = (
    ("avc1", "h264"),
    ("h264", "h264"),
    ("vp09", "vp9"),
    ("vp9", "vp9"),
    ("vp08", "vp8"),
    ("vp8", "vp8"),
    ("av01", "av1"),
    ("av1", "av1"),
    ("hev1", "hevc"),
    ("hvc1", "hevc"),
    ("hevc", "hevc"),
    ("mp4a", "aac"),
    ("aac", "aac"),
    ("opus", "opus"),
)

_RE_DURATION_ISO = re.compile(
    r"^PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?$",
    re.IGNORECASE,
)


def _normalize_codec(raw: str | None) -> str | None:
    if not raw:
        return None
    lower = raw.lower()
    for prefix, canonical in _CODEC_ALIASES:
        if prefix in lower:
            return canonical
    return lower


def _parse_iso_duration(value: str | None) -> float | None:
    if not value:
        return None
    match = _RE_DURATION_ISO.match(value.strip())
    if not match:
        return None
    hours = float(match.group(1) or 0)
    minutes = float(match.group(2) or 0)
    seconds = float(match.group(3) or 0)
    total = hours * 3600.0 + minutes * 60.0 + seconds
    return total if total > 0 else None


def _codec_preference_rank(codec: str | None) -> int:
    c = (codec or "").lower()
    if c == "h264":
        return 3
    if c == "vp9":
        return 2
    if c == "av1":
        return 1
    return 0


def parse_dash_mpd(xml_string: str) -> tuple[list[MediaFormatInfo], float | None]:
    """Parse a Facebook/Instagram DASH MPD manifest into video and audio formats."""
    if not xml_string or "<MPD" not in xml_string:
        return [], None
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return [], None

    duration_seconds = _parse_iso_duration(root.attrib.get("mediaPresentationDuration"))
    video_formats: list[tuple[tuple[int, int, int, int], MediaFormatInfo]] = []
    audio_formats: list[tuple[int, MediaFormatInfo]] = []

    for elem in root.iter():
        if not elem.tag.endswith("AdaptationSet"):
            continue
        content_type = (elem.attrib.get("contentType") or "").lower()
        mime_base = (elem.attrib.get("mimeType") or "").lower()
        is_audio_set = content_type == "audio" or mime_base.startswith("audio/")
        is_video_set = content_type == "video" or mime_base.startswith("video/")

        for rep in elem:
            if not rep.tag.endswith("Representation"):
                continue
            base_url = next(
                (
                    child.text.strip()
                    for child in rep
                    if child.tag.endswith("BaseURL") and child.text
                ),
                None,
            )
            if not base_url:
                continue

            rep_mime = (rep.attrib.get("mimeType") or mime_base).lower()
            codecs_attr = rep.attrib.get("codecs") or ""
            codec = _normalize_codec(codecs_attr)
            bandwidth = (
                int(rep.attrib.get("bandwidth") or 0)
                if str(rep.attrib.get("bandwidth") or "").isdigit()
                else 0
            )

            if is_audio_set or rep_mime.startswith("audio/"):
                fmt = MediaFormatInfo(
                    format_id="audio" if not audio_formats else f"audio-{len(audio_formats) + 1}",
                    container="m4a",
                    audio_codec=codec or "aac",
                    is_direct_stream=True,
                    url=base_url,
                    requires_merge=False,
                    format_note="audio",
                )
                audio_formats.append((bandwidth, fmt))
                continue

            if is_video_set or rep_mime.startswith("video/"):
                width = (
                    int(rep.attrib["width"])
                    if str(rep.attrib.get("width") or "").isdigit()
                    else None
                )
                height = (
                    int(rep.attrib["height"])
                    if str(rep.attrib.get("height") or "").isdigit()
                    else None
                )
                short_edge = (
                    min(width, height) if width and height else height
                )
                quality_label = rep.attrib.get("FBQualityLabel") or (
                    f"{short_edge}p" if short_edge else "original"
                )
                v_codec = codec or "h264"
                fmt_id = f"{quality_label}-{v_codec}" if quality_label else v_codec
                resolution = f"{width}x{height}" if width and height else None
                fmt = MediaFormatInfo(
                    format_id=fmt_id,
                    container="mp4",
                    resolution=resolution,
                    video_codec=v_codec,
                    audio_codec=None,
                    width=width,
                    height=height,
                    is_direct_stream=True,
                    url=base_url,
                    requires_merge=False,
                    format_note=f"DASH {quality_label} ({v_codec})",
                )
                rank = (height or 0, width or 0, _codec_preference_rank(v_codec), bandwidth)
                video_formats.append((rank, fmt))

    # Highest resolution first, with H.264 ranked ahead of VP9/AV1 at equal dimensions.
    video_formats.sort(key=lambda pair: pair[0], reverse=True)
    audio_formats.sort(key=lambda pair: pair[0], reverse=True)

    ordered: list[MediaFormatInfo] = []
    seen_ids: set[str] = set()
    has_audio = bool(audio_formats)
    for _, fmt in video_formats:
        fmt.requires_merge = has_audio
        if fmt.format_id in seen_ids:
            fmt.format_id = f"{fmt.format_id}-{len(seen_ids) + 1}"
        seen_ids.add(fmt.format_id)
        ordered.append(fmt)

    if audio_formats:
        best_audio = audio_formats[0][1]
        best_audio.format_id = "audio"
        ordered.append(best_audio)

    return ordered, duration_seconds
