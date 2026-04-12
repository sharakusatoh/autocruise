# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules
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
from autocruise.version import APP_NAME, APP_TITLE, APP_VERSION, COMPANY_NAME, COPYRIGHT, PRODUCT_NAME, version_tuple

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
                        StringStruct("FileDescription", APP_TITLE),
                        StringStruct("FileVersion", APP_VERSION),
                        StringStruct("InternalName", APP_NAME),
                        StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
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


def include_tree(relative_root: str) -> list[tuple[str, str]]:
    root = project_root / relative_root
    if not root.exists():
        return []

    datas: list[tuple[str, str]] = []
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        destination = str(file_path.parent.relative_to(project_root))
        datas.append((str(file_path), destination))
    return datas


datas: list[tuple[str, str]] = []
for folder_name in ("constitution", "apps", "tasks", "docs"):
    datas.extend(include_tree(folder_name))

for relative_file in (
    "users/default/provider_settings.json",
    "users/default/user_custom_prompt.md",
    "users/default/preferences.yaml",
    "README.md",
    "autocruise_logo.ico",
    "autocruise_logo.png",
    "autocruise_logo.svg",
):
    source = project_root / relative_file
    if source.exists():
        datas.append((str(source), str(source.parent.relative_to(project_root))))

uia_client_script = project_root / "src" / "autocruise" / "infrastructure" / "windows" / "uia_client.ps1"
datas.append((str(uia_client_script), "autocruise/infrastructure/windows"))

hiddenimports = collect_submodules("autocruise")


a = Analysis(
    ["main.py"],
    pathex=[str(project_root), str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    contents_directory=".",
    icon=str(project_root / "autocruise_logo.ico") if (project_root / "autocruise_logo.ico").exists() else None,
    version=version_info,
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
