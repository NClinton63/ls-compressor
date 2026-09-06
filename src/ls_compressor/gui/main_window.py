"""Main application window for LS Compressor."""

import logging
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ls_compressor.core import (
    CompressionAlgorithm,
    EncryptionError,
    MediaFormat,
    MediaOptimizationMode,
    OperationKind,
    is_encrypted_file,
    is_self_extracting_archive,
)
from ls_compressor.core.watch import (
    WatchEvent,
    WatchOperationType,
    derive_watch_destination,
)
from ls_compressor.gui import theme
from ls_compressor.gui.models import GuiJobKind, GuiJobStatus
from ls_compressor.gui.queue import JobQueue
from ls_compressor.gui.resources import icon, load_theme
from ls_compressor.gui.sidebar import Sidebar
from ls_compressor.gui.stat_card import StatCard
from ls_compressor.gui.widgets import (
    AlgorithmComboBox,
    DropArea,
    JobTable,
    SettingsDialog,
)
from ls_compressor.infrastructure.config import (
    AppSettings,
    OutputLocationPreference,
    save_settings,
)
from ls_compressor.infrastructure.watch import WatchService

LOGGER = logging.getLogger("ls_compressor.gui.main_window")

_PAGES = {
    "compress": 0,
    "decompress": 1,
    "optimize": 2,
    "history": 3,
    "settings": 4,
}


class _Page(QWidget):
    """Common layout for a work view: header, dropzone, table, and stat cards."""

    files_dropped = Signal(list)
    add_files_clicked = Signal()
    add_folder_clicked = Signal()
    run_clicked = Signal()
    clear_clicked = Signal()

    def __init__(
        self, title: str, subtitle: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._subtitle_template = subtitle
        self._table = JobTable(self._kind())
        self._stats: list[StatCard] = []
        self._build_ui()

    def _kind(self) -> GuiJobKind | None:
        return None

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_18)

        header = self._build_header()
        layout.addWidget(header)

        self._drop_area = DropArea(self._drop_text())
        self._drop_area.files_dropped.connect(self.files_dropped.emit)
        layout.addWidget(self._drop_area)

        layout.addWidget(self._table, 1)

        stats_layout = QHBoxLayout()
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(theme.SPACE_10)
        for stat in self._create_stats():
            self._stats.append(stat)
            stats_layout.addWidget(stat)
        layout.addLayout(stats_layout)

    def _build_header(self) -> QWidget:
        header = QWidget(self)
        header.setFixedHeight(theme.HEADER_HEIGHT)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(theme.SPACE_8)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(theme.SPACE_2)
        self._title_label = QLabel(self._title)
        self._title_label.setProperty("role", "title")
        self._subtitle_label = QLabel(self._subtitle_template)
        self._subtitle_label.setProperty("role", "subtitle")
        text.addWidget(self._title_label)
        text.addWidget(self._subtitle_label)
        header_layout.addLayout(text)
        header_layout.addStretch()
        header_layout.addLayout(self._build_controls())
        return header

    def _build_controls(self) -> QHBoxLayout:
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(theme.SPACE_8)
        self._add_files_button = QPushButton(
            icon("add", theme.TEXT_SECONDARY, theme.NAV_ICON_SIZE), "Add files"
        )
        self._add_files_button.setObjectName("addFilesButton")
        self._add_files_button.setProperty("variant", "secondary")
        self._add_files_button.clicked.connect(self.add_files_clicked.emit)
        controls.addWidget(self._add_files_button)
        return controls

    def _create_stats(self) -> list[StatCard]:
        return [
            StatCard("Jobs completed", "0", "/ 0"),
            StatCard("Avg. ratio", "0%"),
            StatCard("Throughput", "0.0", "MB/s"),
            StatCard("Elapsed", "0.0", "s"),
        ]

    def _drop_text(self) -> str:
        return "Drop files or folders here"

    def table(self) -> JobTable:
        return self._table

    def update_header(self, context: str) -> None:
        self._subtitle_label.setText(self._subtitle_template.format(context))


class CompressPage(_Page):
    """Compression view with algorithm selection."""

    algorithm_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Compress", "{}", parent)

    def _kind(self) -> GuiJobKind | None:
        return GuiJobKind.COMPRESS

    def _build_controls(self) -> QHBoxLayout:
        controls = super()._build_controls()
        self._algorithm_combo = AlgorithmComboBox(self)
        self._algorithm_combo.currentIndexChanged.connect(
            lambda _index: self.algorithm_changed.emit()
        )
        self._password = QLineEdit(self)
        self._password.setPlaceholderText("Password")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setMaximumWidth(140)
        self._self_extracting = QCheckBox("Self-extracting", self)
        self._run_button = QPushButton("Compress")
        self._run_button.setObjectName("compressButton")
        self._run_button.setProperty("variant", "primary")
        self._run_button.clicked.connect(self.run_clicked.emit)
        controls.addWidget(self._algorithm_combo)
        controls.addWidget(self._password)
        controls.addWidget(self._self_extracting)
        controls.addWidget(self._run_button)
        return controls

    def password(self) -> str:
        """Return the entered encryption password, or an empty string if unset."""
        return self._password.text()

    def is_self_extracting(self) -> bool:
        """Return whether the self-extracting archive option is selected."""
        return self._self_extracting.isChecked()

    def _create_stats(self) -> list[StatCard]:
        return [
            StatCard("Jobs completed", "0", "/ 0"),
            StatCard("Avg. ratio", "0%"),
            StatCard("Throughput", "0.0", "MB/s"),
            StatCard("Elapsed", "0.0", "s"),
        ]

    def _drop_text(self) -> str:
        return "Drop files or folders to add them to the queue"

    def selected_algorithm(self) -> CompressionAlgorithm | None:
        value = self._algorithm_combo.currentData()
        if value is None:
            return None
        return CompressionAlgorithm(value)

    def set_algorithm(self, algorithm: CompressionAlgorithm) -> None:
        index = self._algorithm_combo.findData(algorithm.value)
        if index >= 0:
            self._algorithm_combo.setCurrentIndex(index)

    def populate_algorithms(self, algorithms: list[CompressionAlgorithm]) -> None:
        self._algorithm_combo.clear()
        labels = {CompressionAlgorithm.ZIP: "Deflate"}
        for algorithm in algorithms:
            self._algorithm_combo.addItem(
                labels.get(algorithm, algorithm.display_name), algorithm.value
            )


class DecompressPage(_Page):
    """Decompression view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Decompress", "{}", parent)

    def _kind(self) -> GuiJobKind | None:
        return GuiJobKind.DECOMPRESS

    def _build_controls(self) -> QHBoxLayout:
        controls = super()._build_controls()
        self._run_button = QPushButton("Decompress")
        self._run_button.setObjectName("decompressButton")
        self._run_button.setProperty("variant", "secondary")
        self._run_button.clicked.connect(self.run_clicked.emit)
        controls.addWidget(self._run_button)
        return controls

    def _create_stats(self) -> list[StatCard]:
        return [
            StatCard("Jobs completed", "0", "/ 0"),
            StatCard("Avg. ratio", "0%"),
            StatCard("Throughput", "0.0", "MB/s"),
            StatCard("Elapsed", "0.0", "s"),
        ]

    def _drop_text(self) -> str:
        return "Drop files or folders to add them to the queue"


class MediaPage(_Page):
    """Media asset optimization view with mode selection."""

    mode_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Optimize", "{}", parent)

    def _kind(self) -> GuiJobKind | None:
        return GuiJobKind.MEDIA_OPTIMIZE

    def _build_controls(self) -> QHBoxLayout:
        controls = super()._build_controls()
        self._mode_combo = AlgorithmComboBox(self)
        self._mode_combo.addItem("Lossless", "lossless")
        self._mode_combo.addItem("Lossy", "lossy")
        self._mode_combo.currentIndexChanged.connect(
            lambda _index: self.mode_changed.emit()
        )
        self._run_button = QPushButton("Optimize")
        self._run_button.setObjectName("optimizeButton")
        self._run_button.setProperty("variant", "primary")
        self._run_button.clicked.connect(self.run_clicked.emit)
        controls.addWidget(self._mode_combo)
        controls.addWidget(self._run_button)
        return controls

    def _create_stats(self) -> list[StatCard]:
        return [
            StatCard("Jobs completed", "0", "/ 0"),
            StatCard("Avg. savings", "0%"),
            StatCard("Throughput", "0.0", "MB/s"),
            StatCard("Elapsed", "0.0", "s"),
        ]

    def _drop_text(self) -> str:
        return "Drop images or videos to add them to the queue"

    def selected_mode(self) -> MediaOptimizationMode:
        value = self._mode_combo.currentData()
        return MediaOptimizationMode(value) if value else MediaOptimizationMode.LOSSLESS

    def set_mode(self, mode: MediaOptimizationMode) -> None:
        index = self._mode_combo.findData(mode.value)
        if index >= 0:
            self._mode_combo.setCurrentIndex(index)


class HistoryPage(QWidget):
    """Read-only aggregate view of queued and completed jobs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_16)
        header = QWidget(self)
        header.setFixedHeight(theme.HEADER_HEIGHT)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("History")
        title.setProperty("role", "title")
        subtitle = QLabel("All queued and completed jobs")
        subtitle.setProperty("role", "subtitle")
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(theme.SPACE_2)
        text.addWidget(title)
        text.addWidget(subtitle)
        header_layout.addLayout(text)
        header_layout.addStretch()
        layout.addWidget(header)
        self._table = JobTable(parent=self)
        layout.addWidget(self._table, 1)

    def table(self) -> JobTable:
        return self._table


class SettingsPage(QWidget):
    """Inline settings editor backed by AppSettings."""

    settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_16)
        header = QWidget(self)
        header.setFixedHeight(theme.HEADER_HEIGHT)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Settings")
        title.setProperty("role", "title")
        subtitle = QLabel("Application preferences")
        subtitle.setProperty("role", "subtitle")
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(theme.SPACE_2)
        text.addWidget(title)
        text.addWidget(subtitle)
        header_layout.addLayout(text)
        header_layout.addStretch()
        layout.addWidget(header)
        self._dialog = SettingsDialog(self)
        self._dialog.accepted.connect(self.settings_changed.emit)
        layout.addWidget(self._dialog)
        layout.addStretch()

    def set_settings(self, settings: AppSettings) -> None:
        self._dialog.set_settings(settings)

    def settings(self) -> AppSettings:
        return self._dialog.settings()


class MainWindow(QMainWindow):
    """Two-pane main window with sidebar navigation and stacked views."""

    def __init__(
        self,
        settings: AppSettings,
        queue: JobQueue | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._queue = queue or JobQueue(self)
        self._watch_service = WatchService(self._on_watch_event)
        self._build_ui()
        self._connect_queue()
        self._apply_settings()
        self._watch_service.update_folders(list(self._settings.watch_folders))
        self._watch_service.start()
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_stats)
        self._status_timer.start(250)

    def settings(self) -> AppSettings:
        """Return the current in-memory settings."""
        return self._settings

    def _build_ui(self) -> None:
        self.setWindowTitle("LS Compressor")
        self.setMinimumSize(900, 500)
        self.resize(1000, 520)

        central = QWidget(self)
        central.setObjectName("centralWidget")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = Sidebar(central)
        self._sidebar.page_requested.connect(self._set_page)
        root.addWidget(self._sidebar)

        self._content = QWidget(central)
        self._content.setObjectName("contentArea")
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(
            theme.SPACE_24, theme.SPACE_20, theme.SPACE_24, theme.SPACE_20
        )
        content_layout.setSpacing(0)

        self._stack = QStackedWidget(self._content)
        self._compress_page = CompressPage(self._stack)
        self._compress_page.files_dropped.connect(self._on_files_dropped_compress)
        self._compress_page.add_files_clicked.connect(self._add_files_compress)
        self._compress_page.add_folder_clicked.connect(self._add_folder_compress)
        self._compress_page.run_clicked.connect(
            lambda: self._queue_selected(GuiJobKind.COMPRESS)
        )
        self._compress_page.clear_clicked.connect(self._clear_completed)
        self._compress_page.algorithm_changed.connect(self._on_algorithm_changed)

        self._decompress_page = DecompressPage(self._stack)
        self._decompress_page.files_dropped.connect(self._on_files_dropped_decompress)
        self._decompress_page.add_files_clicked.connect(self._add_files_decompress)
        self._decompress_page.add_folder_clicked.connect(self._add_folder_decompress)
        self._decompress_page.run_clicked.connect(
            lambda: self._queue_selected(GuiJobKind.DECOMPRESS)
        )
        self._decompress_page.clear_clicked.connect(self._clear_completed)

        self._optimize_page = MediaPage(self._stack)
        self._optimize_page.files_dropped.connect(self._on_files_dropped_optimize)
        self._optimize_page.add_files_clicked.connect(self._add_files_optimize)
        self._optimize_page.run_clicked.connect(
            lambda: self._queue_selected(GuiJobKind.MEDIA_OPTIMIZE)
        )
        self._optimize_page.clear_clicked.connect(self._clear_completed)
        self._optimize_page.mode_changed.connect(
            lambda: self._update_header(
                self._optimize_page.table(), GuiJobKind.MEDIA_OPTIMIZE
            )
        )

        self._history_page = HistoryPage(self._stack)
        self._settings_page = SettingsPage(self._stack)
        self._settings_page.settings_changed.connect(self._on_settings_changed)

        self._stack.addWidget(self._compress_page)
        self._stack.addWidget(self._decompress_page)
        self._stack.addWidget(self._optimize_page)
        self._stack.addWidget(self._history_page)
        self._stack.addWidget(self._settings_page)
        content_layout.addWidget(self._stack)
        root.addWidget(self._content, 1)

        self.setCentralWidget(central)
        self._sidebar.set_active(_PAGES["compress"])

    def _set_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._sidebar.set_active(index)
        if index == _PAGES["settings"]:
            self._settings_page.set_settings(self._settings)
        self._update_stats()

    def _connect_queue(self) -> None:
        self._queue.signals.job_added.connect(self._on_job_added)
        self._queue.signals.job_updated.connect(self._on_job_updated)
        self._queue.signals.job_finished.connect(self._on_job_finished)
        self._queue.signals.job_failed.connect(self._on_job_failed)

    def _apply_settings(self) -> None:
        algorithm = (
            self._settings.last_used_algorithm or self._settings.default_algorithm
        )
        self._compress_page.populate_algorithms(list(CompressionAlgorithm))
        self._compress_page.set_algorithm(algorithm)
        self._update_header(self._compress_page.table(), GuiJobKind.COMPRESS)
        self._update_header(self._decompress_page.table(), GuiJobKind.DECOMPRESS)
        self._update_header(self._optimize_page.table(), GuiJobKind.MEDIA_OPTIMIZE)

    def _table_for_kind(self, kind: GuiJobKind) -> JobTable:
        tables = {
            GuiJobKind.COMPRESS: self._compress_page,
            GuiJobKind.DECOMPRESS: self._decompress_page,
            GuiJobKind.MEDIA_OPTIMIZE: self._optimize_page,
        }
        return tables[kind].table()

    def _on_files_dropped_compress(self, paths: list[Path]) -> None:
        self._on_files_dropped(paths, self._compress_page.table(), GuiJobKind.COMPRESS)

    def _on_files_dropped_decompress(self, paths: list[Path]) -> None:
        self._on_files_dropped(
            paths, self._decompress_page.table(), GuiJobKind.DECOMPRESS
        )

    def _on_files_dropped_optimize(self, paths: list[Path]) -> None:
        self._on_files_dropped(
            paths, self._optimize_page.table(), GuiJobKind.MEDIA_OPTIMIZE
        )

    def _on_files_dropped(
        self, paths: list[Path], table: JobTable, kind: GuiJobKind
    ) -> None:
        for path in paths:
            if path.exists():
                table.add_pending_source(path)
            else:
                LOGGER.warning("Dropped path does not exist: %s", path)
        self._update_header(table, kind)

    def _add_files_compress(self) -> None:
        self._add_files(self._compress_page.table(), GuiJobKind.COMPRESS)

    def _add_files_decompress(self) -> None:
        self._add_files(self._decompress_page.table(), GuiJobKind.DECOMPRESS)

    def _add_files_optimize(self) -> None:
        self._add_files(self._optimize_page.table(), GuiJobKind.MEDIA_OPTIMIZE)

    def _add_files(self, table: JobTable, kind: GuiJobKind) -> None:
        default_dir = str(self._settings.last_used_folder or Path.home())
        if kind == GuiJobKind.MEDIA_OPTIMIZE:
            extensions = "*.png *.jpg *.jpeg *.webp *.mp4 *.mov *.avi *.mkv *.webm"
            filters = f"Images/Videos ({extensions});;All files (*)"
            files, _ = QFileDialog.getOpenFileNames(
                self, "Select media files", default_dir, filters
            )
        else:
            files, _ = QFileDialog.getOpenFileNames(self, "Select files", default_dir)
        self._on_files_dropped([Path(file_path) for file_path in files], table, kind)

    def _add_folder_compress(self) -> None:
        self._add_folder(self._compress_page.table(), GuiJobKind.COMPRESS)

    def _add_folder_decompress(self) -> None:
        self._add_folder(self._decompress_page.table(), GuiJobKind.DECOMPRESS)

    def _add_folder_optimize(self) -> None:
        self._add_folder(self._optimize_page.table(), GuiJobKind.MEDIA_OPTIMIZE)

    def _add_folder(self, table: JobTable, kind: GuiJobKind) -> None:
        default_dir = str(self._settings.last_used_folder or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select folder", default_dir)
        if folder:
            self._on_files_dropped([Path(folder)], table, kind)

    def _queue_selected(self, kind: GuiJobKind) -> None:
        table = self._table_for_kind(kind)
        selected_rows = sorted({index.row() for index in table.selectedIndexes()})
        selected_set = set(selected_rows)
        pending_rows = table.pending_sources()
        if selected_set:
            rows_to_queue = [
                (row, source) for row, source in pending_rows if row in selected_set
            ]
        else:
            rows_to_queue = pending_rows
        if not rows_to_queue:
            return

        output_folder: Path | None = None
        if (
            self._settings.output_location_preference
            is OutputLocationPreference.ASK_EACH_TIME
        ):
            default_dir = str(
                self._settings.last_used_folder or rows_to_queue[0][1].parent
            )
            folder = QFileDialog.getExistingDirectory(
                self, "Select output folder", default_dir
            )
            if not folder:
                return
            output_folder = Path(folder)
            self._update_settings(last_used_folder=output_folder)

        password: str | None = None
        self_extracting = False
        if kind == GuiJobKind.COMPRESS:
            password = self._compress_page.password().strip() or None
            self_extracting = self._compress_page.is_self_extracting()
            if self_extracting and not password:
                dialog = QMessageBox(self)
                dialog.setIcon(QMessageBox.Icon.Warning)
                dialog.setWindowTitle("Password required")
                dialog.setText(
                    "A password is required to create a self-extracting archive."
                )
                dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
                dialog.open()
                return
        elif kind == GuiJobKind.DECOMPRESS and any(
            is_encrypted_file(source) or is_self_extracting_archive(source)
            for _, source in rows_to_queue
        ):
            entered, ok = QInputDialog.getText(
                self,
                "Archive password",
                "This archive is encrypted. Enter the password:",
                QLineEdit.EchoMode.Password,
            )
            if not ok or not entered:
                return
            password = entered

        for row, source in rows_to_queue:
            destination = self._derive_destination(
                source,
                kind,
                output_folder,
                password=password,
                self_extracting=self_extracting,
            )
            if kind == GuiJobKind.MEDIA_OPTIMIZE:
                job_id = self._queue.add_job(
                    kind=kind,
                    source=source,
                    destination=destination,
                    media_mode=self._optimize_page.selected_mode(),
                )
                table.convert_row_to_job(
                    row, job_id, kind, destination, media_format=MediaFormat.PNG
                )
                continue
            algorithm = (
                self._compress_page.selected_algorithm()
                if kind == GuiJobKind.COMPRESS
                else CompressionAlgorithm.ZIP
            )
            level = self._settings.compression_level
            if algorithm in {CompressionAlgorithm.GZIP, CompressionAlgorithm.BZ2}:
                level = max(1, level)
            job_id = self._queue.add_job(
                kind=kind,
                source=source,
                destination=destination,
                algorithm=algorithm,
                compression_level=level,
                password=password,
                self_extracting=self_extracting,
            )
            table.convert_row_to_job(row, job_id, kind, algorithm, destination)

    def _derive_destination(
        self,
        source: Path,
        kind: GuiJobKind,
        output_folder: Path | None = None,
        password: str | None = None,
        self_extracting: bool = False,
    ) -> Path:
        """Compute the destination path for a source and operation kind."""
        base = output_folder or source.parent
        if kind == GuiJobKind.COMPRESS:
            if password and self_extracting:
                if sys.platform == "darwin":
                    return base / (source.stem + ".app")
                return base / (source.stem + ".py")
            algorithm = (
                self._compress_page.selected_algorithm()
                or self._settings.default_algorithm
            )
            suffix = algorithm.archive_suffix(is_directory=source.is_dir())
            if password:
                return base / (source.name + suffix + ".lsenc")
            return base / (source.name + suffix)
        if kind == GuiJobKind.MEDIA_OPTIMIZE:
            suffix = source.suffix
            if (
                self._optimize_page.selected_mode() == MediaOptimizationMode.LOSSY
                and suffix.lower() == ".png"
            ):
                suffix = ".webp"
            return base / (source.stem + "-optimized" + suffix)
        if source.is_dir():
            return base / source.name
        name = source.name
        for suffix in (".tar.bz2", ".tar.xz", ".tar.gz", ".zip", ".bz2", ".xz", ".gz"):
            if name.lower().endswith(suffix):
                name = name[: -len(suffix)]
                break
        return base / name

    def _clear_completed(self) -> None:
        self._compress_page.table().clear_completed()
        self._decompress_page.table().clear_completed()
        self._optimize_page.table().clear_completed()
        self._history_page.table().clear_completed()
        self._queue.clear_completed()
        self._update_stats()

    def _on_job_added(self, job_id: UUID) -> None:
        job = self._queue.get_job(job_id)
        if job is None:
            return
        history = self._history_page.table()
        history.add_job_row(job)
        self._update_header(self._table_for_kind(job.kind), job.kind)

    def _on_job_updated(self, job_id: UUID) -> None:
        job = self._queue.get_job(job_id)
        if job is None:
            return
        self._table_for_kind(job.kind).update_job(job)
        self._history_page.table().update_job(job)
        self._update_header(self._table_for_kind(job.kind), job.kind)

    def _on_job_finished(self, job_id: UUID) -> None:
        self._on_job_updated(job_id)
        job = self._queue.get_job(job_id)
        if job is None or job.result is None:
            return
        result = job.result
        changes: dict[str, object] = {
            "last_used_folder": result.destination.parent,
        }
        if result.kind == OperationKind.COMPRESS:
            changes["last_used_algorithm"] = result.algorithm
        self._update_settings(**changes)
        self._update_stats()

    def _on_job_failed(self, job_id: UUID) -> None:
        self._on_job_updated(job_id)
        job = self._queue.get_job(job_id)
        if job is not None:
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setWindowTitle("Operation failed")
            dialog.setText(job.error_message or "The operation could not be completed.")
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.open()
        self._update_stats()

    def _on_algorithm_changed(self, _index: int = 0) -> None:
        self._update_header(self._compress_page.table(), GuiJobKind.COMPRESS)

    def _on_settings_changed(self) -> None:
        self._settings = self._settings_page.settings()
        self._apply_settings()
        app = QApplication.instance()
        if app is not None:
            theme.set_current_theme(self._settings.theme)
            app.setStyleSheet(load_theme(self._settings.theme))
        self._watch_service.update_folders(
            [folder for folder in self._settings.watch_folders if folder.enabled]
        )
        save_settings(self._settings)

    def _on_watch_event(self, event: WatchEvent) -> None:
        """Enqueue a job for a file detected by a watched folder."""
        config = event.config
        destination = derive_watch_destination(event.source, config)
        if config.operation == WatchOperationType.MEDIA_OPTIMIZE:
            self._queue.add_job(
                kind=GuiJobKind.MEDIA_OPTIMIZE,
                source=event.source,
                destination=destination,
                media_mode=config.media_mode,
            )
            return
        level = config.compression_level
        if level is not None and config.algorithm in {
            CompressionAlgorithm.GZIP,
            CompressionAlgorithm.BZ2,
        }:
            level = max(1, level)
        self._queue.add_job(
            kind=GuiJobKind.COMPRESS,
            source=event.source,
            destination=destination,
            algorithm=config.algorithm,
            compression_level=level or self._settings.compression_level,
            password=config.password,
            self_extracting=config.self_extracting,
        )

    def _update_header(self, table: JobTable | None, kind: GuiJobKind | None) -> None:
        if table is None:
            return
        total = table.rowCount()
        noun = "file" if total == 1 else "files"
        if kind == GuiJobKind.COMPRESS:
            algorithm = (
                self._compress_page.selected_algorithm()
                or self._settings.default_algorithm
            )
            self._compress_page.update_header(
                f"{total} {noun} · {algorithm.display_name}"
            )
        elif kind == GuiJobKind.DECOMPRESS:
            self._decompress_page.update_header(f"{total} {noun} · Auto-detect")
        elif kind == GuiJobKind.MEDIA_OPTIMIZE:
            mode = self._optimize_page.selected_mode()
            self._optimize_page.update_header(f"{total} {noun} · {mode.value.title()}")

    def _update_stats(self) -> None:
        jobs = list(self._queue.jobs)
        total = len(jobs)
        completed = sum(1 for job in jobs if job.status == GuiJobStatus.COMPLETED)
        completed_jobs = [job for job in jobs if job.status == GuiJobStatus.COMPLETED]
        compress_ratios = [
            job.result.compression_ratio
            for job in completed_jobs
            if job.result is not None and job.result.kind == OperationKind.COMPRESS
        ]
        average_ratio = (
            sum(compress_ratios) / len(compress_ratios) if compress_ratios else 0.0
        )
        media_savings = [
            job.result.space_savings_percentage
            for job in completed_jobs
            if job.result is not None
            and job.result.kind == OperationKind.MEDIA_OPTIMIZE
        ]
        average_savings = (
            sum(media_savings) / len(media_savings) if media_savings else 0.0
        )
        speeds = [
            job.throughput_mbps for job in completed_jobs if job.throughput_mbps > 0
        ]
        average_speed = sum(speeds) / len(speeds) if speeds else 0.0

        elapsed = sum(
            job.result.elapsed_seconds
            for job in completed_jobs
            if job.result is not None
        )
        compress_values = (
            (str(completed), f"/ {total}"),
            (f"{average_ratio:.1%}", ""),
            (f"{average_speed:.1f}", "MB/s"),
            (f"{elapsed:.1f}", "s"),
        )
        for card, (value, unit) in zip(
            self._compress_page._stats, compress_values, strict=True
        ):
            card.set_value(value, unit)
        for card, (value, unit) in zip(
            self._decompress_page._stats, compress_values, strict=True
        ):
            card.set_value(value, unit)
        optimize_values = (
            (str(completed), f"/ {total}"),
            (f"{average_savings:.1f}", "%"),
            (f"{average_speed:.1f}", "MB/s"),
            (f"{elapsed:.1f}", "s"),
        )
        for card, (value, unit) in zip(
            self._optimize_page._stats, optimize_values, strict=True
        ):
            card.set_value(value, unit)

    def _update_settings(self, **changes: object) -> None:
        self._settings = replace(self._settings, **changes)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._watch_service.stop()
        save_settings(self._settings)
        event.accept()
