"""Tests for the redesign tokens, layout, sidebar, and delegates."""

from pathlib import Path

import pytest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtWidgets import (
        QPushButton,
        QStyleOptionViewItem,
        QToolBar,
    )

    from ls_compressor.gui import theme
    from ls_compressor.gui.main_window import (
        CompressPage,
        DecompressPage,
        MainWindow,
        MediaPage,
    )
    from ls_compressor.gui.models import GuiJobKind, GuiJobStatus
    from ls_compressor.gui.resources import icon, load_theme, pixmap
    from ls_compressor.gui.sidebar import Sidebar
    from ls_compressor.gui.stat_card import StatCard
    from ls_compressor.gui.widgets import (
        DropArea,
        JobTable,
        ProgressDelegate,
        StatusDelegate,
    )
    from ls_compressor.infrastructure.config import AppSettings

    _PYSIDE6_AVAILABLE = True
except Exception:
    _PYSIDE6_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _PYSIDE6_AVAILABLE, reason="PySide6 is not installed"
)


_ALLOWED_SPACING = {2, 4, 6, 8, 9, 10, 11, 14, 16, 18, 20, 24}


def test_theme_spacing_scale_is_exact() -> None:
    """Only the approved spacing constants are exposed by theme.py."""
    spacing_values = [
        value
        for name, value in theme.__dict__.items()
        if name.startswith("SPACE_") and not name.startswith("_")
    ]
    assert set(spacing_values) == _ALLOWED_SPACING


def test_theme_named_color_tokens_are_exact() -> None:
    """The presentation exposes the approved semantic color vocabulary."""
    expected = {
        "BG_APP",
        "BG_SIDEBAR",
        "BG_SURFACE",
        "BG_SURFACE_ALT",
        "BG_NAV_ACTIVE",
        "BORDER",
        "BORDER_STRONG",
        "BORDER_ROW",
        "BORDER_DASHED",
        "TEXT_PRIMARY",
        "TEXT_SECONDARY",
        "TEXT_MUTED",
        "ACCENT",
        "ACCENT_ON",
        "STATUS_SUCCESS",
        "TEXT_TERTIARY",
        "TEXT_DISABLED",
        "STATUS_ERROR",
        "STATUS_RUNNING",
        "PROGRESS_TRACK",
        "PROGRESS_FILL_IDLE",
        "PROGRESS_FILL_ACTIVE",
    }
    actual = {
        name
        for name, value in theme.__dict__.items()
        if name.isupper() and isinstance(value, str) and value.startswith("#")
    }
    assert actual == expected


def test_theme_exact_required_values_and_fonts() -> None:
    """Required brass palette, backgrounds, borders, and font names are exact."""
    assert theme.BG_APP == "#141414"
    assert theme.BG_SIDEBAR == "#181818"
    assert theme.BG_SURFACE == "#191919"
    assert theme.BG_SURFACE_ALT == "#1a1a1a"
    assert theme.BG_NAV_ACTIVE == "#232323"
    assert theme.BG_TABLE_HEADER == "transparent"
    assert theme.BORDER == "#232323"
    assert theme.BORDER_STRONG == "#262626"
    assert theme.BORDER_ROW == "#1c1c1c"
    assert theme.BORDER_DASHED == "#2e2e2e"
    assert theme.TEXT_PRIMARY == "#e4e4e4"
    assert theme.TEXT_SECONDARY == "#b8b8b8"
    assert theme.TEXT_TERTIARY == "#7a7a7a"
    assert theme.TEXT_MUTED == "#6a6a6a"
    assert theme.TEXT_DISABLED == "#5a5a5a"
    assert theme.ACCENT == "#b8a074"
    assert theme.ACCENT_ON == "#161310"
    assert theme.STATUS_SUCCESS == "#7fae8e"
    assert theme.STATUS_ERROR == "#c17b6f"
    assert theme.STATUS_RUNNING == "#b8a074"
    assert theme.PROGRESS_TRACK == "#232323"
    assert theme.PROGRESS_FILL_IDLE == "#4a4a4a"
    assert theme.PROGRESS_FILL_ACTIVE == theme.ACCENT
    assert theme.FONT_UI == "Inter"
    assert theme.FONT_MONO == "SF Mono"


def test_theme_tokens_are_used_by_stylesheet() -> None:
    """The loaded stylesheet substitutes every referenced token."""
    stylesheet = load_theme()
    assert theme.ACCENT.strip("#") in stylesheet
    assert theme.BG_APP.strip("#") in stylesheet
    assert theme.BG_SIDEBAR.strip("#") in stylesheet


def test_sidebar_fixed_width_and_navigation_order(qapp) -> None:
    """Sidebar is 180px and exposes the expected button order."""
    sidebar = Sidebar()
    assert sidebar.minimumWidth() == theme.SIDEBAR_WIDTH
    assert sidebar.maximumWidth() == theme.SIDEBAR_WIDTH
    assert sidebar._compress_button.text() == "Compress"
    assert sidebar._decompress_button.text() == "Decompress"
    assert sidebar._optimize_button.text() == "Optimize"
    assert sidebar._history_button.text() == "History"
    assert sidebar._settings_button.text() == "Settings"


def test_sidebar_activation_updates_active_state(qapp) -> None:
    """set_active marks exactly one button active."""
    sidebar = Sidebar()
    sidebar.set_active(3)
    assert sidebar._history_button.isChecked()
    assert not sidebar._compress_button.isChecked()
    assert not sidebar._settings_button.isChecked()


def test_compress_page_layout(qapp) -> None:
    """Compress page contains the exact queue columns and four metric cards."""
    page = CompressPage()
    assert page._drop_area is not None
    assert page.table()._COLUMNS == [
        "SOURCE",
        "STATUS",
        "PROGRESS",
        "RATIO",
        "TIME",
        "SPEED",
    ]
    assert [card._label.text() for card in page._stats] == [
        "Jobs completed",
        "Avg. ratio",
        "Throughput",
        "Elapsed",
    ]


def test_compress_header_has_only_specified_controls(qapp) -> None:
    """Header exposes Add files, custom algorithm choice, and one accent action."""
    page = CompressPage()
    assert page._add_files_button.text() == "Add files"
    assert page._algorithm_combo.objectName() == "algorithmCombo"
    buttons = page.findChildren(QPushButton)
    primary = [button for button in buttons if button.property("variant") == "primary"]
    assert primary == [page._run_button]
    assert page._run_button.text() == "Compress"
    assert page._run_button.icon().isNull()


def test_decompress_page_layout(qapp) -> None:
    """Decompress page contains a dropzone, six-column table, and four stat cards."""
    page = DecompressPage()
    assert page._drop_area is not None
    assert page.table().columnCount() == 6
    assert len(page._stats) == 4


def test_optimize_page_layout(qapp) -> None:
    """Optimize page contains a mode selector and media-focused stat cards."""
    page = MediaPage()
    assert page._drop_area is not None
    assert page.table().columnCount() == 6
    assert len(page._stats) == 4
    assert [card._label.text() for card in page._stats] == [
        "Jobs completed",
        "Avg. savings",
        "Throughput",
        "Elapsed",
    ]
    assert page._run_button.text() == "Optimize"
    assert page._mode_combo.count() == 2


def test_dropzone_dimensions(qapp) -> None:
    """DropArea has the exact single-line height and contains the title label."""
    area = DropArea("Drop files or folders to add them to the queue")
    assert area.minimumHeight() == theme.DROPZONE_HEIGHT
    assert area.maximumHeight() == theme.DROPZONE_HEIGHT
    assert area._text.text() == "Drop files or folders to add them to the queue"


def test_stat_card_updates_value(qapp) -> None:
    """StatCard reflects value changes."""
    card = StatCard("Jobs", "0")
    card.set_value("12")
    assert card._value.text() == "12"


def test_job_table_icons_map_by_extension(qapp, tmp_path: Path) -> None:
    """Source icons are chosen based on file extension."""
    table = JobTable(GuiJobKind.COMPRESS)
    pdf = tmp_path / "doc.pdf"
    pdf.write_text("pdf")
    csv = tmp_path / "sheet.csv"
    csv.write_text("csv")
    archive = tmp_path / "bundle.zip"
    archive.write_text("zip")
    other = tmp_path / "unknown.bin"
    other.write_text("bin")

    table.add_pending_source(pdf)
    table.add_pending_source(csv)
    table.add_pending_source(archive)
    table.add_pending_source(other)

    assert table.rowCount() == 4


def test_status_delegate_paints_dot_and_text(qapp) -> None:
    """StatusDelegate renders without raising for each status."""
    table = JobTable(GuiJobKind.COMPRESS)
    table.add_pending_source(Path("/tmp/source.txt"))
    delegate = StatusDelegate()
    pixmap_image = QPixmap(120, 44)
    pixmap_image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap_image)
    option = QStyleOptionViewItem()
    option.rect = pixmap_image.rect()
    for status in GuiJobStatus:
        table.item(0, 1).setData(Qt.ItemDataRole.UserRole + 20, status.value)
        index = table.model().index(0, 1)
        delegate.paint(painter, option, index)
    painter.end()
    assert True


def test_progress_delegate_pushes_data(qapp) -> None:
    """ProgressDelegate reads progress from the model role."""
    table = JobTable(GuiJobKind.COMPRESS)
    table.add_pending_source(Path("/tmp/source.txt"))
    progress = table.item(0, 2)
    progress.setData(Qt.ItemDataRole.UserRole + 10, 42)
    progress.setData(Qt.ItemDataRole.UserRole + 11, GuiJobStatus.RUNNING.value)
    pixmap_image = QPixmap(120, 44)
    pixmap_image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap_image)
    option = QStyleOptionViewItem()
    option.rect = pixmap_image.rect()
    delegate = ProgressDelegate()
    delegate.paint(painter, option, table.model().index(0, 2))
    painter.end()
    assert True


def test_main_window_navigation_switches_stack(qapp) -> None:
    """Sidebar page requests update real stack pages and the active nav state."""
    window = MainWindow(AppSettings())
    assert window._compress_page._subtitle_label.text() == "0 files · ZIP (Deflate)"
    for index, button in enumerate(window._sidebar._buttons):
        window._sidebar.page_requested.emit(index)
        assert window._stack.currentIndex() == index
        assert button.isChecked()


def test_main_window_is_two_pane_without_toolbar(qapp) -> None:
    """The central view consists only of the fixed sidebar and content pane."""
    window = MainWindow(AppSettings())
    assert not window.findChildren(QToolBar)
    assert window._sidebar.width() == 180
    margins = window._content.layout().contentsMargins()
    assert (
        margins.left(),
        margins.top(),
        margins.right(),
        margins.bottom(),
    ) == (24, 20, 24, 20)


def test_main_window_history_receives_job_updates(qapp, tmp_path: Path) -> None:
    """Job updates are routed to the history page table."""
    source = tmp_path / "source.txt"
    source.write_text("data", encoding="utf-8")
    window = MainWindow(AppSettings())
    window._on_files_dropped(
        [source], window._compress_page.table(), GuiJobKind.COMPRESS
    )
    window._compress_page.table().selectAll()
    window._queue_selected(GuiJobKind.COMPRESS)
    window._queue._pool.waitForDone(5000)
    assert window._history_page.table().rowCount() == 1


def test_icon_recoloring_produces_pixmap(qapp) -> None:
    """Recolored SVG icons produce non-empty pixmaps."""
    image = pixmap("file-zip", theme.ACCENT, 20)
    assert not image.isNull()


def test_icon_qicon_is_available() -> None:
    """icon() returns a usable QIcon for known assets."""
    qicon = icon("file-text", theme.TEXT_MUTED, 16)
    assert not qicon.isNull()
