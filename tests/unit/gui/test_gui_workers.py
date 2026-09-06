"""Unit tests for QRunnable compression workers."""

from pathlib import Path
from uuid import uuid4

import pytest

try:
    from ls_compressor.core import CompressionAlgorithm
    from ls_compressor.gui.models import GuiJobKind
    from ls_compressor.gui.workers import CompressionWorker

    _PYSIDE6_AVAILABLE = True
except Exception:
    _PYSIDE6_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _PYSIDE6_AVAILABLE, reason="PySide6 is not installed"
)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_worker_emits_result_for_compression(qapp, tmp_path: Path) -> None:
    """A compress worker emits a successful OperationResult."""
    source = tmp_path / "source.txt"
    _write_text(source, "a" * 1000)
    destination = tmp_path / "source.zip"

    worker = CompressionWorker(
        job_id=uuid4(),
        kind=GuiJobKind.COMPRESS,
        source=source,
        destination=destination,
        algorithm=CompressionAlgorithm.ZIP,
        compression_level=6,
    )
    results: list[tuple[object, object]] = []
    worker.signals.result.connect(lambda jid, res: results.append((jid, res)))
    errors: list[tuple[object, str]] = []
    worker.signals.error.connect(lambda jid, msg: errors.append((jid, msg)))

    worker.run()

    assert len(results) == 1
    assert len(errors) == 0
    job_id, result = results[0]
    assert job_id == worker.job_id
    assert result.destination == destination
    assert result.algorithm is CompressionAlgorithm.ZIP
    assert destination.exists()


def test_worker_does_not_silently_overwrite_output(qapp, tmp_path: Path) -> None:
    """A worker reports existing output instead of destroying it."""
    source = tmp_path / "source.txt"
    source.write_text("new", encoding="utf-8")
    destination = tmp_path / "source.zip"
    destination.write_bytes(b"existing")
    worker = CompressionWorker(
        job_id=uuid4(),
        kind=GuiJobKind.COMPRESS,
        source=source,
        destination=destination,
        algorithm=CompressionAlgorithm.ZIP,
        compression_level=6,
    )
    errors: list[str] = []
    worker.signals.error.connect(lambda job_id, message: errors.append(message))

    worker.run()

    assert errors == [f"Destination exists: {destination}"]
    assert destination.read_bytes() == b"existing"


def test_worker_emits_error_for_missing_source(qapp, tmp_path: Path) -> None:
    """A worker reports a user-safe error when the source does not exist."""
    source = tmp_path / "missing.txt"
    destination = tmp_path / "out.zip"

    worker = CompressionWorker(
        job_id=uuid4(),
        kind=GuiJobKind.COMPRESS,
        source=source,
        destination=destination,
        algorithm=CompressionAlgorithm.ZIP,
        compression_level=6,
    )
    errors: list[tuple[object, str]] = []
    worker.signals.error.connect(lambda jid, msg: errors.append((jid, msg)))

    worker.run()

    assert len(errors) == 1
    job_id, message = errors[0]
    assert job_id == worker.job_id
    assert "does not exist" in message
    assert not destination.exists()


def test_worker_emits_result_for_decompression(qapp, tmp_path: Path) -> None:
    """A decompress worker emits a result after extracting a valid archive."""
    source = tmp_path / "source.txt"
    _write_text(source, "a" * 1000)
    archive = tmp_path / "source.zip"
    out_dir = tmp_path / "out"

    CompressionWorker(
        job_id=uuid4(),
        kind=GuiJobKind.COMPRESS,
        source=source,
        destination=archive,
        algorithm=CompressionAlgorithm.ZIP,
        compression_level=6,
    ).run()
    assert archive.exists()

    worker = CompressionWorker(
        job_id=uuid4(),
        kind=GuiJobKind.DECOMPRESS,
        source=archive,
        destination=out_dir,
        algorithm=CompressionAlgorithm.ZIP,
        compression_level=6,
    )
    results: list[tuple[object, object]] = []
    worker.signals.result.connect(lambda jid, res: results.append((jid, res)))
    worker.signals.error.connect(lambda jid, msg: pytest.fail(msg))

    worker.run()

    assert len(results) == 1
    assert results[0][1].kind.value == "decompress"
    assert out_dir.exists()
