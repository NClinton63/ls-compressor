"""Reusable GUI widgets for the LS Compressor main window."""

import sys
from pathlib import Path
from typing import ClassVar
from uuid import UUID

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QIcon,
    QPainter,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ls_compressor.core import (
    CompressionAlgorithm,
    MediaFormat,
    OperationKind,
)
from ls_compressor.core.watch import WatchFolderConfig, WatchOperationType
from ls_compressor.gui import theme
from ls_compressor.gui.models import GuiJob, GuiJobKind, GuiJobStatus
from ls_compressor.gui.resources import icon
from ls_compressor.infrastructure.config import (
    AppSettings,
    OutputLocationPreference,
    ThemePreference,
)

_SOURCE_ICON_EXTENSIONS: dict[str, frozenset[str]] = {
    "file-zip": frozenset(
        {".zip", ".gz", ".tar.gz", ".tar.xz", ".tar.bz2", ".xz", ".bz2"}
    ),
    "file-text": frozenset({".pdf", ".txt", ".md", ".doc", ".docx", ".rtf"}),
    "file-spreadsheet": frozenset({".csv", ".xls", ".xlsx", ".ods"}),
}


def _source_icon_name(path: Path) -> str:
    name = path.name.lower()
    for icon_name, extensions in _SOURCE_ICON_EXTENSIONS.items():
        if any(name.endswith(extension) for extension in extensions):
            return icon_name
    return "file"


def _path_font() -> QFont:
    """Return the platform monospace font with the specified fallbacks."""
    if sys.platform == "darwin":
        candidates = (theme.FONT_MONO, "Menlo")
    elif sys.platform == "win32":
        candidates = ("Consolas", "Courier New")
    else:
        candidates = ("DejaVu Sans Mono", "monospace")
    available = set(QFontDatabase.families())
    family = next((name for name in candidates if name in available), candidates[-1])
    font = QFont(family)
    font.setPixelSize(theme.FONT_SIZE_11)
    return font


class AlgorithmComboBox(QComboBox):
    """Algorithm selector with the same recolorable SVG language as the UI."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("algorithmCombo")
        self.setFixedWidth(theme.ALGORITHM_COMBO_WIDTH)
        self._arrow = QLabel(self)
        self._arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._arrow.setPixmap(
            icon("chevron-down", theme.TEXT_SECONDARY, theme.ICON_SIZE_SM).pixmap(
                theme.ICON_SIZE_SM, theme.ICON_SIZE_SM
            )
        )
        self._arrow.setFixedSize(theme.ICON_SIZE_SM, theme.ICON_SIZE_SM)

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Keep the decorative SVG aligned to the right edge."""
        super().resizeEvent(event)
        x = self.width() - theme.SPACE_14 - theme.ICON_SIZE_SM
        y = (self.height() - theme.ICON_SIZE_SM) // 2
        self._arrow.move(x, y)


class DropArea(QWidget):
    """Single-line drag-and-drop target with a primary label and hint."""

    files_dropped = Signal(list)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropArea")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAcceptDrops(True)
        self.setFixedHeight(theme.DROPZONE_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_16, theme.SPACE_16, theme.SPACE_16, theme.SPACE_16
        )
        layout.setSpacing(theme.SPACE_8)
        layout.addStretch()
        icon_label = QLabel()
        icon_label.setObjectName("dropIcon")
        icon_label.setPixmap(
            icon("upload", theme.TEXT_MUTED, theme.DROP_ICON_SIZE).pixmap(
                theme.DROP_ICON_SIZE, theme.DROP_ICON_SIZE
            )
        )
        self._text = QLabel(title)
        self._text.setObjectName("dropText")
        layout.addWidget(icon_label)
        layout.addWidget(self._text)
        layout.addStretch()

    def set_title(self, title: str) -> None:
        """Update the primary dropzone label."""
        self._text.setText(title)

    def _set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime is not None and (mime.hasUrls() or mime.hasText()):
            self._set_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._set_active(False)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._set_active(False)
        mime = event.mimeData()
        if mime is None:
            return
        paths: list[Path] = []
        if mime.hasUrls():
            paths.extend(
                Path(url.toLocalFile()) for url in mime.urls() if url.toLocalFile()
            )
        elif mime.hasText():
            paths.extend(
                path
                for line in mime.text().splitlines()
                if (path := Path(line.strip())).exists()
            )
        if paths:
            self.files_dropped.emit(paths)


class AccentDelegate(QStyledItemDelegate):
    """Base delegate that paints a 2px left accent on selected rows."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)
        if index.column() == 0 and option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRect(
                option.rect.left(),
                option.rect.top(),
                theme.SPACE_2,
                option.rect.height(),
            )
            painter.restore()


class SourceDelegate(AccentDelegate):
    """Paint source icons and mono filenames without native icon recoloring."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.fillRect(
            option.rect, QColor(theme.BG_SURFACE_ALT if selected else theme.BG_APP)
        )
        painter.setPen(QColor(theme.BORDER_ROW))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        left = option.rect.left() + theme.SPACE_16
        if selected:
            painter.fillRect(
                option.rect.left(),
                option.rect.top(),
                theme.SPACE_2,
                option.rect.height(),
                QColor(theme.ACCENT),
            )
            left += theme.SPACE_14
        decoration = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(decoration, QIcon):
            size = theme.NAV_ICON_SIZE
            top = option.rect.top() + (option.rect.height() - size) // 2
            decoration.paint(
                painter,
                left,
                top,
                size,
                size,
                Qt.AlignmentFlag.AlignCenter,
                QIcon.Mode.Normal,
            )
            left += size + theme.SPACE_8
        font = index.data(Qt.ItemDataRole.FontRole)
        if isinstance(font, QFont):
            painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_PRIMARY if selected else theme.TEXT_SECONDARY))
        text_rect = option.rect.adjusted(
            left - option.rect.left(), 0, -theme.SPACE_16, 0
        )
        text = QFontMetrics(painter.font()).elidedText(
            str(index.data() or ""), Qt.TextElideMode.ElideRight, text_rect.width()
        )
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text
        )
        painter.restore()


class ProgressDelegate(AccentDelegate):
    """Thin 3px progress bar delegate using neutral idle and accent for activity."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)
        value = index.data(Qt.ItemDataRole.UserRole + 10) or 0
        if not isinstance(value, int | float):
            value = 0
        value = max(0, min(100, int(value)))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        running = (
            index.data(Qt.ItemDataRole.UserRole + 11) == GuiJobStatus.RUNNING.value
        )
        margin = theme.SPACE_14
        bar_height = theme.PROGRESS_BAR_HEIGHT
        y = option.rect.top() + (option.rect.height() - bar_height) // 2
        track_rect = option.rect.adjusted(margin, 0, -margin, 0)
        track_rect.setTop(y)
        track_rect.setHeight(bar_height)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.PROGRESS_TRACK))
        painter.drawRect(track_rect)
        fill_width = int(track_rect.width() * value / 100)
        fill_rect = track_rect.adjusted(0, 0, 0, 0)
        fill_rect.setWidth(fill_width)
        if running or selected:
            painter.setBrush(QColor(theme.PROGRESS_FILL_ACTIVE))
        else:
            painter.setBrush(QColor(theme.PROGRESS_FILL_IDLE))
        painter.drawRect(fill_rect)
        painter.restore()


class StatusDelegate(AccentDelegate):
    """Status cell renderer using a 5px dot and colored text, no badge/pill."""

    _COLORS: ClassVar[dict[GuiJobStatus, str]] = {
        GuiJobStatus.PENDING: theme.TEXT_MUTED,
        GuiJobStatus.RUNNING: theme.STATUS_RUNNING,
        GuiJobStatus.COMPLETED: theme.STATUS_SUCCESS,
        GuiJobStatus.FAILED: theme.STATUS_ERROR,
    }

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)
        status_value = index.data(Qt.ItemDataRole.UserRole + 20)
        status = GuiJobStatus(status_value) if status_value else GuiJobStatus.PENDING
        color = self._COLORS.get(status, theme.TEXT_MUTED)
        text = {
            GuiJobStatus.PENDING: "Pending",
            GuiJobStatus.RUNNING: "Compressing…",
            GuiJobStatus.COMPLETED: "Completed",
            GuiJobStatus.FAILED: "Failed",
        }[status]
        dot_size = theme.STATUS_DOT_SIZE
        spacing = theme.SPACE_8
        x = option.rect.left() + theme.SPACE_14
        y = option.rect.top() + (option.rect.height() - dot_size) // 2
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(x, y, dot_size, dot_size))
        text_x = x + dot_size + spacing
        text_rect = option.rect.adjusted(text_x - option.rect.left(), 0, 0, 0)
        painter.setPen(QColor(color))
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text
        )
        painter.restore()


class JobTable(QTableWidget):
    """Persistent table of pending sources and queued compression jobs."""

    _TYPE_ROLE = Qt.ItemDataRole.UserRole
    _DATA_ROLE = Qt.ItemDataRole.UserRole + 1
    _STATUS_ROLE = Qt.ItemDataRole.UserRole + 20
    _PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 10
    _RUNNING_ROLE = Qt.ItemDataRole.UserRole + 11
    _COLUMNS: ClassVar[list[str]] = [
        "SOURCE",
        "STATUS",
        "PROGRESS",
        "RATIO",
        "TIME",
        "SPEED",
    ]

    def __init__(
        self, kind: GuiJobKind | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self.setObjectName("jobTable")
        self.setColumnCount(len(self._COLUMNS))
        self.setHorizontalHeaderLabels(self._COLUMNS)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(theme.TABLE_ROW_HEIGHT)
        self.verticalHeader().setMinimumSectionSize(theme.TABLE_ROW_HEIGHT)
        self.horizontalHeader().setFixedHeight(theme.TABLE_HEADER_HEIGHT)
        self.horizontalHeader().setStretchLastSection(False)
        self.setItemDelegate(AccentDelegate(self))
        self.setItemDelegateForColumn(0, SourceDelegate(self))
        self.setItemDelegateForColumn(1, StatusDelegate(self))
        self.setItemDelegateForColumn(2, ProgressDelegate(self))
        self._resize_columns()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        """Maintain the specified fractional column proportions."""
        super().resizeEvent(event)
        self._resize_columns()

    def _resize_columns(self) -> None:
        """Size columns according to the six specified proportions."""
        weights = (2.2, 0.9, 1.0, 0.9, 0.8, 0.9)
        available = max(0, self.viewport().width())
        total = sum(weights)
        widths = [int(available * weight / total) for weight in weights]
        widths[-1] += available - sum(widths)
        for column, width in enumerate(widths):
            self.setColumnWidth(column, width)

    def add_pending_source(self, source: Path) -> int:
        row = self.rowCount()
        self.insertRow(row)
        source_item = self._make_item(source.name)
        source_item.setToolTip(str(source))
        source_item.setFont(_path_font())
        source_item.setIcon(
            icon(_source_icon_name(source), theme.TEXT_MUTED, theme.NAV_ICON_SIZE)
        )
        source_item.setData(self._TYPE_ROLE, "pending")
        source_item.setData(self._DATA_ROLE, str(source))
        source_item.setData(self._STATUS_ROLE, GuiJobStatus.PENDING.value)
        self.setItem(row, 0, source_item)
        for column in (3, 4, 5):
            self.setItem(row, column, self._make_metric_item("-"))
        self._set_status(row, GuiJobStatus.PENDING)
        self._set_progress(row, 0)
        return row

    def pending_sources(self) -> list[tuple[int, Path]]:
        rows = []
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item is not None and item.data(self._TYPE_ROLE) == "pending":
                rows.append((row, Path(item.data(self._DATA_ROLE))))
        return rows

    def convert_row_to_job(
        self,
        row: int,
        job_id: UUID,
        kind: GuiJobKind,
        destination: Path,
        algorithm: CompressionAlgorithm | None = None,
        media_format: MediaFormat | None = None,
    ) -> None:
        item = self.item(row, 0)
        if item is None:
            return
        item.setData(self._TYPE_ROLE, "job")
        item.setData(self._DATA_ROLE, str(job_id))
        operation = kind.value.replace("_", " ")
        item.setToolTip(
            f"Source: {item.text()}\nOutput: {destination}\nOperation: {operation}"
        )
        self._set_status(row, GuiJobStatus.PENDING)
        self._set_progress(row, 0)

    def add_job_row(self, job: GuiJob) -> int:
        """Append a new row representing an already-queued job."""
        row = self.rowCount()
        self.insertRow(row)
        source_item = self._make_item(job.source.name)
        source_item.setToolTip(str(job.source))
        source_item.setFont(_path_font())
        source_item.setIcon(
            icon(_source_icon_name(job.source), theme.TEXT_MUTED, theme.NAV_ICON_SIZE)
        )
        source_item.setData(self._TYPE_ROLE, "job")
        source_item.setData(self._DATA_ROLE, str(job.job_id))
        self.setItem(row, 0, source_item)
        for column in (3, 4, 5):
            self.setItem(row, column, self._make_metric_item("-"))
        self._set_status(row, GuiJobStatus.PENDING)
        self._set_progress(row, 0, GuiJobStatus.PENDING)
        return row

    def update_job(self, job: GuiJob) -> None:
        row = self._row_for_job(job.job_id)
        if row is None:
            return
        self._set_status(row, job.status)
        self._set_progress(row, int(job.progress_percent), job.status)
        if job.result is not None:
            result = job.result
            source = self.item(row, 0)
            if source is not None:
                source.setToolTip(
                    f"Source: {source.text()}\nOutput: {result.destination}"
                )
            if result.kind == OperationKind.COMPRESS:
                ratio = f"{result.compression_ratio:.1%}"
            elif result.kind == OperationKind.MEDIA_OPTIMIZE:
                ratio = f"{result.space_savings_percentage:.1f}%"
            else:
                ratio = "-"
            self.setItem(row, 3, self._make_metric_item(ratio))
            self.setItem(
                row, 4, self._make_metric_item(f"{result.elapsed_seconds:.1f}s")
            )
            self.setItem(
                row, 5, self._make_metric_item(f"{job.throughput_mbps:.1f} MB/s")
            )

    def clear_completed(self) -> None:
        for row in range(self.rowCount() - 1, -1, -1):
            status = self.item(row, 1)
            if status is not None:
                value = status.data(self._STATUS_ROLE)
                if value in {GuiJobStatus.COMPLETED.value, GuiJobStatus.FAILED.value}:
                    self.removeRow(row)

    def _row_for_job(self, job_id: UUID) -> int | None:
        target = str(job_id)
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item is not None and item.data(self._DATA_ROLE) == target:
                return row
        return None

    def _set_progress(
        self, row: int, value: int, status: GuiJobStatus | None = None
    ) -> None:
        progress_item = self.item(row, 2)
        if progress_item is None:
            progress_item = self._make_item("")
            self.setItem(row, 2, progress_item)
        progress_item.setData(self._PROGRESS_ROLE, value)
        progress_item.setData(
            self._RUNNING_ROLE, status.value if status else GuiJobStatus.PENDING.value
        )

    def _set_status(self, row: int, status: GuiJobStatus) -> None:
        status_item = self.item(row, 1)
        if status_item is None:
            status_item = self._make_item("")
            self.setItem(row, 1, status_item)
        status_item.setData(self._STATUS_ROLE, status.value)

    def _make_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        return item

    def _make_metric_item(self, text: str) -> QTableWidgetItem:
        """Build a read-only right-aligned metric item."""
        item = self._make_item(text)
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        )
        return item


class SettingsDialog(QWidget):
    """Inline settings editor for application default preferences and watch folders."""

    accepted = Signal()
    rejected = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setMinimumWidth(440)
        self._last_used_folder: Path | None = None
        self._last_used_algorithm: CompressionAlgorithm | None = None
        self._algorithm = QComboBox()
        for algorithm in CompressionAlgorithm:
            self._algorithm.addItem(algorithm.display_name, algorithm.value)
        self._level = QSpinBox()
        self._level.setRange(0, 9)
        self._algorithm.currentIndexChanged.connect(self._update_level_range)
        self._same_folder = QRadioButton("Same folder as source")
        self._ask = QRadioButton("Ask each time")
        self._theme = QComboBox()
        self._theme.addItem("Dark", ThemePreference.DARK.value)
        self._theme.addItem("Light", ThemePreference.LIGHT.value)
        self._theme.addItem("System", ThemePreference.SYSTEM.value)
        self._output_group = QButtonGroup(self)
        self._output_group.addButton(self._same_folder)
        self._output_group.addButton(self._ask)

        self._watch_list = QListWidget(self)
        self._watch_list.setObjectName("watchFolderList")
        self._watch_list.setMinimumHeight(120)
        add_watch_button = QPushButton("Add folder")
        add_watch_button.clicked.connect(self._add_watch_folder)
        remove_watch_button = QPushButton("Remove")
        remove_watch_button.clicked.connect(self._remove_watch_folder)
        watch_buttons = QHBoxLayout()
        watch_buttons.setContentsMargins(0, 0, 0, 0)
        watch_buttons.setSpacing(theme.SPACE_8)
        watch_buttons.addWidget(add_watch_button)
        watch_buttons.addWidget(remove_watch_button)
        watch_layout = QVBoxLayout()
        watch_layout.setContentsMargins(0, 0, 0, 0)
        watch_layout.setSpacing(theme.SPACE_8)
        watch_layout.addWidget(self._watch_list)
        watch_layout.addLayout(watch_buttons)
        watch_container = QWidget(self)
        watch_container.setLayout(watch_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accepted.emit)
        buttons.rejected.connect(self.rejected.emit)
        layout = QFormLayout(self)
        layout.setContentsMargins(
            theme.SPACE_24, theme.SPACE_24, theme.SPACE_24, theme.SPACE_24
        )
        layout.setSpacing(theme.SPACE_16)
        layout.addRow("Default algorithm", self._algorithm)
        layout.addRow("Compression level", self._level)
        output_layout = QHBoxLayout()
        output_layout.setSpacing(theme.SPACE_16)
        output_layout.addWidget(self._same_folder)
        output_layout.addWidget(self._ask)
        layout.addRow("Output location", output_layout)
        layout.addRow("Theme", self._theme)
        layout.addRow("Watch folders", watch_container)
        layout.addRow(buttons)

    def _update_level_range(self) -> None:
        self._level.setRange(
            1 if self._algorithm.currentData() in {"gzip", "bz2"} else 0, 9
        )

    def set_settings(self, settings: AppSettings) -> None:
        index = self._algorithm.findData(settings.default_algorithm.value)
        if index >= 0:
            self._algorithm.setCurrentIndex(index)
        self._level.setValue(settings.compression_level)
        (
            self._same_folder
            if settings.output_location_preference
            is OutputLocationPreference.SAME_FOLDER
            else self._ask
        ).setChecked(True)
        theme_index = self._theme.findData(settings.theme.value)
        if theme_index >= 0:
            self._theme.setCurrentIndex(theme_index)
        self._last_used_folder = settings.last_used_folder
        self._last_used_algorithm = settings.last_used_algorithm
        self._watch_list.clear()
        for folder in settings.watch_folders:
            item = self._watch_list_item(folder)
            self._watch_list.addItem(item)

    def settings(self) -> AppSettings:
        value = self._algorithm.currentData()
        algorithm = (
            CompressionAlgorithm(value)
            if value is not None
            else CompressionAlgorithm.ZIP
        )
        preference = (
            OutputLocationPreference.SAME_FOLDER
            if self._same_folder.isChecked()
            else OutputLocationPreference.ASK_EACH_TIME
        )
        theme_value = self._theme.currentData()
        watch_folders: list[WatchFolderConfig] = []
        for row in range(self._watch_list.count()):
            item = self._watch_list.item(row)
            config = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(config, WatchFolderConfig):
                watch_folders.append(config)
        return AppSettings(
            default_algorithm=algorithm,
            compression_level=self._level.value(),
            output_location_preference=preference,
            last_used_folder=self._last_used_folder,
            last_used_algorithm=self._last_used_algorithm,
            watch_folders=tuple(watch_folders),
            theme=(
                ThemePreference(theme_value)
                if theme_value is not None
                else ThemePreference.DARK
            ),
        )

    def _watch_list_item(self, config: WatchFolderConfig) -> QListWidgetItem:
        label = f"{config.path} → {config.output_folder} ({config.operation.value})"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, config)
        return item

    def _add_watch_folder(self) -> None:
        default_dir = str(self._last_used_folder or Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "Select watch folder", default_dir
        )
        if not folder:
            return
        output = QFileDialog.getExistingDirectory(self, "Select output folder", folder)
        if not output:
            return
        config = WatchFolderConfig(
            path=Path(folder),
            output_folder=Path(output),
            operation=WatchOperationType.COMPRESS,
            algorithm=CompressionAlgorithm.ZIP,
        )
        self._watch_list.addItem(self._watch_list_item(config))

    def _remove_watch_folder(self) -> None:
        for item in self._watch_list.selectedItems():
            self._watch_list.takeItem(self._watch_list.row(item))
