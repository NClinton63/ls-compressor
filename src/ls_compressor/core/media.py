"""Media-specific asset optimization for web developers and creative workflows.

The optimizer handles PNG, JPEG, and WebP images through Pillow and video
files through FFmpeg (via imageio_ffmpeg). Each format is implemented as a
strategy so new codecs can be added without changing the public API.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from PIL import Image
from PIL.AvifImagePlugin import AvifImageFile
from PIL.BmpImagePlugin import BmpImageFile
from PIL.GifImagePlugin import GifImageFile
from PIL.JpegImagePlugin import JpegImageFile
from PIL.PngImagePlugin import PngImageFile
from PIL.WebPImagePlugin import WebPImageFile

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover - optional dependency
    pillow_heif = None

from ls_compressor.core.exceptions import (
    CompressionError,
    InvalidRequestError,
    UnsupportedFormatError,
)
from ls_compressor.core.filesystem import (
    CHUNK_SIZE,
    ensure_source,
    prepare_destination,
    replace_path,
    source_size,
)
from ls_compressor.core.models import OperationKind
from ls_compressor.core.progress import ProgressCallback, ProgressReporter

_LOGGER = logging.getLogger("ls_compressor.core.media")


class MediaFormat(StrEnum):
    """Media asset categories supported by the optimizer."""

    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"
    AVIF = "avif"
    GIF = "gif"
    BMP = "bmp"
    HEIC = "heic"
    SVG = "svg"
    VIDEO = "video"

    @property
    def display_name(self) -> str:
        """Return the human-readable name for the media format."""
        names = {
            self.PNG: "PNG Image",
            self.JPEG: "JPEG Image",
            self.WEBP: "WebP Image",
            self.AVIF: "AVIF Image",
            self.GIF: "GIF Image",
            self.BMP: "BMP Image",
            self.HEIC: "HEIC Image",
            self.SVG: "SVG Image",
            self.VIDEO: "Video",
        }
        return names[self]


class MediaOptimizationMode(StrEnum):
    """Optimization fidelity modes."""

    LOSSLESS = "lossless"
    LOSSY = "lossy"


@dataclass(frozen=True, slots=True)
class MediaOptimizationRequest:
    """Describe a media optimization operation without touching the filesystem."""

    source: Path
    destination: Path
    mode: MediaOptimizationMode = MediaOptimizationMode.LOSSLESS
    quality: int | None = None
    overwrite: bool = False
    video_preset: str = "medium"
    video_crf: int | None = None
    max_dimension: int | None = None


@dataclass(frozen=True, slots=True)
class MediaOptimizationResult:
    """Summarize a completed media optimization operation."""

    kind: OperationKind
    source: Path
    destination: Path
    media_format: MediaFormat
    source_size: int
    output_size: int
    elapsed_seconds: float
    integrity_verified: bool

    @property
    def compression_ratio(self) -> float:
        """Return output size divided by source size, or zero for empty input."""
        if self.source_size == 0:
            return 0.0
        return self.output_size / self.source_size

    @property
    def space_savings_percentage(self) -> float:
        """Return the percentage of source bytes eliminated."""
        if self.source_size == 0:
            return 0.0
        return (1.0 - self.compression_ratio) * 100.0


def detect_media_format(source: Path) -> MediaFormat:
    """Return the media format category for a file path.

    Detection prefers content sniffing when available and falls back to the
    file extension for formats that Pillow or FFmpeg can identify directly.
    """
    ensure_source(source)
    suffix = source.suffix.lower()
    image_suffixes = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".avif",
        ".gif",
        ".bmp",
        ".heic",
        ".heif",
        ".svg",
    }
    video_suffixes = {
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".webm",
        ".m4v",
        ".flv",
        ".wmv",
    }
    if suffix in image_suffixes:
        return _image_format_from_suffix(suffix)
    if suffix in video_suffixes:
        return MediaFormat.VIDEO
    try:
        with Image.open(source) as image:
            return _image_format_from_pil(image)
    except Exception as error:
        _LOGGER.debug("Pillow detection failed for %s: %s", source, error)
    if _is_video(source):
        return MediaFormat.VIDEO
    raise UnsupportedFormatError(f"Unsupported media format: {source}")


def _image_format_from_suffix(suffix: str) -> MediaFormat:
    """Map a lowercase image file extension to a media format."""
    mapping = {
        ".png": MediaFormat.PNG,
        ".jpg": MediaFormat.JPEG,
        ".jpeg": MediaFormat.JPEG,
        ".webp": MediaFormat.WEBP,
        ".avif": MediaFormat.AVIF,
        ".gif": MediaFormat.GIF,
        ".bmp": MediaFormat.BMP,
        ".heic": MediaFormat.HEIC,
        ".heif": MediaFormat.HEIC,
        ".svg": MediaFormat.SVG,
    }
    return mapping[suffix]


def _image_format_from_pil(image: Image.Image) -> MediaFormat:
    """Map a Pillow image instance to a media format."""
    if isinstance(image, PngImageFile):
        return MediaFormat.PNG
    if isinstance(image, JpegImageFile):
        return MediaFormat.JPEG
    if isinstance(image, WebPImageFile):
        return MediaFormat.WEBP
    if isinstance(image, AvifImageFile):
        return MediaFormat.AVIF
    if isinstance(image, GifImageFile):
        return MediaFormat.GIF
    if isinstance(image, BmpImageFile):
        return MediaFormat.BMP
    if image.format == "HEIF":
        return MediaFormat.HEIC
    raise UnsupportedFormatError(f"Unsupported image format: {image.format}")


def _is_video(source: Path) -> bool:
    """Probe whether a path points to a readable video stream."""
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        ffmpeg = get_ffmpeg_exe()
    except Exception as error:
        _LOGGER.debug("FFmpeg not available: %s", error)
        return False
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-f",
        "null",
        "-",
    ]
    try:
        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def optimize_media(
    request: MediaOptimizationRequest,
    callback: ProgressCallback | None = None,
) -> MediaOptimizationResult:
    """Optimize a single media file and return a result summary."""
    started = time.monotonic()
    ensure_source(request.source)
    source_path = request.source.resolve()
    destination_path = request.destination.resolve()
    if source_path == destination_path:
        raise InvalidRequestError("Source and destination must differ")
    media_format = detect_media_format(request.source)
    prepare_destination(request.destination, overwrite=request.overwrite)
    total = source_size(request.source)
    progress = ProgressReporter(OperationKind.MEDIA_OPTIMIZE, total, callback)
    temporary = _temporary_path(request.destination)
    try:
        output_format = _destination_format(request.destination, media_format)
        # FFmpeg handles any conversion that starts or ends in a video
        # container (including animated GIF/WebP targets).
        if MediaFormat.VIDEO in {media_format, output_format}:
            optimizer: _MediaOptimizer = _VideoOptimizer()
        else:
            optimizer = _optimizer_for(media_format)
        optimizer.optimize(request, temporary, output_format, progress)
        integrity_verified = optimizer.verify(request, temporary)
        replace_path(temporary, request.destination, overwrite=request.overwrite)
        progress.complete(request.destination)
    except CompressionError:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise CompressionError(f"Media optimization failed: {error}") from error
    return MediaOptimizationResult(
        OperationKind.MEDIA_OPTIMIZE,
        request.source,
        request.destination,
        media_format,
        total,
        request.destination.stat().st_size,
        time.monotonic() - started,
        integrity_verified,
    )


def _destination_format(destination: Path, source_format: MediaFormat) -> MediaFormat:
    """Return the requested output media format, defaulting to the source format."""
    suffix = destination.suffix.lower()
    if source_format is MediaFormat.VIDEO and suffix in {".gif", ".webp", ".webm"}:
        return MediaFormat.VIDEO
    if suffix in {".png"}:
        return MediaFormat.PNG
    if suffix in {".jpg", ".jpeg"}:
        return MediaFormat.JPEG
    if suffix in {".webp"}:
        return MediaFormat.WEBP
    if suffix in {".avif"}:
        return MediaFormat.AVIF
    if suffix in {".svg"}:
        return MediaFormat.SVG
    if suffix == ".gif":
        # Video sources already returned VIDEO above; an image targeting .gif
        # stays on the image path.
        return MediaFormat.GIF
    if suffix in {
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".webm",
        ".m4v",
        ".flv",
        ".wmv",
    }:
        return MediaFormat.VIDEO
    return source_format


def _temporary_path(destination: Path) -> Path:
    """Reserve a temporary output path beside its destination.

    The temporary file preserves the destination suffix so tools such as
    FFmpeg can infer the output container format from the extension.
    """
    import os
    from tempfile import mkstemp

    suffix = destination.suffix
    prefix = f".{destination.stem}." if suffix else f".{destination.name}."
    descriptor, name = mkstemp(
        prefix=prefix,
        suffix=suffix,
        dir=destination.parent,
    )
    os.close(descriptor)
    return Path(name)


def _optimizer_for(media_format: MediaFormat) -> _MediaOptimizer:
    """Return the optimizer strategy for a media format."""
    strategies: dict[MediaFormat, type[_MediaOptimizer]] = {
        MediaFormat.PNG: _ImageOptimizer,
        MediaFormat.JPEG: _ImageOptimizer,
        MediaFormat.WEBP: _ImageOptimizer,
        MediaFormat.AVIF: _ImageOptimizer,
        MediaFormat.GIF: _ImageOptimizer,
        MediaFormat.BMP: _ImageOptimizer,
        MediaFormat.HEIC: _ImageOptimizer,
        MediaFormat.SVG: _SvgOptimizer,
        MediaFormat.VIDEO: _VideoOptimizer,
    }
    return strategies[media_format]()


class _MediaOptimizer(ABC):
    """Abstract base for media optimization strategies."""

    @abstractmethod
    def optimize(
        self,
        request: MediaOptimizationRequest,
        destination: Path,
        output_format: MediaFormat,
        progress: ProgressReporter,
    ) -> None:
        """Optimize the source media and write it to destination."""

    @abstractmethod
    def verify(self, request: MediaOptimizationRequest, destination: Path) -> bool:
        """Return True if the optimized output can be successfully read."""


class _ImageOptimizer(_MediaOptimizer):
    """Pillow-based optimizer for raster image formats."""

    _PIL_FORMATS: ClassVar[dict[MediaFormat, str]] = {
        MediaFormat.PNG: "PNG",
        MediaFormat.JPEG: "JPEG",
        MediaFormat.WEBP: "WEBP",
        MediaFormat.AVIF: "AVIF",
    }

    def optimize(
        self,
        request: MediaOptimizationRequest,
        destination: Path,
        output_format: MediaFormat,
        progress: ProgressReporter,
    ) -> None:
        """Re-encode an image using format-specific lossless or lossy settings."""
        if output_format not in self._PIL_FORMATS:
            raise UnsupportedFormatError(
                f"Cannot write {output_format.display_name} output; "
                "use PNG, JPEG, WebP, or AVIF"
            )
        source_format = detect_media_format(request.source)
        with Image.open(request.source) as image:
            progress.advance(0, request.source)
            image = self._normalize_mode(image, output_format)
            image = self._resize(image, request.max_dimension)
            save_kwargs = self._save_kwargs(
                request,
                output_format,
                source_format == output_format,
            )
            image.save(
                destination, format=self._PIL_FORMATS[output_format], **save_kwargs
            )
        progress.advance(request.source.stat().st_size, request.source)

    def verify(self, request: MediaOptimizationRequest, destination: Path) -> bool:
        """Confirm the output image can be opened and has expected dimensions."""
        try:
            with (
                Image.open(request.source) as source_image,
                Image.open(destination) as output_image,
            ):
                expected = self._resize(source_image, request.max_dimension)
                return expected.size == output_image.size
        except Exception as error:
            _LOGGER.warning("Image verification failed: %s", error)
            return False

    @staticmethod
    def _normalize_mode(image: Image.Image, output_format: MediaFormat) -> Image.Image:
        """Convert the image to a mode compatible with the target format."""
        if output_format is MediaFormat.JPEG and image.mode in {"RGBA", "P", "LA"}:
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            if image.mode in {"RGBA", "LA"}:
                background.paste(
                    image,
                    mask=image.split()[-1] if image.mode in {"RGBA", "LA"} else None,
                )
                return background
        if image.mode == "P" and output_format in {
            MediaFormat.PNG,
            MediaFormat.WEBP,
            MediaFormat.AVIF,
        }:
            return image.convert("RGBA")
        if image.mode in {"CMYK", "I;16", "I", "F"}:
            return image.convert("RGB")
        return image

    @staticmethod
    def _resize(image: Image.Image, max_dimension: int | None) -> Image.Image:
        """Downscale an image so its longest edge fits max_dimension."""
        if max_dimension is None or max_dimension <= 0:
            return image
        longest = max(image.size)
        if longest <= max_dimension:
            return image
        scale = max_dimension / longest
        size = (
            max(1, round(image.width * scale)),
            max(1, round(image.height * scale)),
        )
        return image.resize(size, Image.Resampling.LANCZOS)

    @staticmethod
    def _save_kwargs(
        request: MediaOptimizationRequest,
        output_format: MediaFormat,
        same_format: bool,
    ) -> dict[str, object]:
        """Return format-specific Pillow save options."""
        quality = _clamp_quality(request.quality, output_format)
        if output_format is MediaFormat.PNG:
            return {"optimize": True}
        if output_format is MediaFormat.JPEG:
            return {
                "quality": quality,
                "optimize": True,
                "progressive": True,
                "subsampling": "4:2:0",
            }
        if output_format is MediaFormat.WEBP:
            if request.mode is MediaOptimizationMode.LOSSLESS:
                return {"lossless": True, "quality": 100, "method": 6}
            return {"quality": quality, "method": 6}
        if output_format is MediaFormat.AVIF:
            if request.mode is MediaOptimizationMode.LOSSLESS:
                return {"lossless": True, "quality": 100, "speed": 4}
            return {"quality": quality, "speed": 6}
        raise UnsupportedFormatError(f"Unsupported output format: {output_format}")


def _clamp_quality(quality: int | None, output_format: MediaFormat) -> int:
    """Return a valid quality value for lossy image output."""
    if quality is None:
        return 90
    if output_format in {MediaFormat.WEBP, MediaFormat.AVIF}:
        return min(100, max(1, quality))
    return min(95, max(1, quality))


class _SvgOptimizer(_MediaOptimizer):
    """Scour-based optimizer for SVG vector files."""

    def optimize(
        self,
        request: MediaOptimizationRequest,
        destination: Path,
        output_format: MediaFormat,
        progress: ProgressReporter,
    ) -> None:
        """Minify an SVG document while keeping it renderable."""
        from scour import scour

        progress.advance(0, request.source)
        try:
            source = request.source.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise InvalidRequestError(
                f"SVG file is not valid UTF-8 text: {request.source}"
            ) from error
        options = scour.sanitizeOptions()
        options.strip_comments = True
        options.remove_metadata = True
        options.newlines = False
        options.indent_type = "none"
        options.simple_colors = True
        options.enable_viewboxing = True
        options.group_collapse = True
        options.quiet = True
        try:
            optimized = scour.scourString(source, options)
        except Exception as error:
            raise InvalidRequestError(
                f"SVG optimization failed for: {request.source}"
            ) from error
        destination.write_text(optimized, encoding="utf-8")
        progress.advance(request.source.stat().st_size, request.source)

    def verify(self, source: Path, destination: Path) -> bool:
        """Confirm the optimized SVG still parses as an svg document."""
        try:
            from xml.etree import ElementTree

            root = ElementTree.parse(destination).getroot()
            return root.tag.rpartition("}")[2] == "svg"
        except Exception as error:
            _LOGGER.warning("SVG verification failed: %s", error)
            return False


class _VideoOptimizer(_MediaOptimizer):
    """FFmpeg-based optimizer for common video containers."""

    _VIDEO_PRESETS: ClassVar[frozenset[str]] = frozenset(
        {
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        }
    )

    def optimize(
        self,
        request: MediaOptimizationRequest,
        destination: Path,
        output_format: MediaFormat,
        progress: ProgressReporter,
    ) -> None:
        """Re-encode a video with H.264/AAC using FFmpeg."""
        from imageio_ffmpeg import get_ffmpeg_exe

        ffmpeg = get_ffmpeg_exe()
        command = self._build_command(request, destination, ffmpeg)
        duration = self._probe_duration(request.source, ffmpeg)
        _run_ffmpeg_with_progress(
            command,
            duration,
            progress,
            request.source,
        )

    def verify(self, request: MediaOptimizationRequest, destination: Path) -> bool:
        """Confirm the output video can be probed by FFmpeg."""
        if destination.suffix.lower() == ".webp":
            # Animated WebP decodes in Pillow but not the bundled FFmpeg build.
            try:
                with Image.open(destination) as image:
                    image.verify()
                return True
            except Exception as error:
                _LOGGER.warning("Animated WebP verification failed: %s", error)
                return False
        try:
            from imageio_ffmpeg import get_ffmpeg_exe

            ffmpeg = get_ffmpeg_exe()
        except Exception as error:
            _LOGGER.warning("FFmpeg not available for verification: %s", error)
            return False
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(destination),
            "-f",
            "null",
            "-",
        ]
        try:
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return True
        except subprocess.CalledProcessError as error:
            _LOGGER.warning("Video verification failed: %s", error)
            return False

    def _probe_duration(self, source: Path, ffmpeg: str) -> float | None:
        """Return the video duration in seconds if it can be determined."""
        try:

            ffprobe = str(Path(ffmpeg).parent / "ffprobe")
            if not Path(ffprobe).exists():
                ffprobe = "ffprobe"
        except Exception as error:
            _LOGGER.debug("ffprobe resolution failed: %s", error)
            return None
        command = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ]
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
                text=True,
            )
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as error:
            _LOGGER.debug("Duration probe failed for %s: %s", source, error)
            return None

    def _build_command(
        self,
        request: MediaOptimizationRequest,
        destination: Path,
        ffmpeg: str,
    ) -> list[str]:
        """Build an FFmpeg command tuned to the request settings."""
        suffix = destination.suffix.lower()
        base = [ffmpeg, "-hide_banner", "-loglevel", "info", "-i", str(request.source)]
        if suffix == ".gif":
            return [
                *base,
                "-vf",
                "fps=15,scale=480:-1:flags=lanczos,split[a][b];"
                "[a]palettegen[p];[b][p]paletteuse",
                "-loop",
                "0",
                "-an",
                "-y",
                str(destination),
            ]
        if suffix == ".webp":
            quality = request.quality if request.quality is not None else 75
            return [
                *base,
                "-c:v",
                "libwebp_anim",
                "-loop",
                "0",
                "-lossless",
                "0",
                "-q:v",
                str(min(100, max(0, quality))),
                "-an",
                "-y",
                str(destination),
            ]
        if suffix == ".webm":
            crf = request.video_crf if request.video_crf is not None else 33
            if not 0 <= crf <= 63:
                raise InvalidRequestError("WebM CRF must be between 0 and 63")
            return [
                *base,
                "-c:v",
                "libvpx-vp9",
                "-crf",
                str(crf),
                "-b:v",
                "0",
                "-row-mt",
                "1",
                "-cpu-used",
                "2",
                "-deadline",
                "good",
                "-c:a",
                "libopus",
                "-y",
                str(destination),
            ]
        preset = request.video_preset
        if preset not in self._VIDEO_PRESETS:
            raise InvalidRequestError(f"Unsupported video preset: {preset}")
        crf = request.video_crf if request.video_crf is not None else 23
        if not 0 <= crf <= 51:
            raise InvalidRequestError("Video CRF must be between 0 and 51")
        return [
            *base,
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "-y",
            str(destination),
        ]


def _run_ffmpeg_with_progress(
    command: list[str],
    duration: float | None,
    progress: ProgressReporter,
    source: Path,
    chunk_size: int = CHUNK_SIZE,
) -> None:
    """Run an FFmpeg command and report progress parsed from its stderr."""
    time_pattern = re.compile(r"time=\s*(\d{2}):(\d{2}):(\d{2}\.\d+)")
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.stderr is None:
        raise CompressionError("FFmpeg produced no progress output")
    total = progress.snapshot.total_bytes
    stderr_lines: list[str] = []
    for line in process.stderr:
        stderr_lines.append(line)
        match = time_pattern.search(line)
        if match and duration and duration > 0:
            hours, minutes, seconds = match.groups()
            elapsed = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            completed = int(min(total, total * elapsed / duration))
            progress.advance(completed - progress.snapshot.completed_bytes, source)
    process.wait()
    if process.returncode != 0:
        _LOGGER.error(
            "FFmpeg failed with exit code %d for %s: %s",
            process.returncode,
            source,
            "".join(stderr_lines)[-2000:],
        )
        raise CompressionError(
            f"FFmpeg failed with exit code {process.returncode} for {source}"
        )
