"""Unit tests for the media optimization core."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from ls_compressor.core import (
    CompressionError,
    InvalidRequestError,
    MediaFormat,
    MediaOptimizationMode,
    MediaOptimizationRequest,
    OperationKind,
    UnsupportedFormatError,
    detect_media_format,
    optimize_media,
)


def _make_png(path: Path, *, width: int = 64, height: int = 64) -> None:
    """Write a simple PNG file for testing."""
    image = Image.new("RGBA", (width, height), (255, 0, 0, 128))
    image.save(path, format="PNG")


def _make_jpeg(path: Path, *, width: int = 64, height: int = 64) -> None:
    """Write a simple JPEG file for testing."""
    image = Image.new("RGB", (width, height), (0, 255, 0))
    image.save(path, format="JPEG", quality=95)


def _make_webp(path: Path, *, width: int = 64, height: int = 64) -> None:
    """Write a simple WebP file for testing."""
    image = Image.new("RGBA", (width, height), (0, 0, 255, 128))
    image.save(path, format="WEBP")


def _make_avif(path: Path, *, width: int = 64, height: int = 64) -> None:
    """Write a simple AVIF file for testing."""
    image = Image.new("RGB", (width, height), (120, 60, 30))
    image.save(path, format="AVIF")


def _make_gif(path: Path, *, width: int = 64, height: int = 64) -> None:
    """Write a simple GIF file for testing."""
    image = Image.new("P", (width, height))
    image.save(path, format="GIF")


def _make_bmp(path: Path, *, width: int = 64, height: int = 64) -> None:
    """Write a simple BMP file for testing."""
    image = Image.new("RGB", (width, height), (10, 200, 90))
    image.save(path, format="BMP")


def _make_heic(path: Path, *, width: int = 64, height: int = 64) -> None:
    """Write a simple HEIC file for testing via pillow-heif."""
    pytest.importorskip("pillow_heif")
    image = Image.new("RGB", (width, height), (200, 100, 40))
    image.save(path, format="HEIF")


def _make_video(path: Path) -> None:
    """Write a tiny MP4 video using FFmpeg."""
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except ImportError as error:
        pytest.skip(f"imageio_ffmpeg not available: {error}")
    ffmpeg = get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=32x32:d=0.1",
        "-pix_fmt",
        "yuv420p",
        "-y",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True)


@pytest.fixture
def png_file(tmp_path: Path) -> Path:
    path = tmp_path / "source.png"
    _make_png(path)
    return path


@pytest.fixture
def jpeg_file(tmp_path: Path) -> Path:
    path = tmp_path / "source.jpg"
    _make_jpeg(path)
    return path


@pytest.fixture
def webp_file(tmp_path: Path) -> Path:
    path = tmp_path / "source.webp"
    _make_webp(path)
    return path


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    path = tmp_path / "source.mp4"
    _make_video(path)
    return path


class TestDetectMediaFormat:
    """Detection behavior for supported and unsupported media files."""

    def test_detect_png(self, png_file: Path) -> None:
        assert detect_media_format(png_file) is MediaFormat.PNG

    def test_detect_jpeg(self, jpeg_file: Path) -> None:
        assert detect_media_format(jpeg_file) is MediaFormat.JPEG

    def test_detect_webp(self, webp_file: Path) -> None:
        assert detect_media_format(webp_file) is MediaFormat.WEBP

    def test_detect_video(self, video_file: Path) -> None:
        assert detect_media_format(video_file) is MediaFormat.VIDEO

    def test_detect_avif(self, tmp_path: Path) -> None:
        path = tmp_path / "source.avif"
        _make_avif(path)
        assert detect_media_format(path) is MediaFormat.AVIF

    def test_detect_gif(self, tmp_path: Path) -> None:
        path = tmp_path / "source.gif"
        _make_gif(path)
        assert detect_media_format(path) is MediaFormat.GIF

    def test_detect_bmp(self, tmp_path: Path) -> None:
        path = tmp_path / "source.bmp"
        _make_bmp(path)
        assert detect_media_format(path) is MediaFormat.BMP

    def test_detect_heic(self, tmp_path: Path) -> None:
        path = tmp_path / "source.heic"
        _make_heic(path)
        assert detect_media_format(path) is MediaFormat.HEIC

    def test_detect_unsupported(self, tmp_path: Path) -> None:
        path = tmp_path / "plain.txt"
        path.write_text("not media")
        with pytest.raises(UnsupportedFormatError):
            detect_media_format(path)

    def test_detect_missing(self, tmp_path: Path) -> None:
        with pytest.raises(CompressionError):
            detect_media_format(tmp_path / "missing.png")


class TestOptimizeImages:
    """Lossless and lossy image optimization through Pillow."""

    def test_optimize_png_lossless(self, png_file: Path, tmp_path: Path) -> None:
        destination = tmp_path / "output.png"
        request = MediaOptimizationRequest(
            source=png_file,
            destination=destination,
        )
        result = optimize_media(request)
        assert result.kind is OperationKind.MEDIA_OPTIMIZE
        assert result.media_format is MediaFormat.PNG
        assert destination.exists()
        assert Image.open(destination).format == "PNG"
        assert result.integrity_verified is True
        assert result.source_size > 0
        assert result.output_size > 0

    def test_optimize_jpeg_with_quality(self, jpeg_file: Path, tmp_path: Path) -> None:
        destination = tmp_path / "output.jpg"
        request = MediaOptimizationRequest(
            source=jpeg_file,
            destination=destination,
            mode=MediaOptimizationMode.LOSSY,
            quality=75,
        )
        result = optimize_media(request)
        assert result.media_format is MediaFormat.JPEG
        assert destination.exists()
        assert Image.open(destination).format == "JPEG"
        assert result.integrity_verified is True

    def test_optimize_webp_lossy(self, webp_file: Path, tmp_path: Path) -> None:
        destination = tmp_path / "output.webp"
        request = MediaOptimizationRequest(
            source=webp_file,
            destination=destination,
            mode=MediaOptimizationMode.LOSSY,
            quality=80,
        )
        result = optimize_media(request)
        assert result.media_format is MediaFormat.WEBP
        assert destination.exists()

    def test_resize_constrains_longest_edge(
        self, jpeg_file: Path, tmp_path: Path
    ) -> None:
        destination = tmp_path / "small.webp"
        request = MediaOptimizationRequest(
            source=jpeg_file, destination=destination, max_dimension=32
        )
        result = optimize_media(request)
        assert result.integrity_verified is True
        with Image.open(destination) as output:
            assert max(output.size) == 32

    def test_resize_noop_when_smaller(self, png_file: Path, tmp_path: Path) -> None:
        destination = tmp_path / "same.png"
        request = MediaOptimizationRequest(
            source=png_file, destination=destination, max_dimension=4096
        )
        result = optimize_media(request)
        with Image.open(destination) as output:
            assert output.size == (64, 64)
        assert result.integrity_verified is True

    def test_convert_jpeg_to_webp(self, jpeg_file: Path, tmp_path: Path) -> None:
        destination = tmp_path / "output.webp"
        request = MediaOptimizationRequest(source=jpeg_file, destination=destination)
        result = optimize_media(request)
        assert result.media_format is MediaFormat.JPEG
        assert destination.exists()
        assert Image.open(destination).format == "WEBP"

    def test_convert_png_to_avif(self, png_file: Path, tmp_path: Path) -> None:
        destination = tmp_path / "output.avif"
        request = MediaOptimizationRequest(source=png_file, destination=destination)
        result = optimize_media(request)
        assert destination.exists()
        assert Image.open(destination).format == "AVIF"
        assert result.integrity_verified is True

    def test_convert_gif_to_webp(self, tmp_path: Path) -> None:
        source = tmp_path / "source.gif"
        _make_gif(source)
        destination = tmp_path / "output.webp"
        result = optimize_media(
            MediaOptimizationRequest(source=source, destination=destination)
        )
        assert result.media_format is MediaFormat.GIF
        assert Image.open(destination).format == "WEBP"

    def test_convert_heic_to_jpeg(self, tmp_path: Path) -> None:
        source = tmp_path / "source.heic"
        _make_heic(source)
        destination = tmp_path / "output.jpg"
        result = optimize_media(
            MediaOptimizationRequest(source=source, destination=destination)
        )
        assert result.media_format is MediaFormat.HEIC
        assert Image.open(destination).format == "JPEG"

    def test_progress_callback_receives_updates(
        self, png_file: Path, tmp_path: Path
    ) -> None:
        updates: list[float] = []

        def callback(progress: object) -> None:
            updates.append(progress.percentage)

        request = MediaOptimizationRequest(
            source=png_file,
            destination=tmp_path / "out.png",
        )
        optimize_media(request, callback=callback)
        assert len(updates) >= 1
        assert updates[-1] == 100.0

    def test_same_source_and_destination_raises(self, png_file: Path) -> None:
        request = MediaOptimizationRequest(source=png_file, destination=png_file)
        with pytest.raises(InvalidRequestError):
            optimize_media(request)

    def test_destination_exists_without_overwrite(
        self, png_file: Path, tmp_path: Path
    ) -> None:
        destination = tmp_path / "exists.png"
        destination.write_bytes(b"existing")
        request = MediaOptimizationRequest(source=png_file, destination=destination)
        with pytest.raises(CompressionError):
            optimize_media(request)

    def test_overwrite_existing_destination(
        self, png_file: Path, tmp_path: Path
    ) -> None:
        destination = tmp_path / "exists.png"
        destination.write_bytes(b"existing")
        request = MediaOptimizationRequest(
            source=png_file,
            destination=destination,
            overwrite=True,
        )
        optimize_media(request)
        assert destination.stat().st_size != len(b"existing")


class TestOptimizeSvg:
    """SVG minification through scour."""

    def _make_svg(self, path: Path) -> None:
        path.write_text(
            '<?xml version="1.0"?>\n'
            "<!-- generated -->\n"
            '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60">\n'
            "  <metadata>editor data</metadata>\n"
            "  <title>shape</title>\n"
            '  <rect x="10.0000" y="10.0000" width="60.0000" '
            'height="40.0000" fill="#ff0000"/>\n'
            "</svg>\n",
            encoding="utf-8",
        )

    def test_detect_svg(self, tmp_path: Path) -> None:
        source = tmp_path / "icon.svg"
        self._make_svg(source)
        assert detect_media_format(source) is MediaFormat.SVG

    def test_optimize_svg(self, tmp_path: Path) -> None:
        source = tmp_path / "icon.svg"
        self._make_svg(source)
        destination = tmp_path / "icon.min.svg"
        result = optimize_media(
            MediaOptimizationRequest(source=source, destination=destination)
        )
        assert result.media_format is MediaFormat.SVG
        assert result.integrity_verified is True
        assert result.output_size < result.source_size
        output = destination.read_text(encoding="utf-8")
        assert "<!--" not in output
        assert "<metadata>" not in output
        assert "<title>" in output  # accessibility content preserved

    def test_optimize_svg_rejects_invalid(self, tmp_path: Path) -> None:
        source = tmp_path / "broken.svg"
        source.write_text("not xml at all", encoding="utf-8")
        with pytest.raises(CompressionError):
            optimize_media(
                MediaOptimizationRequest(
                    source=source, destination=tmp_path / "out.svg"
                )
            )


class TestOptimizeVideo:
    """FFmpeg-backed video optimization."""

    def test_optimize_video(self, video_file: Path, tmp_path: Path) -> None:
        destination = tmp_path / "output.mp4"
        request = MediaOptimizationRequest(
            source=video_file,
            destination=destination,
            video_crf=28,
        )
        result = optimize_media(request)
        assert result.media_format is MediaFormat.VIDEO
        assert destination.exists()
        assert result.integrity_verified is True

    def test_invalid_video_preset_raises(
        self, video_file: Path, tmp_path: Path
    ) -> None:
        destination = tmp_path / "output.mp4"
        request = MediaOptimizationRequest(
            source=video_file,
            destination=destination,
            video_preset="fastest",
        )
        with pytest.raises(InvalidRequestError):
            optimize_media(request)

    def test_invalid_video_crf_raises(self, video_file: Path, tmp_path: Path) -> None:
        destination = tmp_path / "output.mp4"
        request = MediaOptimizationRequest(
            source=video_file,
            destination=destination,
            video_crf=60,
        )
        with pytest.raises(InvalidRequestError):
            optimize_media(request)
