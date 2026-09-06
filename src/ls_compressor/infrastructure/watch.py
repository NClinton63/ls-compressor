"""Cross-platform hot-folder monitoring built on watchdog.

The service runs in its own background thread so it can be shared by the CLI
(foreground mode) and the GUI (background thread).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from ls_compressor.core.watch import WatchEvent, WatchFolderConfig

_LOGGER = logging.getLogger("ls_compressor.infrastructure.watch")

_DEBOUNCE_SECONDS = 2.0

WatchCallback = Callable[[WatchEvent], None]


class WatchService:
    """Monitor configured folders and dispatch watch events to a callback."""

    def __init__(self, callback: WatchCallback) -> None:
        """Initialize the service with an event dispatch callback."""
        self._callback = callback
        self._observer: Observer | None = None
        self._handlers: dict[Path, _FolderHandler] = {}
        self._configs: dict[Path, WatchFolderConfig] = {}
        self._last_processed: dict[Path, float] = {}

    def start(self) -> None:
        """Start the underlying watchdog observer if it is not already running."""
        if self._observer is not None:
            return
        self._observer = Observer()
        for config in self._configs.values():
            if config.enabled:
                self._attach(config)
        self._observer.start()
        _LOGGER.info("Watch service started with %d folder(s)", len(self._configs))

    def stop(self) -> None:
        """Stop the observer and clear active handlers."""
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join()
        self._observer = None
        self._handlers.clear()
        _LOGGER.info("Watch service stopped")

    def update_folders(self, configs: list[WatchFolderConfig]) -> None:
        """Replace the active folder configuration set and restart watches."""
        if self._observer is not None:
            for handler in self._handlers.values():
                self._observer.unschedule(handler._watch)
            self._handlers.clear()
        self._configs = {config.path.resolve(): config for config in configs}
        if self._observer is not None:
            for config in self._configs.values():
                if config.enabled:
                    self._attach(config)

    def add_folder(self, config: WatchFolderConfig) -> None:
        """Add or replace a single watch folder configuration."""
        path = config.path.resolve()
        if self._observer is not None and path in self._handlers:
            handler = self._handlers[path]
            self._observer.unschedule(handler._watch)
            del self._handlers[path]
        self._configs[path] = config
        if self._observer is not None and config.enabled:
            self._attach(config)

    def remove_folder(self, path: Path) -> None:
        """Remove a folder from the watched set."""
        resolved = path.resolve()
        if self._observer is not None and resolved in self._handlers:
            handler = self._handlers[resolved]
            self._observer.unschedule(handler._watch)
            del self._handlers[resolved]
        self._configs.pop(resolved, None)

    def _attach(self, config: WatchFolderConfig) -> None:
        """Schedule one folder with the active observer."""
        if not config.path.exists() or not config.path.is_dir():
            _LOGGER.warning("Watch folder does not exist: %s", config.path)
            return
        handler = _FolderHandler(config, self._dispatch)
        watch = self._observer.schedule(
            handler,
            str(config.path),
            recursive=config.recursive,
        )
        handler._watch = watch
        self._handlers[config.path.resolve()] = handler
        _LOGGER.info("Watching folder: %s", config.path)

    def _dispatch(
        self, source: Path, config: WatchFolderConfig, event_type: str
    ) -> None:
        """Filter and forward an observed filesystem event."""
        resolved = source.resolve()
        if not source.is_file():
            return
        if self._is_ignored(source, config):
            return
        now = time.monotonic()
        last = self._last_processed.get(resolved, 0.0)
        if now - last < _DEBOUNCE_SECONDS:
            return
        self._last_processed[resolved] = now
        _LOGGER.info("Dispatching watch event type=%s path=%s", event_type, source)
        self._callback(WatchEvent(source=source, config=config, event_type=event_type))

    @staticmethod
    def _is_ignored(source: Path, config: WatchFolderConfig) -> bool:
        """Return True for hidden files, temp files, and output-folder matches."""
        name = source.name
        if name.startswith(".") or name.startswith("~") or name.endswith(".tmp"):
            return True
        try:
            if config.output_folder.resolve() == source.parent.resolve():
                return True
        except OSError:
            pass
        return False


class _FolderHandler(FileSystemEventHandler):
    """Watchdog event handler that forwards file changes to the watch service."""

    def __init__(
        self,
        config: WatchFolderConfig,
        dispatch: Callable[[Path, WatchFolderConfig, str], None],
    ) -> None:
        self._config = config
        self._dispatch = dispatch
        self._watch: object | None = None

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._dispatch(Path(event.src_path), self._config, "created")

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._dispatch(Path(event.src_path), self._config, "modified")
