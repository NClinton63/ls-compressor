"""Load embedded fonts, SVG icons, and locate project assets."""

import re
import sys
from pathlib import Path

from PySide6 import QtSvg  # noqa: F401
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from ls_compressor.gui import theme


def _project_root() -> Path:
    """Return the bundle root when frozen or the source project root."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        return Path(meipass)
    return Path(__file__).resolve().parents[3]


def _asset_directory() -> Path | None:
    """Return the project assets directory when running from source or a bundle."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        meipass_path = Path(meipass)
        candidates = [
            meipass_path / "assets",
            meipass_path.parent / "Resources" / "assets",
            meipass_path.parent / "assets",
        ]
        for path in candidates:
            if path.is_dir():
                return path
    path = _project_root() / "assets"
    return path if path.is_dir() else None


def theme_path() -> Path | None:
    """Locate the global QSS in source, installed, and frozen applications."""
    package_path = Path(__file__).with_name("theme.qss")
    candidates = [
        package_path,
        _project_root() / "src" / "ls_compressor" / "gui" / "theme.qss",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        candidates.insert(0, Path(meipass) / "ls_compressor" / "gui" / "theme.qss")
    return next((path for path in candidates if path.is_file()), None)


def load_theme(preference: theme.ThemePreference = theme.ThemePreference.DARK) -> str:
    """Return the bundled global stylesheet text with design tokens substituted."""
    path = theme_path()
    if path is None:
        return ""
    template = path.read_text(encoding="utf-8")
    tokens = theme.apply_theme_preference(preference)
    return template.format(**tokens)


def _theme_tokens(
    preference: theme.ThemePreference = theme.ThemePreference.DARK,
) -> dict[str, object]:
    """Map every public uppercase token from theme.py to its value."""
    return theme.apply_theme_preference(preference)


def load_fonts() -> list[str]:
    """Register embedded TrueType fonts and return the loaded font families."""
    assets = _asset_directory()
    if assets is None:
        return []
    font_dir = assets / "fonts"
    if not font_dir.is_dir():
        return []
    families: list[str] = []
    for font_file in sorted(font_dir.glob("*.ttf")):
        family_id = QFontDatabase.addApplicationFont(str(font_file))
        if family_id != -1:
            families.extend(QFontDatabase.applicationFontFamilies(family_id))
    return families


def icon_path(name: str) -> Path | None:
    """Return the filesystem path for an SVG icon when available."""
    assets = _asset_directory()
    if assets is None:
        return None
    path = assets / "icons" / f"{name}.svg"
    return path if path.is_file() else None


def icon(name: str, color: str | None = None, size: int | None = None) -> QIcon:
    """Return a QIcon built from a recolored project SVG asset.

    Parameters
    ----------
    name:
        Base name of the SVG file under ``assets/icons``.
    color:
        Optional stroke color override. Defaults to the theme's primary text color.
    size:
        Optional square pixmap size. If omitted, the icon is rendered at the SVG's
        native size and can be scaled by callers.
    """
    path = icon_path(name)
    if path is None:
        return QIcon()
    svg_color = color or theme.icon_color()
    pixmap = _render_svg(path, svg_color, size)
    return QIcon(pixmap)


def pixmap(name: str, color: str | None = None, size: int = 20) -> QPixmap:
    """Return a recolored SVG pixmap at the requested size."""
    path = icon_path(name)
    if path is None:
        return QPixmap(size, size)
    return _render_svg(path, color or theme.icon_color(), size)


def _render_svg(path: Path, color: str, size: int | None) -> QPixmap:
    """Render an SVG file with its stroke/fill recolored to ``color``."""
    source = path.read_text(encoding="utf-8")
    recolored = _replace_svg_colors(source, color)
    renderer = QSvgRenderer(QByteArray(recolored.encode("utf-8")))
    if size is None:
        default_size = renderer.defaultSize()
        pixmap = QPixmap(default_size)
    else:
        pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return pixmap


def _replace_svg_colors(source: str, color: str) -> str:
    """Replace any hard-coded stroke/fill colors in SVG text with ``color``."""
    source = re.sub(r'stroke="[^"]*"', f'stroke="{color}"', source)
    source = re.sub(r'fill="#[0-9a-fA-F]{3,8}"', f'fill="{color}"', source)
    source = re.sub(
        r'stroke:\s*[^;"\s]+',
        f"stroke:{color}",
        source,
    )
    source = re.sub(
        r"fill:\s*#[0-9a-fA-F]{3,8}",
        f"fill:{color}",
        source,
    )
    return source


def set_application_font(families: list[str] | None = None) -> None:
    """Apply Inter when embedded, otherwise the system default sans-serif font."""
    loaded_families = families if families is not None else load_fonts()
    application = QApplication.instance()
    if application is None:
        return
    if "Inter" in loaded_families:
        font = application.font()
        font.setFamily("Inter")
        application.setFont(font)
