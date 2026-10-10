# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the standalone self-extracting stub binary."""

from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "packaging" / "ls_extract.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[
        "zstandard",
        "zstandard.backend_cffi",
        "py7zr",
        "rarfile",
        "pyzipper",
        "argon2",
        "argon2.low_level",
        "cryptography",
        "cryptography.hazmat",
        "cryptography.hazmat.primitives",
        "cryptography.hazmat.primitives.ciphers.aead",
        "cryptography.hazmat.primitives.kdf.pbkdf2",
        "lzma",
        "tarfile",
        "gzip",
        "bz2",
        "zipfile",
        "platformdirs",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PySide6",
        "shiboken6",
        "watchdog",
        "pytest",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ls-extract",
    console=True,
    upx=False,
)
