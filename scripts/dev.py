"""Dev-mode launcher: run the GUI from source and auto-restart on file changes."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

ROOT = Path(__file__).resolve().parents[1]
WATCH_DIRS = [ROOT / "src", ROOT / "assets"]
APP_MODULE = "ls_compressor.gui.application"


def _is_interesting(event: FileSystemEvent) -> bool:
    path = Path(event.src_path)
    if path.name.startswith(".") or "__pycache__" in path.parts:
        return False
    return event.event_type in {"modified", "created", "moved", "deleted"}


class RelaunchHandler(FileSystemEventHandler):
    """Restart the GUI process when source or asset files change."""

    def __init__(self, process_holder: list[subprocess.Popen | None]) -> None:
        self._process_holder = process_holder
        self._last_relaunch = 0.0

    def on_any_event(self, event: FileSystemEvent) -> None:
        if not _is_interesting(event):
            return
        now = time.monotonic()
        if now - self._last_relaunch < 1.0:
            return
        self._last_relaunch = now
        print(f"Change detected: {event.src_path}")
        _stop_process(self._process_holder)
        self._process_holder[0] = _start_process()


def _start_process() -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    print("Starting LS Compressor GUI...")
    return subprocess.Popen(
        [sys.executable, "-m", APP_MODULE],
        cwd=ROOT,
        env=env,
    )


def _stop_process(process_holder: list[subprocess.Popen | None]) -> None:
    process = process_holder[0]
    if process is None:
        return
    print("Stopping previous GUI process...")
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    process_holder[0] = None


def main() -> int:
    """Run the GUI and relaunch it whenever source files change."""
    process_holder: list[subprocess.Popen | None] = [None]
    process_holder[0] = _start_process()

    observer = Observer()
    handler = RelaunchHandler(process_holder)
    for directory in WATCH_DIRS:
        observer.schedule(handler, str(directory), recursive=True)
    observer.start()

    print("Watching src/ and assets/ for changes. Press Ctrl-C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping dev server...")
    finally:
        observer.stop()
        _stop_process(process_holder)
        observer.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
