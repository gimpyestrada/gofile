# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['drag_drop_uploader.py'],
    pathex=[],
    binaries=[],
    # Only the icon is bundled. config.json must NOT be listed here: it would
    # be embedded in the exe, where anyone with the binary can extract the API
    # tokens. The app reads config.json from the directory beside the exe.
    # The .py modules do not belong here either -- PyInstaller already puts
    # imported modules in the PYZ archive.
    datas=[('upload_cloud_file_icon_181534.ico', '.')],
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
    name='GofileUploader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['upload_cloud_file_icon_181534.ico'],
)
