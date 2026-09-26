# -*- coding: utf-8 -*-
"""工具数据层 —— 零第三方依赖(仅标准库), 且不依赖 tkinter。

存在的意义: 工具定义的强校验与读写属于"数据层"逻辑, 不含任何 GUI
行为。抽到独立模块后, 无图形环境(如 CI 的 Linux 容器)也能校验
tools.py 中的内置工具库, 而不必复制一份校验规则。

app.py 从本模块导入 validate_tool / DEPLOY_TYPES /
load_custom_tools / save_custom_tools, 对外 API 保持不变。
"""
import json
import os
import sys
from collections import Counter

DEPLOY_TYPES = {"msi", "exe", "extract", "custom", "none"}


def validate_tool(t):
    """强校验工具定义, 非法则返回 None"""
    if not isinstance(t, dict):
        return None
    name = t.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    versions = t.get("versions")
    if not isinstance(versions, list) or not versions:
        return None
    clean_versions = []
    for v in versions:
        if not isinstance(v, dict):
            return None
        label, url = v.get("label"), v.get("url")
        if not isinstance(label, str) or not label.strip():
            return None
        # 仅允许 http(s), 杜绝 file:// 读取本地文件
        if not isinstance(url, str) or not url.startswith(
                ("http://", "https://")):
            return None
        clean_versions.append({
            "label": label.strip(), "url": url.strip()})
    t = dict(t)
    t["name"] = name.strip()
    t["versions"] = clean_versions

    if not isinstance(t.get("category"), str) \
            or not t["category"].strip():
        t["category"] = "自定义"
    else:
        # 去除首尾空白, 否则 " 构建工具 " 会通过校验却在 UI 出现空白页签
        t["category"] = t["category"].strip()
    if not isinstance(t.get("description"), str):
        t["description"] = str(t.get("description") or "")
    # homepage 在工具顶层 (不在 deploy 内), 非字符串会在
    # webbrowser.open() 处抛 TypeError
    if "homepage" in t and not isinstance(t["homepage"], str):
        t.pop("homepage", None)
    deploy = t.get("deploy")
    if not isinstance(deploy, dict):
        deploy = {"type": "none"}
    else:
        deploy = dict(deploy)
        if deploy.get("type") not in DEPLOY_TYPES:
            deploy["type"] = "none"
        # 字段类型强校验: 非字符串/布尔会让后续 _resolve_path 等
        # 无 try/except 的调用链抛 AttributeError 导致启动崩溃
        for key in ("verify", "homepage", "args", "cmd"):
            if key in deploy and not isinstance(deploy[key], str):
                deploy.pop(key, None)
        if "need_admin" in deploy and not isinstance(
                deploy.get("need_admin"), bool):
            deploy.pop("need_admin", None)
    if deploy.get("type") == "custom" and not str(
            deploy.get("cmd", "")).strip():
        deploy = {"type": "none"}
    t["deploy"] = deploy
    return t


def load_custom_tools(path):
    """加载自定义工具 (过滤非法项, 兼容导出格式)

    path 为文件路径; 文件缺失或内容损坏时返回空列表。
    """
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("tools", [])
        if not isinstance(data, list):
            return []
        out = []
        for t in data:
            clean = validate_tool(t)
            if clean:
                out.append(clean)
        return out
    except Exception:
        return []


def save_custom_tools(tools, path):
    """保存自定义工具到 path (失败静默, 不影响主流程)"""
    if not path:
        return False
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(tools, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def check_tool_library(tools, categories=None):
    """校验一批工具定义的内在一致性, 返回错误信息列表。

    校验项:
      - 每个工具能通过 validate_tool
      - 工具名不重复
      - category 已在 CATEGORIES 中声明
      - 同一工具内版本标签不重复
      - 声明的分类下至少有一个工具(避免界面出现空白页签)
    """
    errors = []
    if not isinstance(tools, list):
        return ["tools 不是列表"]
    if not tools:
        return ["工具库为空"]

    names = []
    for t in tools:
        name = t.get("name") if isinstance(t, dict) else None
        if validate_tool(t) is None:
            errors.append(f"非法工具定义: {name!r}")
            continue
        names.append(t["name"])
        labels = [v["label"] for v in t["versions"]]
        if len(labels) != len(set(labels)):
            errors.append(f"{t['name']} 版本标签重复: {labels}")
        if categories:
            if t["category"] not in categories:
                errors.append(
                    f"{t['name']} 的分类 {t['category']!r} "
                    f"未在 CATEGORIES 中声明")

    cnt = Counter(names)
    dupes = {n for n, c in cnt.items() if c > 1}
    if dupes:
        errors.append(f"工具名重复: {sorted(dupes)}")

    if categories:
        used = {t.get("category") for t in tools
                if isinstance(t, dict)}
        for c in categories:
            if c not in used:
                errors.append(f"分类 {c!r} 下没有任何工具")

    return errors


def main(argv=None):
    """命令行入口: 校验内置工具库, 供 CI 使用。

    用法:
        python tooldata.py            # 仅校验
        python tooldata.py --stats    # 校验并输出分类统计

    退出码: 0 = 全部通过, 1 = 存在问题
    """
    if argv is None:
        argv = sys.argv[1:]
    show_stats = "--stats" in argv

    try:
        from tools import CATEGORIES, TOOLS
    except ImportError as e:
        print(f"[FAIL] 无法导入 tools.py: {e}")
        return 1

    errors = check_tool_library(TOOLS, CATEGORIES)
    if errors:
        print(f"[FAIL] 工具库校验未通过 ({len(errors)} 项):")
        for e in errors:
            print(f"  x {e}")
        return 1

    # 仅在校验通过后再统计, 且防御非 dict 项
    n_ver = sum(len(t.get("versions", [])) for t in TOOLS
                if isinstance(t, dict))
    print(f"[OK] {len(TOOLS)} 个工具 / {n_ver} 个版本链接"
          f" / {len(CATEGORIES)} 个分类, 校验全部通过")
    if show_stats:
        for cat in CATEGORIES:
            names = [t["name"] for t in TOOLS
                     if isinstance(t, dict) and t.get("category") == cat]
            print(f"  - {cat} ({len(names)}): {'、'.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
