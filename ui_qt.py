# -*- coding: utf-8 -*-
"""PySide6 液态玻璃主题层。

承接原 tkinter 版本(ui_theme.py / ui_widgets.py)的视觉目标, 全部
改用 Qt 原生 API 实现, 不做自绘渲染:

- 配色与字体: 本模块常量
- 全局外观: QSS 样式表(``build_qss``)
- 玻璃卡片: ``GlassCard``(半透明 + 顶部高光 + QGraphicsDropShadowEffect)
- 渐变控件: ``GradientButton`` / ``GradientProgressBar``
- 背景光晕: ``paint_gradient_background``

Tkinter 不支持 ``backdrop-filter``, 此前靠 Pillow 逐像素合成;
Qt 侧改用 QSS 半透明 + 阴影特效, 由引擎负责合成与绘制。
"""

from PySide6 import QtCore, QtGui, QtWidgets

# ─────────────────────── 配色 ───────────────────────


class Palette:
    """深色玻璃主题配色(与 v4.1.0 视觉一致)。"""

    BG_DEEP = "#0A0C1C"
    BG_MID = "#0F1228"
    BG_HI = "#161A38"

    GLASS = "rgba(255, 255, 255, 9)"
    GLASS_HOVER = "rgba(255, 255, 255, 16)"
    GLASS_BORDER = "rgba(255, 255, 255, 26)"
    GLASS_HILIGHT = "rgba(255, 255, 255, 54)"

    TEXT = "#E8ECF8"
    SUBTEXT = "#9AA6C8"
    FAINT = "#6E7BA3"

    ACCENT = "#4F8BFF"
    ACCENT_C = "#7C5CFF"
    OK = "#38D9A9"
    WARN = "#FFB020"
    ERR = "#FF6B6B"

    LOG_BG = "#10132A"
    LOG_FG = "#C9D3EA"


PAL = Palette()

# 光晕色(用于背景绘制)
GLOW_COLORS = (
    (0.18, 0.35, 0.95),    # 青蓝
    (0.55, 0.30, 0.95),    # 紫
    (0.90, 0.35, 0.70),    # 粉
)

# ─────────────────────── 字体 ───────────────────────

_UI_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei",
                  "PingFang SC", "Noto Sans CJK SC", "Segoe UI")
_MONO_CANDIDATES = ("Cascadia Mono", "Consolas",
                    "DejaVu Sans Mono", "Courier New")


def _pick_family(candidates):
    """在系统可用字体里挑第一个存在的。

    回退策略分两种:
    - 系统有字体库: 取第一个命中的候选; 全不命中则返回空串,
      交由 Qt 默认字体处理(不退回 ``candidates[-1]`` —— 那可能是
      "Courier New"之类不含中文字形的字体, 会让中文全变方框)。
    - 系统无字体库(离屏 CI 的 offscreen 平台插件): 返回候选首项。
      此时字体确实不可用, 但保留首选名比留空更好 —— 留空会让
      QFont 退化成默认字体, 连 pointSize 都可能被重置。
    """
    available = set(QtGui.QFontDatabase.families())
    if not available:
        return candidates[0]
    for name in candidates:
        if name in available:
            return name
    return ""


def load_fonts():
    """返回 ``{"ui": QFont, "mono": QFont, "size": QFont}``。"""
    ui = QtGui.QFont()
    fam = _pick_family(_UI_CANDIDATES)
    if fam:
        ui.setFamily(fam)
    ui.setPointSize(9)

    mono = QtGui.QFont()
    fam = _pick_family(_MONO_CANDIDATES)
    if fam:
        mono.setFamily(fam)
    mono.setPointSize(8)

    # 不能用 QFont(ui) 拷贝: 当 ui.family 为空(无字体库的离屏环境)
    # 时, 拷贝结果同样为空, 会连带丢掉 pointSize
    size = QtGui.QFont(ui)
    size.setPointSize(15)
    size.setBold(True)

    return {"ui": ui, "mono": mono, "size": size}


# ─────────────────────── 背景光晕 ───────────────────────


def make_background(w, h):
    """生成渐变光晕背景图(深蓝紫底 + 青/紫/粉光斑)。"""
    if w <= 0 or h <= 0:
        return None
    # 上限保护: 超大窗口不必逐像素, 缩放到 1/2 再放大足够柔和
    scale = 1.0
    if max(w, h) > 1600:
        scale = 1600.0 / max(w, h)
    bw = max(1, int(w * scale))
    bh = max(1, int(h * scale))

    img = QtGui.QImage(bw, bh, QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor(PAL.BG_DEEP))

    base = QtGui.QColor(PAL.BG_MID)
    p_top = QtCore.QPointF(0, 0)
    p_bot = QtCore.QPointF(0, bh)
    grad = QtGui.QLinearGradient(p_top, p_bot)
    grad.setColorAt(0.0, QtGui.QColor(PAL.BG_HI))
    grad.setColorAt(0.55, base)
    grad.setColorAt(1.0, QtGui.QColor(PAL.BG_DEEP))
    painter = QtGui.QPainter(img)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.fillRect(0, 0, bw, bh, grad)

    # 径向光斑: 亮度按距离平方衰减, 只画三处, 开销可忽略
    glow_radius = int(max(bw, bh) * 0.55)
    spots = (
        (0.18, 0.22, GLOW_COLORS[0]),
        (0.72, 0.14, GLOW_COLORS[1]),
        (0.55, 0.88, GLOW_COLORS[2]),
    )
    for fx, fy, rgb in spots:
        cx, cy = int(bw * fx), int(bh * fy)
        r = QtCore.QRectF(cx - glow_radius / 2, cy - glow_radius / 2,
                          glow_radius, glow_radius)
        rg = QtGui.QRadialGradient(r.center(), glow_radius / 2)
        r_, g_, b_ = rgb
        rg.setColorAt(0.0, QtGui.QColor(int(r_ * 90), int(g_ * 90),
                                       int(b_ * 90), 150))
        rg.setColorAt(0.45, QtGui.QColor(int(r_ * 55), int(g_ * 55),
                                         int(b_ * 55), 70))
        rg.setColorAt(1.0, QtGui.QColor(int(r_ * 30), int(g_ * 30),
                                        int(b_ * 30), 0))
        painter.fillRect(r, rg)
    painter.end()

    if scale != 1.0:
        img = img.scaled(w, h, QtCore.Qt.IgnoreAspectRatio,
                         QtCore.Qt.SmoothTransformation)
    return img


class BackgroundWidget(QtWidgets.QWidget):
    """铺在窗口底层的光晕背景, 随窗口尺寸重绘。

    以绝对几何铺满(不参与父布局), 故``sizeHint`` 需给出非零值,
    否则在某些布局场景下会被压缩成零高。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._img = None
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        # 不参与焦点链, 不影响键盘导航
        self.setFocusPolicy(QtCore.Qt.NoFocus)

    def sizeHint(self):
        return QtCore.QSize(1180, 820)

    def minimumSizeHint(self):
        return QtCore.QSize(1, 1)

    def refresh(self):
        w = max(1, self.width())
        h = max(1, self.height())
        if (self._img is not None
                and self._img.width() == w and self._img.height() == h):
            return                      # 尺寸未变, 不必重绘
        self._img = make_background(w, h)
        self.update()

    def paintEvent(self, _event):
        if self._img is None:
            self.refresh()
        if self._img is None:
            return
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, QtGui.QPixmap.fromImage(self._img))
        p.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()


# ─────────────────────── 玻璃卡片 ───────────────────────

PAD = 14


class GlassCard(QtWidgets.QFrame):
    """半透明圆角卡片: 顶边高光 + 柔和投影。

    阴影用 ``QGraphicsDropShadowEffect``(引擎原生特效), 不自绘。

    ``shadow=False`` 用于嵌套场景: Qt 的 graphics effect 会作用于
    已渲染(含子级特效)的结果, 卡片套卡片会出现重影, 且父级阴影会
    被裁成直角(QTBUG), 故内层卡片不挂特效。
    """

    def __init__(self, parent=None, radius=18, shadow=True):
        super().__init__(parent)
        self.setObjectName("glassCard")
        self._radius = radius
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, False)
        if shadow:
            eff = QtWidgets.QGraphicsDropShadowEffect(self)
            eff.setBlurRadius(28)
            eff.setOffset(0, 6)
            eff.setColor(QtGui.QColor(0, 0, 0, 90))
            self.setGraphicsEffect(eff)

    def enterEvent(self, event):
        self.setProperty("hover", True)
        self._restyle()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hover", False)
        self._restyle()
        super().leaveEvent(event)

    def _restyle(self):
        self.style().unpolish(self)
        self.style().polish(self)


# ─────────────────────── 渐变控件 ───────────────────────


class GradientButton(QtWidgets.QPushButton):
    """渐变填充按钮。

    注意: 样式通过动态属性 ``cls`` 匹配, QSS 里必须写属性选择器
    ``QPushButton[cls="accentBtn"]``。若误写成 ``#accentBtn``(那是
    objectName 选择器), 条件样式不会生效 —— 表现为强调色按钮
    和普通按钮长得一样。
    """

    def __init__(self, text="", parent=None, accent=False):
        super().__init__(text, parent)
        self.setProperty("cls", "accentBtn" if accent else "glassBtn")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMinimumHeight(32)

    def set_accent(self, accent):
        self.setProperty("cls", "accentBtn" if accent else "glassBtn")
        self.style().unpolish(self)
        self.style().polish(self)


class GradientProgressBar(QtWidgets.QProgressBar):
    """渐变进度条。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextVisible(False)
        self.setFixedHeight(8)
        self.setProperty("cls", "glassProgress")

    def setMaximum(self, value):
        # ttk 允许 maximum=0, Qt 会除零, 这里钳到 1
        super().setMaximum(max(int(value), 1))


# ─────────────────────── 样式表 ───────────────────────


def build_qss(fonts):
    """生成全局 QSS。字号以 pt 为单位, 随系统 DPI 缩放。"""
    ui_pt = fonts["ui"].pointSize()
    mono_pt = fonts["mono"].pointSize()
    mono = fonts["mono"].family()
    return f"""
QWidget {{
    color: {PAL.TEXT};
    font-family: "{fonts['ui'].family()}";
    font-size: {ui_pt}pt;
}}
QMainWindow, QDialog {{ background: transparent; }}

/* ── 玻璃卡片 ── */
#glassCard {{
    background: {PAL.GLASS};
    border: 1px solid {PAL.GLASS_BORDER};
    border-radius: {18}px;
}}
#glassCard:hover {{ background: {PAL.GLASS_HOVER}; }}

/* ── 按钮 ── */
QPushButton {{
    background: rgba(255, 255, 255, 26);
    border: 1px solid rgba(255, 255, 255, 46);
    border-radius: 8px;
    padding: 6px 14px;
    color: {PAL.TEXT};
}}
QPushButton:hover {{
    background: rgba(255, 255, 255, 44);
    border-color: rgba(255, 255, 255, 70);
}}
QPushButton:pressed {{ background: rgba(255, 255, 255, 20); }}
QPushButton:disabled {{
    color: {PAL.FAINT};
    background: rgba(255, 255, 255, 12);
    border-color: rgba(255, 255, 255, 20);
}}

QPushButton[cls="accentBtn"] {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {PAL.ACCENT}, stop:1 {PAL.ACCENT_C});
    border: 1px solid rgba(255, 255, 255, 78);
    color: #FFFFFF;
    font-weight: bold;
}}
QPushButton[cls="accentBtn"]:hover {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #5F97FF, stop:1 #8C6FFF);
}}
QPushButton[cls="accentBtn"]:disabled {{
    background: rgba(255, 255, 255, 30);
    color: {PAL.FAINT};
    border-color: rgba(255, 255, 255, 34);
}}

/* ── 输入框 ── */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox {{
    background: rgba(255, 255, 255, 18);
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {PAL.ACCENT};
    selection-color: #FFFFFF;
}}
QLineEdit:focus, QPlainTextEdit:focus {{
    border-color: rgba(120, 160, 255, 190);
}}
QLineEdit::placeholder {{ color: {PAL.FAINT}; }}

/* ── 下拉 ── */
QComboBox {{
    background: rgba(255, 255, 255, 22);
    border: 1px solid rgba(255, 255, 255, 46);
    border-radius: 8px;
    padding: 5px 10px;
    min-width: 90px;
}}
QComboBox:hover {{ border-color: rgba(255, 255, 255, 76); }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {PAL.SUBTEXT};
    width: 0; height: 0;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: #1A1F3D;
    border: 1px solid rgba(255, 255, 255, 60);
    border-radius: 8px;
    selection-background-color: {PAL.ACCENT};
    selection-color: #FFFFFF;
    outline: none;
    padding: 4px;
}}

/* ── 树 / 表 ── */
QTreeWidget, QTreeView, QTableWidget, QTableView, QListView {{
    background: rgba(255, 255, 255, 8);
    border: 1px solid rgba(255, 255, 255, 26);
    border-radius: 10px;
    alternate-background-color: rgba(255, 255, 255, 5);
    outline: none;
}}
QTreeWidget::item, QTableWidget::item {{
    padding: 5px 4px;
    border: none;
}}
QTreeWidget::item:hover, QTableWidget::item:hover {{
    background: rgba(255, 255, 255, 22);
}}
QTreeWidget::item:selected, QTableWidget::item:selected {{
    background: rgba(79, 139, 255, 92);
    color: #FFFFFF;
}}
QHeaderView::section {{
    background: rgba(255, 255, 255, 20);
    color: {PAL.SUBTEXT};
    border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 34);
    padding: 6px 4px;
    font-weight: bold;
}}
QHeaderView::section:first {{ border-top-left-radius: 9px; }}
QHeaderView::section:last  {{ border-top-right-radius: 9px; }}
QTreeView::branch {{ background: transparent; }}

/* ── 进度条 ── */
QProgressBar {{
    background: rgba(255, 255, 255, 24);
    border: none;
    border-radius: 4px;
    height: 8px;
}}
QProgressBar::chunk {{
    border-radius: 4px;
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {PAL.ACCENT}, stop:1 {PAL.ACCENT_C});
}}

/* ── 滚动条 ── */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 46);
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(255, 255, 255, 76); }}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 46);
    border-radius: 4px;
    min-width: 30px;
}}

/* ── 菜单 ── */
QMenu {{
    background: #1A1F3D;
    border: 1px solid rgba(255, 255, 255, 60);
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{
    padding: 6px 22px 6px 14px;
    border-radius: 5px;
    color: {PAL.TEXT};
}}
QMenu::item:selected {{
    background: {PAL.ACCENT};
    color: #FFFFFF;
}}
QMenu::separator {{
    height: 1px;
    background: rgba(255, 255, 255, 34);
    margin: 4px 8px;
}}

/* ── 模态框 ── */
QMessageBox {{ background: #151936; }}
QMessageBox QLabel {{ color: {PAL.TEXT}; font-size: {ui_pt}pt; }}
QMessageBox QPushButton {{ min-width: 76px; }}
QMessageBox QAbstractScrollArea {{
    background: #151936;
    border: 1px solid rgba(255, 255, 255, 40);
}}
"""