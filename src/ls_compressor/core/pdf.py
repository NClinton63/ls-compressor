"""PDF conversion: images → PDF, and PDF → page images.

``images_to_pdf`` uses Pillow's native multi-page PDF writer.
``pdf_to_images`` rasterizes each page with PyMuPDF (``pymupdf`` package);
it raises :class:`UnsupportedFormatError` when PyMuPDF is not installed so
the dependency stays optional.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from PIL import Image

from ls_compressor.core.exceptions import (
    DestinationExistsError,
    InvalidRequestError,
    UnsupportedFormatError,
)
from ls_compressor.core.media import MediaFormat, detect_media_format

_IMAGE_SUFFIXES: Final = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_DEFAULT_DPI: Final = 150


def images_to_pdf(
    sources: list[Path],
    destination: Path,
    overwrite: bool = False,
) -> Path:
    """Combine raster images into a single multi-page PDF.

    Args:
        sources: Ordered image paths; each becomes one page.
        destination: Output ``.pdf`` path.
        overwrite: Replace an existing destination when True.

    Returns:
        The destination path.
    """
    if not sources:
        raise InvalidRequestError("At least one image is required")
    if destination.suffix.lower() != ".pdf":
        raise UnsupportedFormatError("PDF destination must end in .pdf")
    if destination.exists() and not overwrite:
        raise DestinationExistsError(destination)

    images: list[Image.Image] = []
    try:
        for source in sources:
            media_format = detect_media_format(source)
            if media_format is MediaFormat.VIDEO:
                raise UnsupportedFormatError(
                    f"PDF pages require raster images, got {source.name}"
                )
            try:
                image = Image.open(source)
                image.load()
            except Exception as error:
                raise UnsupportedFormatError(f"Cannot read image: {source}") from error
            # PDF writer requires 8-bit RGB/L/CMYK — no alpha or palette.
            if image.mode not in {"RGB", "L", "CMYK"}:
                image = image.convert("RGB")
            images.append(image)
        destination.parent.mkdir(parents=True, exist_ok=True)
        images[0].save(destination, save_all=True, append_images=images[1:])
    finally:
        for image in images:
            image.close()
    return destination


def pdf_to_images(
    source: Path,
    destination_dir: Path,
    *,
    image_format: str = "png",
    dpi: int = _DEFAULT_DPI,
    overwrite: bool = False,
) -> list[Path]:
    """Rasterize each PDF page to an image in ``destination_dir``.

    Args:
        source: Input ``.pdf`` file.
        destination_dir: Directory that receives ``{stem}-p{n}.{ext}`` files.
        image_format: ``png``, ``jpeg``, or ``webp``.
        dpi: Render resolution (higher is sharper and larger).
        overwrite: Replace existing page files when True.

    Returns:
        The written page paths in order.
    """
    if source.suffix.lower() != ".pdf":
        raise UnsupportedFormatError(f"Not a PDF: {source}")
    image_format = image_format.lower().lstrip(".")
    if image_format not in {"png", "jpeg", "webp"}:
        raise UnsupportedFormatError(f"Unsupported page image format: {image_format}")
    if not 20 <= dpi <= 600:
        raise InvalidRequestError("DPI must be between 20 and 600")
    try:
        import pymupdf
    except ImportError as error:
        raise UnsupportedFormatError(
            "PDF rendering requires the 'pymupdf' package"
        ) from error

    try:
        document = pymupdf.open(source)
    except Exception as error:
        raise UnsupportedFormatError(f"Cannot read PDF: {source}") from error
    try:
        outputs: list[Path] = []
        destination_dir.mkdir(parents=True, exist_ok=True)
        zoom = dpi / 72.0
        matrix = pymupdf.Matrix(zoom, zoom)
        for index, page in enumerate(document, start=1):
            target = destination_dir / f"{source.stem}-p{index}.{image_format}"
            if target.exists() and not overwrite:
                raise DestinationExistsError(target)
            pixmap = page.get_pixmap(matrix=matrix)
            if image_format == "jpeg":
                pixmap = pymupdf.Pixmap(pixmap, 0) if pixmap.alpha else pixmap
            pixmap.save(target)
            outputs.append(target)
        return outputs
    finally:
        document.close()
