# -*- coding: utf-8 -*-
"""tkinter -> PySide6 兼容层。

业务层代码原本直接操作 tkinter 控件(``StringVar`` /
``Treeview.insert`` / ``Text.insert("end", ...)`` / ``root.after`` /
``messagebox`` 等)。这些调用若全部改写, 会侵入下载、部署、批量队列
等业务逻辑, 与"业务代码不动"的要求冲突。

本模块提供外观与 tkinter 一致的薄封装, 让业务层保持原样:

- :class:`RootShim`   —— ``after`` / ``destroy`` / ``bind`` / ``title`` 等
- :class:`Var`        —— ``StringVar`` (``get`` / ``set`` / ``trace_add``)
- :class:`TreeShim`   —— ``Treeview`` (``insert`` / ``item`` / ``selection``)
- :class:`ComboShim`  —— ``Combobox`` (``["values"]`` / ``current``)
- :class:`TextShim`   —— ``Text`` (``insert`` / ``delete`` / ``see`` / ``index``)
- :class:`Button`     —— ``state()`` / ``set_state`` / ``configure(state=)``
- :class:`ProgressShim` —— ``configure(maximum=, value=)``

线程约定: 下载/安装线程只允许通过 ``after()`` 回到主线程操作控件,
与原tkinter 版本一致(:class:`RootShim` 内部用信号做跨线程投递)。
"""

import itertools
import os

from PySide6 import QtCore, QtGui, QtWidgets

APP = None          # 由 app.py 在启动时注入 QApplication


def _qapp():
    """取得QApplication(不存在则创建)。"""
    global APP
    if APP is None:
        APP = QtWidgets.QApplication.instance()
        if APP is None:
            APP = QtWidgets.QApplication([])
    return APP


def _qapp_ref():
    """WeakRef 风格的取用, 避免导入期就要求 QApplication 已存在。"""
    return _qapp()


# ─────────────────────── 变量 ───────────────────────


class Var:
    """``StringVar`` 等价物, 绑定到 QWidget 或独立持值。

    必须监听控件自身的文本变更: 用户直接键入 QLineEdit 走的是
    ``widget.setText()``, 不会经过 ``Var.set()``。若只在自己的
    set() 里触发回调, "边输入边过滤"这类 trace 行为会完全失效
    (tkinter 的 StringVar trace 是在控件编辑时触发的)。
    """

    def __init__(self, widget=None, value="", on_change=None):
        self._widget = widget
        self._value = "" if value is None else str(value)
        self._callbacks = []
        self._on_change = on_change
        # 置位期间抑制回调: 避免 Var.set() -> setText -> textChanged
        # -> _fire 与 set 自身的 _fire 重复触发
        self._muted = False
        if widget is not None:
            widget.setText(self._value)
            try:
                widget.textChanged.connect(lambda _t: self._fire())
            except (AttributeError, TypeError):
                pass      # 非文本控件(如 QLabel)无此信号, 属正常

    # -- 读写 --
    def get(self):
        if self._widget is not None:
            return self._widget.text()
        return self._value

    def set(self, value):
        value = "" if value is None else str(value)
        old = self.get()
        if value == old:
            return
        # 先静音再写入: setText 会同步触发 textChanged -> _fire,
        # 若不静音, 同一次赋值会回调两遍
        self._muted = True
        try:
            if self._widget is not None:
                self._widget.setText(value)
            else:
                self._value = value
        finally:
            self._muted = False
        self._fire()

    def _fire(self):
        if self._muted:
            return
        for cb in list(self._callbacks):
            try:
                cb()
            except Exception:
                pass
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass

    def trace_add(self, _mode, callback):
        """兼容 ``trace_add("write", fn)``。"""
        self._callbacks.append(callback)
        return len(self._callbacks)


# ─────────────────────── 按钮 ───────────────────────


class Button:
    """按钮 shim: 统一 ``state`` / ``configure(state=)`` / ``set_state``。"""

    def __init__(self, widget):
        self.w = widget

    def __getattr__(self, name):
        return getattr(self.w, name)

    # -- 状态 --
    def _apply_state(self, state):
        self.w.setEnabled(state not in ("disabled", "readonly"))

    def state(self):
        """返回 ``["disabled"]`` 或 ``[]``(对齐 ttk)。"""
        return [] if self.w.isEnabled() else ["disabled"]

    def set_state(self, state):
        self._apply_state(state)

    def configure(self, **kw):
        state = kw.get("state")
        if state is not None:
            self._apply_state(state)
        text = kw.get("text")
        if text is not None:
            self.w.setText(text)
        return self

    config = configure


# ─────────────────────── 下拉框 ───────────────────────


class ComboShim:
    """``Combobox`` 等价物: ``["values"]`` / ``current(n)`` / ``current()``。"""

    def __init__(self, widget):
        self.w = widget

    def __getattr__(self, name):
        return getattr(self.w, name)

    def __setitem__(self, key, value):
        if key == "values":
            self.w.clear()
            self.w.addItems([str(v) for v in (value or [])])
        elif key == "state":
            self.w.setEnabled(value not in ("disabled", "readonly"))
        else:
            raise KeyError(key)

    def __getitem__(self, key):
        if key == "values":
            return [self.w.itemText(i)
                    for i in range(self.w.count())]
        if key == "state":
            return "normal" if self.w.isEnabled() else "disabled"
        raise KeyError(key)

    def current(self, index=None):
        if index is None:
            return self.w.currentIndex()
        if index >= 0:
            self.w.setCurrentIndex(index)
        return None

    def bind(self, _event, callback):
        """``<<ComboboxSelected>>`` -> currentIndexChanged。"""
        self.w.currentIndexChanged.connect(lambda _i: callback(None))

    def winfo_exists(self):
        return True


# ─────────────────────── 树控件 ───────────────────────

# tag 名 ->前景色; 与原tk 版tag_configure 对应
TAG_COLORS = {}


class _TreeItem:
    """包装 QTreeWidgetItem, 暴露 ``item(id, "tags")`` 语义。"""

    __slots__ = ("_q",)

    def __init__(self, q):
        self._q = q

    def tags(self):
        return list(self._q.data(0, QtCore.Qt.UserRole + 1) or [])

    def set_tags(self, tags):
        self._q.setData(0, QtCore.Qt.UserRole + 1, list(tags))

    def values(self):
        return [self._q.text(i)
                for i in range(self._q.columnCount())]


class TreeShim:
    """``ttk.Treeview`` 等价物。

    仅实现业务层实际用到的 API:
    ``delete`` / ``insert`` / ``item`` / ``selection`` /
    ``selection_set`` / ``get_children`` / ``heading`` / ``column`` /
    ``tag_configure`` / ``see`` / ``bind``
    """

    def __init__(self, widget, columns=None, selectmode="browse"):
        self.w = widget
        self._columns = list(columns or ())
        self._iids = {}            # iid -> _TreeItem
        self._sel = []
        self._next_row = 0
        self._cbs = {}
        self._filters = []
        # 回调重入保护: 业务层回调里可能再改选中(如 load_category)
        self._in_select_cb = False

        widget.setColumnCount(len(self._columns))
        widget.setHeaderLabels(self._columns)
        widget.setAlternatingRowColors(True)
        if selectmode == "extended":
            widget.setSelectionMode(
                QtWidgets.QAbstractItemView.ExtendedSelection)
        else:
            widget.setSelectionMode(
                QtWidgets.QAbstractItemView.SingleSelection)

        # 视图侧改动 -> 回调 selectionChanged
        widget.itemSelectionChanged.connect(self._on_view_selection)
        # 保留排序视图的选中同步
        self._observer = widget.model()

    # ── 内部 ──

    def _on_view_selection(self):
        """用户点击/键盘移动导致的选中变化(Qt 信号入口)。

        必须在**这里**派发 ``<<TreeviewSelect>>``: 这是用户交互唯一
        会走的路径, 业务层(_on_category_select / _on_tool_select)全
        靠该回调。只更新 ``_sel`` 而不派发, 表现为"点击分类无反应"。
        """
        items = self.w.selectedItems()
        new_sel = [self._iid_of(it) for it in items]
        if new_sel == self._sel:
            return          # 选择未变化, 不重复派发(对齐 ttk 语义)
        self._sel = new_sel
        if self._in_select_cb:
            return          # 防回调内再次改选中导致递归
        self._in_select_cb = True
        try:
            self._emit_select()
        finally:
            self._in_select_cb = False

    def _iid_of(self, qitem):
        iid = qitem.data(0, QtCore.Qt.UserRole)
        return iid if iid else ""

    def _emit_select(self):
        cb = self._cbs.get("<<TreeviewSelect>>")
        if cb:
            try:
                cb(None)
            except Exception:
                pass

    # ── ttk API ──

    def delete(self, *items):
        # 全量删除: 静音信号, 避免 clear() 连带清空选中而误派发回调
        # (调用方随后会自行 selection_set)
        self.w.blockSignals(True)
        try:
            if not items:
                self.w.clear()
                self._iids.clear()
                self._sel = []
                return
            drop = {str(i) for i in items}
            keep = [(k, o) for k, o in self._iids.items()
                    if k not in drop]
            self.w.clear()
            self._iids.clear()
            self._sel = []
            for key, obj in keep:
                vals = (obj.values() if isinstance(obj, _TreeItem)
                        else list(obj))
                tgs = list(obj.tags()) if isinstance(obj, _TreeItem) else []
                q = QtWidgets.QTreeWidgetItem(self.w)
                q.setData(0, QtCore.Qt.UserRole, key)
                for c, v in enumerate(vals):
                    q.setText(c, str(v))
                it = _TreeItem(q)
                it.set_tags(tgs)
                self._iids[key] = it
            self._apply_tag_colors()
        finally:
            self.w.blockSignals(False)

    def insert(self, _parent, _index, iid=None, values=(), tags=()):
        """追加一行。

        增量追加而非全量重建: ``filter_tools`` 会对每个工具调一次
        insert, 全量重建会退化成 O(n^2) 次 QTreeWidgetItem 构造
        (导入大量自定义工具时明显卡顿)。
        """
        key = str(iid)
        if not key:
            return
        q = QtWidgets.QTreeWidgetItem(self.w)
        q.setData(0, QtCore.Qt.UserRole, key)
        for c, v in enumerate(values):
            if c < self.w.columnCount():
                q.setText(c, str(v))
        it = _TreeItem(q)
        it.set_tags(tags)
        self._iids[key] = it
        # 只重绘该行, 不做全表遍历
        if "installed" in (tags or ()):
            q.setForeground(0, QtGui.QColor(
                TAG_COLORS.get("installed", "#E8ECF8")))
        if "downloading" in (tags or ()):
            bg = QtGui.QColor(TAG_COLORS.get("downloading_bg", "#2A3550"))
            fg = QtGui.QColor(TAG_COLORS.get("downloading_fg", "#7C5CFF"))
            for c in range(q.columnCount()):
                q.setBackground(c, bg)
                q.setForeground(c, fg)

    def item(self, iid, option=None, **kw):
        it = self._iids.get(str(iid))
        if it is None:
            raise KeyError(iid)
        if option == "values":
            return it.values()
        if option == "tags":
            return tuple(it.tags())
        tags = kw.get("tags")
        if tags is not None:
            it.set_tags(tags)
            self._apply_tag_colors()
        return it

    def selection(self):
        return list(self._sel)

    def selection_set(self, iid):
        """选中单行(对齐 ttk selectmode="browse")。

        实现上会先清空再选中, 中间态会被 Qt 的 itemSelectionChanged
        捕获, 导致同一次操作派发两次回调("清空" + "选中")。故这里
        静音 Qt 信号, 统一在末尾按 ttk 语义派发一次。
        """
        key = str(iid)
        if key not in self._iids:
            return
        self.w.blockSignals(True)
        try:
            self.w.clearSelection()
            for i in range(self.w.topLevelItemCount()):
                q = self.w.topLevelItem(i)
                if self._iid_of(q) == key:
                    q.setSelected(True)
                    self.w.setCurrentItem(q)
                    break
        finally:
            self.w.blockSignals(False)
        if self._sel == [key]:
            return              # 选中未变化, 不派发
        self._sel = [key]
        if not self._in_select_cb:
            self._in_select_cb = True
            try:
                self._emit_select()
            finally:
                self._in_select_cb = False

    def selection_add(self, iid):
        key = str(iid)
        if key not in self._iids:
            return
        for i in range(self.w.topLevelItemCount()):
            q = self.w.topLevelItem(i)
            if self._iid_of(q) == key:
                q.setSelected(True)
                break

    def get_children(self, _parent=""):
        return list(self._iids.keys())

    def heading(self, col, **kw):
        text = kw.get("text")
        if text is None:
            return None
        idx = self._columns.index(col) if col in self._columns else 0
        item = self.w.headerItem()
        item.setText(idx, str(text))

    def column(self, col, **kw):
        if "width" not in kw:
            return {}
        idx = self._columns.index(col) if col in self._columns else 0
        header = self.w.header()
        # 关键: stretchLastSection 默认为 True, 会与调用方为某列设置的
        # Stretch 叠加, 把各列宽度重算成均分。ttk 的 column() 没有
        # 这种行为, 故这里显式关闭以对齐 ttk 语义。
        header.setStretchLastSection(False)
        stretch = kw.get("stretch")
        mode = (QtWidgets.QHeaderView.Stretch if stretch
                else QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(idx, mode)
        # Fixed 模式下 setColumnWidth 会被忽略, 必须用 resizeSection
        header.resizeSection(idx, int(kw["width"]))
        anchor = kw.get("anchor")
        if anchor:
            amap = {"w": QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                    "e": QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                    "center": QtCore.Qt.AlignCenter}
            self.w.headerItem().setTextAlignment(
                idx, amap.get(anchor, amap["w"]))
        return {}

    def tag_configure(self, tag, **kw):
        color = kw.get("foreground")
        if color:
            TAG_COLORS[tag] = color
        self._apply_tag_colors()

    def _apply_tag_colors(self):
        color = QtGui.QColor(TAG_COLORS.get("installed", "#E8ECF8"))
        inst_bg = QtGui.QColor(TAG_COLORS.get(
            "downloading_bg", "#2A3550"))
        inst_fg = QtGui.QColor(TAG_COLORS.get(
            "downloading_fg", "#7C5CFF"))
        for i in range(self.w.topLevelItemCount()):
            q = self.w.topLevelItem(i)
            tags = set(q.data(0, QtCore.Qt.UserRole + 1) or [])
            if "installed" in tags:
                q.setForeground(0, color)
            else:
                q.setForeground(0, QtGui.QColor("#E8ECF8"))
            if "downloading" in tags:
                for c in range(q.columnCount()):
                    q.setBackground(c, inst_bg)
                    q.setForeground(c, inst_fg)
            else:
                for c in range(q.columnCount()):
                    q.setBackground(c, QtGui.QColor(0, 0, 0, 0))

    def see(self, iid):
        for i in range(self.w.topLevelItemCount()):
            q = self.w.topLevelItem(i)
            if self._iid_of(q) == str(iid):
                self.w.scrollToItem(q)
                break

    def identify_row(self, y):
        """返回纵向坐标 ``y`` 所在行的 iid, 不在任何行上返回空串。

        ttk 用 ``identify_row(event.y)`` 实现"右键点击哪行就操作哪行",
        业务层(_show_context_menu)依赖这一语义。

        实现用 ``indexAt`` 而非逐行 ``visualItemRect.contains``:
        后者要求点落在 item 的 x 区间内, 而事件坐标来自 viewport,
        x 可能落在缩进区(实测 x=0 时永远判不中)。
        """
        idx = self.w.indexAt(QtCore.QPoint(1, int(y)))
        if not idx.isValid():
            return ""
        q = self.w.itemFromIndex(idx)
        if q is None:
            return ""
        return self._iid_of(q)

    def focus_set(self):
        self.w.setFocus()

    def bind(self, event, callback):
        if event == "<<TreeviewSelect>>":
            self._cbs[event] = callback
            return
        if event in ("<Double-1>", "<Button-3>"):
            if event == "<Double-1>":
                etype = QtCore.QEvent.Type.MouseButtonDblClick
                button = QtCore.Qt.MouseButton.LeftButton
            else:
                etype = QtCore.QEvent.Type.MouseButtonPress
                button = QtCore.Qt.MouseButton.RightButton
            filt = _MouseFilter(etype, button, callback)
            # 必须保留引用: eventFilter 对象被回收后过滤即失效
            self._filters.append(filt)
            self.w.viewport().installEventFilter(filt)

    def configure(self, **kw):
        return self

    config = configure


class _MouseFilter(QtCore.QObject):
    """把 Qt 鼠标事件翻译成 ttk 风格的 ``<Double-1>`` / ``<Button-3>``。"""

    def __init__(self, etype, button, callback):
        super().__init__()
        self._etype = etype
        self._button = button
        self._cb = callback

    def eventFilter(self, obj, event):
        if (event.type() == self._etype
                and event.button() == self._button):
            self._cb(_MouseEventShim(event))
        return False


class _MouseEventShim:
    """提供 ``event.x`` / ``event.y_root`` 等 tk 属性。"""

    def __init__(self, qev):
        self._q = qev
        self.x = int(qev.position().x())
        self.y = int(qev.position().y())
        self.x_root = int(qev.globalPosition().x())
        self.y_root = int(qev.globalPosition().y())


# ─────────────────────── 文本区 ───────────────────────


class TextShim:
    """``tk.Text`` 等价物(日志区)。"""

    def __init__(self, widget):
        self.w = widget
        widget.setReadOnly(True)

    def __getattr__(self, name):
        return getattr(self.w, name)

    def configure(self, **kw):
        state = kw.get("state")
        if state is not None:
            self.w.setReadOnly(state == "disabled")
        return self

    config = configure

    def insert(self, _where, text):
        self.w.appendPlainText(text)

    def delete(self, _a, _b):
        self.w.clear()

    def get(self, _a, _b):
        return self.w.toPlainText()

    def see(self, _where):
        sb = self.w.verticalScrollBar()
        sb.setValue(sb.maximum())

    def index(self, _where):
        # 行数: blockCount 含末尾空块, 减1 得更接近 ttk
        return f"1.0"


# ─────────────────────── 进度条 ───────────────────────


class ProgressShim:
    """``configure(maximum=, value=)`` 等价物。"""

    def __init__(self, widget):
        self.w = widget

    def __getattr__(self, name):
        return getattr(self.w, name)

    def configure(self, **kw):
        if "mode" in kw:
            # ttk 的 indeterminate 忙碌动画, 在 Qt 里对应 range(0, 0)
            if kw["mode"] == "indeterminate":
                self.w.setRange(0, 0)
            else:
                self.w.setRange(0, 100)
        if "maximum" in kw:
            # maximum=0 在 Qt 会导致进度计算除零, 必须钳位
            self.w.setMaximum(max(int(kw["maximum"]), 1))
        if "value" in kw:
            # 忙碌态下setValue 会被 Qt 忽略, 无副作用
            self.w.setValue(int(kw["value"]))
        return self

    config = configure


# ─────────────────────── 窗口壳 ───────────────────────


class _Invoke(QtCore.QObject):
    """信号中转: 使 after() 可从任意线程调用。

    必须挂到窗口下作为子对象: 若无 parent 且生命周期只由 Python
    引用控制, 窗口销毁后它可能先于 QApplication 被 GC, 底层 C++
    对象已释放而 Python 包装仍在 —— 解释器退出阶段访问它会触发
    0xC0000409。
    """

    sig = QtCore.Signal(object)


class RootShim:
    """``tk.Tk`` 等价物: 窗口句柄 + 定时器 + 快捷键 + 模态框入口。"""

    def __init__(self, window):
        self._w = window
        # parent 指向窗口: 随窗口一起销毁, 杜绝悬空 QObject
        self._invoke = _Invoke(window)
        self._invoke.sig.connect(self._run_cb)
        self._timers = {}
        # itertools.count 的 next() 在 CPython 下线程安全, 避免工作线程
        # 并发调用 after() 时计数器竞争导致 key 碰撞
        self._after_seq_gen = itertools.count(1)
        self._after_seq = 0      # 主线程内已分配到的最新 key
        self._closing = False

    # -- 定时器 --
    def after(self, ms, fn, *args):
        """延时执行 ``fn(*args)``。

        线程安全 —— 业务层会在下载/安装工作线程里调用本方法。
        签名与 tkinter ``after(ms, func, *args)`` 一致: 业务代码
        ``root.after(2000, self._restore_status, old)`` 依赖把额外
        参数透传给回调。

        实现要点: QTimer 必须在**主线程**创建。若在工作线程里new 出
        QTimer, 其线程亲和性属于该工作线程, 而 Python 线程没有 Qt 事件
        循环, 定时器永不触发(且 Qt 会打印 "Timers can only be used with
        threads started with QThread"), 导致进度条不动、下载完成后不
        进入安装、批量队列不推进。

        故此处只做一件事: 把回调经信号投递回主线程, 真正的 QTimer 在
        ``_run_cb``(已在主线程) 中创建。
        """
        cb = fn if not args else (lambda: fn(*args))
        self._after_seq = next(self._after_seq_gen)
        self._invoke.sig.emit(
            (self._after_seq, max(int(ms), 0), cb))
        return self._after_seq

    def _after_in_main(self, ms, fn):
        """在主线程创建并启动定时器(仅由 _run_cb 调用)。"""
        self._after_seq += 1
        key = self._after_seq
        t = QtCore.QTimer(self._w)
        t.setSingleShot(True)
        t.timeout.connect(lambda: self._fire(key, fn))
        t.start(ms)
        self._timers[key] = t
        return key

    def _fire(self, key, fn):
        # 先从登记表移除并销毁定时器: 否则每次 after() 都会在字典里
        # 留下一个 QTimer(下载时约 5 次/秒), 既泄漏内存也拖慢查找
        t = self._timers.pop(key, None)
        if t is not None:
            t.deleteLater()
        if self._closing or fn is None:
            return
        try:
            fn()
        except Exception:
            pass

    def _run_cb(self, job):
        if self._closing:
            return
        if isinstance(job, tuple):
            _, ms, fn = job
            self._after_in_main(ms, fn)
        else:
            try:
                job()
            except Exception:
                pass

    def after_cancel(self, key):
        t = self._timers.pop(key, None)
        if t is not None:
            t.stop()

    # -- 窗口 --
    def title(self, text):
        self._w.setWindowTitle(text)

    def geometry(self, spec):
        self._w.resize(spec.replace("+", "x").split("x")[0],
                       int(spec.split("x")[1][:4]))

    def minsize(self, w, h):
        self._w.setMinimumWidth(int(w))
        self._w.setMinimumHeight(int(h))

    def iconbitmap(self, path):
        if os.path.exists(path):
            self._w.setWindowIcon(QtGui.QIcon(path))

    def protocol(self, _name, callback):
        self._w.closeEvent.connect(lambda _e: (callback(), _e.accept())[0])

    def destroy(self):
        """关闭窗口并释放内部资源(幂等)。"""
        if self._closing:
            return
        self._closing = True
        for t in self._timers.values():
            try:
                t.stop()
            except RuntimeError:
                pass
        self._timers.clear()
        # 断开信号: 窗口销毁后不再有回调入口, 避免悬空连接
        try:
            self._invoke.sig.disconnect(self._run_cb)
        except (RuntimeError, TypeError):
            pass
        try:
            self._w.close()
        except RuntimeError:
            pass          # 底层对象已销毁

    def update_idletasks(self):
        QtWidgets.QApplication.processEvents()

    def focus_get(self):
        return QtWidgets.QApplication.focusWidget()

    def bind(self, _seq, _cb):
        pass

    def unbind(self, _seq):
        pass

    # -- 模态框(供 messagebox 转发) --
    def dialog(self):
        return self._w


# ─────────────────────── messagebox / filedialog ───────────────────────


def _parent():
    w = QtWidgets.QApplication.activeModalWidget()
    if w is None:
        w = QtWidgets.QApplication.activeWindow()
    return w


def show_info(title, message):
    QtWidgets.QMessageBox.information(
        _parent(), str(title), str(message))


def show_error(title, message):
    QtWidgets.QMessageBox.critical(
        _parent(), str(title), str(message))


def show_warning(title, message):
    QtWidgets.QMessageBox.warning(
        _parent(), str(title), str(message))


def ask_yesno(title, message):
    r = QtWidgets.QMessageBox.question(
        _parent(), str(title), str(message),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    return r == QtWidgets.QMessageBox.Yes


def ask_directory(initialdir=""):
    return QtWidgets.QFileDialog.getExistingDirectory(
        _parent(), "选择下载目录", initialdir or "")


def ask_saveas(defaultextension=".txt", filetypes=(), initialfile=""):
    name_filter = filetypes[0][0] if filetypes else ""
    ext = (defaultextension or "").lstrip(".")
    patterns = (f"{name_filter} (*.{ext})" if name_filter
                else f"All files (*.{ext})" if ext else "All files (*)")
    path, _ = QtWidgets.QFileDialog.getSaveFileName(
        _parent(), "导出", initialfile, patterns)
    if path and ext and not path.lower().endswith("." + ext.lower()):
        path = path + "." + ext
    return path


def ask_openfilename(filetypes=(), initialdir=""):
    name_filter = filetypes[0][0] if filetypes else ""
    patterns = (f"{name_filter} ({filetypes[0][1]})" if filetypes
                else "All files (*)")
    path, _ = QtWidgets.QFileDialog.getOpenFileName(
        _parent(), "导入", initialdir, patterns)
    return path


class _MessageBoxNS:
    showinfo = staticmethod(show_info)
    showerror = staticmethod(show_error)
    showwarning = staticmethod(show_warning)
    askyesno = staticmethod(ask_yesno)


class _FileDialogNS:
    askdirectory = staticmethod(ask_directory)
    asksaveasfilename = staticmethod(ask_saveas)
    askopenfilename = staticmethod(ask_openfilename)


messagebox = _MessageBoxNS()
filedialog = _FileDialogNS()