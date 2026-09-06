"""Unit tests for the settings dialog."""

from pathlib import Path

import pytest

try:
    from ls_compressor.core import CompressionAlgorithm
    from ls_compressor.core.watch import WatchFolderConfig, WatchOperationType
    from ls_compressor.gui.widgets import SettingsDialog
    from ls_compressor.infrastructure.config import (
        AppSettings,
        OutputLocationPreference,
        ThemePreference,
    )

    _PYSIDE6_AVAILABLE = True
except Exception:
    _PYSIDE6_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _PYSIDE6_AVAILABLE, reason="PySide6 is not installed"
)


def test_settings_dialog_roundtrip_defaults(qapp) -> None:
    """The dialog reflects default settings and returns an equal value."""
    dialog = SettingsDialog()
    defaults = AppSettings()
    dialog.set_settings(defaults)

    assert dialog.settings() == defaults


def test_settings_dialog_reads_algorithm_and_level(qapp) -> None:
    """The dialog extracts an updated algorithm and compression level."""
    dialog = SettingsDialog()
    dialog.set_settings(
        AppSettings(
            default_algorithm=CompressionAlgorithm.GZIP,
            compression_level=9,
            output_location_preference=OutputLocationPreference.ASK_EACH_TIME,
        )
    )

    result = dialog.settings()

    assert result.default_algorithm is CompressionAlgorithm.GZIP
    assert result.compression_level == 9
    assert result.output_location_preference is OutputLocationPreference.ASK_EACH_TIME


def test_settings_dialog_preserves_theme(qapp) -> None:
    """The theme selection survives the settings roundtrip."""
    dialog = SettingsDialog()
    dialog.set_settings(AppSettings(theme=ThemePreference.LIGHT))

    result = dialog.settings()

    assert result.theme is ThemePreference.LIGHT


def test_settings_dialog_preserves_last_used_fields(qapp) -> None:
    """Editing core settings keeps the remembered last-used folder/algorithm."""
    dialog = SettingsDialog()
    original = AppSettings(
        last_used_folder=Path("/tmp/last"),
        last_used_algorithm=CompressionAlgorithm.BZ2,
    )
    dialog.set_settings(original)

    result = dialog.settings()

    assert result.last_used_folder == Path("/tmp/last")
    assert result.last_used_algorithm is CompressionAlgorithm.BZ2


def test_settings_dialog_preserves_watch_folders(qapp) -> None:
    """The watch folder list survives the settings roundtrip."""
    dialog = SettingsDialog()
    original = AppSettings(
        watch_folders=(
            WatchFolderConfig(
                path=Path("/tmp/in"),
                output_folder=Path("/tmp/out"),
                operation=WatchOperationType.MEDIA_OPTIMIZE,
                enabled=False,
            ),
        ),
    )
    dialog.set_settings(original)

    result = dialog.settings()

    assert result.watch_folders == original.watch_folders
