"""Integrity verification for supported lossless archive formats."""

import bz2
import gzip
import hashlib
import lzma
import tarfile
import zipfile
from pathlib import Path
from typing import BinaryIO

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.exceptions import (
    CorruptedArchiveError,
    IntegrityError,
    UnsupportedFormatError,
)
from ls_compressor.core.filesystem import CHUNK_SIZE, iter_files, safe_target


def detect_algorithm(path: Path) -> CompressionAlgorithm:
    """Identify a supported archive algorithm using its content signature."""
    try:
        with path.open("rb") as stream:
            signature = stream.read(6)
    except OSError as error:
        raise CorruptedArchiveError(f"Cannot read archive: {path}") from error
    if signature.startswith(b"PK\x03\x04") or signature.startswith(b"PK\x05\x06"):
        return CompressionAlgorithm.ZIP
    if signature.startswith(b"\xfd7zXZ\x00"):
        return CompressionAlgorithm.XZ
    if signature.startswith(b"\x1f\x8b"):
        return CompressionAlgorithm.GZIP
    if signature.startswith(b"BZh"):
        return CompressionAlgorithm.BZ2
    raise UnsupportedFormatError(f"Unsupported archive format: {path}")


def _digest(stream: BinaryIO) -> bytes:
    """Calculate a SHA-256 digest using bounded reads."""
    digest = hashlib.sha256()
    while chunk := stream.read(CHUNK_SIZE):
        digest.update(chunk)
    return digest.digest()


def _stream_opener(algorithm: CompressionAlgorithm):
    """Return the standard-library opener for a compressed stream."""
    return {
        CompressionAlgorithm.XZ: lzma.open,
        CompressionAlgorithm.GZIP: gzip.open,
        CompressionAlgorithm.BZ2: bz2.open,
    }[algorithm]


def verify_archive(path: Path) -> CompressionAlgorithm:
    """Read every archive payload and raise when it is malformed or unsafe."""
    algorithm = detect_algorithm(path)
    try:
        if algorithm is CompressionAlgorithm.ZIP:
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    safe_target(Path("."), info.filename)
                    if not info.is_dir():
                        with archive.open(info) as stream:
                            _digest(stream)
        elif tarfile.is_tarfile(path):
            with tarfile.open(path, "r:*") as archive:
                for member in archive.getmembers():
                    safe_target(Path("."), member.name)
                    if member.issym() or member.islnk():
                        raise CorruptedArchiveError(
                            f"Archive contains an unsafe link: {member.name}"
                        )
                    stream = archive.extractfile(member)
                    if stream is not None:
                        with stream:
                            _digest(stream)
        else:
            with _stream_opener(algorithm)(path, "rb") as stream:
                _digest(stream)
    except (
        OSError,
        EOFError,
        lzma.LZMAError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as error:
        raise CorruptedArchiveError(f"Archive is corrupted: {path}") from error
    return algorithm


def verify_against_source(source: Path, archive_path: Path) -> None:
    """Verify archive payload bytes and names against their original source."""
    algorithm = verify_archive(archive_path)
    try:
        if algorithm is CompressionAlgorithm.ZIP:
            _verify_zip_source(source, archive_path)
        elif source.is_dir():
            _verify_tar_source(source, archive_path)
        else:
            with (
                source.open("rb") as original,
                _stream_opener(algorithm)(archive_path, "rb") as compressed,
            ):
                if _digest(original) != _digest(compressed):
                    raise IntegrityError("Compressed content differs from source")
    except IntegrityError:
        raise
    except (
        OSError,
        EOFError,
        lzma.LZMAError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as error:
        raise CorruptedArchiveError(f"Archive is corrupted: {archive_path}") from error


def _verify_zip_source(source: Path, archive_path: Path) -> None:
    """Compare ZIP file entries with source files."""
    expected = {
        (
            path.relative_to(source.parent) if source.is_dir() else Path(source.name)
        ).as_posix(): path
        for path in iter_files(source)
    }
    with zipfile.ZipFile(archive_path) as archive:
        actual = {
            info.filename: info for info in archive.infolist() if not info.is_dir()
        }
        if set(actual) != set(expected):
            raise IntegrityError("ZIP entries differ from source")
        for name, path in expected.items():
            with path.open("rb") as original, archive.open(actual[name]) as compressed:
                if _digest(original) != _digest(compressed):
                    raise IntegrityError(f"ZIP entry differs from source: {name}")


def _verify_tar_source(source: Path, archive_path: Path) -> None:
    """Compare tar archive file entries with source files."""
    expected = {
        path.relative_to(source.parent).as_posix(): path for path in iter_files(source)
    }
    with tarfile.open(archive_path, "r:*") as archive:
        actual = {member.name: member for member in archive if member.isfile()}
        if set(actual) != set(expected):
            raise IntegrityError("Tar entries differ from source")
        for name, path in expected.items():
            compressed = archive.extractfile(actual[name])
            if compressed is None:
                raise IntegrityError(f"Missing tar entry: {name}")
            with path.open("rb") as original, compressed:
                if _digest(original) != _digest(compressed):
                    raise IntegrityError(f"Tar entry differs from source: {name}")
