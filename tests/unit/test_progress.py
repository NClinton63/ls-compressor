"""Tests for synchronous progress observation."""

from io import BytesIO
from pathlib import Path

import pytest

from ls_compressor.core.models import OperationKind, OperationProgress
from ls_compressor.core.progress import ProgressReader, ProgressReporter


def test_reporter_notifies_subscribers_with_snapshots() -> None:
    """Advancing a reporter emits an immutable operation snapshot."""
    updates: list[OperationProgress] = []
    reporter = ProgressReporter(OperationKind.COMPRESS, 100)
    reporter.subscribe(updates.append)

    reporter.advance(25, Path("source.txt"))

    assert updates == [
        OperationProgress(OperationKind.COMPRESS, 25, 100, Path("source.txt"))
    ]


def test_reporter_deduplicates_and_removes_subscribers() -> None:
    """Subscription management prevents duplicate and unwanted updates."""
    updates: list[OperationProgress] = []
    reporter = ProgressReporter(OperationKind.VERIFY, 10)
    reporter.subscribe(updates.append)
    reporter.subscribe(updates.append)

    reporter.advance(5)
    reporter.unsubscribe(updates.append)
    reporter.advance(5)

    assert len(updates) == 1


def test_reporter_complete_handles_zero_byte_operation() -> None:
    """Completing empty work still emits a terminal 100 percent update."""
    updates: list[OperationProgress] = []
    reporter = ProgressReporter(OperationKind.COMPRESS, 0, updates.append)

    reporter.complete()

    assert updates[-1].percentage == 100.0


def test_reporter_rejects_negative_advances() -> None:
    """Invalid progress deltas cannot move byte accounting backward."""
    reporter = ProgressReporter(OperationKind.DECOMPRESS, 10)

    with pytest.raises(ValueError, match="cannot be negative"):
        reporter.advance(-1)


def test_progress_reader_reports_consumed_bytes() -> None:
    """The stream wrapper reports only bytes actually returned."""
    counts: list[int] = []
    reader = ProgressReader(BytesIO(b"abcdef"), counts.append)

    assert reader.read(2) == b"ab"
    assert reader.read() == b"cdef"
    assert reader.read() == b""
    assert counts == [2, 4]
