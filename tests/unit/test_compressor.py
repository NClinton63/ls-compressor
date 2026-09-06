"""Roundtrip tests for synchronous compression services."""

import os
from pathlib import Path

import pytest

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.compressor import compress, decompress
from ls_compressor.core.exceptions import DestinationExistsError, InvalidRequestError
from ls_compressor.core.models import CompressionRequest, DecompressionRequest


@pytest.mark.parametrize("algorithm", list(CompressionAlgorithm))
def test_file_roundtrip_all_algorithms(
    tmp_path: Path, algorithm: CompressionAlgorithm
) -> None:
    """Every algorithm losslessly roundtrips a Unicode-named file."""
    source = tmp_path / "héllo.txt"
    source.write_bytes((b"lossless data" * 1000) + b"\x00")
    archive = tmp_path / f"archive{algorithm.archive_suffix(is_directory=False)}"
    restored = (
        tmp_path / "restored"
        if algorithm is not CompressionAlgorithm.ZIP
        else tmp_path / "out"
    )
    updates = []

    compressed = compress(
        CompressionRequest(source, archive, algorithm), updates.append
    )
    extracted = decompress(DecompressionRequest(archive, restored), updates.append)

    output = (
        restored / source.name if algorithm is CompressionAlgorithm.ZIP else restored
    )
    assert output.read_bytes() == source.read_bytes()
    assert compressed.files_processed == extracted.files_processed == 1
    assert compressed.integrity_verified and extracted.integrity_verified
    assert compressed.source_size == source.stat().st_size
    assert compressed.output_size == archive.stat().st_size
    assert compressed.elapsed_seconds >= 0
    assert updates
    assert updates[-1].percentage == 100.0


@pytest.mark.parametrize("algorithm", list(CompressionAlgorithm))
def test_directory_roundtrip_all_algorithms(
    tmp_path: Path, algorithm: CompressionAlgorithm
) -> None:
    """Folders retain nesting, empty files, Unicode names, and empty directories."""
    source = tmp_path / "données"
    (source / "nested" / "empty-dir").mkdir(parents=True)
    (source / "zero").touch()
    (source / "nested" / "文件.txt").write_text("content", encoding="utf-8")
    archive = tmp_path / f"folder{algorithm.archive_suffix(is_directory=True)}"
    restored = tmp_path / "restored"

    result = compress(CompressionRequest(source, archive, algorithm))
    decompressed = decompress(DecompressionRequest(archive, restored))

    root = restored / source.name
    assert (root / "zero").read_bytes() == b""
    assert (root / "nested" / "文件.txt").read_text(encoding="utf-8") == "content"
    assert (root / "nested" / "empty-dir").is_dir()
    assert result.files_processed == decompressed.files_processed == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
def test_permissions_are_preserved_where_portable(tmp_path: Path) -> None:
    """Executable permission bits survive a ZIP roundtrip."""
    source = tmp_path / "script"
    source.write_text("run", encoding="utf-8")
    source.chmod(0o751)
    archive = tmp_path / "script.zip"
    restored = tmp_path / "restored"

    compress(CompressionRequest(source, archive))
    decompress(DecompressionRequest(archive, restored))

    assert (restored / "script").stat().st_mode & 0o777 == 0o751


def test_empty_file_roundtrip(tmp_path: Path) -> None:
    """A zero-byte stream is valid and lossless."""
    source = tmp_path / "empty"
    source.touch()
    archive = tmp_path / "empty.xz"
    restored = tmp_path / "restored"

    compress(CompressionRequest(source, archive, CompressionAlgorithm.XZ))
    decompress(DecompressionRequest(archive, restored))

    assert restored.read_bytes() == b""


def test_overwrite_is_explicit(tmp_path: Path) -> None:
    """Compression protects existing output unless overwrite is requested."""
    source = tmp_path / "source"
    source.write_bytes(b"new")
    archive = tmp_path / "archive.gz"
    archive.write_bytes(b"old")

    with pytest.raises(DestinationExistsError):
        compress(CompressionRequest(source, archive, CompressionAlgorithm.GZIP))
    compress(
        CompressionRequest(source, archive, CompressionAlgorithm.GZIP, overwrite=True)
    )
    assert archive.read_bytes() != b"old"


def test_destination_cannot_be_inside_source_directory(tmp_path: Path) -> None:
    """Folder compression cannot consume its own temporary archive."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "data").write_bytes(b"data")

    with pytest.raises(InvalidRequestError, match="inside the source"):
        compress(CompressionRequest(source, source / "archive.zip"))


def test_bz2_rejects_zero_compression_level(tmp_path: Path) -> None:
    """Invalid BZ2 levels produce a user-safe domain exception."""
    source = tmp_path / "source"
    source.write_bytes(b"data")

    with pytest.raises(InvalidRequestError, match="between 1 and 9"):
        compress(
            CompressionRequest(
                source,
                tmp_path / "archive.bz2",
                CompressionAlgorithm.BZ2,
                compression_level=0,
            )
        )


def test_decompression_overwrite_replaces_destination(tmp_path: Path) -> None:
    """Explicit overwrite replaces existing extracted data."""
    source = tmp_path / "source"
    source.write_bytes(b"new")
    archive = tmp_path / "archive.bz2"
    restored = tmp_path / "restored"
    restored.write_bytes(b"old")
    compress(CompressionRequest(source, archive, CompressionAlgorithm.BZ2))

    with pytest.raises(DestinationExistsError):
        decompress(DecompressionRequest(archive, restored))
    decompress(DecompressionRequest(archive, restored, overwrite=True))

    assert restored.read_bytes() == b"new"
