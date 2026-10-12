# LS Compressor — Feature Documentation

LS Compressor is a cross-platform desktop application for lossless file/folder
compression, archive encryption, media optimization, and automated "hot folder"
processing. It exposes the same core engine through a PySide6 GUI and a
command-line interface.

## Architecture overview

The codebase follows a strict one-way dependency direction:

```
gui/ ─┐
cli/ ─┼─> core/          (domain logic: compression, media, encryption, watch models)
      └─> infrastructure/ (config, logging, paths, watchdog service)
```

- `core/` never imports from `gui/` or `cli/`. All operations are described by
  immutable, frozen request/result dataclasses (`CompressionRequest`,
  `DecompressionRequest`, `MediaOptimizationRequest`, `OperationResult`,
  `OperationProgress`), making every entry point testable without a filesystem
  or a UI.
- Progress is delivered through a callback/observer pattern
  (`core/progress.py`); threading lives entirely in the GUI layer
  (`gui/workers.py`, `gui/queue.py`).
- Every public function carries type hints and docstrings; behavior is covered
  by `tests/unit/` and `tests/integration/` (176 tests).

---

## 1. Compression & decompression

**Algorithms** (`core/algorithms.py`):

| Algorithm | Enum value | File output | Folder output |
|-----------|-----------|-------------|---------------|
| Zstandard (default) | `zstd` | `.zst` | `.tar.zst` |
| ZIP (Deflate) | `zip` | `.zip` | `.zip` |
| LZMA (XZ) | `xz` | `.xz` | `.tar.xz` |
| GZIP | `gzip` | `.gz` | `.tar.gz` |
| BZ2 | `bz2` | `.bz2` | `.tar.bz2` |
| 7-Zip (extraction only) | `7z` | — | `.7z` |
| RAR (extraction only) | `rar` | — | `.rar` |

- **7z and RAR extraction.** Third-party archives in these formats can be
  verified and extracted, including password-protected 7z/RAR archives
  (`--password`). `Algorithm.can_compress` is `False` for both, so they are
  excluded from compression choices in the CLI, GUI, settings, and watch
  folders. RAR extraction shells out to a system `unrar`/`unar` tool via
  `rarfile`; when no backend is installed the operation fails with a clear
  message instead of silently failing.

- **Zstandard is the default algorithm** — modern, fast, strong ratios, with
  full `.zst` stream and `.tar.zst` container support including integrity
  verification and self-extracting launchers (which prompt for `pip install
  zstandard` on machines without it).
- Folder sources are automatically tar-bundled for stream formats
  (Zstd/XZ/GZIP/BZ2); ZIP archives directories natively.
- **Multi-source archives**: `CompressionRequest.extra_sources` (or multiple
  `SRC` arguments before `DEST` in the CLI) packs several files/folders into
  one container. Each source becomes a top-level member named after itself;
  sources must have unique names. Stream algorithms automatically switch to
  their tar container for multi-source input. The GUI "Single archive"
  checkbox merges all queued rows into one job.
- Selectable compression level (0–9); a sensible per-algorithm default is used
  when omitted.
- **Exclusions**: `CompressionRequest.exclude` (or repeatable `--exclude`
  flags / the GUI Exclude field) drops members matching gitignore-lite globs
  — `*.tmp` matches basenames at any depth, `build` or `build/` skips a
  directory and its contents, `dir/*.log` anchors to the source root. A
  `.lsignore` file inside a source folder adds the same patterns
  automatically.
- **Presets** (`CompressionPreset`): Fast → Zstd level 1, Balanced → Zstd
  level 3 (default), Maximum → XZ level 9. CLI `--preset` overrides
  `--algorithm`/`--level`; the GUI preset combo overrides the algorithm
  dropdown when set to anything but "Custom".
- **Split volumes**: `CompressionRequest.split_size` (CLI `--split 100M`, GUI
  "Split size" field) writes the finished archive as numbered volumes
  `DEST.001`, `DEST.002`, … — applied after encryption, so `.lsenc` output
  splits too (self-extracting archives cannot be split). Extraction,
  `verify`, and `list` join the set automatically from any volume; missing
  parts are reported as errors. `core/volumes.py` also exposes
  `parse_size` (e.g. `100M`, `1.5GiB`).
- **Parallel compression**: `CompressionRequest.threads` (CLI `-j/--jobs`)
  enables multi-threaded Zstandard encoding for both `.zst` streams and
  `.tar.zst` containers. `0` uses all available cores; output remains a
  standard zstd frame readable by any decoder. Other algorithms stay
  single-threaded.
- `overwrite` protection: operations refuse to clobber an existing destination
  unless `force`/`--force` is set.
- **Metadata preservation**: extraction restores modification times recorded in
  the archive — ZIP `date_time`, tar member mtime, 7z stored timestamps, RAR
  `mtime`, and the gzip stream header. Directory timestamps are applied after
  their contents so writes don't clobber them. `core/filesystem.apply_mtime`
  is best-effort: unsupported filesystems are ignored rather than failing the
  extraction.
- Source existence/destination preparation handled centrally in
  `core/filesystem.py` (`ensure_source`, `prepare_destination`,
  `replace_path`), with atomic result placement.

**Integrity verification** (`core/verification.py`):

- Every operation verifies the produced archive by default (`verify=True`);
  can be skipped per-request (`--no-verify` in the CLI).
- `verify_archive(path)` sniffs the archive format and validates it; the GUI
  History and CLI `verify` subcommand surface the detected algorithm.

**Result reporting**: `OperationResult` reports source/output sizes, elapsed
time, files processed, compression ratio, and space-savings percentage.

---

## 2. Encryption & self-extracting archives

`core/encryption.py` implements a custom encrypted container format:

- **Cipher:** AES-256-GCM (authenticated encryption — tampering is detected).
- **KDF:** Argon2id (t=3, m=64 MiB, p=2) for all new archives. The KDF
  algorithm and its parameters are stored in the archive header metadata, so
  work factors can be raised later without breaking existing files. Archives
  written before v1.2 (PBKDF2-HMAC-SHA256, 100k iterations, no KDF metadata)
  remain readable; self-extracting launchers honor the stored parameters and
  prompt for `pip install argon2-cffi` when needed.
- **File format:** `LSE\x01` magic + 2-byte metadata length + JSON metadata +
  salt + nonce + ciphertext. `is_encrypted_file()` detects the magic header.

**Password-protected compression:** pass `password` on a `CompressionRequest`
(or `--password` in the CLI, or the password field on the Compress page). The
`encryption_format` field / `--encryption` flag / GUI combo selects the
container:

- `lse` (default) — the custom AES-256-GCM container described above. Maximum
  security: the whole payload including filenames is encrypted, but only
  LS Compressor can open it.
- `zip-aes` — WinZip-compatible AES-256 entries inside a standard `.zip`
  (readable by 7-Zip, WinRAR, macOS Archive Utility, etc.) via `pyzipper`.
- `7z` — a standard AES-256 `.7z` archive with encrypted headers via `py7zr`
  (names are also hidden). Created regardless of the selected algorithm.

Self-extracting launchers remain exclusive to `lse` and are disabled in the
GUI for the compatible formats. Encrypted archives verify with
`verify_archive(path, password=...)` and decompress with the same
`--password` flag.

**Self-extracting archives** (`self_extracting=True` / `--self-extracting`):

- When a prebuilt `ls-extract` stub binary is available, the encrypted payload
  is appended to a copy of the stub (`payload + b"LSEX" + 8-byte LE length`
  footer), producing a standalone executable (`.exe` on Windows, `.lsex`
  elsewhere) that extracts without a Python install. Stub lookup order:
  `LS_EXTRACT_STUB` env var → bundled app resources → the executable's
  directory → `packaging/stub/` for development builds.
- Without a stub, a runnable `.py` launcher embedding the payload as base64 is
  generated instead; on macOS `.app` destinations produce a `.app` bundle.
- Build the stub with `pyinstaller packaging/ls-extract.spec --distpath
  packaging/stub`. The stub reuses `core/` for decryption/extraction and is
  bundled into the packaged app when present at build time.
- `is_self_extracting_archive()` detects binary stubs via the `LSEX` footer
  and script launchers via an embedded marker; `extract_payload()` recovers
  the encrypted payload from either form.
- `verify` works on encrypted/self-extracting inputs: the CLI transparently
  decrypts to a temp directory before verifying (requires `--password`).

Decryption failures raise `EncryptionError`; the CLI exits `1` with a
user-safe message.

---

## 3. Media optimization

`core/media.py` is a strategy-based optimizer aimed at web/creative workflows.
Each format is a pluggable strategy, so new codecs can be added without
changing the public API.

**Supported inputs:**

- **Images:** PNG, JPEG, WebP — handled by Pillow.
- **Video:** `.mp4 .mov .avi .mkv .webm .m4v .flv .wmv` — recompressed via
  FFmpeg (bundled through `imageio[ffmpeg]`).

**Detection:** `detect_media_format()` prefers extension mapping, falls back to
Pillow content sniffing, then an FFmpeg probe (`ffmpeg -i … -f null -`).
Unsupported inputs raise `UnsupportedFormatError`.

**Modes** (`MediaOptimizationMode`):

- `lossless` — maximum-size reduction with no quality loss (PNG recompression,
  lossless WebP, etc.).
- `lossy` — quality-controlled recompression.

**Resize** (`max_dimension` / CLI `--max-size PX` / the Optimize page "px"
spinner) downscales images so the longest edge fits the limit using Lanczos
resampling; images already within the limit pass through untouched.

**Tunables** (`MediaOptimizationRequest`):

- `quality` (1–100) for JPEG/WebP lossy output.
- `video_preset` — FFmpeg x264 preset (`ultrafast` … `veryslow`, default
  `medium`).
- `video_crf` — x264 CRF 0–51 (lower = higher quality).

Results report the detected `MediaFormat`, compression ratio, and savings
percentage, with the same progress-callback contract as archive operations.

---

## 4. Watch folders (Hot Folders)

Two-layer design:

- `core/watch.py` — domain models and processing logic:
  - `WatchFolderConfig`: validated, JSON-serializable config per folder
    (path, output folder, operation, enabled flag, algorithm, compression
    level, media mode, recursive, password, self-extracting).
  - `WatchOperationType`: `compress` or `media_optimize`.
  - `process_watch_event()` / `derive_watch_destination()`: map a detected
    file to its output path and run the configured operation.
- `infrastructure/watch.py` — `WatchService`, built on `watchdog`:
  - Background observer thread monitoring multiple folders.
  - Debounces filesystem events (files still being written aren't processed
    prematurely).
  - Ignores hidden files, temp files, and files inside the output folder
    (prevents feedback loops).

Watch folders are persisted in `AppSettings.watch_folders`, manageable from
the GUI Settings page, and feed detected files into the GUI's existing
`JobQueue`. A foreground CLI watcher is also available
(`ls-compressor watch`).

---

## 5. Graphical interface (PySide6)

Sidebar-navigated main window (`gui/main_window.py`) with five pages:

- **Compress** — drag-and-drop or picker input, algorithm selector (labeled
  e.g. "Deflate"), compression level, optional password, self-extracting
  toggle.
- **Decompress** — drop an archive, optional password for encrypted
  containers.
- **Optimize** — media optimization with lossless/lossy mode selector.
- **History** — table of completed jobs with results.
- **Settings** — inline editor backed by `AppSettings`, plus watch-folder
  management (add/remove/persist).

Supporting UI machinery:

- `gui/queue.py` + `gui/workers.py` — background `QThread` job queue; the UI
  never blocks on compression.
- `gui/stat_card.py` — per-page summary stat cards.
- `gui/widgets.py` — `JobTable`, `SettingsDialog`, drag-and-drop widgets.
- `gui/theme.py` + `gui/theme.qss` — Dark/Light/System theme support.
- `gui/resources.py`, `assets/` — Inter typeface, Lucide SVG icons, app icon.
- The `WatchService` starts on launch and routes detected files into the job
  queue.

---

## 6. Command-line interface

Entry point: `ls-compressor` (also `python -m ls_compressor`). Global flags:
`--version`, `-v/--verbose` (repeatable for diagnostic logging).

| Subcommand | Purpose |
|------------|---------|
| `compress SRC… DEST` | Create an archive from one or more sources. Flags: `-a/--algorithm`, `-l/--level`, `--preset`, `-p/--password`, `--encryption`, `--self-extracting`, `--exclude`, `--split`, `-j/--jobs`, `-f/--force`, `--no-verify`, `-q/--quiet` |
| `decompress SRC DEST` | Extract an archive (incl. encrypted and `.NNN` volumes). Flags: `-p`, `-f`, `--no-verify`, `-q` |
| `verify SRC` | Validate archive integrity; handles encrypted and split-volume inputs with `-p` |
| `list`/`ls SRC` | List archive members and sizes without extracting; handles encrypted and self-extracting inputs with `-p` |
| `media SRC DEST` | Optimize image/video. Flags: `--mode lossless|lossy`, `--quality`, `--video-preset`, `--video-crf`, `-f`, `-q` |
| `watch FOLDER -o OUT` | Foreground hot-folder watcher. Flags: `--operation`, `-a`, `-l`, `--media-mode`, `-p`, `--self-extracting`, `--recursive/--no-recursive`, `-q` |
| `bench SRC` | Benchmark every write-capable algorithm on one source (time, output size, ratio sorted best-first). Flags: `-l/--level` |
| `shell install|uninstall|status` | Manage OS context-menu integration (see below) |
| `completions SHELL` | Print a completion script for `bash`, `zsh`, or `fish` — generated from the parser, so it always reflects the current flags |

Live progress percentage is rendered to stderr; a stable key-value summary is
printed on completion. `compress`, `decompress`, `verify`, `list`, and
`media` also accept `--json`, which emits the result as a JSON document on
stdout (progress suppressed) and prints a JSON error object to stderr on
failure — suitable for scripting. `compress`/`decompress` also accept
`--dry-run` (combines with `--json`), reporting planned members, totals,
split-volume estimates, and existing-destination warnings without writing
output — backed by `core.plan_compression`. Exit codes: `0` success, `1`
operation error, `130` Ctrl-C.

**Config file** (`infrastructure/cli_config.py`): a `ls-compressor.toml`
supplies per-command option defaults — searched at `./ls-compressor.toml`
then the platform config dir, or set explicitly with `--config PATH`
(accepted before or after the subcommand). Example:

```toml
[compress]
algorithm = "xz"
level = 6
exclude = ["*.tmp", "build/"]

[media]
mode = "lossy"
quality = 80
```

Section names match subcommands; option names use underscores or dashes.
Explicit CLI flags always override config values; malformed files and
invalid enum values produce a readable error. Passwords are never read
from config.

**Shell integration** (`infrastructure/shell_integration.py`) registers
per-user "Compress/Extract with LS Compressor" entries — no admin rights:

- macOS: Finder Quick Actions in `~/Library/Services` ("Compress …" and
  "Extract …" appear on right-click → Quick Actions).
- Windows: `HKCU\Software\Classes` context-menu keys for files and folders.
- Linux: KDE service menu (`~/.local/share/kio/servicemenus`) plus Nautilus
  scripts for GNOME Files.
- The packaged `.app` also declares archive document types so Finder offers
  LS Compressor under "Open With".
- The Settings page has an Install/Remove button mirroring the CLI.

---

## 7. Settings, paths & logging

- `infrastructure/config.py` — `AppSettings`: validated, frozen, JSON-backed
  preferences: default algorithm, compression level (0–9), output-location
  behavior (`same_folder` / `ask_each_time`), last-used folder/algorithm,
  watch folders, and theme. Writes are atomic (temp file + replace).
- `infrastructure/paths.py` — platformdirs-based locations:
  - macOS: `~/Library/Application Support/LS Compressor`,
    `~/Library/Logs/LS Compressor`
  - Windows: `%LocalAppData%\LS Compressor`
  - Linux: XDG data/config/cache dirs
- `infrastructure/logging.py` — `configure_logging(verbosity)`; `logging` is
  used everywhere (no `print` outside CLI user output).

---

## 8. Packaging & release

- `packaging/` — PyInstaller spec producing:
  - macOS `dist/LS Compressor.app` (ad-hoc signed, not notarized)
  - Windows `dist/ls-compressor.exe`
  - Linux `dist/ls-compressor`
  - The FFmpeg binary is bundled into the builds.
- `scripts/generate_icons.py` — regenerates icon assets.
- `.github/workflows/release.yml` — release automation.

## Known limitations

- Builds are unsigned/unnotarized — first launch triggers Gatekeeper /
  SmartScreen prompts (see README for workarounds).
- Self-extracting archives are standalone executables only when a matching
  `ls-extract` stub binary was built for the target platform; otherwise they
  fall back to a `.py` launcher that requires a Python runtime.
- XZ support depends on the stdlib `lzma` module.
