"""Tests for the responsive export-pack generators."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from PIL import Image

from ls_compressor.core.exceptions import (
    DestinationExistsError,
    UnsupportedFormatError,
)
from ls_compressor.core.export_packs import (
    generate_scale_pack,
    generate_srcset,
)


@pytest.fixture()
def wide_png(tmp_path: Path) -> Path:
    """Create a 2400x1200 RGB image."""
    path = tmp_path / "wide.png"
    Image.new("RGB", (2400, 1200), (20, 120, 220)).save(path)
    return path


@pytest.fixture()
def small_png(tmp_path: Path) -> Path:
    """Create a 300x200 image (below all srcset widths)."""
    path = tmp_path / "small.png"
    Image.new("RGB", (300, 200), (200, 60, 30)).save(path)
    return path


def _read_image(archive: zipfile.ZipFile, name: str) -> Image.Image:
    """Open an archived member as a decoded PIL image."""
    data = archive.read(name)
    import io

    image = Image.open(io.BytesIO(data))
    image.load()
    return image


class TestScalePack:
    def test_generates_three_png_scales(self, wide_png: Path, tmp_path: Path) -> None:
        destination = tmp_path / "pack.zip"
        names = generate_scale_pack(wide_png, destination, base_width=300)
        assert names == ["wide@1x.png", "wide@2x.png", "wide@3x.png"]
        with zipfile.ZipFile(destination) as archive:
            for name, expected_width in zip(names, (300, 600, 900), strict=True):
                image = _read_image(archive, name)
                assert image.format == "PNG"
                assert image.width == expected_width
                assert image.height == expected_width // 2

    def test_scales_capped_at_source_width(
        self, small_png: Path, tmp_path: Path
    ) -> None:
        destination = tmp_path / "pack.zip"
        generate_scale_pack(small_png, destination, base_width=300)
        with zipfile.ZipFile(destination) as archive:
            image = _read_image(archive, "small@3x.png")
            assert image.width == 300  # capped, not upscaled to 900

    def test_existing_destination_rejected(
        self, wide_png: Path, tmp_path: Path
    ) -> None:
        destination = tmp_path / "pack.zip"
        destination.touch()
        with pytest.raises(DestinationExistsError):
            generate_scale_pack(wide_png, destination, base_width=100)

    def test_invalid_base_width(self, wide_png: Path, tmp_path: Path) -> None:
        with pytest.raises(UnsupportedFormatError):
            generate_scale_pack(wide_png, tmp_path / "p.zip", base_width=0)


class TestSrcset:
    def test_generates_webp_widths_and_snippet(
        self, wide_png: Path, tmp_path: Path
    ) -> None:
        destination = tmp_path / "srcset.zip"
        names = generate_srcset(wide_png, destination)
        assert names == [
            "wide-480w.webp",
            "wide-960w.webp",
            "wide-1440w.webp",
            "wide-2160w.webp",
            "srcset-snippet.html",
        ]
        with zipfile.ZipFile(destination) as archive:
            for name, expected_width in zip(
                names[:4], (480, 960, 1440, 2160), strict=True
            ):
                image = _read_image(archive, name)
                assert image.format == "WEBP"
                assert image.width == expected_width
            snippet = archive.read("srcset-snippet.html").decode()
            assert 'srcset="' in snippet
            assert "wide-2160w.webp 2160w" in snippet
            assert 'sizes="' in snippet
            assert snippet.startswith('<img src="wide-480w.webp"')

    def test_skips_widths_wider_than_source(self, tmp_path: Path) -> None:
        path = tmp_path / "mid.png"
        Image.new("RGB", (1000, 500)).save(path)
        destination = tmp_path / "srcset.zip"
        names = generate_srcset(path, destination)
        assert names == [
            "mid-480w.webp",
            "mid-960w.webp",
            "srcset-snippet.html",
        ]

    def test_too_small_source_rejected(self, small_png: Path, tmp_path: Path) -> None:
        with pytest.raises(UnsupportedFormatError, match="narrower"):
            generate_srcset(small_png, tmp_path / "srcset.zip")

    def test_video_source_rejected(self, tmp_path: Path) -> None:
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")
        with pytest.raises(UnsupportedFormatError):
            generate_srcset(video, tmp_path / "srcset.zip")
