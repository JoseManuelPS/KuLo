# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/home/josemanuelps/projects/kulo/src/kulo/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['kubernetes_asyncio', 'kubernetes_asyncio.client', 'kubernetes_asyncio.config', 'kubernetes_asyncio.watch', 'rich', 'rich.console', 'rich.table', 'rich.text', 'rich.panel'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL', 'scipy', 'pandas', 'setuptools', 'wheel'],
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
    name='kulo-v2.1.0-linux-x86_64',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
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
