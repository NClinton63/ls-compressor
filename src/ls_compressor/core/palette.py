"""Dominant color palette extraction for images."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from ls_compressor.core.exceptions import UnsupportedFormatError
from ls_compressor.core.filesystem import ensure_source
from ls_compressor.core.media import MediaFormat, detect_media_format

_LOGGER = logging.getLogger("ls_compressor.core.palette")

_THUMBNAIL = 96


def extract_palette(source: Path, count: int = 8) -> list[str]:
    """Return up to ``count`` dominant colors of an image as hex strings.

    The image is downscaled to a small thumbnail (matching the web edition's
    approach for speed) and quantized with Pillow's median-cut algorithm;
    transparent pixels are composited over white first.
    """
    ensure_source(source)
    media_format = detect_media_format(source)
    if media_format is MediaFormat.VIDEO:
        raise UnsupportedFormatError(
            f"Palette extraction requires a raster image, not: {source}"
        )
    if count < 1:
        return []
    with Image.open(source) as image:
        thumb = _flatten(image)
        thumb.thumbnail((_THUMBNAIL, _THUMBNAIL), Image.Resampling.LANCZOS)
        quantized = thumb.quantize(colors=count)
        palette = quantized.getpalette() or []
        ranked = sorted(quantized.getcolors() or [], reverse=True)
        colors: list[str] = []
        for _, index in ranked[:count]:
            base = index * 3
            red, green, blue = palette[base : base + 3]
            colors.append(f"#{red:02x}{green:02x}{blue:02x}")
        _LOGGER.debug("Extracted palette colors=%d source=%s", len(colors), source)
        return colors


def _flatten(image: Image.Image) -> Image.Image:
    """Return an RGB image with transparency composited over white."""
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background.convert("RGB")
    return image.convert("RGB")
