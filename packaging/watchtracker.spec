# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import re
import sys

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPEC).resolve().parents[1]
version_source = (root / "src" / "watchtracker" / "__init__.py").read_text(encoding="utf-8")
version = re.search(r'^__version__ = "([^"]+)"$', version_source, re.MULTILINE).group(1)
version_parts = tuple(int(part) for part in version.split("."))
version_tuple = (*version_parts, *(0 for _ in range(4 - len(version_parts))))[:4]
icon_suffix = (
    "icns" if sys.platform == "darwin" else "ico" if sys.platform == "win32" else "png"
)
icon_path = root / "packaging" / "icons" / f"watchtracker.{icon_suffix}"

version_info = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=version_tuple,
            prodvers=version_tuple,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "Personal Media Tracker"),
                            StringStruct("FileDescription", "Personal Media Tracker"),
                            StringStruct("FileVersion", version),
                            StringStruct("InternalName", "Personal Media Tracker"),
                            StringStruct("LegalCopyright", "Copyright (c) 2026"),
                            StringStruct("OriginalFilename", "Personal Media Tracker.exe"),
                            StringStruct("ProductName", "Personal Media Tracker"),
                            StringStruct("ProductVersion", version),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

datas = [
    (str(root / "src" / "watchtracker" / "static"), "watchtracker/static"),
    (str(root / "src" / "watchtracker" / "migrations"), "watchtracker/migrations"),
]
datas += copy_metadata("personal-media-tracker")
hiddenimports = (
    collect_submodules("webview")
    + collect_submodules("keyring.backends")
    + collect_submodules("pwdlib")
    + collect_submodules("argon2")
)

a = Analysis(
    [str(root / "scripts" / "desktop_entry.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "pip_audit"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Personal Media Tracker" if sys.platform != "linux" else "personal-media-tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon_path),
    version=version_info,
)
collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Personal Media Tracker" if sys.platform != "linux" else "personal-media-tracker",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="Personal Media Tracker.app",
        icon=str(icon_path),
        bundle_identifier="com.personalmediatracker.app",
        info_plist={
            "CFBundleDisplayName": "Personal Media Tracker",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
        },
    )
