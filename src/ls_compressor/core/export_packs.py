"""Responsive export packs matching the web platform's ``lib/exports.ts``.

Two packs are supported:

- **Scale pack** — ``{name}@1x.png``, ``@2x``, ``@3x`` (capped at the source
  size) zipped for mobile/design handoff.
- **Srcset pack** — WebP renditions at standard responsive widths plus a
  ready-to-paste ``<img srcset …>`` snippet.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Final

from PIL import Image

from ls_compressor.core.exceptions import (
    DestinationExistsError,
    UnsupportedFormatError,
)
from ls_compressor.core.media import MediaFormat, detect_media_format

_SRCSET_WIDTHS: Final[tuple[int, ...]] = (480, 960, 1440, 2160)
_SRCSET_QUALITY: Final = 85

_SRCSET_SIZES: Final = "(max-width: 600px) 480px, (max-width: 1200px) 960px, 1440px"


def _load_image(source: Path) -> Image.Image:
    """Open an image source, rejecting non-raster inputs."""
    media_format = detect_media_format(source)
    if media_format is MediaFormat.VIDEO:
        raise UnsupportedFormatError(
            f"Export packs require a raster image, got {media_format.value}"
        )
    try:
        image = Image.open(source)
        image.load()
    except Exception as error:
        raise UnsupportedFormatError(f"Cannot read image: {source}") from error
    return image


def _resized(image: Image.Image, width: int, height: int) -> Image.Image:
    """Return a high-quality downscaled copy of ``image``."""
    width = max(1, round(width))
    height = max(1, round(height))
    resized = image.copy()
    resized.thumbnail((width, height), Image.Resampling.LANCZOS)
    return resized


def _write_zip(files: dict[str, bytes], destination: Path) -> None:
    """Write the pack contents to ``destination`` without overwriting."""
    if destination.exists():
        raise DestinationExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def _png_bytes(image: Image.Image) -> bytes:
    """Encode an image as PNG bytes."""
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _webp_bytes(image: Image.Image, quality: int) -> bytes:
    """Encode an image as lossy WebP bytes."""
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=quality)
    return buffer.getvalue()


def generate_scale_pack(
    source: Path,
    destination: Path,
    base_width: int,
) -> list[str]:
    """Create a ``@1x``/``@2x``/``@3x`` PNG scale pack ZIP.

    ``base_width`` is the intended 1x display width; larger scales are capped
    at the source's own pixel width to avoid upscaling.

    Args:
        source: Source image path.
        destination: Output ``.zip`` path.
        base_width: Width of the ``@1x`` rendition in pixels.

    Returns:
        Filenames written to the ZIP.
    """
    if base_width <= 0:
        raise UnsupportedFormatError("base_width must be a positive integer")
    with _load_image(source) as image:
        image.load()
        image = image.convert("RGBA") if image.mode == "P" else image.copy()
        ratio = image.height / image.width
        stem = source.stem
        files: dict[str, bytes] = {}
        for multiplier in (1, 2, 3):
            width = min(base_width * multiplier, image.width)
            resized = _resized(image, width, width * ratio)
            files[f"{stem}@{multiplier}x.png"] = _png_bytes(resized)
        _write_zip(files, destination)
        return list(files)


def generate_srcset(source: Path, destination: Path) -> list[str]:
    """Create a responsive ``srcset`` pack ZIP.

    Emits ``{stem}-{width}w.webp`` renditions for every standard width that
    fits the source, plus ``srcset-snippet.html`` with a paste-ready ``<img>``
    tag matching the web platform's output.

    Args:
        source: Source image path.
        destination: Output ``.zip`` path.

    Returns:
        Filenames written to the ZIP.
    """
    with _load_image(source) as image:
        image.load()
        image = image.convert("RGBA")
        ratio = image.height / image.width
        stem = source.stem
        files: dict[str, bytes] = {}
        srcset: list[str] = []
        first_name = source.name
        for width in (w for w in _SRCSET_WIDTHS if w <= image.width):
            name = f"{stem}-{width}w.webp"
            resized = _resized(image, width, width * ratio)
            files[name] = _webp_bytes(resized, _SRCSET_QUALITY)
            srcset.append(f"{name} {width}w")
            if len(srcset) == 1:
                first_name = name
        if not srcset:
            raise UnsupportedFormatError(
                f"{source.name} is narrower than {_SRCSET_WIDTHS[0]}px; "
                "nothing to generate"
            )
        snippet = (
            f'<img src="{first_name}"\n'
            f'     srcset="{",\n          ".join(srcset)}"\n'
            f'     sizes="{_SRCSET_SIZES}"\n'
            f'     alt="">'
        )
        files["srcset-snippet.html"] = snippet.encode()
        _write_zip(files, destination)
        return list(files)
