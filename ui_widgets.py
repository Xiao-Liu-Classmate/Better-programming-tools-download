# -*- coding: utf-8 -*-
"""液态玻璃 UI 控件集。

所有控件都对外提供与标准 Tk 控件**兼容的接口**(state / text /
textvariable / pack / grid / configure ...), 以便 app.py 现有的
业务逻辑(``_set_buttons`` 改 state、``retry_btn.pack_forget()`` 显隐、
``progress.configure(value=..)`` 等)无需任何改动即可继续工作。

Tkinter 不支持 backdrop-filter 与子控件半透明, 因此这里用
Canvas + Pillow 预渲染的玻璃材质来模拟液态玻璃观感。
"""
import tkinter as tk
import tkinter.font as tkfont

import ui_theme as U
from ui_theme import Palette, HAS_PIL

PAD = 10          # 面板投影留白


class _PhotoCache:
    """按 (类型, 尺寸, 状态) 缓存 PhotoImage。

    限流同时考虑**条目数**与**累计像素数**: 面板图动辄上百万像素,
    只按条数限制最坏可达 1GB 常驻。
    """

    #: 各类型的条目上限
    KIND_LIMIT = {"panel": 24, "button": 120, "progress": 48,
                  "trough": 12}

    #: 累计像素上限(约 40M px ≈ 160MB RGBA)
    MAX_PIXELS = 40_000_000

    def __init__(self):
        self._d = {}
        self._order = []
        self._px = 0

    def _drop_oldest(self):
        while self._order:
            k = self._order.pop(0)
            v = self._d.pop(k, None)
            if v is not None:
                self._px -= k[1] * k[2]
        return None

    def get(self, key, factory):
        if key in self._d:
            return self._d[key]
        kind, w, h = key[0], key[1], key[2]
        limit = self.KIND_LIMIT.get(kind, 60)
        # 淘汰同类型的旧条目
        while sum(1 for k in self._order if k[0] == kind) >= limit:
            for i, k in enumerate(self._order):
                if k[0] == kind:
                    self._order.pop(i)
                    v = self._d.pop(k, None)
                    if v is not None:
                        self._px -= k[1] * k[2]
                    break
        # 超出总像素则全局淘汰
        while self._order and self._px + w * h > self.MAX_PIXELS:
            self._drop_oldest()
        val = factory()
        if val is None:
            return None
        self._d[key] = val
        self._order.append(key)
        self._px += w * h
        return val


_cache = _PhotoCache()


def photo_for(kind, w, h, state="normal", accent=False, radius=12,
              fill=None, edge=None, sheen=True):
    """取(并缓存)一张 PhotoImage。"""
    key = (kind, int(w), int(h), state, bool(accent), int(radius),
           tuple(fill) if fill else None,
           tuple(edge) if edge else None, bool(sheen))

    def factory():
        if not HAS_PIL:
            return None
        if kind == "panel":
            img, _pad = U.make_glass_panel(
                w, h, radius=radius, fill=fill, edge=edge, sheen=sheen)
            return img
        if kind == "button":
            return U.make_gradient_button(
                w, h, state=state, accent=accent, radius=radius)
        if kind == "progress":
            return U.make_progress_fill(w, h, radius=radius)
        if kind == "trough":
            img, _pad = U.make_glass_panel(
                w, h, radius=radius, fill=Palette.TROUGH,
                edge=Palette.TROUGH_EDGE, sheen=False, shadow=False)
            return img
        return None

    return _cache.get(key, factory)


# ──────────────────────────── 玻璃面板 ────────────────────────────

class GlassPanel(tk.Frame):
    """圆角毛玻璃容器。

    Tk 不支持子控件半透明, 因此"玻璃"通过两步模拟:
      1. 本控件持有一张窗口背景图的**局部切片**(由 App 注入),
         圆角裁切后作为底衬 —— 卡片区域因此能"透出"身后的
         渐变光晕, 这才是玻璃通透感的来源;
      2. 在切片之上叠一层半透明白 + 顶部高光 + 边缘反光。

    若未注入背景切片(``bg_provider`` 为 None), 则退化为
    深色实底 + 玻璃高光, 观感略弱但功能完整。
    """

    def __init__(self, master, radius=Palette.GLASS_RADIUS,
                 fill=None, edge=None, sheen=True,
                 bg_provider=None, **kw):
        super().__init__(master, **kw)
        self._radius = radius
        self._fill = fill
        self._edge = edge
        self._sheen = sheen
        self._photo = None
        self._img_id = None
        self._bg_id = None
        self._last = None
        self._bg_provider = bg_provider
        self.canvas = tk.Canvas(
            self, highlightthickness=0, bd=0,
            background=U.Palette.BG_MID_HEX)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.bind("<Configure>", self._on_resize, add="+")
        self._on_resize(None)

    def set_bg_provider(self, fn):
        """注入"取窗口背景切片"的回调(由 App 提供)"""
        self._bg_provider = fn
        self._last = None
        self._on_resize(None)

    def _on_resize(self, _evt=None):
        try:
            w = int(self.winfo_width())
            h = int(self.winfo_height())
        except (TypeError, ValueError):
            return
        if w <= 2 or h <= 2:
            return
        if (w, h) == self._last:
            return
        iw, ih = w - PAD * 2, h - PAD * 2
        if iw < 4 or ih < 4:
            return
        panel = photo_for("panel", iw, ih, radius=self._radius,
                          fill=self._fill, edge=self._edge,
                          sheen=self._sheen)
        if panel is None:
            return
        self._last = (w, h)
        from PIL import Image, ImageTk

        # ① 背景切片(圆角裁切后铺底, 实现"透出")
        bg_img = None
        if self._bg_provider is not None:
            try:
                bg_img = self._bg_provider(iw, ih)
            except Exception:
                bg_img = None
        if bg_img is not None:
            mask = Image.new("L", bg_img.size, 0)
            from PIL import ImageDraw
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, iw - 1, ih - 1], radius=self._radius, fill=255)
            base = bg_img.convert("RGBA")
            base.putalpha(mask)
        else:
            base = None

        # ② 叠上玻璃材质
        if base is not None:
            canvas_img = Image.alpha_composite(base, panel)
        else:
            canvas_img = panel

        self._photo = ImageTk.PhotoImage(canvas_img)
        if self._img_id is None:
            self._img_id = self.canvas.create_image(
                0, 0, anchor="nw", image=self._photo)
        else:
            self.canvas.itemconfigure(self._img_id, image=self._photo)


# ──────────────────────────── 玻璃按钮 ────────────────────────────

class GlassButton(tk.Canvas):
    """圆角渐变按钮。

    兼容接口:
        .text / .state / .command
        .configure(state=..., text=...)
        .pack() / .pack_forget() / .pack_configure(...)
        .invoke()
    """

    def __init__(self, master, text="", command=None, width=110,
                 height=34, accent=False, radius=12,
                 font=None, on_hover=None, **kw):
        self._text = text
        self._command = command
        self._bw = int(width)
        self._bh = int(height)
        self._accent = accent
        self._radius = radius
        self._state = "normal"
        self._hover = False
        self._pressed = False
        self._photo = None
        self._on_hover = on_hover
        self._font = font or ("Microsoft YaHei UI", 9)

        kw.setdefault("highlightthickness", 0)
        kw.setdefault("bd", 0)
        kw.setdefault("cursor", "hand2")
        kw.setdefault("background", U.Palette.BG_MID_HEX)
        kw.setdefault("takefocus", True)
        super().__init__(master, width=self._bw, height=self._bh, **kw)

        self._fontid = tkfont.Font(self, font=self._font)
        self._bind_events()
        self.bind("<Configure>", self._on_resize, add="+")
        self._redraw()

    # -- 事件 --
    def _bind_events(self):
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Return>", lambda e: self.invoke())
        self.bind("<space>", lambda e: self.invoke())
        self.bind("<FocusIn>", lambda e: self._redraw())
        self.bind("<FocusOut>", lambda e: self._redraw())

    def _visual_state(self):
        if self._state == "disabled":
            return "disabled"
        if self._pressed:
            return "active"
        if self._hover:
            return "hover"
        return "normal"

    def _on_enter(self, _e=None):
        if self._state != "disabled":
            self._hover = True
            self._redraw()
        if self._on_hover:
            self._on_hover(True)

    def _on_leave(self, _e=None):
        self._hover = False
        self._pressed = False
        self._redraw()
        if self._on_hover:
            self._on_hover(False)

    def _on_press(self, _e=None):
        if self._state != "disabled":
            self._pressed = True
            self._redraw()

    def _on_release(self, e=None):
        was = self._pressed
        self._pressed = False
        self._redraw()
        if was and self._state != "disabled":
            # 只有在按钮范围内松开才触发
            if e is not None and not self._in_bounds(e):
                return
            self.invoke()

    def _in_bounds(self, e):
        w, h = self.winfo_width(), self.winfo_height()
        return 0 <= e.x <= w and 0 <= e.y <= h

    # -- 绘制 --
    def _on_resize(self, _evt=None):
        # winfo_width() 在控件未完成布局时可能返回 1, 且需防止
        # 内部属性被异常值污染(photo_for 要求 int 尺寸)
        try:
            w = int(self.winfo_width())
            h = int(self.winfo_height())
        except (TypeError, ValueError):
            return
        if w <= 2 or h <= 2:
            return
        if w != self._bw or h != self._bh:
            self._bw, self._bh = w, h
            self.configure(width=w, height=h)
            self._redraw()

    def _redraw(self):
        self.delete("all")
        img = photo_for("button", self._bw, self._bh,
                        state=self._visual_state(),
                        accent=self._accent, radius=self._radius)
        if img is not None:
            from PIL import ImageTk
            self._photo = ImageTk.PhotoImage(img)
            self.create_image(0, 0, anchor="nw", image=self._photo)
        # 文字
        if self._text:
            if self._state == "disabled":
                fg = Palette.BTN_DISABLED_FG
            elif self._accent:
                fg = "#FFFFFF"
            else:
                fg = Palette.TEXT
            self.create_text(
                self._bw / 2, self._bh / 2, text=self._text,
                fill=fg, font=self._fontid, anchor="center")

    # -- 兼容接口 --
    def get_text(self):
        return self._text

    def set_text(self, value):
        self._text = value
        self._redraw()

    text = property(get_text, set_text)

    def get_state(self):
        return self._state

    def set_state(self, value):
        # ttk 用 disabled / normal, tk 也用 disabled / normal
        value = "disabled" if str(value) == "disabled" else "normal"
        if value != self._state:
            self._state = value
            if value == "disabled":
                self._hover = False
                self._pressed = False
                self.configure(cursor="arrow")
            else:
                self.configure(cursor="hand2")
            # 同步到底层 Tk 属性: 否则 btn["state"] 读到的是
            # Canvas 自身的 -state(恒为 normal), 会让 ESC 绑定的
            # `cancel_btn["state"] == "normal"` 判断永远成立
            try:
                super().configure(state=value)
            except tk.TclError:
                pass
            self._redraw()

    state = property(get_state, set_state)

    def cget(self, key):
        """必须区分自有属性与 Canvas 属性。

        app.py 用 `cancel_btn["state"]` 判断能否取消, 若回落到
        Tk 的 -state(恒为 normal) 会导致空闲时按 ESC 也触发取消。
        """
        k = str(key).lstrip("-")
        if k == "state":
            return self._state
        if k == "text":
            return self._text
        return super().cget(key)

    def __getitem__(self, key):
        return self.cget(key)

    def invoke(self):
        if self._state != "disabled" and self._command:
            try:
                self._command()
            except tk.TclError:
                pass

    def configure(self, **kw):          # noqa: A003
        if "state" in kw:
            self.set_state(kw.pop("state"))
        if "text" in kw:
            self.set_text(kw.pop("text"))
        if "command" in kw:
            self._command = kw.pop("command")
        if kw:
            super().configure(**kw)
        return {"state": self._state, "text": self._text}

    config = configure


# ──────────────────────────── 玻璃输入框 ────────────────────────────

class GlassEntry(tk.Entry):
    """圆角感输入框(flat relief + 焦点高亮描边)。

    兼容 ttk.Entry 的 textvariable / show / state 接口。
    """

    def __init__(self, master, textvariable=None, width=20,
                 font=None, justify="left", **kw):
        self._font = font or ("Microsoft YaHei UI", 9)
        self._focused = False
        kw.setdefault("bd", 0)
        kw.setdefault("relief", "flat")
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("insertwidth", 1)
        super().__init__(
            master, textvariable=textvariable, width=width,
            font=self._font, justify=justify, **kw)
        self._apply_colors()
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)

    def _on_focus_in(self, _e=None):
        self._focused = True
        self._apply_colors()

    def _on_focus_out(self, _e=None):
        self._focused = False
        self._apply_colors()

    def _apply_colors(self):
        # 必须绕过 self.configure(会被重写并再次回调此处, 造成无限递归)
        try:
            if str(self.cget("state")) == "disabled":
                super().configure(
                    bg=U.Palette.BG_BOT_HEX, fg=Palette.TEXT_FAINT,
                    insertbackground=Palette.TEXT_FAINT)
            else:
                super().configure(
                    bg=U.Palette.BG_MID_HEX, fg=Palette.TEXT,
                    insertbackground=Palette.ACCENT_C_HEX)
        except tk.TclError:
            pass

    def configure(self, **kw):          # noqa: A003
        r = super().configure(**kw)
        if any(k in kw for k in ("state", "stateful", "disabledforeground")):
            self._apply_colors()
        return r

    config = configure


# ──────────────────────────── 渐变进度条 ────────────────────────────

class GlassProgress(tk.Canvas):
    """渐变进度条。

    兼容 ttk.Progressbar 接口:
        .configure(value=, maximum=, mode=)
        .start(speed) / .stop() / .step()
    """

    INDETERMINATE_MS = 80

    def __init__(self, master, width=200, height=8,
                 mode="determinate", maximum=100, **kw):
        self._bw, self._bh = int(width), int(height)
        self._value = 0.0
        self._maximum = float(maximum) or 100.0
        self._mode = mode
        self._indet = 0.0
        self._after_id = None
        self._interval_ms = self.INDETERMINATE_MS
        self._photos = {}
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("bd", 0)
        kw.setdefault("background", U.Palette.BG_MID_HEX)
        super().__init__(master, width=self._bw, height=self._bh, **kw)
        self.bind("<Configure>", self._on_resize, add="+")
        self._redraw()

    def _on_resize(self, _e=None):
        try:
            w = int(self.winfo_width())
            h = int(self.winfo_height())
        except (TypeError, ValueError):
            return
        if w > 2 and h > 2 and (w != self._bw or h != self._bh):
            self._bw, self._bh = w, h
            self._redraw()

    def _set_photo(self, key, img, x, y):
        from PIL import ImageTk
        if img is None:
            return
        ph = ImageTk.PhotoImage(img)
        self._photos[key] = ph
        self.create_image(x, y, anchor="nw", image=ph)

    def _redraw(self):
        self.delete("all")
        self._photos.clear()
        h = self._bh
        # 槽
        trough = photo_for("trough", self._bw, h, radius=h // 2)
        self._set_photo("trough", trough, 0, 0)
        if self._mode == "indeterminate":
            # 循环滑块: 用 1/4 宽度的渐变块在槽内移动
            seg = max(18, self._bw // 4)
            seg = min(seg, self._bw)
            fill = photo_for("progress", seg, h, radius=h // 2)
            span = max(1, self._bw - seg)
            off = int(self._indet * span) % (span + seg) - seg
            self._set_photo("fill", fill, off, 0)
            return
        ratio = 0.0
        if self._maximum > 0:
            ratio = max(0.0, min(1.0, self._value / self._maximum))
        fw = int(self._bw * ratio)
        if fw >= h:
            fill = photo_for("progress", fw, h, radius=h // 2)
            self._set_photo("fill", fill, 0, 0)

    # -- 兼容接口 --
    def get_value(self):
        return self._value

    def set_value(self, v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return
        if abs(v - self._value) > 1e-9:
            self._value = v
            if self._mode != "indeterminate":
                self._redraw()

    value = property(get_value, set_value)

    def cget(self, key):
        if key == "value":
            return self._value
        if key == "maximum":
            return self._maximum
        if key == "mode":
            return self._mode
        return super().cget(key)

    def configure(self, **kw):          # noqa: A003
        if "value" in kw:
            self.set_value(kw.pop("value"))
        if "maximum" in kw:
            raw = kw.pop("maximum")
            try:
                self._maximum = float(raw) or 100.0
            except (TypeError, ValueError):
                # 不能把非法值塞回 kw: tk.Canvas 没有 -maximum 选项,
                # 会抛 TclError 并沿调用链冒泡导致程序崩溃
                self._maximum = 100.0
            self._redraw()
        if "mode" in kw:
            new_mode = kw.pop("mode")
            if new_mode != self._mode:
                self._mode = new_mode
                if new_mode == "indeterminate":
                    self.set_value(0)
                    self._indet = 0.0
                    self._animate()
                else:
                    self._stop_anim()
                self._redraw()
        if kw:
            super().configure(**kw)
        return {"value": self._value, "maximum": self._maximum,
                "mode": self._mode}

    config = configure

    def _animate(self):
        self._stop_anim()
        self._indet = 0.0
        self._tick()

    def _tick(self):
        self._indet += 0.028
        self._redraw()
        if self._mode == "indeterminate":
            try:
                self._after_id = self.after(
                    self._interval_ms, self._tick)
            except tk.TclError:
                self._after_id = None

    def _stop_anim(self):
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except (tk.TclError, ValueError):
                pass
            self._after_id = None

    def start(self, interval=None):
        if self._mode != "indeterminate":
            return
        if interval:
            try:
                self._interval_ms = max(10, int(interval))
            except (TypeError, ValueError):
                pass
        # configure(mode="indeterminate") 内部已启动动画,
        # 这里再调会重复调度 after
        if self._after_id is not None:
            return
        self._animate()

    def stop(self):
        self._stop_anim()
        if self._mode == "indeterminate":
            self._indet = 0.0
            self._redraw()

    def step(self, amount=1.0):
        if self._mode == "indeterminate":
            return
        self.set_value(self._value + amount)
