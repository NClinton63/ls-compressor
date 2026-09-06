"""Compact aggregate metric card."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ls_compressor.gui import theme


class StatCard(QWidget):
    """Display a metric label, value, and optional muted unit."""

    def __init__(
        self,
        label: str,
        value: str = "0",
        unit: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedHeight(theme.STAT_CARD_HEIGHT)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_14, theme.SPACE_11, theme.SPACE_14, theme.SPACE_11
        )
        layout.setSpacing(theme.SPACE_4)
        self._label = QLabel(label)
        self._label.setProperty("role", "statLabel")
        self._value = QLabel(value)
        self._value.setProperty("role", "statValue")
        self._unit = QLabel(unit)
        self._unit.setProperty("role", "statUnit")
        value_layout = QHBoxLayout()
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(theme.SPACE_4)
        value_layout.addWidget(self._value)
        value_layout.addWidget(self._unit, 0, Qt.AlignmentFlag.AlignBottom)
        value_layout.addStretch()
        layout.addWidget(self._label)
        layout.addLayout(value_layout)

    def set_value(self, value: str, unit: str | None = None) -> None:
        """Update the displayed metric value and optionally its unit."""
        self._value.setText(value)
        if unit is not None:
            self._unit.setText(unit)
