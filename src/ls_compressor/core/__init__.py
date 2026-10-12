"""GUI-independent compression domain types and services."""

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.compressor import compress, decompress, plan_compression
from ls_compressor.core.encryption import (
    create_self_extracting_archive,
    decrypt_archive,
    encrypt_archive,
    extract_payload,
    is_encrypted_file,
    is_self_extracting_archive,
    read_encrypted_extension,
    self_extracting_extension,
)
from ls_compressor.core.exceptions import (
    CompressionError,
    EncryptionError,
    InvalidRequestError,
    UnsupportedFormatError,
)
from ls_compressor.core.icons import generate_icon_pack
from ls_compressor.core.listing import (
    ArchiveEntry,
    format_listing,
    list_archive,
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
    CompressionPlan,
    CompressionPreset,
    CompressionRequest,
    DecompressionRequest,
    EncryptionFormat,
    OperationKind,
    OperationProgress,
    OperationResult,
    PlanMember,
)
from ls_compressor.core.palette import extract_palette
from ls_compressor.core.passwords import PasswordStrength, password_strength
from ls_compressor.core.progress import ProgressCallback, ProgressReporter
from ls_compressor.core.verification import (
    detect_algorithm,
    verify_against_source,
    verify_archive,
)
from ls_compressor.core.volumes import (
    is_volume,
    join_volumes,
    parse_size,
    split_archive,
    volume_base,
    volume_parts,
)

__all__ = [
    "ArchiveEntry",
    "CompressionAlgorithm",
    "CompressionError",
    "CompressionPlan",
    "CompressionPreset",
    "CompressionRequest",
    "DecompressionRequest",
    "EncryptionError",
    "EncryptionFormat",
    "InvalidRequestError",
    "MediaFormat",
    "MediaOptimizationMode",
    "MediaOptimizationRequest",
    "MediaOptimizationResult",
    "OperationKind",
    "OperationProgress",
    "OperationResult",
    "PasswordStrength",
    "PlanMember",
    "ProgressCallback",
    "ProgressReporter",
    "UnsupportedFormatError",
    "compress",
    "create_self_extracting_archive",
    "decompress",
    "decrypt_archive",
    "detect_algorithm",
    "detect_media_format",
    "encrypt_archive",
    "extract_palette",
    "extract_payload",
    "format_listing",
    "generate_icon_pack",
    "is_encrypted_file",
    "is_self_extracting_archive",
    "is_volume",
    "join_volumes",
    "list_archive",
    "optimize_media",
    "parse_size",
    "password_strength",
    "plan_compression",
    "read_encrypted_extension",
    "self_extracting_extension",
    "split_archive",
    "verify_against_source",
    "verify_archive",
    "volume_base",
    "volume_parts",
]
