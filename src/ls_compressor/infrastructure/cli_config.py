"""TOML-backed default overrides for the command-line interface.

A ``ls-compressor.toml`` file supplies per-command option defaults, e.g.::

    [compress]
    algorithm = "xz"
    level = 6
    exclude = ["*.tmp", "build/"]

    [media]
    mode = "lossy"
    quality = 80

Search order: an explicit ``--config PATH``, then
``./ls-compressor.toml``, then the platform config directory.
Command-line flags always override config values.
"""

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ls_compressor.core import (
    CompressionAlgorithm,
    CompressionPreset,
    EncryptionFormat,
    MediaOptimizationMode,
)
from ls_compressor.core.exceptions import InvalidRequestError
from ls_compressor.core.watch import WatchOperationType
from ls_compressor.infrastructure.paths import app_config_dir

CONFIG_FILENAME = "ls-compressor.toml"

_COMMAND_SECTIONS = {
    "compress",
    "decompress",
    "verify",
    "list",
    "media",
    "watch",
    "shell",
}

_ENUM_KEYS: Mapping[str, frozenset[str]] = {
    "algorithm": frozenset(
        algorithm.value for algorithm in CompressionAlgorithm if algorithm.can_compress
    ),
    "encryption": frozenset(fmt.value for fmt in EncryptionFormat),
    "preset": frozenset(preset.value for preset in CompressionPreset),
    "mode": frozenset(mode.value for mode in MediaOptimizationMode),
    "media_mode": frozenset(mode.value for mode in MediaOptimizationMode),
    "operation": frozenset(operation.value for operation in WatchOperationType),
}


def default_config_paths(cwd: Path | None = None) -> list[Path]:
    """Return the config search order, most specific first."""
    cwd = cwd or Path.cwd()
    return [cwd / CONFIG_FILENAME, app_config_dir() / CONFIG_FILENAME]


def load_cli_config(
    path: Path | None = None, cwd: Path | None = None
) -> dict[str, dict[str, Any]]:
    """Load CLI defaults from TOML, returning per-command sections.

    With ``path`` the file must exist; otherwise the first matching file in
    the default search order is used. An empty mapping means no overrides.
    """
    if path is not None:
        if not path.is_file():
            raise InvalidRequestError(f"Config file not found: {path}")
        return _validate(_read(path), path)
    for candidate in default_config_paths(cwd):
        if candidate.is_file():
            return _validate(_read(candidate), candidate)
    return {}


def _read(path: Path) -> dict[str, Any]:
    """Decode a TOML document or raise a user-facing error."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeError) as error:
        raise InvalidRequestError(f"Invalid config file {path}: {error}") from error


def _validate(document: dict[str, Any], path: Path) -> dict[str, dict[str, Any]]:
    """Validate config shape and known enum values."""
    sections: dict[str, dict[str, Any]] = {}
    for name, section in document.items():
        if name not in _COMMAND_SECTIONS:
            raise InvalidRequestError(
                f"Invalid config file {path}: unknown section [{name}]"
            )
        if not isinstance(section, dict):
            raise InvalidRequestError(
                f"Invalid config file {path}: [{name}] must be a table"
            )
        for key, value in section.items():
            if not isinstance(key, str):
                raise InvalidRequestError(
                    f"Invalid config file {path}: bad key in [{name}]"
                )
            normalized = key.replace("-", "_")
            if not isinstance(value, str | int | bool | list) or (
                isinstance(value, list)
                and not all(isinstance(item, str | int | bool) for item in value)
            ):
                raise InvalidRequestError(
                    f"Invalid config file {path}: [{name}] {key} must be a "
                    "string, number, boolean, or flat list"
                )
            allowed = _ENUM_KEYS.get(normalized)
            if allowed is not None and isinstance(value, str) and value not in allowed:
                raise InvalidRequestError(
                    f"Invalid config file {path}: [{name}] {key} = "
                    f"{value!r} is not a valid choice"
                )
            sections.setdefault(name, {})[normalized] = value
    return sections
