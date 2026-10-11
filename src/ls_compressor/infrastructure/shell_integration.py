"""Per-user OS shell integration (context menus and Quick Actions).

All registrations are user-scoped: macOS Finder Quick Actions in
``~/Library/Services``, Windows ``HKCU`` context-menu keys, and KDE
service menus / Nautilus scripts on Linux. Nothing requires admin rights.
"""

import plistlib
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from ls_compressor.core.exceptions import UnsupportedFormatError

_COMPRESS_ACTION = "Compress with LS Compressor"
_EXTRACT_ACTION = "Extract with LS Compressor"


@dataclass(frozen=True, slots=True)
class ShellEntry:
    """Describe one shell integration point and whether it is installed."""

    name: str
    location: str
    installed: bool


def _executable_command() -> str:
    """Return the command used to invoke this application from the shell."""
    resolved = shutil.which("ls-compressor")
    if resolved is not None:
        return resolved
    return sys.argv[0]


def _services_dir(home: Path) -> Path:
    """Return the macOS per-user Services (Quick Actions) directory."""
    return home / "Library" / "Services"


def _kde_services_dir(home: Path) -> Path:
    """Return the KDE service-menus directory for the current user."""
    return home / ".local" / "share" / "kio" / "servicemenus"


def _nautilus_scripts_dir(home: Path) -> Path:
    """Return the Nautilus per-user scripts directory."""
    return home / ".local" / "share" / "nautilus" / "scripts"


def _workflow_plist(command: str) -> dict:
    """Build the document.wflow plist for a Run Shell Script Quick Action."""
    return {
        "AMActionBuildVersion": "521",
        "actions": [
            {
                "action": {
                    "AMActionVersion": "2.0.3",
                    "AMApplication": ["Automator"],
                    "ActionBundlePath": (
                        "/System/Library/Automator/Run Shell Script.action"
                    ),
                    "ActionName": "Run Shell Script",
                    "ActionParameters": {
                        "COMMAND_STRING": command,
                        "CheckedForUserDefaultShell": True,
                        "inputMethod": 1,
                        "shell": "/bin/zsh",
                        "source": "",
                    },
                    "BundleIdentifier": "com.apple.RunShellScript",
                    "CFBundleVersion": "2.0.3",
                    "CanShowSelectedItems": True,
                    "CanShowWhenRunning": True,
                    "Category": ["AMCategoryUtilities"],
                    "Class Name": "RunShellScriptAction",
                    "InputUUID": "4FBB15C5-2E2A-4C0B-9F8D-0A1B2C3D4E5F",
                    "Keywords": ["Shell", "Script", "Command", "Run"],
                    "OutputUUID": "9A1C2B3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D",
                    "UUID": "1B2C3D4E-5F6A-7B8C-9D0E-1F2A3B4C5D6E",
                    "UnlocalizedApplications": ["Automator"],
                    "arguments": {
                        "0": {
                            "0": {
                                "value": 1,
                                "type": 0,
                                "attribute": 0,
                                "AMActionPropertyName": "inputMethod",
                                "AMActionPropertyType": 0,
                            }
                        }
                    },
                    "conversionLabel": 0,
                    "isViewVisible": 1,
                    "location": "449.000000:316.000000",
                    "nibPath": (
                        "/System/Library/Automator/Run Shell Script.action"
                        "/Contents/Resources/Base.lproj/main.nib"
                    ),
                },
                "isViewVisible": 1,
            }
        ],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleIDsByPath": {},
            "applicationPaths": [],
            "inputType": 0,
            "outputType": 1,
            "presentationMode": 11,
            "processesInput": 0,
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": 0,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }


def _workflow_info_plist(name: str) -> dict:
    """Build the Info.plist for a Quick Action workflow bundle."""
    return {
        "CFBundleIdentifier": f"com.lscompressor.{name.replace(' ', '').lower()}",
        "CFBundleName": name,
        "NSServices": [
            {
                "NSMenuItem": {"default": name},
                "NSMessage": "runWorkflowAsService",
                "NSSendTypes": ["public.plain-text", "NSFilenamesPboardType"],
            }
        ],
    }


def _compress_shell_command(executable: str) -> str:
    """Return the zsh snippet a Quick Action runs for compression."""
    return f'for f in "$@"; do "{executable}" compress "$f" "$f.tar.zst"; done'


def _extract_shell_command(executable: str) -> str:
    """Return the zsh snippet a Quick Action runs for extraction."""
    return f'for f in "$@"; do "{executable}" decompress "$f" "${{f}}-extracted"; done'


def _darwin_workflows(home: Path, executable: str) -> dict[Path, str]:
    """Map workflow bundle paths to their shell commands."""
    services = _services_dir(home)
    return {
        services / f"{_COMPRESS_ACTION}.workflow": _compress_shell_command(executable),
        services / f"{_EXTRACT_ACTION}.workflow": _extract_shell_command(executable),
    }


def _darwin_install(home: Path, executable: str) -> list[Path]:
    """Write Finder Quick Action workflow bundles; return created paths."""
    created = []
    for bundle, command in _darwin_workflows(home, executable).items():
        contents = bundle / "Contents"
        contents.mkdir(parents=True, exist_ok=True)
        (contents / "document.wflow").write_bytes(
            plistlib.dumps(_workflow_plist(command))
        )
        (contents / "Info.plist").write_bytes(
            plistlib.dumps(_workflow_info_plist(bundle.stem))
        )
        created.append(bundle)
    return created


def _darwin_uninstall(home: Path) -> list[Path]:
    """Remove the Quick Action workflow bundles; return removed paths."""
    removed = []
    for bundle in _darwin_workflows(home, ""):
        if bundle.exists():
            shutil.rmtree(bundle)
            removed.append(bundle)
    return removed


def _darwin_entries(home: Path) -> list[ShellEntry]:
    """Report install state for the macOS Quick Actions."""
    return [
        ShellEntry(
            name=bundle.stem,
            location=str(bundle),
            installed=bundle.exists(),
        )
        for bundle in _darwin_workflows(home, "")
    ]


def _windows_registry_keys(executable: str) -> dict[str, dict[str, str]]:
    """Return the HKCU context-menu registry spec for Windows installs."""
    return {
        r"Software\Classes\*\shell\LSCompressorCompress": {
            "": f"&{_COMPRESS_ACTION}",
            "Icon": executable,
        },
        r"Software\Classes\*\shell\LSCompressorCompress\command": {
            "": f'"{executable}" compress "%1" "%1.tar.zst"',
        },
        r"Software\Classes\*\shell\LSCompressorExtract": {
            "": f"&{_EXTRACT_ACTION}",
            "Icon": executable,
        },
        r"Software\Classes\*\shell\LSCompressorExtract\command": {
            "": f'"{executable}" decompress "%1" "%1-extracted"',
        },
        r"Software\Classes\Directory\shell\LSCompressorCompress": {
            "": f"&{_COMPRESS_ACTION}",
            "Icon": executable,
        },
        r"Software\Classes\Directory\shell\LSCompressorCompress\command": {
            "": f'"{executable}" compress "%1" "%1.tar.zst"',
        },
    }


def _windows_install(executable: str) -> list[str]:
    """Write the HKCU context-menu keys; return created key paths."""
    import winreg

    created = []
    for key_path, values in _windows_registry_keys(executable).items():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            for name, value in values.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        created.append(rf"HKCU\{key_path}")
    return created


def _windows_uninstall() -> list[str]:
    """Delete the HKCU context-menu keys; return removed key paths."""
    import winreg

    removed = []
    for key_path in sorted(_windows_registry_keys(""), reverse=True):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except OSError:
            continue
        removed.append(rf"HKCU\{key_path}")
    return removed


def _windows_entries() -> list[ShellEntry]:
    """Report install state for the Windows context-menu keys."""
    import winreg

    entries = []
    for key_path in _windows_registry_keys(""):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path):
                installed = True
        except OSError:
            installed = False
        entries.append(
            ShellEntry(
                name=key_path.rsplit("\\", 1)[-1],
                location=rf"HKCU\{key_path}",
                installed=installed,
            )
        )
    return entries


def _kde_desktop_entry(executable: str) -> str:
    """Build the KDE service-menu .desktop file content."""
    return f"""[Desktop Entry]
Type=Service
ServiceTypes=KonqPopupMenu/Plugin
MimeType=all/all;inode/directory;
Actions=lscompress;lsextract;
X-KDE-Submenu=LS Compressor

[Desktop Action lscompress]
Name={_COMPRESS_ACTION}
Exec="{executable}" compress %F "%f.tar.zst"

[Desktop Action lsextract]
Name={_EXTRACT_ACTION}
Exec="{executable}" decompress %F "%f-extracted"
"""


def _nautilus_script(name: str, command: str) -> str:
    """Build an executable Nautilus script for selected files."""
    return f"""#!/bin/sh
# {name}
for f in $NAUTILUS_SCRIPT_SELECTED_FILE_PATHS; do
  {command}
done
"""


def _linux_files(home: Path, executable: str) -> dict[Path, str]:
    """Map Linux integration file paths to their contents."""
    kde = _kde_services_dir(home) / "ls-compressor.desktop"
    nautilus = _nautilus_scripts_dir(home)
    return {
        kde: _kde_desktop_entry(executable),
        nautilus
        / _COMPRESS_ACTION: _nautilus_script(
            _COMPRESS_ACTION,
            f'"{executable}" compress "$f" "$f.tar.zst"',
        ),
        nautilus
        / _EXTRACT_ACTION: _nautilus_script(
            _EXTRACT_ACTION,
            f'"{executable}" decompress "$f" "$f-extracted"',
        ),
    }


def _linux_install(home: Path, executable: str) -> list[Path]:
    """Write KDE/Nautilus integration files; return created paths."""
    created = []
    for path, content in _linux_files(home, executable).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, "utf-8")
        if path.suffix != ".desktop":
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        created.append(path)
    return created


def _linux_uninstall(home: Path) -> list[Path]:
    """Remove KDE/Nautilus integration files; return removed paths."""
    removed = []
    for path in _linux_files(home, ""):
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def _linux_entries(home: Path) -> list[ShellEntry]:
    """Report install state for Linux integration files."""
    return [
        ShellEntry(name=path.name, location=str(path), installed=path.exists())
        for path in _linux_files(home, "")
    ]


def install(platform: str | None = None, home: Path | None = None) -> list[str]:
    """Install shell integration for the current platform.

    Returns a list of created file paths or registry key names.
    """
    platform = platform or sys.platform
    home = home or Path.home()
    executable = _executable_command()
    if platform == "darwin":
        return [str(path) for path in _darwin_install(home, executable)]
    if platform == "win32":
        return _windows_install(executable)
    if platform.startswith("linux"):
        return [str(path) for path in _linux_install(home, executable)]
    raise UnsupportedFormatError(f"Shell integration is unsupported on {platform}")


def uninstall(platform: str | None = None, home: Path | None = None) -> list[str]:
    """Remove previously installed shell integration; return removed items."""
    platform = platform or sys.platform
    home = home or Path.home()
    if platform == "darwin":
        return [str(path) for path in _darwin_uninstall(home)]
    if platform == "win32":
        return _windows_uninstall()
    if platform.startswith("linux"):
        return [str(path) for path in _linux_uninstall(home)]
    raise UnsupportedFormatError(f"Shell integration is unsupported on {platform}")


def status(platform: str | None = None, home: Path | None = None) -> list[ShellEntry]:
    """Report every integration point and whether it is installed."""
    platform = platform or sys.platform
    home = home or Path.home()
    if platform == "darwin":
        return _darwin_entries(home)
    if platform == "win32":
        return _windows_entries()
    if platform.startswith("linux"):
        return _linux_entries(home)
    raise UnsupportedFormatError(f"Shell integration is unsupported on {platform}")
