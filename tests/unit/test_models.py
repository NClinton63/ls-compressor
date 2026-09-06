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


def test_compression_request_defaults_to_verified_zip() -> None:
    """Compression requests favor compatibility and integrity by default."""
    request = CompressionRequest(Path("source.txt"), Path("source.txt.zip"))

    assert request.algorithm is CompressionAlgorithm.ZIP
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
