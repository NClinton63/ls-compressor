"""Tests for core operation models."""

from pathlib import Path

import pytest

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.models import (
    CompressionRequest,
    OperationKind,
    OperationProgress,
    OperationResult,
)


def test_compression_request_defaults_to_verified_zstandard() -> None:
    """Compression requests favor speed and integrity by default."""
    request = CompressionRequest(Path("source.txt"), Path("source.txt.zst"))

    assert request.algorithm is CompressionAlgorithm.ZSTD
    assert request.verify is True
    assert request.overwrite is False
    assert request.compression_level is None


@pytest.mark.parametrize(
    ("completed", "total", "expected"),
    [
        (0, 0, 0.0),
        (1, 0, 100.0),
        (25, 100, 25.0),
        (200, 100, 100.0),
        (-1, 100, 0.0),
    ],
)
def test_progress_percentage_is_safe_and_clamped(
    completed: int, total: int, expected: float
) -> None:
    """Progress remains meaningful for empty and inconsistent byte counts."""
    progress = OperationProgress(OperationKind.COMPRESS, completed, total)

    assert progress.percentage == expected


def test_operation_result_reports_ratio_and_savings() -> None:
    """Operation results expose conventional compression metrics."""
    result = OperationResult(
        kind=OperationKind.COMPRESS,
        source=Path("source"),
        destination=Path("source.zip"),
        algorithm=CompressionAlgorithm.ZIP,
        source_size=1_000,
        output_size=400,
        elapsed_seconds=1.25,
        files_processed=2,
        integrity_verified=True,
    )

    assert result.compression_ratio == pytest.approx(0.4)
    assert result.space_savings_percentage == pytest.approx(60.0)


def test_empty_operation_result_has_defined_ratio() -> None:
    """Zero-byte sources do not cause division by zero."""
    result = OperationResult(
        kind=OperationKind.COMPRESS,
        source=Path("empty"),
        destination=Path("empty.zip"),
        algorithm=CompressionAlgorithm.ZIP,
        source_size=0,
        output_size=22,
        elapsed_seconds=0.1,
        files_processed=1,
        integrity_verified=True,
    )

    assert result.compression_ratio == 0.0
    assert result.space_savings_percentage == 0.0


def test_filesystem_ignore_pattern_matching(tmp_path: Path) -> None:
    """Gitignore-lite patterns match basenames, dirs, and rooted globs."""
    from ls_compressor.core.filesystem import is_excluded, load_ignore_patterns

    assert is_excluded("src/app.pyc", ("*.pyc",))
    assert is_excluded("build/out.o", ("build",))
    assert is_excluded("build/deep/out.o", ("build/",))
    assert is_excluded("src/tmp/x.log", ("src/tmp/*",))
    assert not is_excluded("src/app.py", ("*.pyc", "build"))

    (tmp_path / ".lsignore").write_text("# c\n*.log\n\n", "utf-8")
    assert load_ignore_patterns(tmp_path) == ("*.log",)
    assert load_ignore_patterns(tmp_path / "missing") == ()


def test_plan_compression_reports_members_without_writing(
    tmp_path: Path,
) -> None:
    """plan_compression validates the request and lists planned members."""
    from ls_compressor.core import plan_compression

    source = tmp_path / "folder"
    source.mkdir()
    (source / "a.txt").write_bytes(b"a" * 10)
    (source / "b.txt").write_bytes(b"b" * 20)
    (source / "skip.tmp").write_bytes(b"junk")
    destination = tmp_path / "folder.tar.zst"

    plan = plan_compression(
        CompressionRequest(
            source=source,
            destination=destination,
            exclude=("*.tmp",),
            split_size=15,
        )
    )

    names = [member.name for member in plan.members]
    assert "folder/a.txt" in names and "folder/b.txt" in names
    assert not any("skip.tmp" in name for name in names)
    assert plan.total_bytes == 30
    assert plan.split_volumes == 2
    assert plan.destination_exists is False
    assert not destination.exists()


def test_plan_compression_rejects_invalid_requests(tmp_path: Path) -> None:
    """plan_compression applies the same validation as compress."""
    from ls_compressor.core import plan_compression
    from ls_compressor.core.exceptions import InvalidRequestError

    source = tmp_path / "f.txt"
    source.write_text("x", "utf-8")
    with pytest.raises(InvalidRequestError):
        plan_compression(
            CompressionRequest(
                source=source,
                destination=tmp_path / "f.lsex",
                password="pw",
                self_extracting=True,
                split_size=100,
            )
        )


def test_compression_presets_resolve_algorithm_and_level() -> None:
    """Each preset maps to a valid write-capable algorithm and level."""
    from ls_compressor.core.models import CompressionPreset

    assert CompressionPreset.FAST.algorithm is CompressionAlgorithm.ZSTD
    assert CompressionPreset.FAST.level == 1
    assert CompressionPreset.BALANCED.algorithm is CompressionAlgorithm.ZSTD
    assert CompressionPreset.BALANCED.level == 3
    assert CompressionPreset.MAXIMUM.algorithm is CompressionAlgorithm.XZ
    assert CompressionPreset.MAXIMUM.level == 9
    for preset in CompressionPreset:
        assert preset.algorithm.can_compress
        assert 0 <= preset.level <= 9
        assert preset.display_name
