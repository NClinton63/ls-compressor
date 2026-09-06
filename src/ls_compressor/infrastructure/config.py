"""Validated, JSON-backed application settings."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.watch import WatchFolderConfig
from ls_compressor.infrastructure.paths import config_file_path


class OutputLocationPreference(StrEnum):
    """Available behaviors for choosing compressed output locations."""

    SAME_FOLDER = "same_folder"
    ASK_EACH_TIME = "ask_each_time"


class ThemePreference(StrEnum):
    """Available application color themes."""

    DARK = "dark"
    LIGHT = "light"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Validated user preferences used by application interfaces."""

    default_algorithm: CompressionAlgorithm = CompressionAlgorithm.ZIP
    compression_level: int = 6
    output_location_preference: OutputLocationPreference = (
        OutputLocationPreference.SAME_FOLDER
    )
    last_used_folder: Path | None = None
    last_used_algorithm: CompressionAlgorithm | None = None
    watch_folders: tuple[WatchFolderConfig, ...] = ()
    theme: ThemePreference = ThemePreference.DARK

    def __post_init__(self) -> None:
        """Reject unsupported setting values."""
        if not isinstance(self.theme, ThemePreference):
            raise ValueError("theme must be a supported theme preference")
        if not isinstance(self.default_algorithm, CompressionAlgorithm):
            raise ValueError("default_algorithm must be a supported algorithm")
        if isinstance(self.compression_level, bool) or not isinstance(
            self.compression_level, int
        ):
            raise ValueError("compression_level must be an integer")
        if not 0 <= self.compression_level <= 9:
            raise ValueError("compression_level must be between 0 and 9")
        if not isinstance(self.output_location_preference, OutputLocationPreference):
            raise ValueError("output_location_preference must be supported")
        if self.last_used_folder is not None and not isinstance(
            self.last_used_folder, Path
        ):
            raise ValueError("last_used_folder must be a path or None")
        if self.last_used_algorithm is not None and not isinstance(
            self.last_used_algorithm, CompressionAlgorithm
        ):
            raise ValueError("last_used_algorithm must be supported or None")
        if not isinstance(self.watch_folders, tuple) or not all(
            isinstance(folder, WatchFolderConfig) for folder in self.watch_folders
        ):
            raise ValueError("watch_folders must be a tuple of WatchFolderConfig")
        if not isinstance(self.theme, ThemePreference):
            raise ValueError("theme must be a supported theme preference")

    def to_dict(self) -> dict[str, Any]:
        """Return settings represented by JSON-compatible values."""
        values = asdict(self)
        values["default_algorithm"] = self.default_algorithm.value
        values["output_location_preference"] = self.output_location_preference.value
        values["last_used_folder"] = (
            str(self.last_used_folder) if self.last_used_folder is not None else None
        )
        values["last_used_algorithm"] = (
            self.last_used_algorithm.value
            if self.last_used_algorithm is not None
            else None
        )
        values["watch_folders"] = [folder.to_dict() for folder in self.watch_folders]
        values["theme"] = self.theme.value
        return values

    def to_json(self) -> str:
        """Serialize settings to deterministic JSON text."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "AppSettings":
        """Build validated settings from decoded JSON values."""
        expected = {
            "default_algorithm",
            "compression_level",
            "output_location_preference",
            "last_used_folder",
            "last_used_algorithm",
            "watch_folders",
            "theme",
        }
        if set(values) - expected:
            raise ValueError("settings contain unsupported fields")
        folder = values.get("last_used_folder")
        last_algorithm = values.get("last_used_algorithm")
        watch_folders = values.get("watch_folders", [])
        theme_value = values.get("theme", ThemePreference.DARK.value)
        if not isinstance(watch_folders, list):
            raise ValueError("watch_folders must be a list")
        return cls(
            default_algorithm=CompressionAlgorithm(
                values.get("default_algorithm", CompressionAlgorithm.ZIP.value)
            ),
            compression_level=values.get("compression_level", 6),
            output_location_preference=OutputLocationPreference(
                values.get(
                    "output_location_preference",
                    OutputLocationPreference.SAME_FOLDER.value,
                )
            ),
            last_used_folder=Path(folder) if isinstance(folder, str) else folder,
            last_used_algorithm=(
                CompressionAlgorithm(last_algorithm)
                if last_algorithm is not None
                else None
            ),
            watch_folders=tuple(
                WatchFolderConfig.from_dict(item) for item in watch_folders
            ),
            theme=ThemePreference(theme_value),
        )

    @classmethod
    def from_json(cls, content: str) -> "AppSettings":
        """Deserialize and validate settings from JSON text."""
        values = json.loads(content)
        if not isinstance(values, dict):
            raise ValueError("settings JSON must contain an object")
        return cls.from_dict(values)


def load_settings(path: Path | None = None) -> AppSettings:
    """Load settings, returning safe defaults for unavailable or invalid data."""
    settings_path = path if path is not None else config_file_path()
    try:
        return AppSettings.from_json(settings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return AppSettings()


def save_settings(settings: AppSettings, path: Path | None = None) -> bool:
    """Atomically save settings and report whether persistence succeeded."""
    settings_path = path if path is not None else config_file_path()
    temporary_path: Path | None = None
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=settings_path.parent, prefix=f".{settings_path.name}.", suffix=".tmp"
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(settings.to_json())
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, settings_path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        return False
    return True
