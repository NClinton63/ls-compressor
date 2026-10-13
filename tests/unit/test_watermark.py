"""Tests for optional text watermarking."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageChops

from ls_compressor.core.exceptions import (
    DestinationExistsError,
    InvalidRequestError,
    UnsupportedFormatError,
)
from ls_compressor.core.watermark import WatermarkPosition, apply_watermark


@pytest.fixture()
def rgb_png(tmp_path: Path) -> Path:
    """Create a 400x300 flat-color image."""
    path = tmp_path / "plain.png"
    Image.new("RGB", (400, 300), (30, 90, 200)).save(path)
    return path


def _diff_bbox(source: Path, output: Path) -> tuple[int, int, int, int] | None:
    """Return the RGB difference bbox between source and output."""
    with (
        Image.open(source) as original,
        Image.open(output) as stamped,
    ):
        return ImageChops.difference(
            original.convert("RGB"), stamped.convert("RGB")
        ).getbbox()


class TestApplyWatermark:
    def test_anchored_text_changes_pixels(self, rgb_png: Path, tmp_path: Path):
        destination = tmp_path / "out.png"
        apply_watermark(rgb_png, destination, "HELLO")
        assert _diff_bbox(rgb_png, destination) is not None

    def test_tile_covers_image(self, rgb_png: Path, tmp_path: Path):
        destination = tmp_path / "out.png"
        apply_watermark(rgb_png, destination, "DRAFT", position=WatermarkPosition.TILE)
        bbox = _diff_bbox(rgb_png, destination)
        assert bbox is not None
        assert bbox[0] == 0 and bbox[1] == 0

    def test_corner_anchor_near_edge(self, rgb_png: Path, tmp_path: Path):
        destination = tmp_path / "out.png"
        apply_watermark(
            rgb_png,
            destination,
            "WM",
            position=WatermarkPosition.BOTTOM_RIGHT,
        )
        bbox = _diff_bbox(rgb_png, destination)
        assert bbox is not None
        assert bbox[2] > 300 and bbox[3] > 200

    def test_jpeg_output_converts_to_rgb(self, rgb_png: Path, tmp_path: Path):
        destination = tmp_path / "out.jpg"
        apply_watermark(rgb_png, destination, "WM")
        with Image.open(destination) as image:
            assert image.format == "JPEG"
            assert image.mode == "RGB"

    def test_empty_text_rejected(self, rgb_png: Path, tmp_path: Path):
        with pytest.raises(InvalidRequestError):
            apply_watermark(rgb_png, tmp_path / "o.png", "")

    def test_invalid_opacity_rejected(self, rgb_png: Path, tmp_path: Path):
        for opacity in (0.0, -0.5, 1.5):
            with pytest.raises(InvalidRequestError):
                apply_watermark(rgb_png, tmp_path / "o.png", "X", opacity=opacity)

    def test_existing_destination_rejected(self, rgb_png: Path, tmp_path: Path):
        destination = tmp_path / "out.png"
        destination.touch()
        with pytest.raises(DestinationExistsError):
            apply_watermark(rgb_png, destination, "WM")
        apply_watermark(rgb_png, destination, "WM", overwrite=True)
        assert _diff_bbox(rgb_png, destination) is not None

    def test_video_source_rejected(self, tmp_path: Path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")
        with pytest.raises(UnsupportedFormatError):
            apply_watermark(video, tmp_path / "o.png", "WM")
