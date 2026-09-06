"""Sequential job queue backed by a single-threaded QThreadPool."""

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

from PySide6.QtCore import QObject, QThreadPool, Signal

from ls_compressor.core import (
    CompressionAlgorithm,
    MediaFormat,
    MediaOptimizationMode,
    OperationResult,
)
from ls_compressor.gui.models import GuiJob, GuiJobKind, GuiJobStatus
from ls_compressor.gui.workers import CompressionWorker


class QueueSignals(QObject):
    """Signals describing the state of the job queue."""

    job_added = Signal(object)
    job_updated = Signal(object)
    job_finished = Signal(object)
    job_failed = Signal(object)
    progress_changed = Signal(object, float)
    current_file_changed = Signal(object, object)
    queue_started = Signal()
    queue_empty = Signal()


class JobQueue(QObject):
    """Manage a sequential queue of compression and decompression workers."""

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize a sequential queue backed by one background thread."""
        super().__init__(parent)
        self.signals = QueueSignals(self)
        self._jobs: dict[UUID, GuiJob] = {}
        self._order: list[UUID] = []
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._running_count = 0
        self._has_started = False

    @property
    def jobs(self) -> Sequence[GuiJob]:
        """Return jobs in queue order."""
        return tuple(self._jobs[job_id] for job_id in self._order)

    def get_job(self, job_id: UUID) -> GuiJob | None:
        """Return the tracked job for the supplied id if present."""
        return self._jobs.get(job_id)

    def add_job(
        self,
        kind: GuiJobKind,
        source: Path,
        destination: Path,
        algorithm: CompressionAlgorithm | None = None,
        compression_level: int = 0,
        media_format: MediaFormat | None = None,
        media_mode: MediaOptimizationMode = MediaOptimizationMode.LOSSLESS,
        media_quality: int | None = None,
        video_preset: str = "medium",
        video_crf: int | None = None,
        password: str | None = None,
        self_extracting: bool = False,
    ) -> UUID:
        """Create a pending job and enqueue it for sequential execution."""
        job_id = uuid4()
        job = GuiJob(
            job_id=job_id,
            kind=kind,
            source=source,
            destination=destination,
            status=GuiJobStatus.PENDING,
            algorithm=algorithm,
            compression_level=compression_level,
            media_format=media_format,
            media_mode=media_mode,
            media_quality=media_quality,
            video_preset=video_preset,
            video_crf=video_crf,
            password=password,
            self_extracting=self_extracting,
        )
        self._jobs[job_id] = job
        self._order.append(job_id)
        self.signals.job_added.emit(job_id)
        self._start_job(job)
        return job_id

    def clear_completed(self) -> None:
        """Remove completed and failed jobs from the tracked queue."""
        finished_states = {GuiJobStatus.COMPLETED, GuiJobStatus.FAILED}
        finished = [
            job_id
            for job_id in self._order
            if self._jobs[job_id].status in finished_states
        ]
        for job_id in finished:
            self._order.remove(job_id)
            del self._jobs[job_id]

    def _start_job(self, job: GuiJob) -> None:
        """Start a worker and mark the job as running."""
        self._running_count += 1
        if not self._has_started:
            self._has_started = True
            self.signals.queue_started.emit()
        self._update_job(job.job_id, status=GuiJobStatus.RUNNING)
        worker = CompressionWorker(
            job_id=job.job_id,
            kind=job.kind,
            source=job.source,
            destination=job.destination,
            algorithm=job.algorithm,
            compression_level=job.compression_level,
            media_format=job.media_format,
            media_mode=job.media_mode,
            media_quality=job.media_quality,
            video_preset=job.video_preset,
            video_crf=job.video_crf,
            password=job.password,
            self_extracting=job.self_extracting,
        )
        worker.signals.started.connect(self._on_started)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.current_file.connect(self._on_current_file)
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._on_error)
        self._pool.start(worker)

    def _on_started(self, job_id: UUID) -> None:
        """Update the job status to running when the worker starts."""
        self._update_job(job_id, status=GuiJobStatus.RUNNING)

    def _on_progress(self, job_id: UUID, percent: float, current_file: Path) -> None:
        """Update progress and current file for an active job."""
        self._update_job(job_id, progress_percent=percent, current_file=current_file)
        self.signals.progress_changed.emit(job_id, percent)
        if current_file is not None:
            self.signals.current_file_changed.emit(job_id, current_file)

    def _on_current_file(self, job_id: UUID, current_file: Path) -> None:
        """Update the current file for an active job."""
        self._update_job(job_id, current_file=current_file)

    def _on_result(self, job_id: UUID, result: OperationResult) -> None:
        """Mark a job as completed and notify listeners."""
        elapsed = max(result.elapsed_seconds, 0.001)
        throughput = (result.source_size / elapsed) / (1024 * 1024)
        self._update_job(
            job_id,
            status=GuiJobStatus.COMPLETED,
            result=result,
            throughput_mbps=throughput,
        )
        self.signals.job_finished.emit(job_id)
        self._job_finished()

    def _on_error(self, job_id: UUID, message: str) -> None:
        """Mark a job as failed and notify listeners."""
        self._update_job(job_id, status=GuiJobStatus.FAILED, error_message=message)
        self.signals.job_failed.emit(job_id)
        self._job_finished()

    def _job_finished(self) -> None:
        """Decrement the running count and emit queue_empty when idle."""
        self._running_count = max(0, self._running_count - 1)
        if self._running_count == 0 and self._has_started:
            self._has_started = False
            self.signals.queue_empty.emit()

    def _update_job(self, job_id: UUID, **changes: object) -> None:
        """Apply field changes to a tracked job and emit the update signal."""
        if job_id not in self._jobs:
            return
        self._jobs[job_id] = self._jobs[job_id].update(**changes)
        self.signals.job_updated.emit(job_id)
