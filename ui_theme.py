# -*- coding: utf-8 -*-
"""液态玻璃 UI 主题引擎。

设计目标
--------
Tkinter 不支持 CSS `backdrop-filter`, 也无法给子控件设置真·半透明。
本模块用 Pillow **程序化合成**出液态玻璃(liquid glass)观感:

1. 背景层 —— 深色多色渐变 + 若干柔光光斑, 模拟玻璃折射的环境光
2. 面板层 —— 圆角矩形, 白色低透明度填充(半透明毛玻璃),
             叠加顶部高光带与 1px 半透明描边(玻璃边缘反光)
3. 控件层 —— 圆角按钮(渐变填充 + hover 发光)、渐变进度条

因卡片是半透明的, 背景会透过来, 视觉上就是"玻璃"。

本模块只负责**视觉**, 不含任何业务逻辑。

依赖: Pillow(仅在可用时启用)。缺失时自动降级为纯色主题,
      程序仍可正常运行。
"""
import os
import tkinter.font as tkfont

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
    HAS_PIL = True
except Exception:                                    # pragma: no cover
    Image = ImageChops = ImageDraw = None
    ImageFilter = ImageFont = None
    HAS_PIL = False

FONT_DIR = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")


# ────────────────────────── 调色板 ──────────────────────────

class Palette:
    """深色液态玻璃主题配色。"""

    # 背景渐变三色(左上 → 右下)
    BG_TOP = (17, 21, 43)
    BG_MID = (24, 28, 58)
    BG_BOT = (14, 16, 32)

    # 光斑(在背景上营造玻璃折射的彩色氛围)
    BLOBS = (
        # (相对x, 相对y, 半径, RGB, 强度)
        (0.18, 0.05, 0.42, (56, 108, 255), 60),
        (0.85, 0.12, 0.36, (168, 85, 247), 48),
        (0.62, 0.78, 0.44, (34, 211, 238), 34),
        (0.05, 0.62, 0.32, (236, 72, 153), 26),
        (0.50, 0.42, 0.30, (99, 102, 241), 22),
    )

    # 玻璃面板
    # 半透明白 —— alpha 决定"玻璃感"强弱: 太低看不见卡片边界,
    # 太高则失去通透感。深色底上 28 左右比较合适。
    GLASS_FILL = (255, 255, 255, 30)
    GLASS_EDGE = (255, 255, 255, 58)
    GLASS_SHEEN = (255, 255, 255, 20)
    GLASS_RADIUS = 18

    # 文字
    TEXT = "#EEF1F8"
    TEXT_DIM = "#98A2BD"
    TEXT_FAINT = "#6B7590"

    # 主色(渐变)
    ACCENT_A = (79, 139, 255)
    ACCENT_B = (168, 85, 247)
    ACCENT_C = (34, 211, 238)

    # 语义色
    OK = (52, 211, 153)
    WARN = (251, 191, 36)
    DANGER = (248, 113, 113)

    # 控件
    ENTRY_BG = (255, 255, 255, 16)
    ENTRY_EDGE = (255, 255, 255, 34)
    ENTRY_FOCUS_EDGE = (120, 170, 255, 150)

    BTN_BG = (255, 255, 255, 18)
    BTN_EDGE = (255, 255, 255, 40)
    BTN_HOVER = (255, 255, 255, 34)
    BTN_ACTIVE = (255, 255, 255, 52)
    BTN_DISABLED_BG = (255, 255, 255, 8)
    BTN_DISABLED_EDGE = (255, 255, 255, 18)
    BTN_DISABLED_FG = "#5A637C"

    # Treeview
    TREE_BG = (255, 255, 255, 10)
    TREE_FG = "#E6EAF4"
    TREE_HEAD_BG = (255, 255, 255, 14)
    TREE_HEAD_FG = "#C3CCE4"
    TREE_SEL_BG = (79, 139, 255, 92)
    TREE_HL_BG = (168, 85, 247, 78)         # 下载中高亮
    TREE_ROW_ALT = (255, 255, 255, 6)

    # 进度条
    TROUGH = (255, 255, 255, 16)
    TROUGH_EDGE = (255, 255, 255, 26)

    # ── Tk 用的十六进制版本(Tk 不接受 RGB 元组)
    BG_MID_HEX = "#181C3A"
    BG_BOT_HEX = "#0E1020"
    ACCENT_A_HEX = "#4F8BFF"
    ACCENT_C_HEX = "#22D3EE"
    OK_HEX = "#34D399"


# ────────────────────────── 字体 ──────────────────────────

def _pick(*names):
    """从候选字体名中挑第一个本机存在的。

    tkfont.families() 需要已存在的 Tk 根窗口, 在无头环境(如 CI)会抛
    RuntimeError; 此时退化为按优先级取第一个候选。
    """
    if HAS_PIL:
        try:
            lower = {n.lower() for n in tkfont.families()}
            for n in names:
                if n.lower() in lower:
                    return n
        except Exception:
            pass
        # 退路: 检查字体文件是否存在于系统字体目录
        files = {
            "microsoft yahei ui": ("msyh.ttc", "msyhbd.ttc"),
            "microsoft yahei": ("msyh.ttc", "msyhbd.ttc"),
            "segoe ui semibold": ("seguisb.ttf",),
            "segoe ui": ("segoeui.ttf",),
            "cascadia mono": ("CascadiaMono.ttf",),
            "consolas": ("consola.ttf",),
            "tahoma": ("tahoma.ttf",),
            "courier new": ("cour.ttf",),
        }
        for n in names:
            key = n.lower()
            if key in files and any(
                    os.path.exists(os.path.join(FONT_DIR, f))
                    for f in files[key]):
                return n
    return names[-1]


def load_fonts():
    """返回 UI 需要的字体族名(优先雅黑, 回退 Segoe UI)。"""
    return {
        "ui": _pick("Microsoft YaHei UI", "Microsoft YaHei",
                    "Segoe UI", "Tahoma"),
        "ui_bold": _pick("Microsoft YaHei UI", "Microsoft YaHei",
                         "Segoe UI Semibold", "Segoe UI", "Tahoma"),
        "mono": _pick("Cascadia Mono", "Consolas", "Courier New"),
        "title": _pick("Microsoft YaHei UI", "Segoe UI Semibold",
                       "Segoe UI", "Tahoma"),
    }


# ────────────────────── 像素级绘制工具 ──────────────────────

def hexof(rgb):
    """RGB 元组 → '#rrggbb' 字符串(Tk 的颜色名不接受元组)。"""
    return "#%02X%02X%02X" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _mix(c, bg, alpha):
    """把颜色 c 以 alpha 混合到背景 bg 上(返回不透明 RGB)。"""
    return _lerp(bg, c, alpha)


def make_background(w, h, pal=Palette, blur=True, scale=4):
    """生成液态玻璃背景: 多色渐变 + 柔光光斑。

    scale: 降采样倍率。渐变与光斑都是低频信号, 按 1/scale 生成后
    再放大可把逐像素循环的开销降到 1/scale²(默认约 1/16),
    肉眼几乎无差别。
    """
    if not HAS_PIL:
        return None
    w, h = max(1, int(w)), max(1, int(h))
    s = max(1, int(scale))
    gw, gh = max(2, w // s), max(2, h // s)

    img = Image.new("RGB", (gw, gh), pal.BG_MID)
    d = ImageDraw.Draw(img)

    # 垂直渐变
    for y in range(gh):
        if y < gh * 0.5:
            t = y / max(1, gh * 0.5)
            col = _lerp(pal.BG_TOP, pal.BG_MID, t)
        else:
            t = (y - gh * 0.5) / max(1, gh * 0.5)
            col = _lerp(pal.BG_MID, pal.BG_BOT, t)
        d.line([(0, y), (gw, y)], fill=col)

    # 彩色光斑(独立层 + 高斯模糊, 得到柔和折射感)
    blob_layer = Image.new("RGB", (gw, gh), (0, 0, 0))
    bd = ImageDraw.Draw(blob_layer)
    m = max(gw, gh)
    for rx, ry, rr, rgb, _inten in pal.BLOBS:
        cx, cy = rx * gw, ry * gh
        rad = max(6, int(rr * m * 0.5))
        k = max(1, int(rad / 2))
        for i in range(k, 0, -1):
            f = i / k
            a = (1.0 - f) ** 2
            c = tuple(int(c2 * a) for c2 in rgb)
            bd.ellipse([cx - rad * f, cy - rad * f,
                        cx + rad * f, cy + rad * f], fill=c)
    blob_layer = blob_layer.filter(
        ImageFilter.GaussianBlur(radius=max(2, m * 0.055)))

    # 屏幕方式叠加
    px_bg = img.load()
    px_bl = blob_layer.load()
    for y in range(gh):
        for x in range(gw):
            br, bg_, bb = px_bg[x, y]
            sr, sg, sb = px_bl[x, y]
            add = (sr + sg + sb) / 3.0
            k = min(0.85, add / 255.0 * 1.15)
            if k > 0.004:
                px_bg[x, y] = (
                    int(br + sr * k), int(bg_ + sg * k),
                    int(bb + sb * k))

    if (gw, gh) != (w, h):
        img = img.resize((w, h), Image.BILINEAR)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
    return img


def make_glass_panel(w, h, pal=Palette, radius=None,
                     fill=None, edge=None, sheen=True, shadow=True):
    """生成圆角毛玻璃面板(RGBA, 带顶部高光带、边缘反光与柔和投影)。"""
    if not HAS_PIL:
        return None
    w, h = max(2, int(w)), max(2, int(h))
    r = pal.GLASS_RADIUS if radius is None else int(radius)
    r = max(0, min(r, min(w, h) // 2))
    fill = pal.GLASS_FILL if fill is None else fill
    edge = pal.GLASS_EDGE if edge is None else edge

    # 投影需要额外画布空间
    pad = 10 if shadow else 0
    cw, ch = w + pad * 2, h + pad * 2
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))

    # ── 柔和投影(向下偏移)
    # 注意: 投影必须**避开玻璃主体区域**, 否则黑色会透过半透明玻璃
    # 表现为面板内部发灰(视觉上像蒙了一层脏)。
    if shadow:
        sh = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        box = [pad, pad + 6, pad + w - 1, pad + h - 1 + 6]
        if r > 0:
            sd.rounded_rectangle(box, radius=r, fill=(0, 0, 0, 110))
        else:
            sd.rectangle(box, fill=(0, 0, 0, 110))
        sh = sh.filter(ImageFilter.GaussianBlur(radius=8))
        # 把玻璃主体区域从投影中挖空: 主体处 alpha 置 0, 外侧保留。
        # 必须用逐像素相乘(ImageChops.multiply), 用 composite 会取反。
        from PIL import ImageChops
        inner = [pad, pad, pad + w - 1, pad + h - 1]
        mask = Image.new("L", (cw, ch), 0)
        md = ImageDraw.Draw(mask)
        if r > 0:
            md.rounded_rectangle(inner, radius=r, fill=255)
        else:
            md.rectangle(inner, fill=255)
        sh.putalpha(ImageChops.multiply(
            sh.getchannel("A"), Image.eval(mask, lambda v: 255 - v)))
        canvas = Image.alpha_composite(canvas, sh)

    # ── 玻璃主体
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bxy = [pad, pad, pad + w - 1, pad + h - 1]
    if r > 0:
        d.rounded_rectangle(bxy, radius=r, fill=fill)
    else:
        d.rectangle(bxy, fill=fill)

    if sheen and h > 14:
        # 顶部高光带: 上部叠一层低透明度白, 形成玻璃受光感
        band = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        bd = ImageDraw.Draw(band)
        bh = pad + max(2, int(h * 0.38))
        if r > 0:
            bd.rounded_rectangle([pad, pad, pad + w - 1, bh],
                                 radius=r, fill=pal.GLASS_SHEEN)
            # 渐隐: 用下半部分擦除, 让高光自然过渡
            grad = Image.new("L", (cw, ch), 0)
            gd = ImageDraw.Draw(grad)
            for y in range(pad, bh + 1):
                t = (y - pad) / max(1, bh - pad)
                gd.line([(pad, y), (pad + w - 1, y)],
                        fill=int(255 * (1 - t) ** 1.4))
            band.putalpha(Image.composite(
                band.getchannel("A"), Image.new("L", (cw, ch), 0), grad))
        else:
            bd.rectangle([pad, pad, pad + w - 1, bh],
                         fill=pal.GLASS_SHEEN)
        img = Image.alpha_composite(img, band)

    # ── 边缘反光: 顶边更亮, 底边更暗, 模拟玻璃棱边折射
    if r > 0:
        d.rounded_rectangle(bxy, radius=r, outline=edge, width=1)
        # 顶部亮线
        d.arc([pad, pad, pad + w - 1, pad + h - 1],
              start=185, end=355, fill=(255, 255, 255, 78), width=1)
    else:
        d.rectangle(bxy, outline=edge, width=1)
        d.line([(pad, pad), (pad + w - 1, pad)],
               fill=(255, 255, 255, 78), width=1)

    # 玻璃主体叠到投影之上(缺这步会只返回投影, 面板看起来是空的)
    canvas = Image.alpha_composite(canvas, img)
    return canvas, pad      # 返回(图像, 内容偏移量)


def draw_check(draw, cx, cy, size, color, width=None):
    """矢量绘制对勾(不依赖字体字形, 避免缺字变方块)。"""
    w = max(1, int(width or size * 0.22))
    s = size / 2.0
    draw.line([(cx - s * 0.85, cy), (cx - s * 0.2, cy + s * 0.62)],
              fill=color, width=w, joint="curve")
    draw.line([(cx - s * 0.2, cy + s * 0.62),
               (cx + s * 0.9, cy - s * 0.66)],
              fill=color, width=w, joint="curve")


def draw_chevron(draw, cx, cy, size, color, width=None):
    """矢量绘制下拉箭头(替代 ▾, 雅黑无此字形)。"""
    w = max(1, int(width or size * 0.2))
    s = size / 2.0
    draw.line([(cx - s, cy - s * 0.4), (cx, cy + s * 0.45),
               (cx + s, cy - s * 0.4)],
              fill=color, width=w, joint="curve")


def make_gradient_button(w, h, pal=Palette, state="normal",
                         accent=False, radius=12):
    """生成按钮底图(圆角 + 渐变 + 内高光)。"""
    if not HAS_PIL:
        return None
    w, h = max(4, int(w)), max(4, int(h))
    r = max(0, min(int(radius), min(w, h) // 2))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if accent:
        c1, c2 = pal.ACCENT_A, pal.ACCENT_B
        if state == "hover":
            c1 = _lerp(c1, (255, 255, 255), 0.16)
            c2 = _lerp(c2, (255, 255, 255), 0.16)
        elif state == "active":
            c1 = _lerp(c1, (0, 0, 0), 0.14)
            c2 = _lerp(c2, (0, 0, 0), 0.14)
        elif state == "disabled":
            c1 = c2 = (110, 120, 150)
    else:
        bg = {0: pal.BTN_BG, 1: pal.BTN_HOVER, 2: pal.BTN_ACTIVE,
              3: pal.BTN_DISABLED_BG}[
            {"normal": 0, "hover": 1, "active": 2,
             "disabled": 3}[state]]
        c1 = c2 = bg[:3]
        c1 = (*c1, bg[3])
        c2 = (*c1[:3], bg[3])

    # 竖向渐变填充
    for y in range(h):
        t = y / max(1, h - 1)
        if isinstance(c1, tuple) and len(c1) == 4 and state != "disabled" \
                and accent:
            col = (*_lerp(c1[:3], c2[:3], t), int((c1[3] + c2[3]) / 2))
        else:
            col = c1 if isinstance(c1, tuple) else (*c1, 255)
        if r > 0:
            d.line([(r, y), (w - r, y)], fill=col)
        else:
            d.line([(0, y), (w, y)], fill=col)
    # 圆角外的四角清掉
    if r > 0:
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, w - 1, h - 1], radius=r, fill=255)
        img.putalpha(Image.composite(
            img.getchannel("A"), Image.new("L", (w, h), 0), mask))

    # 内高光(顶部 1px)与描边
    if r > 0:
        d.rounded_rectangle(
            [0, 0, w - 1, h - 1], radius=r,
            outline=(255, 255, 255, 70) if accent and state != "disabled"
            else pal.BTN_EDGE, width=1)
    return img


def make_progress_fill(w, h, pal=Palette, radius=None):
    """进度条填充(横向渐变 + 圆角)。"""
    if not HAS_PIL:
        return None
    w, h = max(2, int(w)), max(2, int(h))
    r = h // 2 if radius is None else int(radius)
    r = max(0, min(r, min(w, h) // 2))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c1, c2 = pal.ACCENT_C, pal.ACCENT_B
    for x in range(w):
        t = x / max(1, w - 1)
        d.line([(x, 0), (x, h)], fill=(*_lerp(c1, c2, t), 235))
    if r > 0:
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, w - 1, h - 1], radius=r, fill=255)
        img.putalpha(Image.composite(
            img.getchannel("A"), Image.new("L", (w, h), 0), mask))
    return img


def make_round_avatar(text, size, pal=Palette, colors=None):
    """生成带首字母的圆形头像(用于工具列表/分类图标)。"""
    if not HAS_PIL or ImageFont is None:
        return None
    s = max(8, int(size))
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c1, c2 = colors or (pal.ACCENT_A, pal.ACCENT_B)
    for i in range(s // 2 + 1):
        t = i / max(1, s // 2)
        d.ellipse([i, i, s - 1 - i, s - 1 - i],
                  fill=(*_lerp(c1, c2, t), 235))
    try:
        f = ImageFont.truetype(
            os.path.join(FONT_DIR, "msyhbd.ttc"),
            max(8, int(s * 0.5)))
    except Exception:
        f = ImageFont.load_default()
    ch = (text or "?")[0].upper()
    bb = d.textbbox((0, 0), ch, font=f)
    d.text(((s - (bb[2] - bb[0])) / 2 - bb[0],
            (s - (bb[3] - bb[1])) / 2 - bb[1]),
           ch, font=f, fill=(255, 255, 255, 255))
    return img
