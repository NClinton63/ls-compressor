# LS Compressor — Feature Improvements & Roadmap

Oct 10, 2026 · @sir Bekam

LS Compressor's architecture (frozen request/result dataclasses, `core/` isolated from `gui/` and `cli/`) means most improvements below arrive as new strategies or request fields, without restructuring. Items are grouped by audience, with the highest-impact gaps first and a phased roadmap at the end.

## Biggest gaps (do these first)

Five changes would do the most to make LS Compressor a daily driver rather than a tool for your own archives only.

1. **Modern algorithms: Zstandard (and optionally Brotli).** All four current formats are older. Zstd is now the default expectation for speed with strong ratios and supports multithreading. Add `zst` / `tar.zst` as an enum value and make it the default.
2. **7z and RAR extraction.** Users receive archives in these formats constantly. Even read-only support (via `py7zr` and `rarfile`/`unrar`) removes the "only my own archives" limit.
3. **Standard-compatible encryption.** The custom `LSE` container is well built (AES-256-GCM is the right choice), but nobody else's tools can open it. Offer AES-encrypted ZIP and 7z as an option, and keep the custom container as the "maximum security" mode.
4. **Self-extracting archives that don't need Python.** This is the most significant known limitation: a non-technical recipient can't use a `.py` launcher. Consider a small compiled Windows stub (PyInstaller, or a Rust/Go extractor) so the output is a real `.exe`, or a free "LS Extract" mini-app as an alternative.
5. **Stronger key derivation.** PBKDF2 at 100,000 iterations is below current guidance for SHA-256 (OWASP suggests 600,000). Consider Argon2id with the iteration count stored in the metadata, so old archives still open and the setting can be raised later.

## For everyday, non-technical users

These features hide complexity and match how most people actually compress files.

- **Right-click shell integration** (Windows Explorer, macOS Finder Quick Actions, Linux file managers): "Compress with LS Compressor".
- **Plain-language presets:** "Email (small)", "Maximum compression", "Fast", "Secure share". Hide algorithm and level behind an "Advanced" toggle.
- **Size estimate before running**, plus a "target size" mode ("make this fit under 25 MB").
- **Multi-file and multi-folder selection into one archive**, with an in-app preview of archive contents and selective extraction of individual files.
- **Password strength meter**, plus a warning that a lost password cannot be recovered.
- **Completion notifications**, an "open output folder" button, and trash/undo for the original after "compress and delete source".
- **Localization.** Qt's translation system makes this tractable; French is a natural first addition given your region.

## For power users and developers

Scripting, pipelines and large datasets benefit from finer control and a documented library surface.

- **Split/multi-volume archives** (for example 100 MB parts for email limits or FAT32 drives), with a reassembly step in decompress.
- **Include/exclude patterns** (`--exclude "node_modules" --exclude "*.log"`, plus `.lsignore` file support).
- **Parallel compression** across files and a worker-count setting; each job currently appears to run as a single unit.
- **Metadata preservation** options (permissions, timestamps, symlinks, xattrs) and **reproducible archives** (fixed timestamps and ordering) for build pipelines.
- **CLI improvements:** `--json` output, `--dry-run`, shell completions, a config file (`ls-compressor.toml`), and `list`/`info` subcommands to inspect an archive without extracting.
- **Public Python API** documented as a library (`from ls_compressor.core import ...`); the request/result dataclasses already make this easy.
- **Benchmark command** (`ls-compressor bench FILE`) that compares algorithms on the user's own data and recommends one.

## Media optimization

The strategy-based design in `core/media.py` makes each of these a new pluggable strategy.

- **More formats:** AVIF, HEIC/HEIF input, GIF-to-video/WebP conversion, SVG minification and PDF optimization. Audio (MP3, AAC, Opus, FLAC) is a conspicuous omission for a media optimizer.
- **Modern video codecs:** H.265 and AV1 alongside x264, plus hardware encoder detection (NVENC, VideoToolbox, QSV) for speed.
- **Resize and constraints:** max width/height, target file size, and "optimize for web/social/email" presets.
- **Metadata stripping** (EXIF/GPS) as a privacy feature, with the option to preserve color profiles.
- **Before/after comparison view** for lossy mode so users can judge quality before committing, with SSIM/PSNR shown as a metric.
- **Batch folder processing** with a summary report ("saved 1.4 GB across 312 files").

## Watch folders

Hot folders are the strongest automation feature; these changes make them dependable enough to run unattended.

- **Rules, not just one operation per folder:** match by extension, size or age (for example "images over 2 MB get optimized; everything else is ignored").
- **Post-processing actions:** delete, move or keep the original after success; retry on failure; and a "quiet hours" schedule.
- **Background service or tray app** (login startup) so watching works when the main window is closed. It currently appears tied to the app being open.
- **Stronger credential handling:** `WatchFolderConfig` stores the password in the JSON settings. Move it to the OS keychain (via `keyring`) or at least warn clearly.

## Security and trust features

Privacy-minded users will judge the app on these.

- **Key file support** (password plus a file) and optional **public-key encryption** (age-style) for sharing without exchanging passwords.
- **Checksums and signing:** emit SHA-256 manifests, and optionally sign archives.
- **Secure delete** of originals, with an honest note about SSD limitations.
- **Document the metadata-hiding advantage.** The container encrypts the whole compressed payload, so filenames stay hidden; zip-level encryption leaves them visible. State this explicitly in the docs.

## Distribution and polish

Unsigned builds trigger Gatekeeper and SmartScreen warnings, which will cost users regardless of features, so trust and reach come first here.

- **Code signing and notarization.** Even a low-cost route (Windows via SignPath or Azure Trusted Signing, or a free open-source tier where available) removes the biggest first-run barrier.
- **Auto-update check:** a simple "new version available" notice at first, then in-app updates.
- **Package manager distribution:** Homebrew cask, winget, Scoop, and a Flatpak or AppImage.
- **Opt-in anonymous crash reporting** and an in-app "copy diagnostics" button for bug reports.
- **Accessibility:** keyboard navigation, screen reader labels and a high-contrast theme.

## Suggested roadmap

Four phases, ordered so each release ships something visible while earlier releases lay groundwork for later ones.

| Phase | Focus |
| --- | --- |
| v1.1 | Zstd, multi-file selection, presets, archive preview/list, exclude patterns, password strength meter |
| v1.2 | 7z/RAR extraction, AES-ZIP/7z, split archives, shell integration, Argon2id |
| v1.3 | Audio and AVIF/HEIC media support, watch-folder rules and tray mode, keychain storage |
| v2.0 | Standalone self-extractors, signed builds, auto-update, localization, public library API |
