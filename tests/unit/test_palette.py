"""Tests for dominant color palette extraction."""

from pathlib import Path

import pytest
from PIL import Image

from ls_compressor.cli.main import main
from ls_compressor.core import (
    UnsupportedFormatError,
    extract_palette,
)


def _make_image(path: Path, colors: tuple[tuple[int, int, int], ...]) -> None:
    """Write an image split into horizontal bands of the given colors."""
    width, height = 64, 64
    image = Image.new("RGB", (width, height))
    band = width // len(colors)
    for x in range(width):
        for y in range(height):
            image.putpixel((x, y), colors[min(x // band, len(colors) - 1)])
    image.save(path, format="PNG")


def test_extract_dominant_colors(tmp_path: Path) -> None:
    """The dominant hues of a two-color image are returned as hex."""
    source = tmp_path / "bands.png"
    _make_image(source, ((255, 0, 0), (0, 0, 255)))
    colors = extract_palette(source, count=2)
    assert len(colors) == 2
    assert set(colors) == {"#ff0000", "#0000ff"}


def test_extract_respects_count(tmp_path: Path) -> None:
    """The count argument caps the number of returned colors."""
    source = tmp_path / "bands.png"
    _make_image(source, ((255, 0, 0), (0, 255, 0), (0, 0, 255)))
    assert len(extract_palette(source, count=1)) == 1
    assert len(extract_palette(source, count=4)) <= 4


def test_extract_zero_count_returns_empty(tmp_path: Path) -> None:
    """A non-positive count yields no colors."""
    source = tmp_path / "bands.png"
    _make_image(source, ((255, 0, 0),))
    assert extract_palette(source, count=0) == []


def test_extract_rejects_video_like_input(tmp_path: Path) -> None:
    """Non-image inputs raise a domain error."""
    source = tmp_path / "plain.txt"
    source.write_text("not an image", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        extract_palette(source)


def test_palette_cli(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """The palette subcommand prints hex colors."""
    source = tmp_path / "bands.png"
    _make_image(source, ((255, 0, 0), (0, 0, 255)))
    assert main(["palette", str(source), "-n", "2"]) == 0
    out = capsys.readouterr().out
    assert "#" in out


def test_palette_cli_json(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """--json emits a machine-readable palette payload."""
    import json

    source = tmp_path / "bands.png"
    _make_image(source, ((255, 0, 0),))
    assert main(["palette", str(source), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "palette"
    assert payload["colors"] == ["#ff0000"]
