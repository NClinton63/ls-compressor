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


class CompressionPreset(StrEnum):
    """Named algorithm/level bundles for common speed-size trade-offs."""

    FAST = "fast"
    BALANCED = "balanced"
    MAXIMUM = "maximum"

    @property
    def algorithm(self) -> CompressionAlgorithm:
        """Return the algorithm selected by this preset."""
        return {
            self.FAST: CompressionAlgorithm.ZSTD,
            self.BALANCED: CompressionAlgorithm.ZSTD,
            self.MAXIMUM: CompressionAlgorithm.XZ,
        }[self]

    @property
    def level(self) -> int:
        """Return the compression level selected by this preset."""
        return {self.FAST: 1, self.BALANCED: 3, self.MAXIMUM: 9}[self]

    @property
    def display_name(self) -> str:
        """Return the human-readable preset name."""
        return {
            self.FAST: "Fast",
            self.BALANCED: "Balanced",
            self.MAXIMUM: "Maximum",
        }[self]


class EncryptionFormat(StrEnum):
    """Encryption containers available for password-protected archives."""

    LSE = "lse"
    ZIP_AES = "zip-aes"
    SEVENZ = "7z"

    @property
    def display_name(self) -> str:
        """Return the human-readable name for the encryption format."""
        names = {
            self.LSE: "LS Container (maximum security)",
            self.ZIP_AES: "AES-256 ZIP (compatible)",
            self.SEVENZ: "AES-256 7z (compatible)",
        }
        return names[self]


@dataclass(frozen=True, slots=True)
class CompressionRequest:
    """Describe a compression operation without performing filesystem access."""

    source: Path
    destination: Path
    algorithm: CompressionAlgorithm = CompressionAlgorithm.ZSTD
    compression_level: int | None = None
    overwrite: bool = False
    verify: bool = True
    password: str | None = None
    self_extracting: bool = False
    encryption_format: EncryptionFormat = EncryptionFormat.LSE
    extra_sources: tuple[Path, ...] = ()
    exclude: tuple[str, ...] = ()
    split_size: int | None = None

    @property
    def all_sources(self) -> tuple[Path, ...]:
        """Return every input source, primary first."""
        return (self.source, *self.extra_sources)


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
