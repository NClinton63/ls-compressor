"""Unit tests for the main window and drag-and-drop logic."""

from pathlib import Path

import pytest

try:
    from PIL import Image
except Exception:
    Image = None

try:
    from PySide6.QtCore import QMimeData, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication

    from ls_compressor.core import CompressionAlgorithm
    from ls_compressor.core.watch import (
        WatchEvent,
        WatchFolderConfig,
        WatchOperationType,
    )
    from ls_compressor.gui.main_window import MainWindow
    from ls_compressor.gui.models import GuiJobKind, GuiJobStatus
    from ls_compressor.gui.sidebar import Sidebar
    from ls_compressor.gui.widgets import DropArea
    from ls_compressor.infrastructure.config import AppSettings

    _PYSIDE6_AVAILABLE = True
except Exception:
    _PYSIDE6_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _PYSIDE6_AVAILABLE, reason="PySide6 is not installed"
)


def _process_events() -> None:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def test_main_window_creates_stacked_pages(qapp) -> None:
    """The main window initializes with a sidebar and stacked content pages."""
    window = MainWindow(AppSettings())

    assert window._stack.count() == 5
    assert window._compress_page.table().rowCount() == 0
    assert window._decompress_page.table().rowCount() == 0
    assert window._history_page.table().rowCount() == 0
    assert window._sidebar is not None


def test_main_window_accepts_dropped_files(qapp, tmp_path: Path) -> None:
    """Dropping file URLs onto the compress drop area adds pending sources."""
    source = tmp_path / "dropped.txt"
    source.write_text("hello", encoding="utf-8")
    window = MainWindow(AppSettings())
    drop_area = window._compress_page._drop_area

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    event = QDropEvent(
        drop_area.rect().center(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    drop_area.dropEvent(event)

    pending = window._compress_page.table().pending_sources()
    assert len(pending) == 1
    assert pending[0][1] == source


def test_drop_area_emits_dropped_text_paths(qapp, tmp_path: Path) -> None:
    """Dropping plain text paths emits the resolved local paths."""
    source = tmp_path / "text.txt"
    source.write_text("hello", encoding="utf-8")
    area = DropArea("Drop here")
    received: list[Path] = []
    area.files_dropped.connect(lambda paths: received.extend(paths))

    mime = QMimeData()
    mime.setText(str(source))
    event = QDropEvent(
        area.rect().center(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    area.dropEvent(event)

    assert received == [source]


def test_main_window_queues_selected_compress_jobs(qapp, tmp_path: Path) -> None:
    """Selected pending rows become compression jobs in the queue."""
    source = tmp_path / "source.txt"
    source.write_text("a" * 100, encoding="utf-8")
    window = MainWindow(AppSettings())
    window._on_files_dropped(
        [source], window._compress_page.table(), GuiJobKind.COMPRESS
    )
    window._compress_page.table().selectAll()

    window._queue_selected(GuiJobKind.COMPRESS)

    assert window._queue._pool.waitForDone(5000)
    _process_events()

    completed = [
        job for job in window._queue.jobs if job.status is GuiJobStatus.COMPLETED
    ]
    assert len(completed) == 1


def test_main_window_navigates_between_pages(qapp) -> None:
    """Sidebar navigation switches the stacked widget page."""
    window = MainWindow(AppSettings())

    window._set_page(1)
    assert window._stack.currentIndex() == 1

    window._set_page(3)
    assert window._stack.currentIndex() == 3


def test_sidebar_buttons_match_page_order(qapp) -> None:
    """Sidebar exposes the expected navigation buttons in order."""
    sidebar = Sidebar()

    assert sidebar._compress_button.text() == "Compress"
    assert sidebar._decompress_button.text() == "Decompress"
    assert sidebar._optimize_button.text() == "Optimize"
    assert sidebar._history_button.text() == "History"
    assert sidebar._settings_button.text() == "Settings"
    sidebar.page_requested.emit(3)


def test_same_folder_destination_ignores_last_used_folder(qapp, tmp_path: Path) -> None:
    """Same-folder preference always derives output beside the source."""
    source = tmp_path / "source" / "report.txt"
    source.parent.mkdir()
    source.write_text("content", encoding="utf-8")
    window = MainWindow(AppSettings(last_used_folder=tmp_path / "previous"))

    destination = window._derive_destination(source, GuiJobKind.COMPRESS)

    assert destination == source.parent / "report.txt.zip"


def test_decompression_strips_compound_archive_suffix(qapp, tmp_path: Path) -> None:
    """Compressed TAR names restore to the original folder name."""
    window = MainWindow(AppSettings())
    archive = tmp_path / "project.tar.gz"

    destination = window._derive_destination(archive, GuiJobKind.DECOMPRESS)

    assert destination == tmp_path / "project"


def test_main_window_queues_selected_media_jobs(qapp, tmp_path: Path) -> None:
    """Selected pending rows become media optimization jobs in the queue."""
    pytest.importorskip("PIL")
    source = tmp_path / "source.png"
    image = Image.new("RGBA", (64, 64), (255, 0, 0, 128))
    image.save(source, format="PNG")
    window = MainWindow(AppSettings())
    window._on_files_dropped(
        [source], window._optimize_page.table(), GuiJobKind.MEDIA_OPTIMIZE
    )
    window._optimize_page.table().selectAll()

    window._queue_selected(GuiJobKind.MEDIA_OPTIMIZE)

    assert window._queue._pool.waitForDone(5000)
    _process_events()

    completed = [
        job for job in window._queue.jobs if job.status is GuiJobStatus.COMPLETED
    ]
    assert len(completed) == 1
    assert completed[0].result is not None
    assert completed[0].result.kind.value == "media_optimize"


def test_main_window_enqueues_watch_event(qapp, tmp_path: Path) -> None:
    """A watch event for a file creates a matching GUI job in the queue."""
    source = tmp_path / "watch" / "auto.txt"
    source.parent.mkdir()
    source.write_text("auto", encoding="utf-8")
    output_folder = tmp_path / "out"
    output_folder.mkdir()
    window = MainWindow(AppSettings())
    config = WatchFolderConfig(
        path=source.parent,
        output_folder=output_folder,
        operation=WatchOperationType.COMPRESS,
        algorithm=CompressionAlgorithm.ZIP,
    )
    event = WatchEvent(source=source, config=config, event_type="created")

    window._on_watch_event(event)

    assert window._queue._pool.waitForDone(5000)
    _process_events()

    completed = [
        job for job in window._queue.jobs if job.status is GuiJobStatus.COMPLETED
    ]
    assert len(completed) == 1
    assert completed[0].destination == output_folder / "auto.txt.zip"
