"""Filesystem helpers for safe archive operations."""

import errno
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from ls_compressor.core.exceptions import (
    DestinationExistsError,
    FileAccessError,
    InsufficientSpaceError,
    SourceNotFoundError,
)

CHUNK_SIZE = 1024 * 1024


def iter_files(source: Path) -> Iterator[Path]:
    """Yield regular files beneath source in deterministic order."""
    if source.is_file():
        yield source
        return
    for path in sorted(source.rglob("*")):
        if path.is_file() and not path.is_symlink():
            yield path


def source_size(source: Path) -> int:
    """Return the total byte size of regular source files."""
    ensure_source(source)
    try:
        return sum(path.stat().st_size for path in iter_files(source))
    except PermissionError as error:
        raise FileAccessError(f"Cannot read source: {source}") from error


def ensure_source(source: Path) -> None:
    """Ensure source exists and is a regular file or directory."""
    if not source.exists():
        raise SourceNotFoundError(f"Source does not exist: {source}")
    if source.is_symlink() or not (source.is_file() or source.is_dir()):
        raise FileAccessError(f"Unsupported source type: {source}")


def prepare_destination(destination: Path, *, overwrite: bool) -> None:
    """Validate a destination and create its parent directory."""
    if destination.exists() and not overwrite:
        raise DestinationExistsError(f"Destination exists: {destination}")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise_filesystem_error(error, destination)


def clear_destination(destination: Path) -> None:
    """Remove an existing destination file or directory."""
    if not destination.exists() and not destination.is_symlink():
        return
    try:
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    except OSError as error:
        raise_filesystem_error(error, destination)


def safe_target(root: Path, member_name: str) -> Path:
    """Resolve an archive member beneath root or reject path traversal."""
    target = root.joinpath(member_name)
    try:
        target.resolve().relative_to(root.resolve())
    except (OSError, ValueError) as error:
        raise FileAccessError(f"Unsafe archive member: {member_name}") from error
    return target


def copy_chunks(
    source: BinaryIO, destination: BinaryIO, chunk_size: int = CHUNK_SIZE
) -> int:
    """Copy binary file objects in bounded chunks and return bytes copied."""
    copied = 0
    while True:
        chunk = source.read(chunk_size)
        if not chunk:
            return copied
        destination.write(chunk)
        copied += len(chunk)


def apply_mode(path: Path, mode: int) -> None:
    """Apply portable permission bits to a path where supported."""
    try:
        path.chmod(mode & 0o7777)
    except (OSError, NotImplementedError):
        return


def raise_filesystem_error(error: OSError, path: Path) -> None:
    """Raise a domain exception corresponding to a filesystem error."""
    if error.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)}:
        raise InsufficientSpaceError(f"Insufficient space for: {path}") from error
    if isinstance(error, PermissionError) or error.errno in {errno.EACCES, errno.EPERM}:
        raise FileAccessError(f"Cannot access: {path}") from error
    raise FileAccessError(f"Filesystem operation failed for: {path}") from error


def replace_path(temporary: Path, destination: Path, *, overwrite: bool) -> None:
    """Atomically move temporary output into its final destination."""
    if destination.exists():
        if not overwrite:
            raise DestinationExistsError(f"Destination exists: {destination}")
        clear_destination(destination)
    try:
        os.replace(temporary, destination)
    except OSError as error:
        raise_filesystem_error(error, destination)
