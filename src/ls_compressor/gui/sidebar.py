"""Fixed-width sidebar with logo, primary nav, and settings navigation."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ls_compressor.gui import theme
from ls_compressor.gui.resources import icon, pixmap


class Sidebar(QWidget):
    """180px fixed sidebar driving stacked-view navigation.

    Navigation buttons are ordered Compress, Decompress, History, then a stretch,
    then Settings. Activating a nav button emits :pyattr:`page_requested` with the
    target page index.
    """

    page_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedWidth(theme.SIDEBAR_WIDTH)
        self._buttons: list[QPushButton] = []
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SIDEBAR_PADDING,
            theme.SPACE_18,
            theme.SIDEBAR_PADDING,
            theme.SPACE_18,
        )
        layout.setSpacing(theme.SPACE_2)

        logo = QWidget(self)
        logo_layout = QHBoxLayout(logo)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.setSpacing(theme.SPACE_8)
        mark = QLabel()
        mark.setObjectName("logoMark")
        mark.setFixedSize(theme.LOGO_SIZE, theme.LOGO_SIZE)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setPixmap(pixmap("logo", theme.ACCENT, theme.LOGO_ICON_SIZE))
        text = QLabel("LS Compressor")
        text.setObjectName("logoText")
        logo_layout.addWidget(mark)
        logo_layout.addWidget(text)
        logo_layout.addStretch()
        layout.addWidget(logo)
        layout.addSpacing(theme.SPACE_18)

        self._compress_button = self._nav_button("compress", "Compress", 0)
        self._decompress_button = self._nav_button("decompress", "Decompress", 1)
        self._optimize_button = self._nav_button("optimize", "Optimize", 2)
        self._history_button = self._nav_button("history", "History", 3)
        layout.addWidget(self._compress_button)
        layout.addWidget(self._decompress_button)
        layout.addWidget(self._optimize_button)
        layout.addWidget(self._history_button)
        layout.addStretch()
        self._settings_button = self._nav_button("settings", "Settings", 4)
        layout.addWidget(self._settings_button)

    def _nav_button(self, icon_name: str, label: str, page_index: int) -> QPushButton:
        button = QPushButton(icon(icon_name, theme.TEXT_MUTED), label, self)
        button.setProperty("variant", "nav")
        button.setProperty("iconName", icon_name)
        button.setIconSize(QSize(theme.NAV_ICON_SIZE, theme.NAV_ICON_SIZE))
        button.setCheckable(True)
        self._nav_group.addButton(button)
        button.setProperty("active", False)
        button.clicked.connect(
            lambda _checked, idx=page_index: self.page_requested.emit(idx)
        )
        self._buttons.append(button)
        return button

    def set_active(self, index: int) -> None:
        """Visually mark the button at ``index`` as active and clear the others."""
        for idx, button in enumerate(self._buttons):
            active = idx == index
            button.setChecked(active)
            button.setProperty("active", active)
            icon_name = button.property("iconName")
            color = theme.ACCENT if active else theme.TEXT_MUTED
            button.setIcon(icon(icon_name, color, theme.NAV_ICON_SIZE))
            button.style().unpolish(button)
            button.style().polish(button)
