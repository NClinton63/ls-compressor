"""Archive content listing without extraction."""

import tarfile
import tempfile
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import py7zr
import pyzipper
import rarfile
import zstandard

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.encryption import (
    decrypt_archive,
    extract_payload,
    is_encrypted_file,
    is_self_extracting_archive,
)
from ls_compressor.core.exceptions import (
    CorruptedArchiveError,
    EncryptionError,
    UnsupportedFormatError,
)
from ls_compressor.core.verification import (
    _zstd_contains_tar,
    detect_algorithm,
)
from ls_compressor.core.volumes import is_volume, join_volumes


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    """Describe a single member inside an archive."""

    name: str
    uncompressed_size: int | None
    compressed_size: int | None
    is_dir: bool


def _list_zip(path: Path, password: str | None) -> list[ArchiveEntry]:
    """List ZIP member names and sizes, honoring AES encryption."""
    try:
        with pyzipper.AESZipFile(path) as archive:
            if password is not None:
                archive.setpassword(password.encode("utf-8"))
            return [
                ArchiveEntry(
                    name=info.filename,
                    uncompressed_size=info.file_size,
                    compressed_size=info.compress_size,
                    is_dir=info.is_dir(),
                )
                for info in archive.infolist()
            ]
    except RuntimeError as error:
        message = str(error).lower()
        if "password" in message or "encrypt" in message:
            raise EncryptionError(
                "A valid password is required to list this archive"
            ) from error
        raise CorruptedArchiveError(f"Archive is corrupted: {path}") from error


def _list_tar(archive: tarfile.TarFile) -> list[ArchiveEntry]:
    """Collect member metadata from an open tar archive."""
    return [
        ArchiveEntry(
            name=member.name,
            uncompressed_size=member.size if member.isfile() else 0,
            compressed_size=None,
            is_dir=member.isdir(),
        )
        for member in archive
    ]


def _list_7z(path: Path, password: str | None) -> list[ArchiveEntry]:
    """List 7z member names and sizes."""
    try:
        with py7zr.SevenZipFile(path, "r", password=password) as archive:
            if archive.needs_password() and not password:
                raise EncryptionError("A password is required to list this archive")
            return [
                ArchiveEntry(
                    name=info.filename,
                    uncompressed_size=info.uncompressed,
                    compressed_size=info.compressed,
                    is_dir=info.is_directory,
                )
                for info in archive.list()
            ]
    except EncryptionError:
        raise
    except py7zr.PasswordRequired as error:
        raise EncryptionError("A password is required to list this archive") from error


def _list_rar(path: Path, password: str | None) -> list[ArchiveEntry]:
    """List RAR member names and sizes."""
    try:
        with rarfile.RarFile(path) as archive:
            if archive.needs_password() and not password:
                raise EncryptionError("A password is required to list this archive")
            if password is not None:
                archive.setpassword(password)
            return [
                ArchiveEntry(
                    name=info.filename,
                    uncompressed_size=info.file_size,
                    compressed_size=info.compress_size,
                    is_dir=info.is_dir(),
                )
                for info in archive.infolist()
            ]
    except EncryptionError:
        raise
    except rarfile.RarCannotExec as error:
        raise UnsupportedFormatError(
            "RAR listing requires the 'unrar' or 'unar' tool to be installed"
        ) from error
    except (rarfile.PasswordRequired, rarfile.RarWrongPassword) as error:
        raise EncryptionError("A password is required to list this archive") from error


def _list_container(path: Path) -> list[ArchiveEntry]:
    """List members of a tar or Zstandard-tar container."""
    with ExitStack() as stack:
        with path.open("rb") as probe:
            signature = probe.read(4)
        if signature.startswith(b"\x28\xb5\x2f\xfd"):
            raw = stack.enter_context(path.open("rb"))
            decompressed = stack.enter_context(
                zstandard.ZstdDecompressor().stream_reader(raw)
            )
            archive = stack.enter_context(tarfile.open(fileobj=decompressed, mode="r|"))
        else:
            archive = stack.enter_context(tarfile.open(path, "r:*"))
        return _list_tar(archive)


def list_archive(
    path: Path | str,
    password: str | None = None,
) -> tuple[CompressionAlgorithm, list[ArchiveEntry]]:
    """Return the detected format and member listing of an archive.

    Encrypted (``.lsenc``) and self-extracting inputs are transparently
    decrypted to a temporary file when ``password`` is supplied.
    """
    path = Path(path)
    if is_volume(path):
        with tempfile.TemporaryDirectory() as temp_dir:
            joined = join_volumes(path, Path(temp_dir))
            return list_archive(joined, password=password)
    if is_encrypted_file(path) or is_self_extracting_archive(path):
        if not password:
            raise EncryptionError("A password is required to list this archive")
        with tempfile.TemporaryDirectory() as temp_dir:
            encrypted = path
            if is_self_extracting_archive(path):
                payload = Path(temp_dir) / "payload.lse"
                payload.write_bytes(extract_payload(path))
                encrypted = payload
            archive = Path(temp_dir) / "archive"
            decrypt_archive(encrypted, archive, password)
            return _list_plain(archive, password)
    return _list_plain(path, password)


def _list_plain(
    path: Path, password: str | None
) -> tuple[CompressionAlgorithm, list[ArchiveEntry]]:
    """List members of an unencrypted archive file."""
    algorithm = detect_algorithm(path)
    if algorithm is CompressionAlgorithm.ZIP:
        return algorithm, _list_zip(path, password)
    if algorithm is CompressionAlgorithm.SEVENZ:
        return algorithm, _list_7z(path, password)
    if algorithm is CompressionAlgorithm.RAR:
        return algorithm, _list_rar(path, password)
    is_container = tarfile.is_tarfile(path) or (
        algorithm is CompressionAlgorithm.ZSTD and _zstd_contains_tar(path)
    )
    if is_container:
        return algorithm, _list_container(path)
    return algorithm, [
        ArchiveEntry(
            name=path.name,
            uncompressed_size=None,
            compressed_size=path.stat().st_size,
            is_dir=False,
        )
    ]


def format_listing(
    entries: list[ArchiveEntry],
    *,
    human_size: Callable[[int | None], str] | None = None,
) -> str:
    """Render archive entries as an aligned text table."""
    if human_size is None:

        def human_size(size: int | None) -> str:
            return "-" if size is None else str(size)

    lines = []
    for entry in entries:
        kind = "dir " if entry.is_dir else "file"
        lines.append(
            f"{kind} {human_size(entry.uncompressed_size):>12} "
            f"{human_size(entry.compressed_size):>12}  {entry.name}"
        )
    return "\n".join(lines)
