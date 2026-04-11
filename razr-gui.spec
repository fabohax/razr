# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

SPEC_PATH = Path(globals().get('SPEC', Path.cwd() / 'razr-gui.spec')).resolve()
PROJECT_DIR = SPEC_PATH.parent
GUI_ENTRY = str(PROJECT_DIR / 'gui.py')


a = Analysis(
    [GUI_ENTRY],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='razr-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
