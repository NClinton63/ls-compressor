"""Tests for archive integrity verification."""

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.exceptions import (
    CorruptedArchiveError,
    FileAccessError,
    UnsupportedFormatError,
)
from ls_compressor.core.verification import detect_algorithm, verify_archive


@pytest.mark.parametrize(
    ("signature", "algorithm"),
    [
        (b"PK\x05\x06" + b"\x00" * 18, CompressionAlgorithm.ZIP),
        (b"\xfd7zXZ\x00", CompressionAlgorithm.XZ),
        (b"\x1f\x8brest", CompressionAlgorithm.GZIP),
        (b"BZh9rest", CompressionAlgorithm.BZ2),
    ],
)
def test_detect_algorithm_uses_signatures(
    tmp_path: Path, signature: bytes, algorithm: CompressionAlgorithm
) -> None:
    """Supported formats are identified independently of filename."""
    archive = tmp_path / "archive"
    archive.write_bytes(signature)

    assert detect_algorithm(archive) is algorithm


def test_unknown_signature_is_unsupported(tmp_path: Path) -> None:
    """Unknown data maps to the unsupported-format exception."""
    archive = tmp_path / "archive"
    archive.write_bytes(b"unknown")

    with pytest.raises(UnsupportedFormatError):
        detect_algorithm(archive)


def test_corrupted_zip_is_rejected(tmp_path: Path) -> None:
    """Malformed archives do not pass integrity checks."""
    archive = tmp_path / "bad.zip"
    archive.write_bytes(b"PK\x03\x04broken")

    with pytest.raises(CorruptedArchiveError):
        verify_archive(archive)


def test_zip_traversal_is_rejected(tmp_path: Path) -> None:
    """Verification rejects ZIP path traversal before extraction."""
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape", b"bad")

    with pytest.raises(FileAccessError):
        verify_archive(archive)


def test_tar_traversal_is_rejected(tmp_path: Path) -> None:
    """Verification rejects compressed tar path traversal."""
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        info = tarfile.TarInfo("../escape")
        info.size = 3
        output.addfile(info, io.BytesIO(b"bad"))

    with pytest.raises(FileAccessError):
        verify_archive(archive)
