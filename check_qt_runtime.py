# -*- coding: utf-8 -*-
"""校验打包产物是否含可用的 Qt 运行时。

打包后自检脚本, 由 CI/release workflow 调用。退出码非0 即校验失败。

为什么不能搜字节串:
onefile 产物里的 Python 模块位于 zlib 压缩的 PYZ 归档中,
字符串 ``PySide6.QtCore`` 在 exe 原始字节里必然搜不到 —— 用它做
判据会产生"永远失败"的假检测(旧版正是如此)。可靠判据是**未压缩的
二进制资源**: Qt6*.dll、平台插件目录、PyInstaller 的 Qt 运行时钩子。

用法:
    python check_qt_runtime.py [dist/Programming-Tools-Downloader.exe]
"""

import subprocess
import sys
from pathlib import Path

# 必须存在: 缺任一则界面无法初始化
REQUIRED = (
    "Qt6Core.dll",
    "Qt6Gui.dll",
    "Qt6Widgets.dll",
    "platforms",       # 平台插件目录
    "qwindows",        # Windows 平台插件本体
    "pyi_rth_pyside6",  # PyInstaller 生成的 Qt 运行时钩子
)

# 必须已被裁剪: 用不到却打进来会让体积多出上百 MB
FORBIDDEN = (
    "Qt6WebEngineCore.dll",
    "Qt6Qml.dll",
    "Qt63DRender.dll",
)

DEFAULT_EXE = "dist/Programming-Tools-Downloader.exe"


def list_entries(exe):
    """列出 onefile 产物内的条目名。"""
    try:
        r = subprocess.run(
            ["pyi-archive_viewer", "-l", str(exe)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600)
    except FileNotFoundError:
        print("找不到 pyi-archive_viewer。\n"
              "它随 pyinstaller 一起安装, 请确认:\n"
              "  pip install pyinstaller\n"
              "且其 Scripts 目录在 PATH 中。")
        return ""
    except subprocess.TimeoutExpired:
        print("读取产物超时(600秒)")
        return ""
    if r.returncode != 0 and not r.stdout.strip():
        print(f"pyi-archive_viewer 退出码 {r.returncode}")
        return ""
    return r.stdout + r.stderr


def find_exe(arg):
    if arg:
        p = Path(arg)
        if p.exists():
            return p
        print(f"指定的产物不存在: {arg}")
        return None
    hits = sorted(Path("dist").glob("*.exe"))
    if not hits:
        print("dist 下没有 exe, 请先执行 pyinstaller build.spec")
        return None
    return hits[0]


def main():
    exe = find_exe(sys.argv[1] if len(sys.argv) > 1 else None)
    if exe is None:
        return 2

    listing = list_entries(exe)
    if not listing.strip():
        print("无法读取产物内容(pyi-archive_viewer 无输出)")
        return 2

    size_mb = exe.stat().st_size / 1048576
    print(f"产物: {exe}  ({size_mb:.2f} MB)")

    missing = [t for t in REQUIRED if t not in listing]
    fat = [t for t in FORBIDDEN if t in listing]

    print("\n必须包含:")
    for t in REQUIRED:
        mark = "缺失 <<<" if t in missing else "有"
        print(f"  {t:<22} {mark}")

    print("\n应当已裁剪:")
    for t in FORBIDDEN:
        mark = "仍在 <<<" if t in fat else "已排除"
        print(f"  {t:<22} {mark}")

    # 体积下限: 含 Qt 的裁剪版约 30MB+; 退回到 11MB 说明 Qt 没打进去
    if size_mb < 25:
        print(f"\n体积仅 {size_mb:.2f} MB, 疑似未打包 PySide6")
        return 1

    if missing or fat:
        print("\n校验失败")
        return 1
    print("\nQt 运行时完整, 校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())