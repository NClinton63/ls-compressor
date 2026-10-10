"""Tests for supported compression algorithm definitions."""

import pytest

from ls_compressor.core.algorithms import CompressionAlgorithm


@pytest.mark.parametrize(
    ("algorithm", "file_suffix", "directory_suffix"),
    [
        (CompressionAlgorithm.ZSTD, ".zst", ".tar.zst"),
        (CompressionAlgorithm.ZIP, ".zip", ".zip"),
        (CompressionAlgorithm.XZ, ".xz", ".tar.xz"),
        (CompressionAlgorithm.GZIP, ".gz", ".tar.gz"),
        (CompressionAlgorithm.BZ2, ".bz2", ".tar.bz2"),
        (CompressionAlgorithm.SEVENZ, ".7z", ".7z"),
        (CompressionAlgorithm.RAR, ".rar", ".rar"),
    ],
)
def test_archive_suffix_matches_source_type(
    algorithm: CompressionAlgorithm,
    file_suffix: str,
    directory_suffix: str,
) -> None:
    """Algorithms use stream suffixes for files and TAR suffixes for folders."""
    assert algorithm.archive_suffix(is_directory=False) == file_suffix
    assert algorithm.archive_suffix(is_directory=True) == directory_suffix


def test_zip_is_default_compatible_algorithm() -> None:
    """ZIP retains its expected serialized and display names."""
    assert CompressionAlgorithm.ZIP.value == "zip"
    assert CompressionAlgorithm.ZIP.display_name == "ZIP (Deflate)"


def test_zstandard_is_the_default_algorithm() -> None:
    """Zstandard is listed first and uses its expected display name."""
    assert CompressionAlgorithm.ZSTD.value == "zstd"
    assert CompressionAlgorithm.ZSTD.display_name == "Zstandard"
    assert next(iter(CompressionAlgorithm)) is CompressionAlgorithm.ZSTD


@pytest.mark.parametrize(
    ("algorithm", "expected"),
    [
        (CompressionAlgorithm.ZSTD, True),
        (CompressionAlgorithm.ZIP, True),
        (CompressionAlgorithm.XZ, True),
        (CompressionAlgorithm.GZIP, True),
        (CompressionAlgorithm.BZ2, True),
        (CompressionAlgorithm.SEVENZ, False),
        (CompressionAlgorithm.RAR, False),
    ],
)
def test_can_compress_flags_write_support(
    algorithm: CompressionAlgorithm, expected: bool
) -> None:
    """Only creation-capable formats report can_compress."""
    assert algorithm.can_compress is expected
