# -*- mode: python ; coding: utf-8 -*-
"""Cross-platform PyInstaller spec for LS Compressor."""

import sys
import tomllib
from pathlib import Path

SPEC_DIR = Path(SPECPATH)
ROOT = SPEC_DIR.parent

try:
    from imageio_ffmpeg import get_ffmpeg_exe

    FFMPEG_BINARY = get_ffmpeg_exe()
except Exception:
    FFMPEG_BINARY = None

with open(ROOT / "pyproject.toml", "rb") as pyproject_file:
    VERSION = tomllib.load(pyproject_file)["project"]["version"]

APP_NAME = "LS Compressor"
BUNDLE_ID = "com.lscompressor.app"


binaries = []
if FFMPEG_BINARY is not None:
    binaries.append((FFMPEG_BINARY, "."))

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=[
        (str(ROOT / "assets"), "assets"),
        (str(ROOT / "src" / "ls_compressor" / "gui" / "theme.qss"), "ls_compressor/gui"),
    ],
    hiddenimports=[
        "PySide6.QtSvg",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "shiboken6",
        "lzma",
        "tarfile",
        "gzip",
        "bz2",
        "zipfile",
        "platformdirs",
        "PIL",
        "PIL.PngImagePlugin",
        "PIL.JpegImagePlugin",
        "PIL.WebPImagePlugin",
        "imageio",
        "imageio_ffmpeg",
        "imageio_ffmpeg._utils",
        "watchdog",
        "watchdog.observers",
        "cryptography",
        "cryptography.hazmat",
        "cryptography.hazmat.primitives",
        "cryptography.hazmat.primitives.ciphers.aead",
        "cryptography.hazmat.primitives.kdf.pbkdf2",
        "cryptography.hazmat.primitives.hashes",
        "cffi",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

common_exe_kwargs = {
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": False,
    "upx": False,
    "upx_exclude": [],
    "runtime_tmpdir": None,
    "console": False,
    "disable_windowed_traceback": False,
    "argv_emulation": False,
    "target_arch": None,
    "codesign_identity": None,
    "entitlements_file": None,
}

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        name="ls-compressor",
        exclude_binaries=True,
        **common_exe_kwargs,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        name=APP_NAME,
    )
    BUNDLE(
        coll,
        name="LS Compressor.app",
        icon=str(ROOT / "assets" / "icon.icns"),
        bundle_identifier=BUNDLE_ID,
        version=VERSION,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "CFBundleIdentifier": BUNDLE_ID,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.14",
            "CFBundlePackageType": "APPL",
        },
    )
else:
    icon = None
    version_file = None
    if sys.platform == "win32":
        icon = str(ROOT / "assets" / "icon.ico")
        version_file = str(ROOT / "packaging" / "win_version_info.txt")

    EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="ls-compressor",
        version=version_file,
        icon=icon,
        **common_exe_kwargs,
    )
