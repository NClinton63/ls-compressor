"""Tests for archive content listing."""

from pathlib import Path

import pytest

from ls_compressor.core import (
    CompressionAlgorithm,
    CompressionRequest,
    EncryptionError,
    compress,
    list_archive,
)


def _tree(tmp_path: Path) -> Path:
    source = tmp_path / "docs"
    (source / "nested").mkdir(parents=True)
    (source / "a.txt").write_text("alpha", encoding="utf-8")
    (source / "nested" / "b.txt").write_text("beta", encoding="utf-8")
    return source


def test_list_zip_archive(tmp_path: Path) -> None:
    """ZIP entries list names, sizes, and directory markers."""
    source = _tree(tmp_path)
    archive = tmp_path / "out.zip"
    compress(CompressionRequest(source, archive, CompressionAlgorithm.ZIP))

    algorithm, entries = list_archive(archive)

    assert algorithm is CompressionAlgorithm.ZIP
    names = {entry.name for entry in entries}
    assert "docs/a.txt" in names
    assert "docs/nested/b.txt" in names
    file_entry = next(e for e in entries if e.name == "docs/a.txt")
    assert file_entry.uncompressed_size == 5
    assert not file_entry.is_dir


def test_list_tar_zst_archive(tmp_path: Path) -> None:
    """Zstandard-tar containers list their members."""
    source = _tree(tmp_path)
    archive = tmp_path / "out.tar.zst"
    compress(CompressionRequest(source, archive, CompressionAlgorithm.ZSTD))

    algorithm, entries = list_archive(archive)

    assert algorithm is CompressionAlgorithm.ZSTD
    names = {entry.name for entry in entries}
    assert "docs/a.txt" in names
    assert any(entry.is_dir for entry in entries)


def test_list_single_stream_reports_one_entry(tmp_path: Path) -> None:
    """Single-file streams expose one synthetic entry."""
    source = tmp_path / "blob.bin"
    source.write_bytes(b"data" * 100)
    archive = tmp_path / "blob.gz"
    compress(CompressionRequest(source, archive, CompressionAlgorithm.GZIP))

    algorithm, entries = list_archive(archive)

    assert algorithm is CompressionAlgorithm.GZIP
    assert len(entries) == 1
    assert entries[0].compressed_size == archive.stat().st_size


def test_list_encrypted_archive(tmp_path: Path) -> None:
    """Encrypted archives list after password-based decryption."""
    source = _tree(tmp_path)
    archive = tmp_path / "out.lsenc"
    compress(
        CompressionRequest(source, archive, CompressionAlgorithm.ZIP, password="pw")
    )

    with pytest.raises(EncryptionError):
        list_archive(archive)

    algorithm, entries = list_archive(archive, password="pw")
    assert algorithm is CompressionAlgorithm.ZIP
    assert any(e.name == "docs/a.txt" for e in entries)


def test_list_aes_7z_archive(tmp_path: Path) -> None:
    """AES-7z archives list with the password."""
    from ls_compressor.core import EncryptionFormat

    source = _tree(tmp_path)
    archive = tmp_path / "out.7z"
    compress(
        CompressionRequest(
            source,
            archive,
            CompressionAlgorithm.SEVENZ,
            password="pw",
            encryption_format=EncryptionFormat.SEVENZ,
        )
    )

    algorithm, entries = list_archive(archive, password="pw")
    assert algorithm is CompressionAlgorithm.SEVENZ
    assert any("a.txt" in e.name for e in entries)
