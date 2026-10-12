"""Roundtrip tests for synchronous compression services."""

import os
from pathlib import Path

import py7zr
import pytest

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.compressor import compress, decompress
from ls_compressor.core.exceptions import (
    DestinationExistsError,
    EncryptionError,
    InvalidRequestError,
    UnsupportedFormatError,
)
from ls_compressor.core.models import CompressionRequest, DecompressionRequest


@pytest.mark.parametrize(
    "algorithm", [a for a in CompressionAlgorithm if a.can_compress]
)
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


@pytest.mark.parametrize("threads", [None, 1, 0, 2, 8])
def test_zstd_threads_roundtrip(tmp_path: Path, threads: int | None) -> None:
    """Multi-threaded Zstandard output stays valid and lossless."""
    payload = os.urandom(256 * 1024)
    source = tmp_path / "blob.bin"
    source.write_bytes(payload)
    archive = tmp_path / "blob.zst"
    restored = tmp_path / "restored.bin"

    compress(CompressionRequest(source, archive, threads=threads))
    decompress(DecompressionRequest(archive, restored))

    assert restored.read_bytes() == payload


def test_zstd_threads_apply_to_tar_container(tmp_path: Path) -> None:
    """Directory archives also honor the worker count."""
    source_dir = tmp_path / "data"
    source_dir.mkdir()
    (source_dir / "a.bin").write_bytes(os.urandom(64 * 1024))
    (source_dir / "b.bin").write_bytes(os.urandom(64 * 1024))
    archive = tmp_path / "data.tar.zst"
    extracted = tmp_path / "out"

    compress(CompressionRequest(source_dir, archive, threads=2))
    decompress(DecompressionRequest(archive, extracted))

    assert (extracted / "data" / "a.bin").read_bytes() == (
        source_dir / "a.bin"
    ).read_bytes()
    assert (extracted / "data" / "b.bin").read_bytes() == (
        source_dir / "b.bin"
    ).read_bytes()


@pytest.mark.parametrize(
    "algorithm", [a for a in CompressionAlgorithm if a.can_compress]
)
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

    compress(CompressionRequest(source, archive, CompressionAlgorithm.ZIP))
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


def test_7z_archive_extracts_with_nesting(tmp_path: Path) -> None:
    """External 7z archives restore nested files and folders."""
    staging = tmp_path / "staging"
    (staging / "nested").mkdir(parents=True)
    (staging / "a.txt").write_text("alpha", encoding="utf-8")
    (staging / "nested" / "b.txt").write_text("beta", encoding="utf-8")
    archive = tmp_path / "external.7z"
    with py7zr.SevenZipFile(archive, "w") as bundle:
        bundle.writeall(staging, "staging")
    restored = tmp_path / "restored"

    result = decompress(DecompressionRequest(archive, restored))

    assert (restored / "staging" / "a.txt").read_text(encoding="utf-8") == "alpha"
    assert (restored / "staging" / "nested" / "b.txt").read_text() == "beta"
    assert result.files_processed == 2
    assert result.algorithm is CompressionAlgorithm.SEVENZ


def test_encrypted_7z_requires_password(tmp_path: Path) -> None:
    """Password-protected 7z archives refuse silent extraction."""
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "secret.txt").write_text("hidden", encoding="utf-8")
    archive = tmp_path / "protected.7z"
    with py7zr.SevenZipFile(archive, "w", password="s3cret") as bundle:
        bundle.writeall(staging, "staging")
    restored = tmp_path / "restored"

    with pytest.raises(EncryptionError):
        decompress(DecompressionRequest(archive, restored))

    decompress(DecompressionRequest(archive, restored, password="s3cret"))
    assert (restored / "staging" / "secret.txt").read_text() == "hidden"


def test_extraction_only_algorithms_cannot_compress(tmp_path: Path) -> None:
    """7z and RAR are rejected as compression output formats."""
    source = tmp_path / "data.txt"
    source.write_text("data", encoding="utf-8")

    for algorithm in (CompressionAlgorithm.SEVENZ, CompressionAlgorithm.RAR):
        with pytest.raises(UnsupportedFormatError, match="extraction-only"):
            compress(
                CompressionRequest(
                    source, tmp_path / f"out{algorithm.value}", algorithm
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


@pytest.mark.parametrize(
    "algorithm",
    [CompressionAlgorithm.ZIP, CompressionAlgorithm.ZSTD, CompressionAlgorithm.XZ],
)
def test_multi_source_roundtrip(
    tmp_path: Path, algorithm: CompressionAlgorithm
) -> None:
    """Several sources share one archive and extract to distinct members."""
    file_a = tmp_path / "a.txt"
    file_a.write_text("alpha", encoding="utf-8")
    folder = tmp_path / "docs"
    (folder / "nested").mkdir(parents=True)
    (folder / "nested" / "b.txt").write_text("beta", encoding="utf-8")
    archive = tmp_path / f"bundle{algorithm.archive_suffix(is_directory=True)}"
    restored = tmp_path / "restored"

    result = compress(
        CompressionRequest(
            file_a,
            archive,
            algorithm,
            extra_sources=(folder,),
        )
    )
    decompress(DecompressionRequest(archive, restored))

    assert (restored / "a.txt").read_text() == "alpha"
    assert (restored / "docs" / "nested" / "b.txt").read_text() == "beta"
    assert result.files_processed == 2
    assert result.integrity_verified


def test_multi_source_rejects_duplicate_names(tmp_path: Path) -> None:
    """Two sources with the same name would collide inside the archive."""
    dir_a = tmp_path / "one"
    dir_b = tmp_path / "two"
    dir_a.mkdir()
    dir_b.mkdir()
    same_a = dir_a / "report.txt"
    same_b = dir_b / "report.txt"
    same_a.write_text("a")
    same_b.write_text("b")

    with pytest.raises(InvalidRequestError, match="unique names"):
        compress(
            CompressionRequest(
                same_a,
                tmp_path / "out.zip",
                CompressionAlgorithm.ZIP,
                extra_sources=(same_b,),
            )
        )


def test_multi_source_encrypted_roundtrip(tmp_path: Path) -> None:
    """Password-protected multi-source archives decrypt to the full tree."""
    file_a = tmp_path / "a.txt"
    file_a.write_text("alpha", encoding="utf-8")
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "b.txt").write_text("beta", encoding="utf-8")
    archive = tmp_path / "bundle.lsenc"
    restored = tmp_path / "restored"

    compress(
        CompressionRequest(
            file_a,
            archive,
            CompressionAlgorithm.ZSTD,
            password="pw",
            extra_sources=(folder,),
        )
    )
    decompress(DecompressionRequest(archive, restored, password="pw"))

    assert (restored / "a.txt").read_text() == "alpha"
    assert (restored / "docs" / "b.txt").read_text() == "beta"


def test_exclude_patterns_skip_matching_members(tmp_path: Path) -> None:
    """--exclude globs drop matching files and directories from the archive."""
    source = tmp_path / "proj"
    (source / "build").mkdir(parents=True)
    (source / "src").mkdir()
    (source / "src" / "app.py").write_text("code")
    (source / "src" / "app.pyc").write_text("bytecode")
    (source / "build" / "out.o").write_text("obj")
    archive = tmp_path / "out.zip"
    restored = tmp_path / "restored"

    compress(
        CompressionRequest(
            source,
            archive,
            CompressionAlgorithm.ZIP,
            exclude=("*.pyc", "build"),
        )
    )
    decompress(DecompressionRequest(archive, restored))

    assert (restored / "proj" / "src" / "app.py").exists()
    assert not (restored / "proj" / "src" / "app.pyc").exists()
    assert not (restored / "proj" / "build" / "out.o").exists()


def test_lsignore_file_excludes_members(tmp_path: Path) -> None:
    """A .lsignore file in the source directory filters archive members."""
    source = tmp_path / "proj"
    (source / "logs").mkdir(parents=True)
    (source / "keep.txt").write_text("keep")
    (source / "logs" / "debug.log").write_text("noise")
    (source / ".lsignore").write_text("# comment\nlogs/\n*.tmp\n", "utf-8")
    archive = tmp_path / "out.zip"
    restored = tmp_path / "restored"

    compress(CompressionRequest(source, archive, CompressionAlgorithm.ZIP))
    decompress(DecompressionRequest(archive, restored))

    assert (restored / "proj" / "keep.txt").exists()
    assert (restored / "proj" / ".lsignore").exists()
    assert not (restored / "proj" / "logs" / "debug.log").exists()


def test_exclude_all_members_rejected(tmp_path: Path) -> None:
    """A request that excludes every member fails clearly."""
    source = tmp_path / "only.txt"
    source.write_text("data")

    with pytest.raises(InvalidRequestError, match="excluded"):
        compress(
            CompressionRequest(
                source,
                tmp_path / "out.zip",
                CompressionAlgorithm.ZIP,
                exclude=("*.txt",),
            )
        )


@pytest.mark.parametrize(
    "algorithm",
    [
        CompressionAlgorithm.ZIP,
        CompressionAlgorithm.ZSTD,
        CompressionAlgorithm.GZIP,
    ],
)
def test_extract_restores_file_mtime(tmp_path: Path, algorithm) -> None:
    """File mtimes survive a compress/extract roundtrip per format."""
    source_dir = tmp_path / "data"
    source_dir.mkdir()
    source = source_dir / "note.txt"
    source.write_text("timestamped")
    stored = 1_600_000_000  # even second, ZIP-safe granularity
    os.utime(source, (stored, stored))
    os.utime(source_dir, (stored, stored))
    archive = tmp_path / f"data{algorithm.archive_suffix(is_directory=True)}"
    extracted = tmp_path / "restored"

    target = source_dir if algorithm is not CompressionAlgorithm.GZIP else source
    compress(CompressionRequest(target, archive, algorithm))
    decompress(DecompressionRequest(archive, extracted))

    restored = (
        extracted / "data" / "note.txt"
        if algorithm is not CompressionAlgorithm.GZIP
        else extracted
    )
    assert abs(restored.stat().st_mtime - stored) <= 2
    if algorithm is not CompressionAlgorithm.GZIP:
        assert abs((extracted / "data").stat().st_mtime - stored) <= 2
