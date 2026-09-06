"""Unit tests for the sequential job queue."""

from pathlib import Path

import pytest

try:
    from PySide6.QtCore import QCoreApplication

    from ls_compressor.core import CompressionAlgorithm
    from ls_compressor.gui.models import GuiJobKind, GuiJobStatus
    from ls_compressor.gui.queue import JobQueue

    _PYSIDE6_AVAILABLE = True
except Exception:
    _PYSIDE6_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _PYSIDE6_AVAILABLE, reason="PySide6 is not installed"
)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _process_events() -> None:
    app = QCoreApplication.instance()
    if app is not None:
        app.processEvents()


def test_queue_adds_job_and_emits_added_signal(qapp, tmp_path: Path) -> None:
    """Adding a job returns an id, emits the signal, and starts the worker."""
    queue = JobQueue()
    added_ids = []
    queue.signals.job_added.connect(lambda job_id: added_ids.append(job_id))

    source = tmp_path / "source.txt"
    _write_text(source, "data")
    job_id = queue.add_job(
        kind=GuiJobKind.COMPRESS,
        source=source,
        destination=tmp_path / "source.zip",
        algorithm=CompressionAlgorithm.ZIP,
        compression_level=6,
    )

    assert job_id is not None
    assert len(added_ids) == 1
    assert added_ids[0] == job_id
    assert queue.get_job(job_id).status == GuiJobStatus.RUNNING


def test_queue_runs_job_to_completion(qapp, tmp_path: Path) -> None:
    """A queued compression job finishes and emits the expected signals."""
    queue = JobQueue()
    finished_ids = []
    queue.signals.job_finished.connect(lambda job_id: finished_ids.append(job_id))

    source = tmp_path / "source.txt"
    _write_text(source, "x" * 500)
    destination = tmp_path / "source.zip"
    job_id = queue.add_job(
        kind=GuiJobKind.COMPRESS,
        source=source,
        destination=destination,
        algorithm=CompressionAlgorithm.ZIP,
        compression_level=6,
    )

    assert queue._pool.waitForDone(5000)
    _process_events()

    assert queue.get_job(job_id).status == GuiJobStatus.COMPLETED
    assert job_id in finished_ids
    assert destination.exists()


def test_queue_runs_multiple_jobs_sequentially(qapp, tmp_path: Path) -> None:
    """Multiple queued jobs complete without running in parallel."""
    queue = JobQueue()
    queue.signals.queue_empty.connect(lambda: None)

    for index in range(3):
        source = tmp_path / f"source{index}.txt"
        _write_text(source, f"data{index}" * 200)
        queue.add_job(
            kind=GuiJobKind.COMPRESS,
            source=source,
            destination=tmp_path / f"source{index}.zip",
            algorithm=CompressionAlgorithm.ZIP,
            compression_level=6,
        )

    assert queue._pool.waitForDone(10000)
    _process_events()

    completed = sum(1 for job in queue.jobs if job.status == GuiJobStatus.COMPLETED)
    assert completed == 3


def test_queue_reports_failed_job(qapp, tmp_path: Path) -> None:
    """A job with a missing source is reported as failed with a safe message."""
    queue = JobQueue()
    failed_ids = []
    queue.signals.job_failed.connect(lambda job_id: failed_ids.append(job_id))

    job_id = queue.add_job(
        kind=GuiJobKind.COMPRESS,
        source=tmp_path / "missing.txt",
        destination=tmp_path / "out.zip",
        algorithm=CompressionAlgorithm.ZIP,
        compression_level=6,
    )

    assert queue._pool.waitForDone(5000)
    _process_events()

    job = queue.get_job(job_id)
    assert job.status == GuiJobStatus.FAILED
    assert "does not exist" in job.error_message
    assert job_id in failed_ids
