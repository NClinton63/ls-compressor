"""Tests for font conversion and subsetting."""

from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from ls_compressor.core.exceptions import (
    DestinationExistsError,
    InvalidRequestError,
    UnsupportedFormatError,
)
from ls_compressor.core.fonts import convert_font


def _write_test_font(path: Path) -> None:
    """Build a minimal TrueType font with glyphs for A and B."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    builder = FontBuilder(1000)
    builder.setupGlyphOrder([".notdef", "A", "B"])
    builder.setupCharacterMap({ord("A"): "A", ord("B"): "B"})

    empty = TTGlyphPen(None).glyph()
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((500, 0))
    pen.lineTo((250, 700))
    pen.closePath()
    glyph_a = pen.glyph()
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((400, 0))
    pen.lineTo((400, 350))
    pen.closePath()
    glyph_b = pen.glyph()

    builder.setupGlyf({".notdef": empty, "A": glyph_a, "B": glyph_b})
    builder.setupHorizontalMetrics(dict.fromkeys((".notdef", "A", "B"), (600, 0)))
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "TestFont", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.save(path)


@pytest.fixture()
def ttf_file(tmp_path: Path) -> Path:
    """Provide a minimal valid .ttf source."""
    path = tmp_path / "test.ttf"
    _write_test_font(path)
    return path


class TestConvertFont:
    def test_ttf_to_woff2(self, ttf_file: Path, tmp_path: Path) -> None:
        destination = tmp_path / "out.woff2"
        convert_font(ttf_file, destination)
        font = TTFont(destination)
        assert font.flavor == "woff2"
        assert set(font.getGlyphOrder()) == {".notdef", "A", "B"}

    def test_ttf_to_woff(self, ttf_file: Path, tmp_path: Path) -> None:
        destination = tmp_path / "out.woff"
        convert_font(ttf_file, destination)
        assert TTFont(destination).flavor == "woff"

    def test_woff2_back_to_ttf(self, ttf_file: Path, tmp_path: Path) -> None:
        woff2 = tmp_path / "mid.woff2"
        convert_font(ttf_file, woff2)
        ttf = tmp_path / "restored.ttf"
        convert_font(woff2, ttf)
        assert TTFont(ttf).flavor is None

    def test_subset_keeps_only_requested_glyphs(
        self, ttf_file: Path, tmp_path: Path
    ) -> None:
        destination = tmp_path / "sub.woff2"
        convert_font(ttf_file, destination, subset_text="A")
        font = TTFont(destination)
        assert "A" in font.getGlyphOrder()
        assert "B" not in font.getGlyphOrder()
        assert destination.stat().st_size > 0

    def test_unsupported_source_rejected(self, tmp_path: Path) -> None:
        source = tmp_path / "x.png"
        source.write_bytes(b"\x89PNG")
        with pytest.raises(UnsupportedFormatError):
            convert_font(source, tmp_path / "o.woff2")

    def test_unsupported_destination_rejected(
        self, ttf_file: Path, tmp_path: Path
    ) -> None:
        with pytest.raises(UnsupportedFormatError):
            convert_font(ttf_file, tmp_path / "o.bmp")

    def test_corrupt_font_rejected(self, tmp_path: Path) -> None:
        source = tmp_path / "bad.ttf"
        source.write_bytes(b"not a font")
        with pytest.raises(UnsupportedFormatError):
            convert_font(source, tmp_path / "o.woff2")

    def test_existing_destination_rejected(
        self, ttf_file: Path, tmp_path: Path
    ) -> None:
        destination = tmp_path / "out.woff2"
        destination.touch()
        with pytest.raises(DestinationExistsError):
            convert_font(ttf_file, destination)
        convert_font(ttf_file, destination, overwrite=True)
        assert TTFont(destination).flavor == "woff2"

    def test_empty_subset_rejected(self, ttf_file: Path, tmp_path: Path) -> None:
        with pytest.raises(InvalidRequestError):
            convert_font(ttf_file, tmp_path / "o.woff2", subset_text="")
