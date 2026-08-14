# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path.cwd()
lexicon_dir = project_root / "src" / "wwm" / "lexicon"
datas = [(str(lexicon_dir), "wwm/lexicon")]

a = Analysis(
    [str(project_root / "src" / "wwm" / "__main__.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=["PyQt6", "PyQt6.QtWidgets", "PyQt6.QtGui", "PyQt6.QtCore"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WWMTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WWMTranslator",
)
