"""Packaging-focused tests for asset lookup and build artifacts."""

import compileall
import importlib.util
import sys
from pathlib import Path

import pytest

from ls_compressor.gui import resources


def _repo_root() -> Path:
    """Return the repository root from the test location."""
    return Path(__file__).resolve().parents[2]


def test_project_root_returns_meipass_when_frozen(monkeypatch, tmp_path):
    """The resource helper must use sys._MEIPASS when it is available."""
    meipass = tmp_path / "bundle"
    meipass.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    assert resources._project_root() == meipass


def test_project_root_returns_repo_root_in_source():
    """In a normal source checkout, the project root contains pyproject.toml."""
    root = resources._project_root()
    assert (root / "pyproject.toml").is_file()
    assert (root / "assets").is_dir()


def test_gui_icons_resolve():
    """Every icon used by the sidebar and content views maps to an SVG file."""
    for name in (
        "add",
        "chevron-down",
        "compress",
        "decompress",
        "file",
        "file-spreadsheet",
        "file-text",
        "file-zip",
        "history",
        "logo",
        "optimize",
        "settings",
        "upload",
    ):
        path = resources.icon_path(name)
        assert path is not None, f"icon '{name}' has no path"
        assert path.is_file(), f"icon '{name}' is missing at {path}"


def test_icon_fallback_for_missing_name():
    """A missing icon name must return an empty QIcon without raising."""
    icon = resources.icon("does-not-exist")
    assert icon is not None


def test_application_icon_assets_exist():
    """The generated app-icon assets must be present for the spec to reference."""
    root = _repo_root()
    assert (root / "assets" / "icon.svg").is_file()
    assert (root / "assets" / "icon.png").is_file()
    assert (root / "assets" / "icon.ico").is_file()
    if sys.platform == "darwin":
        assert (root / "assets" / "icon.icns").is_file()


def test_pyinstaller_spec_compiles():
    """The PyInstaller spec file must be syntactically valid Python."""
    spec_path = _repo_root() / "packaging" / "ls-compressor.spec"
    assert compileall.compile_file(str(spec_path))


def test_macos_release_zip_preserves_app_bundle():
    """The macOS release ZIP must retain LS Compressor.app as its root."""
    workflow = (_repo_root() / ".github" / "workflows" / "release.yml").read_text()
    assert "ditto -c -k --sequesterRsrc --keepParent" in workflow


def test_generate_icons_script_is_importable():
    """The icon-generation script must load without import errors."""
    script = _repo_root() / "scripts" / "generate_icons.py"
    spec = importlib.util.spec_from_file_location("generate_icons", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.create_icon_image)
    assert callable(module.generate_ico)
    assert callable(module.generate_icns)
    assert callable(module.write_svg)


def test_generated_ico_contains_expected_sizes():
    """The generated .ico must contain the standard Windows icon sizes."""
    ico = _repo_root() / "assets" / "icon.ico"
    pytest.importorskip("PIL")
    from PIL import Image

    with Image.open(ico) as image:
        sizes = image.info["sizes"]
    assert (256, 256) in sizes
    assert (128, 128) in sizes
    assert (32, 32) in sizes
    assert (16, 16) in sizes


@pytest.mark.skipif(sys.platform != "darwin", reason=".icns only built on macOS")
def test_generated_icns_has_high_resolution():
    """The generated .icns must open and include the 1024x1024 source size."""
    icns = _repo_root() / "assets" / "icon.icns"
    pytest.importorskip("PIL")
    from PIL import Image

    with Image.open(icns) as image:
        assert image.size == (1024, 1024)
