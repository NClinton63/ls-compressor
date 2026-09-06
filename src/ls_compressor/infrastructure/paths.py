"""Platform-specific filesystem locations for application state."""

from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "LS Compressor"
APP_AUTHOR = "LS Compressor"
_CONFIG_FILENAME = "settings.json"
_LOG_FILENAME = "ls-compressor.log"


def _platform_dirs() -> PlatformDirs:
    """Return the platform directory resolver for LS Compressor."""
    return PlatformDirs(appname=APP_NAME, appauthor=APP_AUTHOR)


def _directory(path: str, *, create: bool) -> Path:
    """Return a directory path and optionally create it lazily."""
    directory = Path(path)
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def app_config_dir(*, create: bool = False) -> Path:
    """Return the platform-specific application configuration directory."""
    return _directory(_platform_dirs().user_config_dir, create=create)


def app_data_dir(*, create: bool = False) -> Path:
    """Return the platform-specific application data directory."""
    return _directory(_platform_dirs().user_data_dir, create=create)


def app_log_dir(*, create: bool = False) -> Path:
    """Return the platform-specific application log directory."""
    return _directory(_platform_dirs().user_log_dir, create=create)


def config_file_path(*, create_parent: bool = False) -> Path:
    """Return the settings file path and optionally create its parent directory."""
    return app_config_dir(create=create_parent) / _CONFIG_FILENAME


def log_file_path(*, create_parent: bool = False) -> Path:
    """Return the log file path and optionally create its parent directory."""
    return app_log_dir(create=create_parent) / _LOG_FILENAME
