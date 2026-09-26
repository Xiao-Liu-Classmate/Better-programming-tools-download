# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置
#
# 手动打包 (推荐, 会自动更新本文件):
#   pyinstaller --onefile --windowed --name "编程工具下载器" \
#               --icon app_icon.ico --noupx app.py
#
# 或直接使用本文件:
#   pyinstaller 编程工具下载器.spec
#
# 产物: dist\编程工具下载器.exe (约 11 MB)
# 说明: upx=False —— UPX 压缩易被杀软误报, 体积差异可忽略

a = Analysis(
    ['app.py'],
    pathex=[],
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
    name='编程工具下载器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)
