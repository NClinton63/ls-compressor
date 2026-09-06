"""Immutable GUI job models and status enumerations."""

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from ls_compressor.core import (
    CompressionAlgorithm,
    MediaFormat,
    MediaOptimizationMode,
    OperationResult,
)


class GuiJobKind(StrEnum):
    """Kinds of work a GUI job can represent."""

    COMPRESS = "compress"
    DECOMPRESS = "decompress"
    MEDIA_OPTIMIZE = "media_optimize"


class GuiJobStatus(StrEnum):
    """Lifecycle states for a GUI job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class GuiJob:
    """Present a compression, decompression, or media task in the GUI queue."""

    job_id: UUID
    kind: GuiJobKind
    source: Path
    destination: Path
    status: GuiJobStatus
    algorithm: CompressionAlgorithm | None = None
    compression_level: int = 0
    media_format: MediaFormat | None = None
    media_mode: MediaOptimizationMode = MediaOptimizationMode.LOSSLESS
    media_quality: int | None = None
    video_preset: str = "medium"
    video_crf: int | None = None
    password: str | None = None
    self_extracting: bool = False
    progress_percent: float = 0.0
    current_file: Path | None = None
    result: OperationResult | None = None
    error_message: str = ""
    throughput_mbps: float = 0.0

    def update(self, **changes: object) -> "GuiJob":
        """Return a new job instance with the supplied field changes."""
        return replace(self, **changes)
