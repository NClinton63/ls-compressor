"""Favicon and app-icon export pack generation."""

from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from pathlib import Path
from tempfile import mkstemp

from PIL import Image

from ls_compressor.core.exceptions import UnsupportedFormatError
from ls_compressor.core.filesystem import (
    ensure_source,
    prepare_destination,
    replace_path,
)
from ls_compressor.core.media import MediaFormat, detect_media_format

_LOGGER = logging.getLogger("ls_compressor.core.icons")

_ICON_SIZES = (
    ("favicon-16x16.png", 16),
    ("favicon-32x32.png", 32),
    ("favicon-48x48.png", 48),
    ("apple-touch-icon.png", 180),
    ("android-chrome-192x192.png", 192),
    ("android-chrome-512x512.png", 512),
)

_HTML_SNIPPET = (
    '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">\n'
    '<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">\n'
    '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">\n'
    '<link rel="manifest" href="/site.webmanifest">\n'
)

_MANIFEST = json.dumps(
    {
        "name": "",
        "short_name": "",
        "icons": [
            {
                "src": "/android-chrome-192x192.png",
                "sizes": "192x192",
                "type": "image/png",
            },
            {
                "src": "/android-chrome-512x512.png",
                "sizes": "512x512",
                "type": "image/png",
            },
        ],
        "theme_color": "#ffffff",
        "background_color": "#ffffff",
        "display": "standalone",
    },
    indent=2,
)


def generate_icon_pack(
    source: Path, destination: Path, *, overwrite: bool = False
) -> list[str]:
    """Write a favicon/app-icon pack ZIP for a source image.

    The pack matches the web edition's output: six PNG sizes, a
    ``site.webmanifest``, and a ``README-snippet.html`` with paste-ready
    link tags. Returns the member names written to the archive.
    """
    ensure_source(source)
    media_format = detect_media_format(source)
    if media_format is MediaFormat.VIDEO:
        raise UnsupportedFormatError(
            f"Icon packs require a raster image, not: {source}"
        )
    prepare_destination(destination, overwrite=overwrite)
    with Image.open(source) as image:
        members = _pack_members(image.convert("RGBA"))
    descriptor, temp_name = mkstemp(
        prefix=f".{destination.stem}.", suffix=".zip", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temp_name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in members:
                archive.writestr(name, payload)
        replace_path(temporary, destination, overwrite=overwrite)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    _LOGGER.info("Generated icon pack: %s (%d files)", destination, len(members))
    return [name for name, _ in members]


def _pack_members(image: Image.Image) -> list[tuple[str, bytes]]:
    """Rasterize every icon size and bundle the manifest and snippet."""
    members: list[tuple[str, bytes]] = [
        ("site.webmanifest", _MANIFEST.encode("utf-8")),
        ("README-snippet.html", _HTML_SNIPPET.encode("utf-8")),
    ]
    for name, size in _ICON_SIZES:
        members.append((name, _rasterize(image, size)))
    return members


def _rasterize(image: Image.Image, size: int) -> bytes:
    """Resize the image to a square PNG at the given pixel size."""
    buffer = io.BytesIO()
    image.resize((size, size), Image.Resampling.LANCZOS).save(buffer, "PNG")
    return buffer.getvalue()
