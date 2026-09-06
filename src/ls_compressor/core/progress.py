"""Synchronous observer-based progress reporting for core operations."""

from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from ls_compressor.core.models import OperationKind, OperationProgress

ProgressCallback = Callable[[OperationProgress], None]


class ProgressReporter:
    """Track byte progress and synchronously notify registered observers."""

    def __init__(
        self,
        kind: OperationKind,
        total_bytes: int,
        callback: ProgressCallback | None = None,
    ) -> None:
        """Initialize a reporter for one operation."""
        self._kind = kind
        self._total_bytes = max(0, total_bytes)
        self._completed_bytes = 0
        self._current_file: Path | None = None
        self._callbacks: list[ProgressCallback] = []
        if callback is not None:
            self.subscribe(callback)

    @property
    def snapshot(self) -> OperationProgress:
        """Return the reporter's current immutable progress value."""
        return OperationProgress(
            self._kind,
            self._completed_bytes,
            self._total_bytes,
            self._current_file,
        )

    def subscribe(self, callback: ProgressCallback) -> None:
        """Register an observer unless it is already registered."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unsubscribe(self, callback: ProgressCallback) -> None:
        """Remove a registered observer without failing when absent."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def advance(self, byte_count: int, current_file: Path | None = None) -> None:
        """Advance completed bytes and synchronously notify observers."""
        if byte_count < 0:
            raise ValueError("Progress byte count cannot be negative")
        self._completed_bytes += byte_count
        self._current_file = current_file
        self._notify()

    def complete(self, current_file: Path | None = None) -> None:
        """Mark the operation complete and notify observers."""
        self._completed_bytes = self._total_bytes or 1
        if current_file is not None:
            self._current_file = current_file
        self._notify()

    def _notify(self) -> None:
        """Send the current snapshot to a stable observer collection."""
        progress = self.snapshot
        for callback in tuple(self._callbacks):
            callback(progress)


class ProgressReader:
    """Wrap a binary stream and report bytes as they are read."""

    def __init__(self, stream: BinaryIO, reporter: Callable[[int], None]) -> None:
        """Initialize a progress-reporting stream wrapper."""
        self._stream = stream
        self._reporter = reporter

    def read(self, size: int = -1) -> bytes:
        """Read bytes from the wrapped stream and report their count."""
        data = self._stream.read(size)
        if data:
            self._reporter(len(data))
        return data
