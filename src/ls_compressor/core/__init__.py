"""GUI-independent compression domain types and services."""

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.compressor import compress, decompress
from ls_compressor.core.encryption import (
    create_self_extracting_archive,
    decrypt_archive,
    encrypt_archive,
    extract_payload,
    is_encrypted_file,
    is_self_extracting_archive,
    read_encrypted_extension,
)
from ls_compressor.core.exceptions import (
    CompressionError,
    EncryptionError,
    InvalidRequestError,
    UnsupportedFormatError,
)
from ls_compressor.core.media import (
    MediaFormat,
    MediaOptimizationMode,
    MediaOptimizationRequest,
    MediaOptimizationResult,
    detect_media_format,
    optimize_media,
)
from ls_compressor.core.models import (
    CompressionRequest,
    DecompressionRequest,
    OperationKind,
    OperationProgress,
    OperationResult,
)
from ls_compressor.core.progress import ProgressCallback, ProgressReporter
from ls_compressor.core.verification import (
    detect_algorithm,
    verify_against_source,
    verify_archive,
)

__all__ = [
    "CompressionAlgorithm",
    "CompressionError",
    "CompressionRequest",
    "DecompressionRequest",
    "EncryptionError",
    "InvalidRequestError",
    "MediaFormat",
    "MediaOptimizationMode",
    "MediaOptimizationRequest",
    "MediaOptimizationResult",
    "OperationKind",
    "OperationProgress",
    "OperationResult",
    "ProgressCallback",
    "ProgressReporter",
    "UnsupportedFormatError",
    "compress",
    "create_self_extracting_archive",
    "decrypt_archive",
    "decompress",
    "detect_algorithm",
    "detect_media_format",
    "encrypt_archive",
    "extract_payload",
    "is_encrypted_file",
    "is_self_extracting_archive",
    "optimize_media",
    "read_encrypted_extension",
    "verify_against_source",
    "verify_archive",
]
