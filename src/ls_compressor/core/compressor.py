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
import pyzipper
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
    is_excluded,
    load_ignore_patterns,
    prepare_destination,
    raise_filesystem_error,
    replace_path,
    safe_target,
    source_size,
)
from ls_compressor.core.models import (
    CompressionPlan,
    CompressionRequest,
    DecompressionRequest,
    EncryptionFormat,
    OperationKind,
    OperationResult,
    PlanMember,
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
from ls_compressor.core.volumes import is_volume, join_volumes, split_archive


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


def _validate_compression_request(request: CompressionRequest) -> None:
    """Raise when a compression request cannot be carried out."""
    encrypted_7z = (
        request.password is not None
        and request.encryption_format is EncryptionFormat.SEVENZ
    )
    if not request.algorithm.can_compress and not encrypted_7z:
        raise UnsupportedFormatError(
            f"{request.algorithm.display_name} archives are extraction-only"
        )
    if (
        request.self_extracting
        and request.encryption_format is not EncryptionFormat.LSE
    ):
        raise InvalidRequestError(
            "Self-extracting archives require the LS container format"
        )
    if request.split_size is not None:
        if request.self_extracting:
            raise InvalidRequestError(
                "Self-extracting archives cannot be split into volumes"
            )
        if request.split_size < 1:
            raise InvalidRequestError("Split size must be at least 1 byte")
    sources = request.all_sources
    for source in sources:
        ensure_source(source)
    destination_path = request.destination.resolve()
    for source in sources:
        source_path = source.resolve()
        if source_path == destination_path:
            raise InvalidRequestError("Source and destination must differ")
        if source.is_dir() and destination_path.is_relative_to(source_path):
            raise InvalidRequestError(
                "Destination cannot be inside the source directory"
            )
    if len(sources) > 1:
        names = [source.name for source in sources]
        if len(set(names)) != len(names):
            raise InvalidRequestError(
                "Sources must have unique names to share one archive"
            )


def plan_compression(request: CompressionRequest) -> CompressionPlan:
    """Describe the members a request would archive without writing output."""
    _validate_compression_request(request)
    members = [
        PlanMember(
            name=name,
            size=path.stat().st_size if path.is_file() else 0,
            is_dir=path.is_dir(),
        )
        for _, path, name in _iter_source_members(request)
    ]
    if not any(not member.is_dir for member in members):
        raise InvalidRequestError("All sources were excluded by ignore patterns")
    total = sum(member.size for member in members)
    split_volumes = 0
    if request.split_size is not None:
        split_volumes = max(1, -(-total // request.split_size))
    return CompressionPlan(
        destination=request.destination,
        algorithm=request.algorithm,
        members=tuple(members),
        total_bytes=total,
        destination_exists=request.destination.exists(),
        split_volumes=split_volumes,
    )


def compress(
    request: CompressionRequest, callback: ProgressCallback | None = None
) -> OperationResult:
    """Compress a file or directory and verify integrity before success."""
    started = time.monotonic()
    _validate_compression_request(request)
    sources = request.all_sources
    prepare_destination(request.destination, overwrite=request.overwrite)
    members = [
        (path, name)
        for _, path, name in _iter_source_members(request)
        if path.is_file()
    ]
    if not members:
        raise InvalidRequestError("All sources were excluded by ignore patterns")
    total = sum(path.stat().st_size for path, _ in members)
    files = [path for path, _ in members]
    temporary = _temporary_path(request.destination)
    progress = ProgressReporter(OperationKind.COMPRESS, total, callback)

    def update(count: int, current: Path | None) -> None:
        progress.advance(count, current)

    try:
        if request.password and request.encryption_format is EncryptionFormat.SEVENZ:
            _compress_7z_encrypted(request, temporary, update)
        elif request.password and request.encryption_format is EncryptionFormat.ZIP_AES:
            _compress_zip_aes(request, temporary, update)
        else:
            if request.algorithm is CompressionAlgorithm.ZIP:
                _compress_zip(request, temporary, update)
            elif len(sources) > 1 or request.source.is_dir():
                _compress_tar(request, temporary, update)
            else:
                _compress_stream(request, temporary, update)
        if request.verify:
            verify_against_source(
                sources,
                temporary,
                password=request.password,
                exclude=request.exclude,
            )
        if request.password and request.encryption_format is EncryptionFormat.LSE:
            temporary = _wrap_encrypted_output(request, temporary)
        if request.split_size is not None:
            parts = split_archive(
                temporary,
                request.destination,
                request.split_size,
                overwrite=request.overwrite,
            )
            output_size = sum(part.stat().st_size for part in parts)
        else:
            replace_path(temporary, request.destination, overwrite=request.overwrite)
            output_size = request.destination.stat().st_size
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
        output_size,
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


def _member_name(source: Path, path: Path) -> str:
    """Return the archive member name for a path within one source."""
    if source.is_dir():
        return path.relative_to(source.parent).as_posix()
    return source.name


def _iter_source_members(request: CompressionRequest):
    """Yield (source, path, member_name) for every member, honoring ignores."""
    for source in request.all_sources:
        patterns = (*request.exclude, *load_ignore_patterns(source))
        if not source.is_dir():
            if not is_excluded(source.name, patterns):
                yield source, source, source.name
            continue
        for path in [source, *sorted(source.rglob("*"))]:
            if path.is_symlink():
                continue
            rel = path.relative_to(source).as_posix()
            if rel != "." and is_excluded(rel, patterns):
                continue
            yield source, path, _member_name(source, path)


def _compress_zip(
    request: CompressionRequest, temporary: Path, update: Callable[[int, Path], None]
) -> None:
    """Create a deflated ZIP archive with chunked writes."""
    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, **_compression_kwargs(request)
    ) as archive:
        for _, path, name in _iter_source_members(request):
            if path.is_dir():
                info = zipfile.ZipInfo(name + "/")
                info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
                archive.writestr(info, b"")
                continue
            info = zipfile.ZipInfo.from_file(path, name)
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as src, archive.open(info, "w") as destination:
                while chunk := src.read(CHUNK_SIZE):
                    destination.write(chunk)
                    update(len(chunk), path)


def _compress_zip_aes(
    request: CompressionRequest, temporary: Path, update: Callable[[int, Path], None]
) -> None:
    """Create a WinZip-compatible AES-256 encrypted ZIP archive."""
    with pyzipper.AESZipFile(
        temporary,
        "w",
        compression=pyzipper.ZIP_DEFLATED,
        encryption=pyzipper.WZ_AES,
    ) as archive:
        archive.setpassword(request.password.encode("utf-8"))
        for _, path, name in _iter_source_members(request):
            if path.is_dir():
                archive.write(path, name + "/")
            else:
                archive.write(path, name)
                update(path.stat().st_size, path)


def _compress_7z_encrypted(
    request: CompressionRequest, temporary: Path, update: Callable[[int, Path], None]
) -> None:
    """Create a 7-Zip AES-256 encrypted archive with an encrypted header."""
    with py7zr.SevenZipFile(
        temporary, "w", password=request.password, header_encryption=True
    ) as archive:
        for _, path, name in _iter_source_members(request):
            archive.write(path, name)
            if path.is_file():
                update(path.stat().st_size, path)


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
    """Add every source tree to an open tar archive."""
    for _, path, name in _iter_source_members(request):
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
    with tempfile.TemporaryDirectory(
        prefix=f".{request.destination.name}.", dir=request.destination.parent
    ) as work_dir:
        return _decompress(request, Path(work_dir), callback, started)


def _decompress(
    request: DecompressionRequest,
    work_dir: Path,
    callback: ProgressCallback | None,
    started: float,
) -> OperationResult:
    """Run the extraction after resolving any joined volume input."""
    archive_path, archive_size = _archive_source(request, work_dir)
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
            files_processed = _extract_zip(
                archive_path, temporary, update, request.password
            )
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
        pyzipper.BadZipFile,
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
    source: Path,
    destination: Path,
    update: Callable[[int, Path], None],
    password: str | None = None,
) -> int:
    """Extract ZIP entries with traversal checks and preserved permissions."""
    count = 0
    try:
        with pyzipper.AESZipFile(source) as archive:
            if password is not None:
                archive.setpassword(password.encode("utf-8"))
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
    except RuntimeError as error:
        message = str(error).lower()
        if "password" in message or "encrypt" in message:
            raise EncryptionError(
                "A valid password is required to extract this archive"
            ) from error
        raise CorruptedArchiveError(f"Archive is corrupted: {source}") from error
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


def _uses_container(request: CompressionRequest) -> bool:
    """Return True when the archive holds multiple members (tar/ZIP/7z)."""
    return len(request.all_sources) > 1 or request.source.is_dir()


def _wrap_encrypted_output(request: CompressionRequest, archive_path: Path) -> Path:
    """Turn an unencrypted archive into an encrypted or self-extracting output."""
    if not request.self_extracting:
        encrypted = _temporary_path(request.destination)
        encrypt_archive(
            archive_path,
            encrypted,
            request.password,
            algorithm=request.algorithm,
            is_directory=_uses_container(request),
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
            is_directory=_uses_container(request),
        )
        archive_path.unlink()
        return bundle
    launcher = _temporary_path(request.destination)
    create_self_extracting_archive(
        archive_path,
        launcher,
        request.password,
        algorithm=request.algorithm,
        is_directory=_uses_container(request),
    )
    archive_path.unlink()
    return launcher


def _archive_source(request: DecompressionRequest, work_dir: Path) -> tuple[Path, int]:
    """Resolve the real archive path and size, decrypting encrypted inputs first."""
    source = request.source
    if is_volume(source):
        source = join_volumes(source, work_dir)
    if is_encrypted_file(source):
        if not request.password:
            raise EncryptionError("A password is required to decrypt this archive")
        archive_path = work_dir / "decrypted"
        decrypt_archive(source, archive_path, request.password)
        return archive_path, request.source.stat().st_size
    if is_self_extracting_archive(source):
        if not request.password:
            raise EncryptionError("A password is required to decrypt this archive")
        payload = extract_payload(source)
        encrypted = work_dir / "payload.lse"
        encrypted.write_bytes(payload)
        archive_path = work_dir / "decrypted"
        decrypt_archive(encrypted, archive_path, request.password)
        return archive_path, request.source.stat().st_size
    return source, request.source.stat().st_size
