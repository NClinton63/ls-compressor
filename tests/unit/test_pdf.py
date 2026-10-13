"""Tests for PDF conversion (images→PDF and PDF→images)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from ls_compressor.core.exceptions import (
    DestinationExistsError,
    InvalidRequestError,
    UnsupportedFormatError,
)
from ls_compressor.core.pdf import images_to_pdf, pdf_to_images


@pytest.fixture()
def images(tmp_path: Path) -> list[Path]:
    """Create two small images."""
    paths = []
    for index, color in enumerate(((255, 0, 0), (0, 255, 0))):
        path = tmp_path / f"img{index}.png"
        Image.new("RGB", (32, 24), color).save(path)
        paths.append(path)
    return paths


class TestImagesToPdf:
    def test_combines_images(self, images: list[Path], tmp_path: Path) -> None:
        destination = tmp_path / "out.pdf"
        images_to_pdf(images, destination)
        data = destination.read_bytes()
        assert data.startswith(b"%PDF")
        # Two pages: /Type /Page appears twice (once per page object).
        assert data.count(b"/Type /Page") - data.count(b"/Type /Pages") == 2

    def test_rgba_flattened(self, tmp_path: Path) -> None:
        source = tmp_path / "alpha.png"
        Image.new("RGBA", (16, 16), (1, 2, 3, 128)).save(source)
        destination = tmp_path / "out.pdf"
        images_to_pdf([source], destination)
        assert destination.read_bytes().startswith(b"%PDF")

    def test_requires_pdf_extension(self, images: list[Path], tmp_path: Path) -> None:
        with pytest.raises(UnsupportedFormatError):
            images_to_pdf(images, tmp_path / "out.png")

    def test_existing_destination_rejected(
        self, images: list[Path], tmp_path: Path
    ) -> None:
        destination = tmp_path / "out.pdf"
        destination.touch()
        with pytest.raises(DestinationExistsError):
            images_to_pdf(images, destination)

    def test_empty_sources_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidRequestError):
            images_to_pdf([], tmp_path / "out.pdf")


class TestPdfToImages:
    @pytest.fixture()
    def pdf_file(self, images: list[Path], tmp_path: Path) -> Path:
        destination = tmp_path / "source.pdf"
        images_to_pdf(images, destination)
        return destination

    def test_renders_each_page(self, pdf_file: Path, tmp_path: Path) -> None:
        pytest.importorskip("pymupdf")
        out_dir = tmp_path / "pages"
        outputs = pdf_to_images(pdf_file, out_dir)
        assert len(outputs) == 2
        for path in outputs:
            with Image.open(path) as image:
                assert image.format == "PNG"
                assert image.width > 32  # 150dpi renders larger than source

    def test_jpeg_format(self, pdf_file: Path, tmp_path: Path) -> None:
        pytest.importorskip("pymupdf")
        outputs = pdf_to_images(pdf_file, tmp_path / "pages", image_format="jpeg")
        assert outputs[0].suffix == ".jpeg"
        with Image.open(outputs[0]) as image:
            assert image.format == "JPEG"

    def test_not_pdf_rejected(self, images: list[Path], tmp_path: Path) -> None:
        pytest.importorskip("pymupdf")
        with pytest.raises(UnsupportedFormatError, match="Not a PDF"):
            pdf_to_images(images[0], tmp_path / "out")

    def test_invalid_format_and_dpi(self, pdf_file: Path, tmp_path: Path) -> None:
        pytest.importorskip("pymupdf")
        with pytest.raises(UnsupportedFormatError):
            pdf_to_images(pdf_file, tmp_path / "o", image_format="bmp")
        with pytest.raises(InvalidRequestError):
            pdf_to_images(pdf_file, tmp_path / "o", dpi=2000)

    def test_existing_page_rejected(self, pdf_file: Path, tmp_path: Path) -> None:
        pytest.importorskip("pymupdf")
        out_dir = tmp_path / "pages"
        pdf_to_images(pdf_file, out_dir)
        with pytest.raises(DestinationExistsError):
            pdf_to_images(pdf_file, out_dir)
