"""Application infrastructure for settings, paths, and logging."""

from ls_compressor.infrastructure.config import (
    AppSettings,
    OutputLocationPreference,
    load_settings,
    save_settings,
)
from ls_compressor.infrastructure.logging import configure_logging
from ls_compressor.infrastructure.paths import (
    APP_AUTHOR,
    APP_NAME,
    app_config_dir,
    app_data_dir,
    app_log_dir,
    config_file_path,
    log_file_path,
)

__all__ = [
    "APP_AUTHOR",
    "APP_NAME",
    "AppSettings",
    "OutputLocationPreference",
    "app_config_dir",
    "app_data_dir",
    "app_log_dir",
    "config_file_path",
    "configure_logging",
    "load_settings",
    "log_file_path",
    "save_settings",
]
