# AGENTS.md — ls-compressor

## Build order (do not skip ahead)
1. `core/models.py`, `core/exceptions.py`, `core/algorithms.py` — data structures 
   and algorithm enum first, no logic yet.
2. `core/compressor.py` + `core/verification.py` + `core/filesystem.py` — 
   implement against `models.py`. Write `tests/unit/` alongside each file, 
   not after.
3. `core/progress.py` — callback/observer pattern, no threading here (that's GUI's job).
4. `cli/main.py` — thin wrapper over `core/`. This is your integration-test 
   surface before GUI exists.
5. `infrastructure/config.py`, `infrastructure/logging.py`, `infrastructure/paths.py`.
6. `gui/` — only after CLI roundtrip tests pass.
7. `packaging/` + `.github/workflows/release.yml` — last.

## Media optimization phase (complete)
8. `core/media.py` — media format enum, request/result models, and strategy-based
   optimizer for PNG/JPEG/WebP images and FFmpeg-backed video recompression.
9. Extend `cli/main.py` with a `media` subcommand before wiring the GUI.
10. Extend `gui/` with a new "Optimize" sidebar page and job kind.
11. Update packaging and CI for new runtime dependencies (Pillow, imageio[ffmpeg]).

## Watch folders (Hot Folders) phase (complete)
12. `core/watch.py` — `WatchFolderConfig`, `WatchOperationType`, `WatchEvent`, and
    `process_watch_event`/`derive_watch_destination` helpers.
13. `infrastructure/watch.py` — `WatchService` built on `watchdog` to monitor folders
    in a background thread, debounce events, and ignore hidden/temp/output files.
14. Extend `infrastructure/config.py` to persist `watch_folders` in `AppSettings`.
15. Extend `cli/main.py` with a foreground `watch` subcommand.
16. Extend `gui/widgets.py` (SettingsDialog) and `gui/main_window.py` to add,
    remove, and persist watch folders; start the service on launch and feed
    detected files into the existing `JobQueue`.
17. Update packaging for the `watchdog` dependency.

## Rules
- Never let `core/` import from `gui/` or `cli/`. Dependency direction is one-way.
- Every function in `core/` needs a docstring + type hints before it's considered done.
- No file is "done" without a corresponding test in `tests/unit/` or `tests/integration/`.
- Run `pytest`, `black --check`, and `ruff check` before moving to the next 
  numbered step above — don't accumulate lint debt across steps.
- Use `logging`, never `print`, anywhere outside `cli/main.py`'s direct user output.

## Current status
- Steps 1-7, media optimization phase, and watch folders phase complete: core
  services, CLI with `media` and `watch` subcommands, sidebar-based PySide6 GUI
  with Compress/Decompress/Optimize/History/Settings pages including hot-folder
  settings, application assets, PyInstaller packaging, release automation, and
  documentation are implemented.
- Watch folders: `watchdog`-backed background monitoring, persistent folder list,
  foreground CLI watcher, GUI integration feeding the existing job queue, and
  themed Settings UI (including Dark/Light/System theme toggle).
- Final verification: 176 unit/integration tests pass; Black and Ruff pass;
  PyInstaller macOS bundle rebuild succeeds and includes the bundled FFmpeg binary.