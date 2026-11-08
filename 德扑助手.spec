# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from pathlib import Path
import sys

datas = [('layouts.json', '.'), ('assets', 'assets'), ('solver/poker-engine.exe', 'solver'), ('solver/NOTICE.md', 'solver')]
binaries = []
# Conda keeps these outside DLLs. Include them explicitly so a clean machine
# does not depend on an activated Conda environment or its PATH.
for dll in ('ffi.dll', 'tcl86t.dll', 'tk86t.dll'):
    dependency = Path(sys.prefix) / 'Library' / 'bin' / dll
    if dependency.is_file():
        binaries.append((str(dependency), '.'))
hiddenimports = ['mss', 'cv2']
tmp_ret = collect_all('rapidocr_onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['popup.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='德扑助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='德扑助手',
)
