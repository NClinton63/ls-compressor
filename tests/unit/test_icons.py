"""Tests for favicon/app-icon pack generation."""

import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from ls_compressor.cli.main import main
from ls_compressor.core import (
    UnsupportedFormatError,
    generate_icon_pack,
)
from ls_compressor.core.exceptions import DestinationExistsError


def _make_source(path: Path, *, size: int = 256) -> None:
    """Write a square RGBA PNG source image."""
    image = Image.new("RGBA", (size, size), (40, 120, 220, 255))
    image.save(path, format="PNG")


def test_generates_complete_pack(tmp_path: Path) -> None:
    """The pack contains every icon size plus manifest and snippet."""
    source = tmp_path / "logo.png"
    _make_source(source)
    destination = tmp_path / "icons.zip"

    members = generate_icon_pack(source, destination)

    assert "favicon-16x16.png" in members
    assert "favicon-32x32.png" in members
    assert "apple-touch-icon.png" in members
    assert "android-chrome-512x512.png" in members
    assert "site.webmanifest" in members
    assert "README-snippet.html" in members


def test_pack_contents_are_valid(tmp_path: Path) -> None:
    """Icons are real PNGs at the advertised sizes; the manifest is JSON."""
    source = tmp_path / "logo.png"
    _make_source(source)
    destination = tmp_path / "icons.zip"
    generate_icon_pack(source, destination)

    with zipfile.ZipFile(destination) as archive:
        with Image.open(io.BytesIO(archive.read("favicon-32x32.png"))) as icon:
            assert icon.size == (32, 32)
            assert icon.format == "PNG"
        manifest = json.loads(archive.read("site.webmanifest"))
        assert manifest["icons"][0]["sizes"] == "192x192"
        assert b"apple-touch-icon" in archive.read("README-snippet.html")


def test_preserves_alpha(tmp_path: Path) -> None:
    """Transparent source regions stay transparent in the icons."""
    source = tmp_path / "logo.png"
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    image.putpixel((32, 32), (255, 0, 0, 255))
    image.save(source, format="PNG")
    destination = tmp_path / "icons.zip"

    generate_icon_pack(source, destination)

    with (
        zipfile.ZipFile(destination) as archive,
        Image.open(io.BytesIO(archive.read("favicon-16x16.png"))) as icon,
    ):
        assert icon.mode == "RGBA"
        assert icon.getpixel((0, 0))[3] == 0


def test_refuses_overwrite(tmp_path: Path) -> None:
    """Existing destinations are protected unless overwrite is requested."""
    source = tmp_path / "logo.png"
    _make_source(source)
    destination = tmp_path / "icons.zip"
    destination.write_bytes(b"existing")
    with pytest.raises(DestinationExistsError):
        generate_icon_pack(source, destination)


def test_rejects_video_input(tmp_path: Path) -> None:
    """Non-image input raises a domain error."""
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32)
    destination = tmp_path / "icons.zip"
    with pytest.raises(UnsupportedFormatError):
        generate_icon_pack(source, destination)


def test_icons_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The icons subcommand writes a pack and reports its members."""
    source = tmp_path / "logo.png"
    _make_source(source)
    destination = tmp_path / "pack.zip"
    assert main(["icons", str(source), str(destination)]) == 0
    out = capsys.readouterr().out
    assert "favicon-32x32.png" in out
    assert destination.exists()
