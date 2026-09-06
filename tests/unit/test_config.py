"""Unit tests for application settings persistence."""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from ls_compressor.core import CompressionAlgorithm
from ls_compressor.core.watch import WatchFolderConfig, WatchOperationType
from ls_compressor.infrastructure.config import (
    AppSettings,
    OutputLocationPreference,
    ThemePreference,
    load_settings,
    save_settings,
)


def test_settings_have_sensible_defaults() -> None:
    """Fresh settings favor ZIP and nearby output without recent state."""
    settings = AppSettings()

    assert settings.default_algorithm is CompressionAlgorithm.ZIP
    assert settings.compression_level == 6
    assert settings.output_location_preference is OutputLocationPreference.SAME_FOLDER
    assert settings.last_used_folder is None
    assert settings.last_used_algorithm is None
    assert settings.watch_folders == ()
    assert settings.theme is ThemePreference.DARK


def test_settings_roundtrip_as_json(tmp_path: Path) -> None:
    """Every persisted setting retains its typed value after loading."""
    path = tmp_path / "nested" / "settings.json"
    settings = AppSettings(
        default_algorithm=CompressionAlgorithm.XZ,
        compression_level=9,
        output_location_preference=OutputLocationPreference.ASK_EACH_TIME,
        last_used_folder=tmp_path / "résumé",
        last_used_algorithm=CompressionAlgorithm.GZIP,
        theme=ThemePreference.LIGHT,
        watch_folders=(
            WatchFolderConfig(
                path=tmp_path / "watch",
                output_folder=tmp_path / "out",
                operation=WatchOperationType.MEDIA_OPTIMIZE,
                enabled=False,
            ),
        ),
    )

    assert save_settings(settings, path)

    assert load_settings(path) == settings
    assert path.read_text(encoding="utf-8").endswith("\n")


@pytest.mark.parametrize(
    "content",
    [
        "{broken",
        "[]",
        '{"default_algorithm": "rar"}',
        '{"compression_level": 10}',
        '{"compression_level": true}',
        '{"last_used_folder": 42}',
        '{"unexpected": "field"}',
        '{"watch_folders": "not-a-list"}',
        (
            '{"watch_folders": '
            '[{"path": "/tmp", "output_folder": "/tmp", "enabled": "yes"}]}'
        ),
    ],
)
def test_loading_invalid_settings_returns_defaults(
    tmp_path: Path, content: str
) -> None:
    """Corrupt or invalid user-controlled data never prevents startup."""
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")

    assert load_settings(path) == AppSettings()


def test_missing_settings_return_defaults_without_creating_files(
    tmp_path: Path,
) -> None:
    """Loading an absent injectable path has no write side effects."""
    path = tmp_path / "missing" / "settings.json"

    assert load_settings(path) == AppSettings()
    assert not path.parent.exists()


@pytest.mark.parametrize("level", [-1, 10, 1.5, True])
def test_settings_reject_invalid_compression_levels(level: object) -> None:
    """Compression level validation rejects values outside integer bounds."""
    with pytest.raises(ValueError):
        AppSettings(compression_level=cast(Any, level))


def test_json_serialization_has_only_portable_values(tmp_path: Path) -> None:
    """Serialized settings contain strings, numbers, and null values only."""
    watch = WatchFolderConfig(
        path=tmp_path / "watch",
        output_folder=tmp_path / "out",
    )
    settings = AppSettings(last_used_folder=tmp_path, watch_folders=(watch,))

    decoded = json.loads(settings.to_json())

    assert decoded["last_used_folder"] == str(tmp_path)
    assert decoded["default_algorithm"] == "zip"
    assert decoded["watch_folders"] == [watch.to_dict()]
    assert decoded["theme"] == "dark"


def test_failed_atomic_replace_preserves_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A persistence failure leaves the previous valid settings untouched."""
    path = tmp_path / "settings.json"
    original = AppSettings(compression_level=4)
    assert save_settings(original, path)

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("unavailable")

    monkeypatch.setattr("ls_compressor.infrastructure.config.os.replace", fail_replace)

    assert not save_settings(AppSettings(compression_level=8), path)
    assert load_settings(path) == original
    assert not list(tmp_path.glob("*.tmp"))
