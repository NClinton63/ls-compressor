"""Integrity verification for supported lossless archive formats."""

import bz2
import gzip
import hashlib
import lzma
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import BinaryIO

import py7zr
import pyzipper
import rarfile
import zstandard

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.exceptions import (
    CorruptedArchiveError,
    EncryptionError,
    IntegrityError,
    UnsupportedFormatError,
)
from ls_compressor.core.filesystem import (
    CHUNK_SIZE,
    is_excluded,
    iter_files,
    load_ignore_patterns,
    safe_target,
)


def detect_algorithm(path: Path) -> CompressionAlgorithm:
    """Identify a supported archive algorithm using its content signature."""
    try:
        with path.open("rb") as stream:
            signature = stream.read(6)
    except OSError as error:
        raise CorruptedArchiveError(f"Cannot read archive: {path}") from error
    if signature.startswith(b"PK\x03\x04") or signature.startswith(b"PK\x05\x06"):
        return CompressionAlgorithm.ZIP
    if signature.startswith(b"7z\xbc\xaf'\x1c"):
        return CompressionAlgorithm.SEVENZ
    if signature.startswith(b"Rar!\x1a\x07"):
        return CompressionAlgorithm.RAR
    if signature.startswith(b"\x28\xb5\x2f\xfd"):
        return CompressionAlgorithm.ZSTD
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
        CompressionAlgorithm.ZSTD: zstandard.open,
        CompressionAlgorithm.XZ: lzma.open,
        CompressionAlgorithm.GZIP: gzip.open,
        CompressionAlgorithm.BZ2: bz2.open,
    }[algorithm]


def _zstd_contains_tar(path: Path) -> bool:
    """Return True when a Zstandard stream decompresses to a tar archive."""
    try:
        with zstandard.open(path, "rb") as stream:
            head = stream.read(512)
    except OSError:
        return False
    return len(head) > 262 and head[257:262] == b"ustar"


def _verify_tar_members(archive: tarfile.TarFile) -> None:
    """Validate member names and digest every payload in an open tar."""
    for member in archive:
        safe_target(Path("."), member.name)
        if member.issym() or member.islnk():
            raise CorruptedArchiveError(
                f"Archive contains an unsafe link: {member.name}"
            )
        if member.isfile():
            stream = archive.extractfile(member)
            if stream is not None:
                with stream:
                    _digest(stream)


def _verify_7z(path: Path, password: str | None) -> None:
    """Validate member names and CRC-check every payload in a 7z archive."""
    try:
        with py7zr.SevenZipFile(path, "r", password=password) as archive:
            if archive.needs_password() and not password:
                raise EncryptionError("A password is required to verify this archive")
            for name in archive.namelist():
                safe_target(Path("."), name)
            bad = archive.testzip()
    except EncryptionError:
        raise
    except py7zr.PasswordRequired as error:
        raise EncryptionError(
            "A password is required to verify this archive"
        ) from error
    except (OSError, py7zr.exceptions.ArchiveError) as error:
        raise CorruptedArchiveError(f"Archive is corrupted: {path}") from error
    if bad is not None:
        raise CorruptedArchiveError(f"Archive is corrupted: {path} ({bad})")


def _verify_rar(path: Path, password: str | None) -> None:
    """Validate member names and CRC-check every payload in a RAR archive."""
    try:
        with rarfile.RarFile(path) as archive:
            if archive.needs_password() and not password:
                raise EncryptionError("A password is required to verify this archive")
            if password is not None:
                archive.setpassword(password)
            for info in archive.infolist():
                safe_target(Path("."), info.filename)
            archive.testrar()
    except EncryptionError:
        raise
    except rarfile.RarCannotExec as error:
        raise UnsupportedFormatError(
            "RAR verification requires the 'unrar' or 'unar' tool to be installed"
        ) from error
    except (rarfile.PasswordRequired, rarfile.RarWrongPassword) as error:
        raise EncryptionError(
            "A password is required to verify this archive"
        ) from error
    except (OSError, rarfile.Error) as error:
        raise CorruptedArchiveError(f"Archive is corrupted: {path}") from error


def verify_archive(path: Path, password: str | None = None) -> CompressionAlgorithm:
    """Read every archive payload and raise when it is malformed or unsafe."""
    algorithm = detect_algorithm(path)
    if algorithm is CompressionAlgorithm.SEVENZ:
        _verify_7z(path, password)
        return algorithm
    if algorithm is CompressionAlgorithm.RAR:
        _verify_rar(path, password)
        return algorithm
    try:
        if algorithm is CompressionAlgorithm.ZIP:
            with pyzipper.AESZipFile(path) as archive:
                if password is not None:
                    archive.setpassword(password.encode("utf-8"))
                for info in archive.infolist():
                    safe_target(Path("."), info.filename)
                    if not info.is_dir():
                        with archive.open(info) as stream:
                            _digest(stream)
        elif algorithm is CompressionAlgorithm.ZSTD and _zstd_contains_tar(path):
            with (
                zstandard.open(path, "rb") as decompressed,
                tarfile.open(fileobj=decompressed, mode="r|") as archive,
            ):
                _verify_tar_members(archive)
        elif tarfile.is_tarfile(path):
            with tarfile.open(path, "r:*") as archive:
                _verify_tar_members(archive)
        else:
            with _stream_opener(algorithm)(path, "rb") as stream:
                _digest(stream)
    except RuntimeError as error:
        message = str(error).lower()
        if "password" in message or "encrypt" in message:
            raise EncryptionError(
                "A valid password is required to verify this archive"
            ) from error
        raise CorruptedArchiveError(f"Archive is corrupted: {path}") from error
    except (
        OSError,
        EOFError,
        lzma.LZMAError,
        tarfile.TarError,
        zipfile.BadZipFile,
        pyzipper.BadZipFile,
        zstandard.ZstdError,
    ) as error:
        raise CorruptedArchiveError(f"Archive is corrupted: {path}") from error
    return algorithm


def _expected_entries(
    sources: tuple[Path, ...], exclude: tuple[str, ...] = ()
) -> dict[str, Path]:
    """Map expected archive member names to source filesystem paths."""
    entries: dict[str, Path] = {}
    for source in sources:
        patterns = (*exclude, *load_ignore_patterns(source))
        for path in iter_files(source):
            if source.is_dir():
                rel = path.relative_to(source).as_posix()
                name = path.relative_to(source.parent).as_posix()
            else:
                rel = source.name
                name = source.name
            if is_excluded(rel, patterns):
                continue
            entries[name] = path
    return entries


def verify_against_source(
    source: Path | tuple[Path, ...],
    archive_path: Path,
    password: str | None = None,
    exclude: tuple[str, ...] = (),
) -> None:
    """Verify archive payload bytes and names against their original sources."""
    sources = (source,) if isinstance(source, Path) else tuple(source)
    algorithm = verify_archive(archive_path, password=password)
    try:
        if algorithm is CompressionAlgorithm.ZIP:
            _verify_zip_source(sources, archive_path, password, exclude)
        elif algorithm is CompressionAlgorithm.SEVENZ:
            _verify_7z_source(sources, archive_path, password, exclude)
        elif algorithm is CompressionAlgorithm.ZSTD and _zstd_contains_tar(
            archive_path
        ):
            _verify_zstd_tar_source(sources, archive_path, exclude)
        elif len(sources) > 1 or sources[0].is_dir():
            _verify_tar_source(sources, archive_path, exclude)
        else:
            with (
                sources[0].open("rb") as original,
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
        pyzipper.BadZipFile,
        zstandard.ZstdError,
    ) as error:
        raise CorruptedArchiveError(f"Archive is corrupted: {archive_path}") from error


def _verify_zip_source(
    sources: tuple[Path, ...],
    archive_path: Path,
    password: str | None = None,
    exclude: tuple[str, ...] = (),
) -> None:
    """Compare ZIP file entries with source files."""
    expected = _expected_entries(sources, exclude)
    with pyzipper.AESZipFile(archive_path) as archive:
        if password is not None:
            archive.setpassword(password.encode("utf-8"))
        actual = {
            info.filename: info for info in archive.infolist() if not info.is_dir()
        }
        if set(actual) != set(expected):
            raise IntegrityError("ZIP entries differ from source")
        for name, path in expected.items():
            with path.open("rb") as original, archive.open(actual[name]) as compressed:
                if _digest(original) != _digest(compressed):
                    raise IntegrityError(f"ZIP entry differs from source: {name}")


def _verify_7z_source(
    sources: tuple[Path, ...],
    archive_path: Path,
    password: str | None,
    exclude: tuple[str, ...] = (),
) -> None:
    """Compare 7z archive entries with source files via a temp extraction."""
    expected = _expected_entries(sources, exclude)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            with py7zr.SevenZipFile(archive_path, "r", password=password) as archive:
                archive.extractall(path=temp_dir)
            actual = {
                path.relative_to(temp_dir).as_posix(): path
                for path in iter_files(Path(temp_dir))
            }
            if set(actual) != set(expected):
                raise IntegrityError("7z entries differ from source")
            for name, path in expected.items():
                with (
                    path.open("rb") as original,
                    actual[name].open("rb") as extracted,
                ):
                    if _digest(original) != _digest(extracted):
                        raise IntegrityError(f"7z entry differs from source: {name}")
    except IntegrityError:
        raise
    except (OSError, py7zr.exceptions.ArchiveError) as error:
        raise CorruptedArchiveError(f"Archive is corrupted: {archive_path}") from error


def _verify_zstd_tar_source(
    sources: tuple[Path, ...],
    archive_path: Path,
    exclude: tuple[str, ...] = (),
) -> None:
    """Compare a Zstandard-compressed tar stream with source files."""
    expected = _expected_entries(sources, exclude)
    actual: dict[str, bytes] = {}
    with (
        zstandard.open(archive_path, "rb") as decompressed,
        tarfile.open(fileobj=decompressed, mode="r|") as archive,
    ):
        for member in archive:
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is not None:
                    with stream:
                        actual[member.name] = _digest(stream)
    if set(actual) != set(expected):
        raise IntegrityError("Tar entries differ from source")
    for name, path in expected.items():
        with path.open("rb") as original:
            if _digest(original) != actual[name]:
                raise IntegrityError(f"Tar entry differs from source: {name}")


def _verify_tar_source(
    sources: tuple[Path, ...],
    archive_path: Path,
    exclude: tuple[str, ...] = (),
) -> None:
    """Compare tar archive file entries with source files."""
    expected = _expected_entries(sources, exclude)
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
