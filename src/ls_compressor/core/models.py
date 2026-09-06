"""Typed request, progress, and result models for compression operations."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ls_compressor.core.algorithms import CompressionAlgorithm


class OperationKind(StrEnum):
    """Kinds of operations exposed by the compression core."""

    COMPRESS = "compress"
    DECOMPRESS = "decompress"
    VERIFY = "verify"
    MEDIA_OPTIMIZE = "media_optimize"


@dataclass(frozen=True, slots=True)
class CompressionRequest:
    """Describe a compression operation without performing filesystem access."""

    source: Path
    destination: Path
    algorithm: CompressionAlgorithm = CompressionAlgorithm.ZIP
    compression_level: int | None = None
    overwrite: bool = False
    verify: bool = True
    password: str | None = None
    self_extracting: bool = False


@dataclass(frozen=True, slots=True)
class DecompressionRequest:
    """Describe an archive extraction operation."""

    source: Path
    destination: Path
    overwrite: bool = False
    verify: bool = True
    password: str | None = None


@dataclass(frozen=True, slots=True)
class OperationProgress:
    """Represent an immutable progress update from a core operation."""

    kind: OperationKind
    completed_bytes: int
    total_bytes: int
    current_file: Path | None = None

    @property
    def percentage(self) -> float:
        """Return completion as a percentage clamped to the range 0-100."""
        if self.total_bytes <= 0:
            return 100.0 if self.completed_bytes > 0 else 0.0
        return min(100.0, max(0.0, self.completed_bytes / self.total_bytes * 100.0))


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Summarize a successfully completed compression operation."""

    kind: OperationKind
    source: Path
    destination: Path
    algorithm: CompressionAlgorithm
    source_size: int
    output_size: int
    elapsed_seconds: float
    files_processed: int
    integrity_verified: bool

    @property
    def compression_ratio(self) -> float:
        """Return output size divided by source size, or zero for empty input."""
        if self.source_size == 0:
            return 0.0
        return self.output_size / self.source_size

    @property
    def space_savings_percentage(self) -> float:
        """Return the percentage of source bytes eliminated by compression."""
        if self.source_size == 0:
            return 0.0
        return (1.0 - self.compression_ratio) * 100.0
