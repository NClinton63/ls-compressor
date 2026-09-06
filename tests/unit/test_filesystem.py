"""Tests for filesystem archive helpers."""

import errno
from pathlib import Path

import pytest

from ls_compressor.core.exceptions import (
    DestinationExistsError,
    FileAccessError,
    InsufficientSpaceError,
    SourceNotFoundError,
)
from ls_compressor.core.filesystem import (
    iter_files,
    prepare_destination,
    raise_filesystem_error,
    safe_target,
    source_size,
)


def test_iter_files_and_size_include_nested_and_zero_byte_files(tmp_path: Path) -> None:
    """Recursive enumeration is stable and includes empty files."""
    source = tmp_path / "folder"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "é.txt").write_bytes(b"data")
    (source / "empty").touch()

    assert [path.name for path in iter_files(source)] == ["empty", "é.txt"]
    assert source_size(source) == 4


def test_missing_source_raises_domain_error(tmp_path: Path) -> None:
    """Missing sources map to the public source exception."""
    with pytest.raises(SourceNotFoundError):
        source_size(tmp_path / "missing")


def test_destination_requires_explicit_overwrite(tmp_path: Path) -> None:
    """Existing destinations are protected by default."""
    destination = tmp_path / "exists"
    destination.touch()

    with pytest.raises(DestinationExistsError):
        prepare_destination(destination, overwrite=False)


def test_safe_target_rejects_relative_and_absolute_traversal(tmp_path: Path) -> None:
    """Archive paths cannot escape the extraction root."""
    with pytest.raises(FileAccessError):
        safe_target(tmp_path, "../escape")
    with pytest.raises(FileAccessError):
        safe_target(tmp_path, "/absolute")


def test_disk_full_maps_to_domain_error(tmp_path: Path) -> None:
    """Storage exhaustion has a user-safe exception."""
    with pytest.raises(InsufficientSpaceError):
        raise_filesystem_error(OSError(errno.ENOSPC, "full"), tmp_path)
