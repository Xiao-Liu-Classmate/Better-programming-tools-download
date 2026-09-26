# -*- coding: utf-8 -*-
"""代码卫生自检 (仅用标准库, 无需联网安装依赖)

    python -m tests.selfcheck

检查项:
1. 字节码编译 (语法错误)
2. 未使用的顶层导入
3. 文件编码声明
4. 过长的代码行 (仅报告, 不阻断)
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGETS = ["app.py", "tools.py", "tooldata.py",
           "tests/test_app.py", "tests/selfcheck.py"]
MAX_LINE = 100

errors = []
warnings = []


def check_compile(path):
    """编译检查, 返回源码或 None。所有读取失败都归类上报,
    避免自检工具自身以 traceback 崩掉。"""
    try:
        src = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        errors.append(f"{path.name} 编码错误(需 UTF-8): {e}")
        return None
    except (OSError, ValueError) as e:
        errors.append(f"{path.name} 读取失败: {e}")
        return None
    try:
        compile(src, str(path), "exec")
    except SyntaxError as e:
        errors.append(f"{path.name}:{e.lineno} 语法错误: {e.msg}")
        return None
    except ValueError as e:
        # 例如源码含 NUL 字节
        errors.append(f"{path.name} 值错误: {e}")
        return None
    return src


def check_encoding_declared(path, src):
    """PEP 263: 非 ASCII 源码应声明编码"""
    with open(path, "rb") as f:
        if f.read(3) == b"\xef\xbb\xbf":      # UTF-8 BOM
            return
    for line in src.splitlines()[:2]:
        if "coding" in line and "utf-8" in line.lower():
            return
    if any(ord(c) > 127 for c in src):
        errors.append(f"{path.name} 含非 ASCII 字符但未声明 "
                      f"# -*- coding: utf-8 -*-")


def check_unused_imports(path, src):
    """检测模块级未使用导入。

    - 只看模块级(顶层)的 import, 忽略函数体内的局部导入
    - 名字出现在任意字符串常量或 __all__ 中即视为已使用
    - 识别 # noqa 标注
    """
    tree = ast.parse(src, str(path))
    imported = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                name = (a.asname or a.name).split(".")[0]
                imported[name] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.col_offset != 0:
                continue
            for a in node.names:
                if a.name != "*":
                    imported[a.asname or a.name] = node.lineno

    if not imported:
        return

    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(
                node.value, str):
            # __all__ / 注解 / 文档字符串中的名字
            used.add(node.value.strip())

    lines = src.splitlines()
    for name, lineno in imported.items():
        if name in used:
            continue
        # 尊重 # noqa 抑制
        if "noqa" in lines[lineno - 1]:
            continue
        warnings.append(
            f"{path.name}:{lineno} 可能未使用的导入: {name}")


def check_long_lines(path, src):
    long_lines = 0
    for i, line in enumerate(src.splitlines(), 1):
        if len(line) > MAX_LINE:
            long_lines += 1
            if long_lines <= 3:
                warnings.append(
                    f"{path.name}:{i} 行长 {len(line)} "
                    f"(超过 {MAX_LINE})")
    if long_lines > 3:
        warnings.append(f"{path.name} 共 {long_lines} 行超过 "
                        f"{MAX_LINE} 字符")
    return long_lines


def main():
    total_long = 0
    print("=" * 58)
    print("代码卫生自检")
    print("=" * 58)
    for rel in TARGETS:
        path = ROOT / rel
        if not path.exists():
            errors.append(f"{rel} 不存在")
            continue
        src = check_compile(path)
        if src is None:
            continue
        check_encoding_declared(path, src)
        check_unused_imports(path, src)
        n = check_long_lines(path, src)
        total_long += n
        print(f"  [OK] {rel}  ({len(src.splitlines())} 行)")

    print("-" * 58)
    if warnings:
        print(f"提示 {len(warnings)} 条:")
        for w in warnings:
            print(f"  ! {w}")
    else:
        print("无提示")

    if errors:
        print(f"\n错误 {len(errors)} 条:")
        for e in errors:
            print(f"  x {e}")
        print("=" * 58)
        return 1

    print(f"\n自检通过 (超长行 {total_long} 处, 仅提示)")
    print("=" * 58)
    return 0


if __name__ == "__main__":
    sys.exit(main())
