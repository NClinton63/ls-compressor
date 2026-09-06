"""User-safe exception hierarchy for compression operations."""


class CompressionError(Exception):
    """Base exception for errors that can be presented safely to a user."""


class InvalidRequestError(CompressionError):
    """Raised when an operation request is incomplete or inconsistent."""


class UnsupportedFormatError(CompressionError):
    """Raised when an archive format cannot be identified or handled."""


class CorruptedArchiveError(CompressionError):
    """Raised when an archive is malformed or fails an integrity check."""


class IntegrityError(CompressionError):
    """Raised when compressed content differs from its source."""


class SourceNotFoundError(CompressionError):
    """Raised when an operation source does not exist."""


class DestinationExistsError(CompressionError):
    """Raised when output would overwrite data without permission."""


class OperationCancelledError(CompressionError):
    """Raised when a running operation is cancelled by the caller."""


class InsufficientSpaceError(CompressionError):
    """Raised when an operation cannot continue because storage is full."""


class FileAccessError(CompressionError):
    """Raised when filesystem permissions prevent an operation."""


class EncryptionError(CompressionError):
    """Raised when encryption or decryption cannot be completed."""
