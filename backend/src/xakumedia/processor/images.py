"""Image format conversion for the download pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Pillow's format name for each supported output extension.
_PIL_FORMATS = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "avif": "AVIF",
}

# Formats that cannot store an alpha channel.
_OPAQUE_FORMATS = {"jpg", "jpeg"}


class ImageConversionError(RuntimeError):
    """Raised when Pillow cannot convert an image to the requested format."""


def convert_image_format(
    path: Path,
    target_format: str,
    quality: int = 92,
) -> Path:
    """Convert ``path`` to ``target_format`` and return the new file path.

    Returns the original path unchanged when the file is already in the target
    format or when ``target_format`` is ``original``. The source file is removed
    only after the converted file has been written successfully.
    """
    target = target_format.lower().lstrip(".")
    if not target or target == "original":
        return path
    if path.suffix.lower().lstrip(".") == target:
        return path

    pil_format = _PIL_FORMATS.get(target)
    if not pil_format:
        raise ImageConversionError(f"Unsupported image format: {target_format}")

    from PIL import Image, UnidentifiedImageError

    destination = path.with_suffix(f".{target}")
    try:
        with Image.open(path) as image:
            converted = image
            if target in _OPAQUE_FORMATS and image.mode not in ("RGB", "L"):
                converted = image.convert("RGB")

            save_options: dict[str, object] = {}
            if pil_format == "JPEG":
                save_options = {"quality": quality, "optimize": True}
            elif pil_format == "WEBP":
                save_options = {"quality": quality, "method": 4}
            elif pil_format == "AVIF":
                save_options = {"quality": quality}

            converted.save(destination, format=pil_format, **save_options)
    except UnidentifiedImageError as exc:
        raise ImageConversionError(f"Unreadable image file: {path.name}") from exc
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise ImageConversionError(f"Could not convert {path.name}: {exc}") from exc

    path.unlink(missing_ok=True)
    logger.info(f"Converted image {path.name} -> {destination.name}")
    return destination


__all__ = ["ImageConversionError", "convert_image_format"]
