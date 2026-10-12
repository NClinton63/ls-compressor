"""Optional text watermarking for raster images (designer handoff tool).

Matches the web edition's optional watermark feature: renders a tiled or
anchored text layer over the image and re-encodes it in the destination
format. All destination writes go through the same no-overwrite rules as
the rest of the core.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from ls_compressor.core.exceptions import (
    DestinationExistsError,
    InvalidRequestError,
    UnsupportedFormatError,
)
from ls_compressor.core.media import (
    MediaFormat,
    detect_media_format,
)

_FONT_SIZE_RATIO: Final = 0.05  # ~5% of the shortest edge
_DEFAULT_MARGIN_RATIO: Final = 0.02
_TILE_ANGLE: Final = -30.0


class WatermarkPosition(StrEnum):
    """Anchor position for the watermark text."""

    TILE = "tile"
    CENTER = "center"
    TOP_LEFT = "top-left"
    TOP_RIGHT = "top-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_RIGHT = "bottom-right"


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a scalable font, falling back to PIL's built-in bitmap font."""
    for name in ("Helvetica.ttf", "Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _text_bbox(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> tuple[int, int, int, int]:
    """Return the bounding box of ``text`` rendered with ``font``."""
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return left, top, right, bottom


def _anchor_position(
    position: WatermarkPosition,
    image_size: tuple[int, int],
    text_size: tuple[int, int],
    margin: int,
) -> tuple[int, int]:
    """Resolve an anchor position to (x, y) pixel coordinates."""
    width, height = image_size
    text_width, text_height = text_size
    positions = {
        WatermarkPosition.CENTER: (
            (width - text_width) // 2,
            (height - text_height) // 2,
        ),
        WatermarkPosition.TOP_LEFT: (margin, margin),
        WatermarkPosition.TOP_RIGHT: (width - text_width - margin, margin),
        WatermarkPosition.BOTTOM_LEFT: (margin, height - text_height - margin),
        WatermarkPosition.BOTTOM_RIGHT: (
            width - text_width - margin,
            height - text_height - margin,
        ),
    }
    return positions[position]


def _draw_tiled(
    overlay: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
) -> None:
    """Draw ``text`` diagonally across the whole overlay."""
    width, height = overlay.size
    measure = Image.new("RGBA", (8, 8))
    draw = ImageDraw.Draw(measure)
    _, _, text_width, text_height = _text_bbox(draw, text, font)
    step_x = text_width + max(20, text_width // 2)
    step_y = text_height + max(20, text_height * 3)
    # Render on a larger canvas, rotate, then crop back to size.
    pad = max(width, height)
    tile = Image.new("RGBA", (width + pad, height + pad))
    tile_draw = ImageDraw.Draw(tile)
    for y in range(0, height + pad, step_y):
        for x in range(0, width + pad, step_x):
            tile_draw.text((x, y), text, font=font, fill=fill)
    tile = tile.rotate(_TILE_ANGLE, expand=False)
    overlay.alpha_composite(
        tile.crop((pad // 2, pad // 2, pad // 2 + width, pad // 2 + height))
    )


def apply_watermark(
    source: Path,
    destination: Path,
    text: str,
    position: WatermarkPosition = WatermarkPosition.BOTTOM_RIGHT,
    opacity: float = 0.4,
    overwrite: bool = False,
) -> Path:
    """Render ``text`` onto ``source`` and save to ``destination``.

    Args:
        source: Input raster image.
        destination: Output path; the extension selects the encoding
            (PNG/JPEG/WebP via Pillow).
        text: Watermark text.
        position: Anchor position or ``tile`` for a repeated diagonal pattern.
        opacity: Text opacity, 0.0-1.0.
        overwrite: Replace an existing destination when True.

    Returns:
        The destination path.
    """
    if not text:
        raise InvalidRequestError("Watermark text must not be empty")
    if not 0.0 < opacity <= 1.0:
        raise InvalidRequestError("Opacity must be in the range (0, 1]")
    if destination.exists() and not overwrite:
        raise DestinationExistsError(destination)
    media_format = detect_media_format(source)
    if media_format is MediaFormat.VIDEO:
        raise UnsupportedFormatError("Watermarking video is not supported")

    with Image.open(source) as image:
        image.load()
        base = image.convert("RGBA")
        overlay = Image.new("RGBA", base.size)
        alpha = round(255 * opacity)
        fill = (255, 255, 255, alpha)
        font = _load_font(max(12, round(min(base.size) * _FONT_SIZE_RATIO)))
        margin = round(min(base.size) * _DEFAULT_MARGIN_RATIO)

        if position is WatermarkPosition.TILE:
            _draw_tiled(overlay, text, font, fill)
        else:
            draw = ImageDraw.Draw(overlay)
            left, top, right, bottom = _text_bbox(draw, text, font)
            origin = _anchor_position(
                position,
                base.size,
                (right - left, bottom - top),
                margin,
            )
            draw.text((origin[0] - left, origin[1] - top), text, font=font, fill=fill)

        result = Image.alpha_composite(base, overlay)
        suffix = destination.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            result = result.convert("RGB")
        destination.parent.mkdir(parents=True, exist_ok=True)
        result.save(destination)
    return destination
