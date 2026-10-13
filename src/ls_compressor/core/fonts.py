"""Font conversion and subsetting (TTF/OTF/WOFF/WOFF2).

Mirrors the web edition's font tooling: convert desktop fonts to
web-ready WOFF2 and optionally subset to a character set — which is also
the fastest way to strip hinting/name overhead for app bundles.
"""

from __future__ import annotations

from pathlib import Path

from ls_compressor.core.exceptions import (
    DestinationExistsError,
    InvalidRequestError,
    UnsupportedFormatError,
)

_FONT_EXTENSIONS = frozenset({".ttf", ".otf", ".woff", ".woff2"})
_FLAVOR_FOR_SUFFIX = {".woff": "woff", ".woff2": "woff2"}


def convert_font(
    source: Path,
    destination: Path,
    *,
    subset_text: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Convert a font to the destination format, optionally subsetting it.

    The destination extension selects the output flavor: ``.woff2`` and
    ``.woff`` produce compressed web fonts; ``.ttf``/``.otf`` produce
    desktop fonts (useful to unwrap a WOFF back into an installable font).

    Args:
        source: Input font (``.ttf``, ``.otf``, ``.woff``, ``.woff2``).
        destination: Output path.
        subset_text: When given, keep only the Unicode code points needed
            to render this text.
        overwrite: Replace an existing destination when True.

    Returns:
        The destination path.
    """
    if source.suffix.lower() not in _FONT_EXTENSIONS:
        raise UnsupportedFormatError(f"Unsupported font format: {source}")
    if destination.suffix.lower() not in _FONT_EXTENSIONS:
        raise UnsupportedFormatError(f"Unsupported font destination: {destination}")
    if destination.exists() and not overwrite:
        raise DestinationExistsError(destination)
    if subset_text is not None and not subset_text:
        raise InvalidRequestError("Subset text must not be empty")

    try:
        from fontTools import subset as ft_subset
        from fontTools.ttLib import TTFont, TTLibError
    except ImportError as error:
        raise UnsupportedFormatError(
            "Font conversion requires the 'fontTools' package"
        ) from error

    try:
        font = TTFont(source)
    except TTLibError as error:
        raise UnsupportedFormatError(f"Cannot read font: {source}") from error

    if subset_text is not None:
        options = ft_subset.Options()
        options.name_IDs = ["*"]  # keep name records for identification
        subsetter = ft_subset.Subsetter(options=options)
        subsetter.populate(text=subset_text)
        try:
            subsetter.subset(font)
        except Exception as error:
            raise InvalidRequestError(
                f"Could not subset {source.name}: {error}"
            ) from error

    font.flavor = _FLAVOR_FOR_SUFFIX.get(destination.suffix.lower())
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        font.save(destination)
    except Exception as error:
        raise UnsupportedFormatError(
            f"Cannot write {destination.suffix} font: {error}"
        ) from error
    return destination
