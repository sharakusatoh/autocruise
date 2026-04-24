# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

project_root = Path(SPEC).resolve().parent
sys.path.insert(0, str(project_root / "src"))
from autocruise.version import APP_VERSION, COMPANY_NAME, COPYRIGHT, PRODUCT_NAME, version_tuple

setup_name = "AutoCruiseSetup"
app_version_tuple = version_tuple()
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=app_version_tuple,
        prodvers=app_version_tuple,
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
                        StringStruct("CompanyName", COMPANY_NAME),
                        StringStruct("FileDescription", "AutoCruise Bootstrapper"),
                        StringStruct("FileVersion", APP_VERSION),
                        StringStruct("InternalName", setup_name),
                        StringStruct("OriginalFilename", f"{setup_name}.exe"),
                        StringStruct("ProductName", PRODUCT_NAME),
                        StringStruct("ProductVersion", APP_VERSION),
                        StringStruct("LegalCopyright", COPYRIGHT),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

a = Analysis(
    ["setup_bootstrapper.py"],
    pathex=[str(project_root), str(project_root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=setup_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    icon=str(project_root / "autocruise_logo.ico") if (project_root / "autocruise_logo.ico").exists() else None,
    version=version_info,
)
