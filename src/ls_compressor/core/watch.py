"""Domain models for automated watch-folder (Hot Folder) processing."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.compressor import compress
from ls_compressor.core.exceptions import CompressionError
from ls_compressor.core.media import MediaOptimizationMode, optimize_media
from ls_compressor.core.models import CompressionRequest, OperationResult


class WatchOperationType(StrEnum):
    """Kinds of processing a watch folder can trigger."""

    COMPRESS = "compress"
    MEDIA_OPTIMIZE = "media_optimize"


@dataclass(frozen=True, slots=True)
class WatchFolderConfig:
    """Configuration for a single monitored folder."""

    path: Path
    output_folder: Path
    operation: WatchOperationType = WatchOperationType.COMPRESS
    enabled: bool = True
    algorithm: CompressionAlgorithm = CompressionAlgorithm.ZIP
    compression_level: int | None = None
    media_mode: MediaOptimizationMode = MediaOptimizationMode.LOSSLESS
    recursive: bool = True
    password: str | None = None
    self_extracting: bool = False

    def __post_init__(self) -> None:
        """Reject inconsistent watch folder configuration values."""
        if not isinstance(self.path, Path):
            raise ValueError("path must be a Path")
        if not isinstance(self.output_folder, Path):
            raise ValueError("output_folder must be a Path")
        if not isinstance(self.operation, WatchOperationType):
            raise ValueError("operation must be a supported watch operation")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a boolean")
        if not isinstance(self.algorithm, CompressionAlgorithm):
            raise ValueError("algorithm must be a supported compression algorithm")
        if self.compression_level is not None and (
            not isinstance(self.compression_level, int) or self.compression_level < 1
        ):
            raise ValueError("compression_level must be a positive integer or None")
        if not isinstance(self.media_mode, MediaOptimizationMode):
            raise ValueError("media_mode must be a supported media optimization mode")
        if not isinstance(self.recursive, bool):
            raise ValueError("recursive must be a boolean")
        if self.password is not None and not isinstance(self.password, str):
            raise ValueError("password must be a string or None")
        if not isinstance(self.self_extracting, bool):
            raise ValueError("self_extracting must be a boolean")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dictionary."""
        return {
            "path": str(self.path),
            "output_folder": str(self.output_folder),
            "operation": self.operation.value,
            "enabled": self.enabled,
            "algorithm": self.algorithm.value,
            "compression_level": self.compression_level,
            "media_mode": self.media_mode.value,
            "recursive": self.recursive,
            "password": self.password,
            "self_extracting": self.self_extracting,
        }

    @classmethod
    def from_dict(cls, values: dict[str, object]) -> WatchFolderConfig:
        """Build a validated configuration from decoded JSON values."""
        enabled = values.get("enabled", True)
        recursive = values.get("recursive", True)
        compression_level = values.get("compression_level")
        password = values.get("password")
        self_extracting = values.get("self_extracting", False)
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        if not isinstance(recursive, bool):
            raise ValueError("recursive must be a boolean")
        if compression_level is not None and not isinstance(compression_level, int):
            raise ValueError("compression_level must be an integer or None")
        if password is not None and not isinstance(password, str):
            raise ValueError("password must be a string or None")
        if not isinstance(self_extracting, bool):
            raise ValueError("self_extracting must be a boolean")
        return cls(
            path=Path(str(values["path"])),
            output_folder=Path(str(values["output_folder"])),
            operation=WatchOperationType(values.get("operation", "compress")),
            enabled=enabled,
            algorithm=CompressionAlgorithm(
                values.get("algorithm", CompressionAlgorithm.ZIP.value)
            ),
            compression_level=compression_level,
            media_mode=MediaOptimizationMode(
                values.get("media_mode", MediaOptimizationMode.LOSSLESS.value)
            ),
            recursive=recursive,
            password=password,
            self_extracting=self_extracting,
        )


@dataclass(frozen=True, slots=True)
class WatchEvent:
    """A filesystem event observed inside a watched folder."""

    source: Path
    config: WatchFolderConfig
    event_type: str


def derive_watch_destination(source: Path, config: WatchFolderConfig) -> Path:
    """Return the destination path for a watched source file."""
    if config.operation == WatchOperationType.MEDIA_OPTIMIZE:
        suffix = source.suffix
        if (
            config.media_mode == MediaOptimizationMode.LOSSY
            and suffix.lower() == ".png"
        ):
            suffix = ".webp"
        return config.output_folder / (source.stem + "-optimized" + suffix)
    if config.password:
        if config.self_extracting:
            if sys.platform == "darwin":
                return config.output_folder / (source.stem + ".app")
            return config.output_folder / (source.stem + ".py")
        return config.output_folder / (
            source.name
            + config.algorithm.archive_suffix(is_directory=source.is_dir())
            + ".lsenc"
        )
    return config.output_folder / (
        source.name + config.algorithm.archive_suffix(is_directory=source.is_dir())
    )


def process_watch_event(event: WatchEvent) -> OperationResult:
    """Execute the configured operation for a watched file event."""
    config = event.config
    destination = derive_watch_destination(event.source, config)
    try:
        if config.operation == WatchOperationType.MEDIA_OPTIMIZE:
            from ls_compressor.core.media import MediaOptimizationRequest

            request = MediaOptimizationRequest(
                source=event.source,
                destination=destination,
                mode=config.media_mode,
                overwrite=False,
            )
            return optimize_media(request)
        request = CompressionRequest(
            source=event.source,
            destination=destination,
            algorithm=config.algorithm,
            compression_level=config.compression_level,
            overwrite=False,
            verify=True,
            password=config.password,
            self_extracting=config.self_extracting,
        )
        return compress(request)
    except CompressionError:
        raise
    except OSError as error:
        raise CompressionError(f"Watch processing failed: {error}") from error
