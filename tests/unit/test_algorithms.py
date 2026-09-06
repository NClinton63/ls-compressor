"""Tests for supported compression algorithm definitions."""

import pytest

from ls_compressor.core.algorithms import CompressionAlgorithm


@pytest.mark.parametrize(
    ("algorithm", "file_suffix", "directory_suffix"),
    [
        (CompressionAlgorithm.ZIP, ".zip", ".zip"),
        (CompressionAlgorithm.XZ, ".xz", ".tar.xz"),
        (CompressionAlgorithm.GZIP, ".gz", ".tar.gz"),
        (CompressionAlgorithm.BZ2, ".bz2", ".tar.bz2"),
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
