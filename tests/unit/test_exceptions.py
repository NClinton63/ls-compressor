"""Tests for the core's user-safe exception hierarchy."""

import pytest

from ls_compressor.core.exceptions import (
    CompressionError,
    CorruptedArchiveError,
    FileAccessError,
    InsufficientSpaceError,
    IntegrityError,
    UnsupportedFormatError,
)


@pytest.mark.parametrize(
    "error_type",
    [
        CorruptedArchiveError,
        FileAccessError,
        InsufficientSpaceError,
        IntegrityError,
        UnsupportedFormatError,
    ],
)
def test_domain_errors_share_user_safe_base(error_type: type[CompressionError]) -> None:
    """Callers can handle all expected domain failures without broad catches."""
    error = error_type("Readable message")

    assert isinstance(error, CompressionError)
    assert str(error) == "Readable message"
