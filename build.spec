# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。

界面层已迁移到 PySide6(Qt 6), 因此:
- hiddenimports 声明 Qt 各模块: 静态分析对 Qt 的动态加载支持有限,
  漏掉会导致运行期ImportError
- excludes 排除用不到的 Qt 子系统(WebEngine/QML/3D/多媒体等),
  它们合计可达数百 MB, 不裁剪会让 exe 体积失控
"""

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Qt 核心与所用的控件/绘图模块
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        # shim 层通过属性转发访问, 静态分析可能漏掉
        'shiboken6',
    ],
    hookspath=[],
    hooksconfig={
        'PySide6': {
            # 不需要 WebEngine; 关掉可省下 QtWebEngineCore(~130MB)
            'exclude_qt_webengine': True,
            # 不需要 QML 引擎
            'exclude_qt_qml': True,
            # 不需要 3D
            'exclude_qt_3d': True,
        },
    },
    runtime_hooks=[],
    excludes=[
        # Qt 里用不到的大件
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuick3D',
        'PySide6.QtQuickWidgets',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtDesigner',
        'PySide6.QtHelp',
        # 原tkinter 版遗留: 迁移后不再需要
        'tkinter',
        'PIL',
        # 体积大且本项目不依赖
        'numpy',
        'matplotlib',
        'pandas',
        'scipy',
    ],
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
    name='Programming-Tools-Downloader',
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