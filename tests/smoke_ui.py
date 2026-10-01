# -*- coding: utf-8 -*-
"""界面集成冒烟测试(CI 专用)。

与单元测试的分工:
- 单元测试: 覆盖纯逻辑, 不建窗口
- 本脚本: **实际实例化主窗口并驱动关键交互路径**

历史教训: 迁移到 PySide6 时曾遗留多处 tkinter API
(``pack_forget`` / ``configure(text=)`` / ``progress.start()`` /
``identify_row``), 全部在下载主流程里抛 AttributeError, 而单元测试
与 CI 均为绿灯 —— 因为它们从不构建界面。故本脚本刻意触达那些路径。

用法:
    QT_QPA_PLATFORM=offscreen python tests/smoke_ui.py
退出码非 0 即失败。
"""

import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from PySide6 import QtCore, QtWidgets  # noqa: E402

import app as A  # noqa: E402
import ui_bind  # noqa: E402

FAILED = []


def check(label, cond, extra=""):
    if cond:
        print(f"  [OK] {label}")
    else:
        print(f"  [FAIL] {label} {extra}")
        FAILED.append(label)


def pump(q, rounds=6, pause=0.01):
    for _ in range(rounds):
        q.processEvents()
        time.sleep(pause)


def wait_for(fn, q, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        q.processEvents()
        if fn():
            return True
        time.sleep(0.01)
    return False


def click_row(view, idx):
    """模拟真实鼠标点击一行(清空选中 -> 选中目标行)。

    必须走这条路径而非 shim 的 selection_set: 用户点击只会触发
    Qt 的 itemSelectionChanged, 不会经过 shim 的程序化接口。
    历史上正是"程序化调用正常、真实点击失效"的漏网之处。
    """
    view.clearSelection()
    item = view.topLevelItem(idx)
    if item is None:
        return False
    item.setSelected(True)
    view.setCurrentItem(item)
    return True


def main():
    q = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = QtWidgets.QMainWindow()
    win.resize(1180, 820)
    w = A.App(ui_bind.RootShim(win))
    win.show()
    pump(q)

    print("[1] 背景层")
    check("可见", w.bg_canvas.isVisible())
    check("已绘制", w.bg_canvas._img is not None)
    check("铺满窗口", w.bg_canvas.width() > 1000)

    print("[2] 搜索(直接键入触发, 非仅程序赋值)")
    total = len(w.tool_tree.get_children())
    w.search_entry.setText("python")
    pump(q)
    hit = len(w.tool_tree.get_children())
    check("键入即过滤", 0 < hit < total, f"{total} -> {hit}")
    w.search_entry.setText("")
    pump(q)
    check("清空恢复", len(w.tool_tree.get_children()) == total)

    print("[3] 排序")
    w._sort_combo.setCurrentIndex(1)
    pump(q)
    asc = w.tool_tree.item(w.tool_tree.get_children()[0], "values")[0]
    w._sort_combo.setCurrentIndex(2)
    pump(q)
    desc = w.tool_tree.item(w.tool_tree.get_children()[0], "values")[0]
    check("A-Z 生效", asc <= desc, f"{asc} / {desc}")
    w._sort_combo.setCurrentIndex(0)
    pump(q)

    print("[4] 分类树(模拟真实点击)")
    cats = w.cat_tree.get_children()
    check("分类已填充", len(cats) > 5, f"{len(cats)}")
    # 逐个点击: 点击分类必须真的切换 current_category 并过滤工具列表
    expect_n = {"语言运行时": 8, "构建工具": 2}
    switched = 0
    for i, c in enumerate(cats):
        if c == "all":
            continue
        before = w.current_category
        check("点击目标行存在", click_row(w.cat_view, i), f"idx={i}")
        pump(q)
        if w.current_category != before and w.current_category == c:
            switched += 1
        else:
            print(f"    [!!] 点击 {c!r} 未切换: "
                  f"{before!r} -> {w.current_category!r}")
        if c in expect_n:
            n = len(w.tool_tree.get_children())
            check(f"{c} 工具数={expect_n[c]}", n == expect_n[c], f"实际 {n}")
    check("全部分类点击均可切换", switched == len(cats) - 1,
          f"{switched}/{len(cats) - 1}")
    # 回到全部
    click_row(w.cat_view, 0)
    pump(q)
    check("点'全部'恢复 28 条", len(w.tool_tree.get_children()) == 28,
          f"实际 {len(w.tool_tree.get_children())}")

    print("[4b] 工具列表(模拟真实点击)")
    w.tool_tree.selection_set("all")
    pump(q)
    n_rows = w.tool_view.topLevelItemCount()
    ok_sel = 0
    for idx in (0, 3, min(7, n_rows - 1)):
        if click_row(w.tool_view, idx):
            pump(q)
            if w.current_tool is not None and w.current_versions:
                ok_sel += 1
    check("点击行可填充当前工具与版本", ok_sel == 3, f"{ok_sel}/3")

    print("[4c] 分类 + 搜索组合")
    click_row(w.cat_view, cats.index("语言运行时"))
    pump(q)
    w.keyword.set("python")
    pump(q)
    hit = len(w.tool_tree.get_children())
    check("分类内搜索有结果", 0 < hit < 8, f"实际 {hit}")
    w.keyword.set("")
    pump(q)
    check("清空搜索回到该分类全量",
          len(w.tool_tree.get_children()) == 8,
          f"实际 {len(w.tool_tree.get_children())}")
    click_row(w.cat_view, 0)
    pump(q)

    print("[5] 选中工具与版本下拉")
    kids = w.tool_tree.get_children()
    w.tool_tree.selection_set(kids[0])
    pump(q)
    check("current_tool", w.current_tool is not None)
    check("版本下拉非空", bool(w.version_combo["values"]))
    tool, ver = w._get_selected_version()
    check("取到版本", ver is not None)

    print("[6] identify_row(右键菜单定位)")
    item = w.tool_view.topLevelItem(2)
    r = w.tool_view.visualItemRect(item)
    got = w.tool_tree.identify_row(r.y() + r.height() // 2)
    check("定位第 3 行", got == kids[2], f"{got!r}")
    check("空白返回空串", w.tool_tree.identify_row(-99) == "")

    print("[7] 进度条(旧 start/stop 已不存在)")
    w.progress.configure(mode="indeterminate")
    check("忙碌态 (0,0)",
          (w._prog_widget.minimum(), w._prog_widget.maximum()) == (0, 0))
    w.progress.configure(mode="determinate")
    w.progress.configure(maximum=1000, value=420)
    check("确定态 420/1000", w._prog_widget.value() == 420)
    w._update_progress(512, 1024, 100.0, w._task_seq)
    check("进度文本", bool(w.progress_label.text()))

    print("[8] 按钮显隐(旧 pack_forget 已不存在)")
    w.retry_btn.w.setVisible(True)
    check("retry 可见", w.retry_btn.w.isVisible())
    w.retry_btn.w.setVisible(False)
    check("retry 隐藏", not w.retry_btn.w.isVisible())
    w._set_buttons(True)
    check("忙碌时取消可用", "disabled" not in w.cancel_btn.state())
    w._set_buttons(False)
    check("空闲时取消禁用", "disabled" in w.cancel_btn.state())

    print("[9] 线程桥接(工作线程 after 必须回主线程)")
    main_thread = threading.current_thread()
    seen = []
    t = threading.Thread(target=lambda: w.root.after(
        0, lambda: seen.append(
            threading.current_thread() is main_thread)))
    t.start()
    t.join()
    check("after 已执行", wait_for(lambda: bool(seen), q))
    check("在主线程执行", bool(seen) and seen[0] is True, seen)

    print("[10] 线程桥接(透传参数 + 回收)")
    got_val = []
    t = threading.Thread(target=lambda: w.root.after(
        0, lambda v: got_val.append(v), "V"))
    t.start()
    t.join()
    check("参数已透传", wait_for(lambda: bool(got_val), q)
          and got_val == ["V"], got_val)
    check("定时器已回收", len(w.root._timers) == 0,
          f"残留 {len(w.root._timers)}")

    print("[11] 取消定时")
    fired = []
    key = w.root.after(400, lambda: fired.append(1))
    w.root.after_cancel(key)
    for _ in range(40):
        q.processEvents()
        time.sleep(0.01)
    check("未触发", not fired, fired)

    print("[12] 日志")
    n0 = len(w.log_text.get("1.0", "end"))
    w._log("[smoke] line")
    pump(q)
    check("已追加", len(w.log_text.get("1.0", "end")) > n0)
    check("只读", w._log_widget.isReadOnly())
    w._clear_log()
    pump(q)
    check("已清空", w.log_text.get("1.0", "end").strip() == "")

    print("[13] 下载主流程(旧代码在此必崩)")
    w.tool_tree.selection_set(w.tool_tree.get_children()[0])
    pump(q)
    w.keyword.set("")
    pump(q)
    w.tool_tree.selection_set(w.tool_tree.get_children()[0])
    pump(q)
    ran = {}
    orig = A.ToolDownloader.run
    A.ToolDownloader.run = lambda s, *a, **k: ran.setdefault("yes", True)
    try:
        w.start_download()
        pump(q, rounds=10, pause=0.05)
        check("start_download 不抛异常", True)
        check("世代号已推进", w._task_seq >= 1)
    except Exception as e:
        check("start_download 不抛异常", False,
              f"{type(e).__name__}: {e}")
    finally:
        A.ToolDownloader.run = orig
        w._closing = True
        w.cancel_event.set()

    print("[14] URL 复制")
    w.url_var.set("https://example.com/a.exe")
    pump(q)
    w._copy_url()
    pump(q)
    check("剪贴板已写入", "example.com" in
          QtWidgets.QApplication.clipboard().text())

    print("[15] 关闭")
    check("关闭守卫已安装", isinstance(
        getattr(w, "_close_guard", None), A._CloseGuard))
    w._closing = False
    w._on_close()
    pump(q)
    check("_closing 已置位", w._closing is True)
    check("配置已保存", "save_dir" in w._config)
    w._on_close()
    check("二次关闭不崩", True)

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项: {FAILED}")
        return 1
    print("界面集成冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())