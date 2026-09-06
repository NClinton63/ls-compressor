"""Application entry point for the LS Compressor desktop GUI."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ls_compressor.gui import theme as theme_module
from ls_compressor.gui.main_window import MainWindow
from ls_compressor.gui.resources import load_fonts, load_theme, set_application_font
from ls_compressor.infrastructure.config import load_settings, save_settings
from ls_compressor.infrastructure.logging import configure_logging


def _apply_theme(application: QApplication, theme_preference: object) -> None:
    """Load the chosen theme stylesheet and apply it to the application."""
    theme_module.set_current_theme(theme_preference)
    application.setStyleSheet(load_theme(theme_preference))


def _configure_platform(application: QApplication) -> None:
    """Apply platform-specific settings for a native-looking window."""
    application.setStyle("Fusion")
    application.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, True)


def main() -> int:
    """Start the GUI and return the application exit code."""
    configure_logging(0)
    application = QApplication(sys.argv)
    application.setApplicationName("LS Compressor")
    application.setApplicationVersion("0.1.0")
    application.setOrganizationName("LS Compressor")
    _configure_platform(application)

    font_families = load_fonts()
    set_application_font(font_families)

    settings = load_settings()
    _apply_theme(application, settings.theme)
    window = MainWindow(settings)
    window.show()

    exit_code = application.exec()
    save_settings(window.settings())
    return exit_code
