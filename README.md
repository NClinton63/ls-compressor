# LS Compressor

A small, cross-platform desktop GUI for lossless file and folder
compression. It is built with Python and PySide6, supports ZIP, GZIP, BZ2,
and XZ archives, and runs the same core logic from either the graphical
interface or the command line.

> **Status:** The packaged builds are unsigned and not notarized. macOS and
> Windows will show a security warning the first time you run them. See the
> [unsigned build warnings](#unsigned-build-warnings) section for safe
> workarounds.

## Features

- Drag-and-drop or picker-based file and folder selection.
- Queue-based background compression and decompression.
- ZIP, GZIP, BZ2, and XZ output formats for compression.
- Automatic integrity verification after each operation.
- Persistent user settings and recent folders.
- Cross-platform: macOS `.app`, Windows `.exe`, and Linux executable.

## Installation

### macOS

1. Download `ls-compressor-macos.zip` from this repository's Releases page.
2. Unzip it to move `LS Compressor.app` into `Applications`.
3. See [macOS Gatekeeper workaround](#macos) below before launching.

### Windows

1. Download `ls-compressor-windows.zip` from this repository's Releases page.
2. Extract `ls-compressor.exe` and run it.
3. See [Windows SmartScreen workaround](#windows) below.

### Linux

1. Download `ls-compressor-linux.tar.gz` from this repository's Releases page.
2. Extract the executable:
   ```bash
   tar -xzf ls-compressor-linux.tar.gz
   ./ls-compressor
   ```
3. On Wayland or headless servers, set `QT_QPA_PLATFORM=offscreen` or `xcb` as needed.

## Running from source

Requires Python 3.11 or newer.

```bash
# Install dependencies in a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements-dev.txt -e .
```

### GUI

```bash
ls-compressor-gui
```

or

```bash
python -c "from ls_compressor.gui.application import main; raise SystemExit(main())"
```

### CLI

```bash
ls-compressor --help
python -m ls_compressor --help
```

## CLI examples

```bash
# Compress a file into the current directory
ls-compressor compress ./report.pdf ./report.pdf.zip

# Compress a folder with ZIP level 9
ls-compressor compress ./project ./project.zip --level 9 --force

# Decompress an archive
ls-compressor decompress ./project.zip ./restored-project --force

# Verify an archive
ls-compressor verify ./archive.tar.xz
```

## Building from source

Generate the application icon assets and the PyInstaller bundle:

```bash
python -m pip install -r requirements-dev.txt -e .
python scripts/generate_icons.py
python -m PyInstaller packaging/ls-compressor.spec --noconfirm --clean
```

Platform outputs are written to `dist/`:

- macOS: `dist/LS Compressor.app`
- Windows: `dist/ls-compressor.exe`
- Linux: `dist/ls-compressor`

## Source layout

```
assets/                 Fonts, toolbar SVGs, and the application icon
packaging/              PyInstaller spec, entry point, and version files
scripts/                Build helper scripts such as icon generation
src/ls_compressor/      Application code (core, cli, gui, infrastructure)
tests/                  Unit and integration tests
```

## Screenshots

> Placeholder for application screenshots.
>
> ![LS Compressor main window](docs/screenshots/main-window.png)

## Application data and logs

Settings and logs are placed in platform-specific directories using
`platformdirs`.

- **macOS:** `~/Library/Application Support/LS Compressor` and
  `~/Library/Logs/LS Compressor`
- **Windows:** `%LocalAppData%\LS Compressor` and `%LocalAppData%\LS Compressor\Logs`
- **Linux:** locations follow the active XDG configuration, data, and cache roots.
  The application directories are named `LS Compressor`.

## Tests

```bash
QT_QPA_PLATFORM=offscreen pytest
```

Style checks:

```bash
black --check src tests scripts packaging
ruff check src tests scripts packaging
```

## Known limitations

- Packaged builds are ad-hoc signed on macOS and **not notarized**.
- Windows builds are **not code-signed**.
- First launch on macOS and Windows will show a security prompt from the
  operating system.
- Linux builds may need `libxcb-xinerama` or `libgl1` on minimal
  distributions for Qt to load.
- The XZ archive support depends on the Python `lzma` module; it is
  available on all supported CPython builds.

## Unsigned build warnings

### macOS

Because the `.app` is not notarized, Gatekeeper will block it by default.
The safest way to open it is to use **System Settings > Privacy & Security**
and click **Open Anyway** after the first attempted launch. Alternatively,
from the terminal:

```bash
xattr -rd com.apple.quarantine "/Applications/LS Compressor.app"
```

This removes the quarantine flag. Only do this for the build you downloaded
from the official GitHub Release page.

### Windows

Because the `.exe` is not code-signed, Windows Defender SmartScreen may show a
"Windows protected your PC" prompt. Click **More info**, then **Run anyway**
to launch the application. If your organization blocks unsigned executables,
you may need an administrator to allow the file or to build and sign the
application yourself.

### Linux

No additional warnings are expected, but the dynamic loader may refuse to run
an AppImage-style bundle if the executable bit is missing. Ensure the file is
executable:

```bash
chmod +x ls-compressor
```

## Third-party assets

This project uses the [Inter](https://rsms.me/inter/) typeface and
[Lucide](https://lucide.dev/) icons. See `THIRD_PARTY_NOTICES.md` for full
license and attribution details.

## License

LS Compressor is released under the MIT License. See `LICENSE`.
