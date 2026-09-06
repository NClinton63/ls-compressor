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

    def test_convert_jpeg_to_webp(self, jpeg_file: Path, tmp_path: Path) -> None:
        destination = tmp_path / "output.webp"
        request = MediaOptimizationRequest(source=jpeg_file, destination=destination)
        result = optimize_media(request)
        assert result.media_format is MediaFormat.JPEG
        assert destination.exists()
        assert Image.open(destination).format == "WEBP"

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
