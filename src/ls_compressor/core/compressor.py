"""Synchronous lossless compression and decompression services."""

import bz2
import gzip
import lzma
import os
import sys
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

import py7zr
import rarfile
import zstandard

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.encryption import (
    create_self_extracting_archive,
    decrypt_archive,
    encrypt_archive,
    extract_payload,
    is_encrypted_file,
    is_self_extracting_archive,
)
from ls_compressor.core.exceptions import (
    CompressionError,
    CorruptedArchiveError,
    EncryptionError,
    InvalidRequestError,
    UnsupportedFormatError,
)
from ls_compressor.core.filesystem import (
    CHUNK_SIZE,
    apply_mode,
    clear_destination,
    ensure_source,
    iter_files,
    prepare_destination,
    raise_filesystem_error,
    replace_path,
    safe_target,
    source_size,
)
from ls_compressor.core.models import (
    CompressionRequest,
    DecompressionRequest,
    OperationKind,
    OperationResult,
)
from ls_compressor.core.progress import (
    ProgressCallback,
    ProgressReader,
    ProgressReporter,
)
from ls_compressor.core.verification import (
    detect_algorithm,
    verify_against_source,
    verify_archive,
)


def _zstd_open(path: Path, mode: str, level: int | None = None):
    """Open a Zstandard stream, applying a compression level for writes."""
    if "r" in mode:
        return zstandard.open(path, mode)
    compressor = zstandard.ZstdCompressor(level=level if level is not None else 3)
    return zstandard.open(path, mode, cctx=compressor)


def _stream_opener(algorithm: CompressionAlgorithm):
    """Return the compressed stream opener for an algorithm."""
    return {
        CompressionAlgorithm.ZSTD: _zstd_open,
        CompressionAlgorithm.XZ: lzma.open,
        CompressionAlgorithm.GZIP: gzip.open,
        CompressionAlgorithm.BZ2: bz2.open,
    }[algorithm]


def compress(
    request: CompressionRequest, callback: ProgressCallback | None = None
) -> OperationResult:
    """Compress a file or directory and verify integrity before success."""
    started = time.monotonic()
    if not request.algorithm.can_compress:
        raise UnsupportedFormatError(
            f"{request.algorithm.display_name} archives are extraction-only"
        )
    ensure_source(request.source)
    source_path = request.source.resolve()
    destination_path = request.destination.resolve()
    if source_path == destination_path:
        raise InvalidRequestError("Source and destination must differ")
    if request.source.is_dir() and destination_path.is_relative_to(source_path):
        raise InvalidRequestError("Destination cannot be inside the source directory")
    prepare_destination(request.destination, overwrite=request.overwrite)
    total = source_size(request.source)
    files = list(iter_files(request.source))
    temporary = _temporary_path(request.destination)
    progress = ProgressReporter(OperationKind.COMPRESS, total, callback)

    def update(count: int, current: Path | None) -> None:
        progress.advance(count, current)

    try:
        if request.algorithm is CompressionAlgorithm.ZIP:
            _compress_zip(request, temporary, update)
        elif request.source.is_dir():
            _compress_tar(request, temporary, update)
        else:
            _compress_stream(request, temporary, update)
        if request.verify:
            verify_against_source(request.source, temporary)
        if request.password:
            temporary = _wrap_encrypted_output(request, temporary)
        replace_path(temporary, request.destination, overwrite=request.overwrite)
        progress.complete()
    except CompressionError:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise_filesystem_error(error, request.destination)
    return OperationResult(
        OperationKind.COMPRESS,
        request.source,
        request.destination,
        request.algorithm,
        total,
        request.destination.stat().st_size,
        time.monotonic() - started,
        len(files),
        request.verify,
    )


def _temporary_path(destination: Path) -> Path:
    """Reserve a temporary output path beside its destination."""
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    os.close(descriptor)
    return Path(name)


def _compression_kwargs(request: CompressionRequest) -> dict[str, int]:
    """Build algorithm-specific compression level arguments."""
    if request.compression_level is None:
        return {}
    minimum = (
        0
        if request.algorithm
        in {
            CompressionAlgorithm.ZSTD,
            CompressionAlgorithm.ZIP,
            CompressionAlgorithm.XZ,
        }
        else 1
    )
    if not minimum <= request.compression_level <= 9:
        raise InvalidRequestError(
            f"{request.algorithm.display_name} compression level must be between "
            f"{minimum} and 9"
        )
    if request.algorithm is CompressionAlgorithm.ZSTD:
        return {"level": request.compression_level}
    key = "preset" if request.algorithm is CompressionAlgorithm.XZ else "compresslevel"
    return {key: request.compression_level}


def _compress_zip(
    request: CompressionRequest, temporary: Path, update: Callable[[int, Path], None]
) -> None:
    """Create a deflated ZIP archive with chunked writes."""
    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, **_compression_kwargs(request)
    ) as archive:
        if request.source.is_dir():
            for directory in [request.source, *sorted(request.source.rglob("*"))]:
                if directory.is_dir():
                    name = directory.relative_to(request.source.parent).as_posix() + "/"
                    info = zipfile.ZipInfo(name)
                    info.external_attr = (directory.stat().st_mode & 0xFFFF) << 16
                    archive.writestr(info, b"")
        for path in iter_files(request.source):
            name = (
                path.relative_to(request.source.parent).as_posix()
                if request.source.is_dir()
                else path.name
            )
            info = zipfile.ZipInfo.from_file(path, name)
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as source, archive.open(info, "w") as destination:
                while chunk := source.read(CHUNK_SIZE):
                    destination.write(chunk)
                    update(len(chunk), path)


def _compress_tar(
    request: CompressionRequest, temporary: Path, update: Callable[[int, Path], None]
) -> None:
    """Create a compressed tar archive while reporting file-byte progress."""
    kwargs = _compression_kwargs(request)
    if request.algorithm is CompressionAlgorithm.ZSTD:
        level = kwargs.get("level", 3)
        compressor = zstandard.ZstdCompressor(level=level)
        with (
            temporary.open("wb") as stream,
            compressor.stream_writer(stream) as compressed,
            tarfile.open(fileobj=compressed, mode="w|") as archive,
        ):
            _add_tar_members(request, archive, update)
        return
    mode = {
        CompressionAlgorithm.XZ: "w:xz",
        CompressionAlgorithm.GZIP: "w:gz",
        CompressionAlgorithm.BZ2: "w:bz2",
    }[request.algorithm]
    with tarfile.open(temporary, mode, **kwargs) as archive:
        _add_tar_members(request, archive, update)


def _add_tar_members(
    request: CompressionRequest,
    archive: tarfile.TarFile,
    update: Callable[[int, Path], None],
) -> None:
    """Add a source directory tree to an open tar archive."""
    for path in [request.source, *sorted(request.source.rglob("*"))]:
        if path.is_symlink():
            continue
        name = path.relative_to(request.source.parent).as_posix()
        info = archive.gettarinfo(str(path), name)
        if path.is_file():
            with path.open("rb") as stream:
                reader = ProgressReader(
                    stream, lambda count, item=path: update(count, item)
                )
                archive.addfile(info, reader)
        else:
            archive.addfile(info)


def _compress_stream(
    request: CompressionRequest, temporary: Path, update: Callable[[int, Path], None]
) -> None:
    """Compress one file as an XZ, GZIP, or BZ2 stream."""
    kwargs = _compression_kwargs(request)
    with (
        request.source.open("rb") as source,
        _stream_opener(request.algorithm)(temporary, "wb", **kwargs) as destination,
    ):
        while chunk := source.read(CHUNK_SIZE):
            destination.write(chunk)
            update(len(chunk), request.source)


def decompress(
    request: DecompressionRequest, callback: ProgressCallback | None = None
) -> OperationResult:
    """Safely extract an archive and optionally verify it before extraction."""
    started = time.monotonic()
    ensure_source(request.source)
    prepare_destination(request.destination, overwrite=request.overwrite)
    archive_path, archive_size = _archive_source(request)
    algorithm = (
        verify_archive(archive_path, password=request.password)
        if request.verify
        else detect_algorithm(archive_path)
    )
    is_container = (
        algorithm is CompressionAlgorithm.ZIP
        or tarfile.is_tarfile(archive_path)
        or (algorithm is CompressionAlgorithm.ZSTD and _zstd_contains_tar(archive_path))
    )
    is_container = is_container or algorithm in {
        CompressionAlgorithm.SEVENZ,
        CompressionAlgorithm.RAR,
    }
    temporary = (
        _temporary_directory(request.destination)
        if is_container
        else _temporary_path(request.destination)
    )
    progress = ProgressReporter(OperationKind.DECOMPRESS, archive_size, callback)
    files_processed = 0

    def update(count: int, current: Path | None) -> None:
        progress.advance(count, current)

    try:
        if algorithm is CompressionAlgorithm.ZIP:
            files_processed = _extract_zip(archive_path, temporary, update)
        elif algorithm is CompressionAlgorithm.SEVENZ:
            files_processed = _extract_7z(
                archive_path, temporary, update, request.password
            )
        elif algorithm is CompressionAlgorithm.RAR:
            files_processed = _extract_rar(
                archive_path, temporary, update, request.password
            )
        elif is_container:
            files_processed = _extract_tar(archive_path, temporary, update)
        else:
            _extract_stream(archive_path, temporary, algorithm, update)
            files_processed = 1
        output_size = source_size(temporary)
        replace_path(temporary, request.destination, overwrite=request.overwrite)
        progress.complete()
    except CompressionError:
        clear_destination(temporary)
        raise
    except (
        OSError,
        EOFError,
        lzma.LZMAError,
        tarfile.TarError,
        zipfile.BadZipFile,
        zstandard.ZstdError,
        rarfile.Error,
    ) as error:
        clear_destination(temporary)
        raise_filesystem_error(error, request.destination)
    return OperationResult(
        OperationKind.DECOMPRESS,
        request.source,
        request.destination,
        algorithm,
        archive_size,
        output_size,
        time.monotonic() - started,
        files_processed,
        request.verify,
    )


def _temporary_directory(destination: Path) -> Path:
    """Create a temporary extraction directory beside its destination."""
    return Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )


def _extract_zip(
    source: Path, destination: Path, update: Callable[[int, Path], None]
) -> int:
    """Extract ZIP entries with traversal checks and preserved permissions."""
    count = 0
    with zipfile.ZipFile(source) as archive:
        for info in archive.infolist():
            target = safe_target(destination, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                apply_mode(target, info.external_attr >> 16)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as compressed, target.open("wb") as output:
                while chunk := compressed.read(CHUNK_SIZE):
                    output.write(chunk)
                    update(len(chunk), target)
            apply_mode(target, info.external_attr >> 16)
            count += 1
    return count


def _zstd_contains_tar(path: Path) -> bool:
    """Return True when a Zstandard stream decompresses to a tar archive."""
    try:
        with zstandard.open(path, "rb") as stream:
            head = stream.read(512)
    except OSError:
        return False
    return len(head) > 262 and head[257:262] == b"ustar"


def _extract_tar(
    source: Path, destination: Path, update: Callable[[int, Path], None]
) -> int:
    """Extract regular tar entries with traversal and link checks."""
    count = 0
    with ExitStack() as stack:
        with source.open("rb") as probe:
            signature = probe.read(4)
        if signature.startswith(b"\x28\xb5\x2f\xfd"):
            raw = stack.enter_context(source.open("rb"))
            decompressed = stack.enter_context(
                zstandard.ZstdDecompressor().stream_reader(raw)
            )
            archive = stack.enter_context(tarfile.open(fileobj=decompressed, mode="r|"))
        else:
            archive = stack.enter_context(tarfile.open(source, "r:*"))
        for member in archive:
            target = safe_target(destination, member.name)
            if member.issym() or member.islnk():
                raise InvalidRequestError(
                    f"Archive links are not supported: {member.name}"
                )
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                apply_mode(target, member.mode)
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            compressed = archive.extractfile(member)
            if compressed is None:
                continue
            with compressed, target.open("wb") as output:
                while chunk := compressed.read(CHUNK_SIZE):
                    output.write(chunk)
                    update(len(chunk), target)
            apply_mode(target, member.mode)
            count += 1
    return count


def _extract_7z(
    source: Path,
    destination: Path,
    update: Callable[[int, Path], None],
    password: str | None,
) -> int:
    """Extract a 7z archive after validating every member path."""
    try:
        with py7zr.SevenZipFile(source, "r", password=password) as archive:
            if archive.needs_password() and not password:
                raise EncryptionError("A password is required to extract this archive")
            members = archive.list()
            for info in members:
                safe_target(destination, info.filename)
            archive.extractall(destination)
    except EncryptionError:
        raise
    except py7zr.PasswordRequired as error:
        raise EncryptionError(
            "A password is required to extract this archive"
        ) from error
    except (OSError, py7zr.exceptions.ArchiveError) as error:
        raise CorruptedArchiveError(f"Archive is corrupted: {source}") from error
    count = 0
    for info in members:
        if info.is_directory:
            continue
        count += 1
        update(info.uncompressed or 0, destination / info.filename)
    if not members:
        update(0, destination)
    return count


def _extract_rar(
    source: Path,
    destination: Path,
    update: Callable[[int, Path], None],
    password: str | None,
) -> int:
    """Extract a RAR archive with streaming reads and traversal checks."""
    count = 0
    try:
        with rarfile.RarFile(source) as archive:
            if archive.needs_password() and not password:
                raise EncryptionError("A password is required to extract this archive")
            for info in archive.infolist():
                target = safe_target(destination, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with (
                    archive.open(info, pwd=password) as compressed,
                    target.open("wb") as output,
                ):
                    while chunk := compressed.read(CHUNK_SIZE):
                        output.write(chunk)
                        update(len(chunk), target)
                count += 1
    except EncryptionError:
        raise
    except rarfile.RarCannotExec as error:
        raise UnsupportedFormatError(
            "RAR extraction requires the 'unrar' or 'unar' tool to be installed"
        ) from error
    except (rarfile.PasswordRequired, rarfile.RarWrongPassword) as error:
        raise EncryptionError(
            "A password is required to extract this archive"
        ) from error
    return count


def _extract_stream(
    source: Path,
    destination: Path,
    algorithm: CompressionAlgorithm,
    update: Callable[[int, Path], None],
) -> None:
    """Extract one compressed stream with bounded memory use."""
    with (
        _stream_opener(algorithm)(source, "rb") as compressed,
        destination.open("wb") as output,
    ):
        while chunk := compressed.read(CHUNK_SIZE):
            output.write(chunk)
            update(len(chunk), destination)


def _wrap_encrypted_output(request: CompressionRequest, archive_path: Path) -> Path:
    """Turn an unencrypted archive into an encrypted or self-extracting output."""
    if not request.self_extracting:
        encrypted = _temporary_path(request.destination)
        encrypt_archive(
            archive_path,
            encrypted,
            request.password,
            algorithm=request.algorithm,
            is_directory=request.source.is_dir(),
        )
        archive_path.unlink()
        return encrypted
    if sys.platform == "darwin" and request.destination.suffix.lower() == ".app":
        bundle = _temporary_directory(request.destination)
        create_self_extracting_archive(
            archive_path,
            bundle,
            request.password,
            algorithm=request.algorithm,
            is_directory=request.source.is_dir(),
        )
        archive_path.unlink()
        return bundle
    launcher = _temporary_path(request.destination)
    create_self_extracting_archive(
        archive_path,
        launcher,
        request.password,
        algorithm=request.algorithm,
        is_directory=request.source.is_dir(),
    )
    archive_path.unlink()
    return launcher


def _archive_source(request: DecompressionRequest) -> tuple[Path, int]:
    """Resolve the real archive path and size, decrypting encrypted inputs first."""
    if is_encrypted_file(request.source):
        if not request.password:
            raise EncryptionError("A password is required to decrypt this archive")
        archive_path = _temporary_path(request.destination)
        decrypt_archive(request.source, archive_path, request.password)
        return archive_path, request.source.stat().st_size
    if is_self_extracting_archive(request.source):
        if not request.password:
            raise EncryptionError("A password is required to decrypt this archive")
        payload = extract_payload(request.source)
        with tempfile.TemporaryDirectory() as temp_dir:
            encrypted = Path(temp_dir) / "payload.lse"
            encrypted.write_bytes(payload)
            archive_path = _temporary_path(request.destination)
            decrypt_archive(encrypted, archive_path, request.password)
        return archive_path, request.source.stat().st_size
    return request.source, request.source.stat().st_size
