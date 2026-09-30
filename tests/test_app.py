# -*- coding: utf-8 -*-
"""编程工具下载器 —— 单元测试

覆盖纯逻辑函数, 不触网、不创建 GUI 窗口, 可在 CI 中运行:

    python -m unittest discover -s tests -v
    python -m pytest tests -v
"""
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest

# 路径自适应: 定位仓库根目录并加入导入路径
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


class TestSafeFilename(unittest.TestCase):
    """文件名净化: 防路径穿越与命令注入"""

    def test_plain_name_kept(self):
        self.assertEqual(app.safe_filename("python-3.12.5-amd64.exe"),
                         "python-3.12.5-amd64.exe")

    def test_chinese_name_kept(self):
        self.assertEqual(app.safe_filename("编程工具.exe"), "编程工具.exe")

    def test_strips_directory(self):
        self.assertEqual(app.safe_filename("C:/evil/../../setup.exe"),
                         "setup.exe")

    def test_strips_windows_dir(self):
        self.assertNotIn("\\", app.safe_filename("C:\\Windows\\evil.exe"))

    def test_dotdot_removed(self):
        out = app.safe_filename("..\\..\\cmd.exe")
        self.assertNotIn("..", out)

    def test_shell_metachar_replaced(self):
        out = app.safe_filename("a&b;c|d`e$(f).exe")
        for ch in "&;|`$()":
            self.assertNotIn(ch, out)

    def test_quote_replaced(self):
        self.assertNotIn("'", app.safe_filename("it's.exe"))

    def test_empty_fallback(self):
        self.assertTrue(app.safe_filename(""))

    def test_none_fallback(self):
        self.assertTrue(app.safe_filename(None))

    def test_length_capped(self):
        self.assertLessEqual(len(app.safe_filename("a" * 500 + ".exe")),
                             180)

    def test_extension_preserved_on_truncate(self):
        out = app.safe_filename("a" * 500 + ".exe")
        self.assertTrue(out.endswith(".exe"))

    def test_percent_decoded(self):
        """safe_filename 内部会先 unquote, 空格得以保留"""
        self.assertEqual(
            app.safe_filename("Docker%20Desktop%20Installer.exe"),
            "Docker Desktop Installer.exe")

    def test_utf8_percent_decoded(self):
        self.assertEqual(
            app.safe_filename("%E5%B7%A5%E5%85%B7.exe"), "工具.exe")


class TestUniqueFilepath(unittest.TestCase):
    """避免覆盖同名文件"""

    def setUp(self):
        import shutil
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_first_use_original(self):
        p = app.unique_filepath(self.tmp, "a.txt")
        self.assertEqual(os.path.basename(p), "a.txt")

    def test_existing_gets_suffix(self):
        open(os.path.join(self.tmp, "a.txt"), "w").close()
        p = app.unique_filepath(self.tmp, "a.txt")
        self.assertNotEqual(os.path.basename(p), "a.txt")
        self.assertIn("1", os.path.basename(p))

    def test_never_overwrites(self):
        f1 = app.unique_filepath(self.tmp, "a.txt")
        open(f1, "w").close()
        f2 = app.unique_filepath(self.tmp, "a.txt")
        self.assertNotEqual(f1, f2)

    def test_sanitizes_input(self):
        p = app.unique_filepath(self.tmp, "../evil.txt")
        self.assertEqual(os.path.dirname(p), self.tmp)


class TestValidateTool(unittest.TestCase):
    """自定义工具导入的强校验"""

    @staticmethod
    def _minimal(**kw):
        base = {"name": "T", "versions": [
            {"label": "1", "url": "https://a.com/x.exe"}]}
        base.update(kw)
        return base

    def test_valid_passes(self):
        self.assertIsNotNone(app.validate_tool(self._minimal()))

    def test_reject_non_dict(self):
        self.assertIsNone(app.validate_tool("nope"))

    def test_reject_missing_name(self):
        self.assertIsNone(app.validate_tool(
            {"versions": [{"label": "1", "url": "https://a/x"}]}))

    def test_reject_blank_name(self):
        self.assertIsNone(app.validate_tool(self._minimal(name="   ")))

    def test_reject_empty_versions(self):
        self.assertIsNone(app.validate_tool(self._minimal(versions=[])))

    def test_reject_versions_not_list(self):
        self.assertIsNone(app.validate_tool(
            self._minimal(versions={"a": 1})))

    def test_reject_version_missing_label(self):
        self.assertIsNone(app.validate_tool(
            self._minimal(versions=[{"url": "https://a/x.exe"}])))

    def test_reject_version_missing_url(self):
        self.assertIsNone(app.validate_tool(
            self._minimal(versions=[{"label": "1"}])))

    def test_reject_non_http_scheme(self):
        """防止 file:// 等本地协议读取任意文件"""
        self.assertIsNone(app.validate_tool(self._minimal(versions=[
            {"label": "1", "url": "file:///C:/Windows/System32/cmd.exe"}])))

    def test_reject_javascript_scheme(self):
        self.assertIsNone(app.validate_tool(self._minimal(versions=[
            {"label": "1", "url": "javascript:alert(1)"}])))

    def test_accept_http(self):
        self.assertIsNotNone(app.validate_tool(self._minimal(versions=[
            {"label": "1", "url": "http://a.com/x.exe"}])))

    def test_name_trimmed(self):
        t = app.validate_tool(self._minimal(name="  T  "))
        self.assertEqual(t["name"], "T")

    def test_default_category(self):
        t = app.validate_tool(self._minimal())
        self.assertEqual(t["category"], "自定义")

    def test_bad_deploy_type_downgraded(self):
        t = app.validate_tool(self._minimal(
            deploy={"type": "rm -rf"}))
        self.assertEqual(t["deploy"]["type"], "none")

    def test_deploy_not_dict_replaced(self):
        t = app.validate_tool(self._minimal(deploy="oops"))
        self.assertEqual(t["deploy"]["type"], "none")

    def test_custom_without_cmd_disabled(self):
        t = app.validate_tool(self._minimal(
            deploy={"type": "custom", "cmd": "  "}))
        self.assertEqual(t["deploy"]["type"], "none")

    def test_non_str_verify_stripped(self):
        """回归: 曾导致程序启动崩溃"""
        t = app.validate_tool(self._minimal(
            deploy={"type": "msi", "verify": 123}))
        self.assertNotIn("verify", t["deploy"])

    def test_non_str_homepage_stripped(self):
        t = app.validate_tool(self._minimal(
            deploy={"type": "msi", "homepage": ["x"]}))
        self.assertNotIn("homepage", t["deploy"])

    def test_top_level_non_str_homepage_stripped(self):
        t = app.validate_tool(self._minimal(homepage=123))
        self.assertNotIn("homepage", t)

    def test_top_level_homepage_kept(self):
        t = app.validate_tool(self._minimal(homepage="https://ok.com"))
        self.assertEqual(t["homepage"], "https://ok.com")

    def test_non_str_args_stripped(self):
        t = app.validate_tool(self._minimal(
            deploy={"type": "exe", "args": ["/S"]}))
        self.assertNotIn("args", t["deploy"])

    def test_non_bool_need_admin_stripped(self):
        t = app.validate_tool(self._minimal(
            deploy={"type": "exe", "need_admin": "yes"}))
        self.assertNotIn("need_admin", t["deploy"])

    def test_valid_deploy_fields_kept(self):
        t = app.validate_tool(self._minimal(deploy={
            "type": "exe", "args": "/S", "need_admin": True,
            "verify": r"C:\Program Files\x.exe"}))
        d = t["deploy"]
        self.assertEqual(d["args"], "/S")
        self.assertIs(d["need_admin"], True)
        self.assertEqual(d["verify"], r"C:\Program Files\x.exe")

    def test_original_not_mutated(self):
        raw = self._minimal(deploy={"type": "msi", "verify": 1})
        app.validate_tool(raw)
        self.assertEqual(raw["deploy"]["verify"], 1)


class TestSubPlaceholder(unittest.TestCase):
    """自定义安装命令的占位符替换"""

    def test_unquoted_gets_quotes(self):
        out = app._sub_placeholder("run {file}", "{file}",
                                   r"C:\Program Files\a.exe")
        self.assertEqual(out, 'run "C:\\Program Files\\a.exe"')

    def test_double_quotes_preserved(self):
        out = app._sub_placeholder('run "{file}"', "{file}",
                                   r"C:\a.exe")
        self.assertEqual(out, 'run "C:\\a.exe"')

    def test_single_quotes_preserved(self):
        """回归: Windows Terminal 模板使用单引号, 曾被加双引号"""
        out = app._sub_placeholder(
            "pwsh -Command \"Add-AppxPackage -Path '{file}'\"",
            "{file}", r"C:\Users\A B\x.msixbundle")
        self.assertIn("'C:\\Users\\A B\\x.msixbundle'", out)
        self.assertNotIn("\"'", out)

    def test_multiple_placeholders(self):
        out = app._sub_placeholder("a {file} b {appdata}", "{file}",
                                   "x.exe")
        self.assertEqual(out, 'a "x.exe" b {appdata}')


class TestHostsBlocking(unittest.TestCase):
    """hosts 屏蔽诊断"""

    def test_empty_url_safe(self):
        self.assertIsNone(app.check_hosts_blocking(""))

    def test_garbage_safe(self):
        self.assertIsNone(app.check_hosts_blocking("not a url"))

    def test_unblocked_returns_none(self):
        # 正常域名不应误报
        self.assertIsNone(app.check_hosts_blocking(
            "https://www.microsoft.com/x.exe"))

    # ��面用例: 注入临时 hosts, 不依赖运行机器的真实 hosts
    def _write_hosts(self, content):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "hosts")
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_detects_loopback_entry(self):
        p = self._write_hosts("127.0.0.1 evil.example.com\n")
        try:
            self.assertEqual(
                app.check_hosts_blocking(
                    "https://evil.example.com/x", hosts_path=p),
                ("evil.example.com", "127.0.0.1"))
        finally:
            import shutil
            shutil.rmtree(os.path.dirname(p), ignore_errors=True)

    def test_detects_subdomain_of_blocked(self):
        p = self._write_hosts("127.0.0.1 blocked.com\n")
        try:
            self.assertIsNotNone(app.check_hosts_blocking(
                "https://cdn.blocked.com/x", hosts_path=p))
        finally:
            import shutil
            shutil.rmtree(os.path.dirname(p), ignore_errors=True)

    def test_ignores_comment_lines(self):
        p = self._write_hosts("# 127.0.0.1 commented.com\n")
        try:
            self.assertIsNone(app.check_hosts_blocking(
                "https://commented.com/x", hosts_path=p))
        finally:
            import shutil
            shutil.rmtree(os.path.dirname(p), ignore_errors=True)

    def test_ignores_non_loopback_ip(self):
        """真实 IP 不应被判为屏蔽"""
        p = self._write_hosts("203.0.113.5 real.com\n")
        try:
            self.assertIsNone(app.check_hosts_blocking(
                "https://real.com/x", hosts_path=p))
        finally:
            import shutil
            shutil.rmtree(os.path.dirname(p), ignore_errors=True)

    def test_multiple_aliases_on_one_line(self):
        """一行多个别名也应被识别"""
        p = self._write_hosts("127.0.0.1 a.com b.com\n")
        try:
            self.assertEqual(
                app.check_hosts_blocking(
                    "https://b.com/x", hosts_path=p),
                ("b.com", "127.0.0.1"))
        finally:
            import shutil
            shutil.rmtree(os.path.dirname(p), ignore_errors=True)

    def test_missing_file_safe(self):
        self.assertIsNone(app.check_hosts_blocking(
            "https://x.com/a", hosts_path="C:\\nonexistent\\hosts"))


class TestNeedsCurl(unittest.TestCase):
    """CDN 指纹绕过的站点判定"""

    def test_jetbrains_prefers_curl(self):
        self.assertTrue(app.ToolDownloader._needs_curl(
            "https://download.jetbrains.com/idea/idea-2025.3.exe"))

    def test_docker_prefers_curl(self):
        self.assertTrue(app.ToolDownloader._needs_curl(
            "https://desktop.docker.com/win/main/amd64/x.exe"))

    def test_regular_host_uses_urllib(self):
        self.assertFalse(app.ToolDownloader._needs_curl(
            "https://www.python.org/ftp/python/3.12.5/x.exe"))

    def test_suffix_lookalike_rejected(self):
        """回归: evildownload.jetbrains.com 不应命中"""
        self.assertFalse(app.ToolDownloader._needs_curl(
            "https://evildownload.jetbrains.com/x.exe"))

    def test_suffix_lookalike_docker_rejected(self):
        self.assertFalse(app.ToolDownloader._needs_curl(
            "https://desktop.docker.com.evil.net/x.exe"))

    def test_subdomain_allowed(self):
        self.assertTrue(app.ToolDownloader._needs_curl(
            "https://cdn.download.jetbrains.com/x.exe"))

    def test_malformed_url_safe(self):
        self.assertFalse(app.ToolDownloader._needs_curl("://bad"))

    def test_empty_url_safe(self):
        self.assertFalse(app.ToolDownloader._needs_curl(""))


class TestParseHelpers(unittest.TestCase):
    """响应头与进度解析"""

    def test_cd_filename_ascii(self):
        self.assertEqual(
            app.parse_cd_filename(
                'attachment; filename="python-3.12.5-amd64.exe"'),
            "python-3.12.5-amd64.exe")

    def test_cd_filename_utf8(self):
        self.assertEqual(
            app.parse_cd_filename("attachment; filename*=UTF-8''%E5%B7%A5%E5%85%B7.exe"),
            "工具.exe")

    def test_cd_filename_none(self):
        self.assertIsNone(app.parse_cd_filename(""))

    def test_cd_filename_malformed(self):
        self.assertIsNone(app.parse_cd_filename("attachment; ="))

    def test_curl_progress_full_line(self):
        """curl 进度行格式: 已下载量  百分比%  速度/s"""
        got = app.parse_curl_progress(b"1000  50%  2.5M/s")
        self.assertIsNotNone(got)
        size, total, speed = got
        self.assertEqual(size, 1000)
        self.assertEqual(total, 2000)      # 50% => 总量为 2 倍
        self.assertEqual(speed, 2.5 * 1024 ** 2)

    def test_curl_progress_with_unit(self):
        got = app.parse_curl_progress(b"1000M 50% 2.5M/s")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], 1000 * 1024 ** 2)

    def test_curl_progress_bare_number(self):
        """降级路径: 纯字节数"""
        got = app.parse_curl_progress(b"100")
        self.assertEqual(got, (100, 0, 0.0))

    def test_curl_progress_ignores_garbage(self):
        self.assertIsNone(app.parse_curl_progress(b"* junk line"))


class TestHumanFormat(unittest.TestCase):
    """可读化格式化"""

    def test_size_bytes(self):
        self.assertIn("B", app.human_size(512))

    def test_size_kb(self):
        self.assertIn("KB", app.human_size(2048))

    def test_size_mb(self):
        self.assertIn("MB", app.human_size(5 * 1024 ** 2))

    def test_size_gb(self):
        self.assertIn("GB", app.human_size(3 * 1024 ** 3))

    def test_size_zero(self):
        self.assertTrue(app.human_size(0))

    def test_time_seconds(self):
        self.assertIn("s", app.human_time(30))

    def test_time_minutes(self):
        self.assertIn("m", app.human_time(125))

    def test_time_hours(self):
        self.assertIn("h", app.human_time(7200))

    def test_time_zero(self):
        self.assertTrue(app.human_time(0))

    def test_time_negative_empty(self):
        self.assertEqual(app.human_time(-1), "")

    def test_time_nan_empty(self):
        self.assertEqual(app.human_time(float("nan")), "")


class TestDeployerIsInstalled(unittest.TestCase):
    """已安装检测, 任何异常都不应抛出"""

    def test_empty_path(self):
        self.assertFalse(app.Deployer.is_installed(""))

    def test_none_path(self):
        self.assertFalse(app.Deployer.is_installed(None))

    def test_non_str_path_no_crash(self):
        """回归: 曾抛 AttributeError 导致启动崩溃"""
        self.assertFalse(app.Deployer.is_installed(123))

    def test_bytes_path_no_crash(self):
        self.assertFalse(app.Deployer.is_installed(b"C:\\x.exe"))

    def test_existing_path(self):
        self.assertTrue(app.Deployer.is_installed(__file__))

    def test_missing_path(self):
        self.assertFalse(app.Deployer.is_installed(
            r"C:\nonexistent\path\app.exe"))

    def test_wildcard(self):
        """通配符语义: 空目录不匹配, 有匹配文件则为真"""
        import tempfile as _tf
        d = _tf.mkdtemp()
        try:
            self.assertFalse(
                app.Deployer.is_installed(os.path.join(d, "*.exe")))
            open(os.path.join(d, "a.exe"), "w").close()
            self.assertTrue(
                app.Deployer.is_installed(os.path.join(d, "*.exe")))
            self.assertFalse(
                app.Deployer.is_installed(os.path.join(d, "*.msi")))
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class TestUIThemeRendering(unittest.TestCase):
    """UI 主题渲染层(不依赖 GUI 窗口, 可在 CI 无头环境跑)"""

    @classmethod
    def setUpClass(cls):
        import ui_theme
        cls.U = ui_theme

    def setUp(self):
        if not self.U.HAS_PIL:
            self.skipTest("Pillow 不可用")

    def test_palette_has_hex_variants(self):
        """Tk 不接受 RGB 元组, 调色板必须提供 *_HEX"""
        p = self.U.Palette
        for name in ("BG_MID_HEX", "BG_BOT_HEX", "ACCENT_A_HEX",
                     "ACCENT_C_HEX", "OK_HEX"):
            v = getattr(p, name, None)
            self.assertIsInstance(v, str, f"{name} 缺失")
            self.assertTrue(v.startswith("#"), f"{name} 需为 #rrggbb")
            int(v[1:], 16)      # 必须是合法十六进制

    def test_hexof(self):
        self.assertEqual(self.U.hexof((255, 0, 128)), "#FF0080")

    def test_background_size(self):
        img = self.U.make_background(320, 200)
        self.assertEqual(img.size, (320, 200))

    def test_background_handles_tiny(self):
        for w, h in ((1, 1), (2, 3), (10, 10)):
            self.assertEqual(self.U.make_background(w, h).size, (w, h))

    def test_glass_panel_transparent_center(self):
        """玻璃必须是半透明的, 否则失去通透感"""
        img, pad = self.U.make_glass_panel(80, 50)
        r, g, b, a = img.getpixel((40, 25))
        self.assertGreater(a, 0, "玻璃中心应非全透明")
        self.assertLess(a, 255, "玻璃中心不应完全不透明")
        self.assertGreater(r, 200, "玻璃应为白色调")

    def test_glass_panel_shadow_outside_only(self):
        """投影只在外侧, 不能污染玻璃主体(否则面板发灰)"""
        img, pad = self.U.make_glass_panel(80, 50)
        center_a = img.getpixel((40, 25))[3]
        below_a = img.getpixel((40, pad + 50 + 4))[3]
        self.assertGreater(center_a, 0)
        self.assertGreater(below_a, 0, "面板下方应有投影")

    def test_glass_panel_no_shadow(self):
        img, pad = self.U.make_glass_panel(80, 50, shadow=False)
        self.assertEqual(pad, 0)
        self.assertGreater(img.getpixel((40, 25))[3], 0)

    def test_glass_panel_radius_clamped(self):
        """半径不能超过边长一半, 否则 PIL 报错"""
        img, _ = self.U.make_glass_panel(20, 20, radius=999)
        self.assertIsNotNone(img)

    def test_button_states_differ(self):
        normal = self.U.make_gradient_button(90, 30, state="normal")
        hover = self.U.make_gradient_button(90, 30, state="hover")
        active = self.U.make_gradient_button(90, 30, state="active")
        self.assertEqual(normal.size, hover.size)
        self.assertNotEqual(normal.tobytes(), hover.tobytes())
        self.assertNotEqual(hover.tobytes(), active.tobytes())

    def test_accent_button_differs(self):
        plain = self.U.make_gradient_button(90, 30, accent=False)
        accent = self.U.make_gradient_button(90, 30, accent=True)
        self.assertNotEqual(plain.tobytes(), accent.tobytes())

    def test_button_disabled_is_gray(self):
        dis = self.U.make_gradient_button(60, 24, state="disabled")
        r, g, b, _ = dis.getpixel((30, 12))
        # 灰色: 三通道接近
        self.assertLess(max(r, g, b) - min(r, g, b), 20)

    def test_progress_fill_gradient(self):
        img = self.U.make_progress_fill(100, 8)
        self.assertEqual(img.size, (100, 8))
        left = img.getpixel((2, 4))
        right = img.getpixel((97, 4))
        self.assertNotEqual(left, right, "进度条应为渐变")

    def test_draw_check_and_chevron(self):
        """图标须用矢量绘制 —— 雅黑缺 ✓ / ▾ 字形, 会渲染成方块"""
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        self.U.draw_check(d, 20, 20, 12, (255, 255, 255, 255))
        self.U.draw_chevron(d, 20, 20, 12, (255, 255, 255, 255))
        self.assertGreater(
            sum(1 for p in img.getdata() if p[3] > 0), 0,
            "矢量图标未绘制出任何像素")

    def test_fonts_resolved(self):
        f = self.U.load_fonts()
        for k in ("ui", "ui_bold", "mono", "title"):
            self.assertIsInstance(f[k], str)
            self.assertTrue(f[k])


class TestUIWidgetInterfaces(unittest.TestCase):
    """自绘控件必须兼容 ttk 接口(否则 app.py 现有逻辑会崩)"""

    def test_source_exposes_compat_api(self):
        """静态检查: 关键控件提供 ttk 兼容方法"""
        src = (ROOT / "ui_widgets.py").read_text(encoding="utf-8")
        for token in ("def configure", "def cget", "def invoke",
                      "def set_state", "def set_text",
                      "def start", "def stop", "config = configure"):
            self.assertIn(token, src, f"缺少兼容接口: {token}")

    def test_button_state_is_property(self):
        src = (ROOT / "ui_widgets.py").read_text(encoding="utf-8")
        self.assertIn("state = property(get_state, set_state)", src)
        self.assertIn("text = property(get_text, set_text)", src)

    def test_no_tkinter_internal_attr_collision(self):
        """回归: 曾用 self._w 存宽度, 与 tkinter 内部 widget 路径冲突,
        导致 photo_for 收到字符串尺寸而崩溃"""
        src = (ROOT / "ui_widgets.py").read_text(encoding="utf-8")
        for bad in ("self._w =", "self._h =", "self._w /", "self._h /"):
            self.assertNotIn(bad, src, f"不应再使用内部属性名: {bad}")

    def test_no_recursive_configure(self):
        """回归: _apply_colors 调 self.configure 会无限递归"""
        src = (ROOT / "ui_widgets.py").read_text(encoding="utf-8")
        body = src.split("def _apply_colors")[1].split("\n    def ")[0]
        # 只看代码行, 排除注释里的说明文字
        code = [ln.split("#")[0] for ln in body.splitlines()]
        for ln in code:
            self.assertNotIn("self.configure(", ln,
                             "_apply_colors 内必须用 super().configure")

    def test_button_supports_getitem_and_cget(self):
        """回归: btn[\"state\"] 若回落到 Canvas 的 -state(恒 normal),
        ESC 绑定的 `cancel_btn["state"] == "normal"` 会永远成立,
        导致空闲时按 ESC 也触发取消。"""
        src = (ROOT / "ui_widgets.py").read_text(encoding="utf-8")
        cls = src.split("class GlassButton")[1].split("\nclass ")[0]
        self.assertIn("def __getitem__", cls,
                      "GlassButton 必须支持 btn[\"state\"] 语法")
        self.assertIn("def cget", cls)
        self.assertIn('if k == "state"', cls,
                      "cget 必须优先返回自有 state 而非 Canvas 的 -state")

    def test_panel_uses_reduced_photo_size(self):
        """回归: 玻璃图自带投影留白, 若按面板原尺寸取图并把画布内缩,
        右侧/底部的描边与圆角会被裁掉(方角断边)。"""
        src = (ROOT / "ui_widgets.py").read_text(encoding="utf-8")
        cls = src.split("class GlassPanel")[1].split("\nclass ")[0]
        self.assertIn("iw, ih = w - PAD * 2", cls,
                      "取图尺寸必须减去两侧投影留白")
        # 画布本身应铺满父容器
        self.assertIn("self.canvas.place(x=0, y=0, relwidth=1, relheight=1)",
                      cls)

    def test_background_is_not_covered(self):
        """回归: content 层若用不透明底色铺满 root, 渐变背景会被遮死,
        液态玻璃特效等于没做。必须启用色键透明。"""
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("-transparentcolor", src,
                      "需用色键透明让背景透上来")

    def test_no_ttk_style_with_rgba_tuple(self):
        """回归: Palette.TROUGH 等是 4 元组, 传给 ttk.Style.configure
        会抛 bad color 导致程序无法启动。"""
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        body = src.split("def _apply_ttk_styles")[1].split("\n    def ")[0]
        for name in ("p.TROUGH", "p.GLASS_FILL", "p.TREE_SEL_BG",
                     "p.ACCENT_A,", "p.ACCENT_B)"):
            self.assertNotIn(name, body,
                             f"ttk style 不应接收 RGB 元组: {name}")


class TestToolDataLayer(unittest.TestCase):
    """tooldata 数据层: 须脱离 tkinter 独立可用(供 CI Linux 容器)"""

    @classmethod
    def setUpClass(cls):
        import tooldata
        cls.td = tooldata

    def test_module_has_no_tkinter(self):
        """数据层不得真的 import tkinter(文档提及不算)"""
        import ast
        import tooldata
        tree = ast.parse((ROOT / "tooldata.py").read_text(
            encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("tkinter", imported,
                         f"数据层不应 import tkinter, 实际: {imported}")
        self.assertLessEqual(
            imported, {"json", "os", "sys", "collections", "tools"},
            f"数据层出现了意外依赖: {imported}")

    def test_cli_entry_exists(self):
        self.assertTrue(callable(self.td.main))

    def test_builtin_library_valid(self):
        from tools import CATEGORIES, TOOLS
        self.assertEqual(self.td.check_tool_library(TOOLS, CATEGORIES), [])

    def test_detects_duplicate_names(self):
        t = {"name": "A", "category": "c",
             "versions": [{"label": "1", "url": "https://a/x"}]}
        errs = self.td.check_tool_library([t, dict(t)], ["c"])
        self.assertTrue(any("重复" in e for e in errs), errs)

    def test_detects_duplicate_labels(self):
        v = {"label": "1", "url": "https://a/x"}
        t = {"name": "A", "category": "c", "versions": [v, dict(v)]}
        errs = self.td.check_tool_library([t], ["c"])
        self.assertTrue(any("标签重复" in e for e in errs), errs)

    def test_detects_unknown_category(self):
        t = {"name": "A", "category": "nope",
             "versions": [{"label": "1", "url": "https://a/x"}]}
        errs = self.td.check_tool_library([t], ["c"])
        self.assertTrue(any("未在 CATEGORIES" in e for e in errs), errs)

    def test_detects_empty_category(self):
        t = {"name": "A", "category": "c",
             "versions": [{"label": "1", "url": "https://a/x"}]}
        errs = self.td.check_tool_library([t], ["c", "empty"])
        self.assertTrue(any("没有任何工具" in e for e in errs), errs)

    def test_empty_library_is_error(self):
        self.assertTrue(self.td.check_tool_library([]))

    def test_non_list_is_error(self):
        self.assertTrue(self.td.check_tool_library({"a": 1}))

    def test_app_reexports_validate_tool(self):
        """app.py 应对外保持 validate_tool 名称(向后兼容)"""
        self.assertIs(app.validate_tool, self.td.validate_tool)

    def test_app_deploy_types_reexported(self):
        self.assertEqual(app.DEPLOY_TYPES, self.td.DEPLOY_TYPES)

    def test_main_returns_zero_for_builtin(self):
        self.assertEqual(self.td.main([]), 0)

    def test_main_stats_flag(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.td.main(["--stats"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("[OK]", out)
        # --stats 应逐分类列出工具名
        for cat in ("语言运行时", "开发环境 (IDE)", "构建工具"):
            self.assertIn(cat, out)

    def test_main_without_stats_is_quiet(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.td.main([])
        self.assertNotIn("语言运行时 (", buf.getvalue())


class TestBuiltinToolsData(unittest.TestCase):
    """内置工具库完整性"""

    def setUp(self):
        from tools import TOOLS
        self.tools = TOOLS

    def test_has_tools(self):
        self.assertGreaterEqual(len(self.tools), 20)

    def test_all_validated(self):
        for t in self.tools:
            self.assertIsNotNone(app.validate_tool(t),
                                 f"非法工具定义: {t.get('name')}")

    def test_unique_names(self):
        names = [t["name"] for t in self.tools]
        self.assertEqual(len(names), len(set(names)), "工具名重复")

    def test_urls_https_or_http(self):
        for t in self.tools:
            for v in t["versions"]:
                self.assertTrue(
                    v["url"].startswith(("http://", "https://")),
                    f"{t['name']} 使用了非 http(s) 协议")

    def test_deploy_type_known(self):
        for t in self.tools:
            self.assertIn(t.get("deploy", {}).get("type", "none"),
                          app.DEPLOY_TYPES,
                          f"{t['name']} 的 deploy.type 非法")

    def test_category_declared(self):
        """每个工具的分类都必须在 CATEGORIES 中声明"""
        from tools import CATEGORIES
        for t in self.tools:
            self.assertIn(t["category"], CATEGORIES,
                          f"{t['name']} 的分类 {t['category']} 未在 "
                          f"CATEGORIES 中声明")

    def test_category_not_empty(self):
        from tools import CATEGORIES
        self.assertTrue(CATEGORIES)
        self.assertEqual(len(CATEGORIES), len(set(CATEGORIES)),
                         "CATEGORIES 存在重复项")

    def test_every_category_has_tools(self):
        """空分类会让界面出现空白页签"""
        from tools import CATEGORIES
        used = {t["category"] for t in self.tools}
        for c in CATEGORIES:
            self.assertIn(c, used, f"分类「{c}」下没有任何工具")

    def test_greenfield_tools_not_github(self):
        """绿色版工具应来自非 GitHub 源(国内可用性优先)"""
        for name in ("Apache Maven", "Gradle", "Flutter SDK"):
            tool = next((t for t in self.tools if t["name"] == name), None)
            self.assertIsNotNone(tool, f"缺少工具: {name}")
            for v in tool["versions"]:
                self.assertNotIn("github.com", v["url"],
                                 f"{name} 使用了 GitHub 源, 国内不可用")

    def test_labels_unique_per_tool(self):
        for t in self.tools:
            labels = [v["label"] for v in t["versions"]]
            self.assertEqual(len(labels), len(set(labels)),
                             f"{t['name']} 版本标签重复")

    def test_no_internal_fields_committed(self):
        """tools.py 不得包含运行时注入的内部字段"""
        for t in self.tools:
            self.assertIsNone(t.get("_installed"),
                              f"{t.get('name')} 残留运行时字段 _installed")


class TestReadmeDocs(unittest.TestCase):
    """README 与代码的一致性"""

    @classmethod
    def setUpClass(cls):
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    @staticmethod
    def _count_tests():
        """统计本文件中的 test_ 开头的用例数"""
        import ast
        src = (ROOT / "tests" / "test_app.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        return sum(1 for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)
                   and n.name.startswith("test_"))

    def test_not_placeholder(self):
        self.assertGreater(len(self.readme.strip()), 200)

    def test_has_title(self):
        self.assertIn("#", self.readme)

    def test_mentions_shortcuts(self):
        self.assertIn("Ctrl+F", self.readme)

    def test_mentions_deploy_types(self):
        for k in ("msi", "exe", "extract", "custom"):
            self.assertIn(k, self.readme, f"README 未说明 {k} 部署类型")

    def test_mentions_security(self):
        self.assertIn("安全", self.readme)

    def test_mentions_troubleshooting(self):
        self.assertIn("故障排查", self.readme)

    def test_tool_count_matches(self):
        """README 声明的工具数量须与 tools.py 实际一致"""
        from tools import TOOLS
        self.assertIn(f"{len(TOOLS)} 款", self.readme,
                      "README 工具数量与 tools.py 不一致")

    def test_test_count_matches(self):
        """文档中声明的测试数量须与实际用例数一致(防漂移)"""
        import re
        actual = self._count_tests()
        m = re.search(r"(\d+)\s*项", self.readme)
        self.assertIsNotNone(m, "README 未声明测试数量")
        self.assertEqual(int(m.group(1)), actual,
                         f"README 声明 {m.group(1)} 项, "
                         f"实际 {actual} 项")

    def test_changelog_test_count_matches(self):
        import re
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        m = re.search(r"(\d+)\s*项", changelog)
        self.assertIsNotNone(m, "CHANGELOG 未声明测试数量")
        self.assertEqual(int(m.group(1)), self._count_tests())

    def test_no_stale_tool_count(self):
        """「关于」对话框等位置不应残留旧工具数"""
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        from tools import TOOLS
        self.assertNotIn("22+ 款", src,
                         "app.py 仍残留旧工具数量文案")


class TestCustomToolsFileIO(unittest.TestCase):
    """自定义工具文件读写容错"""

    def setUp(self):
        import shutil
        import unittest.mock as mock
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patcher = mock.patch.object(
            app, "CUSTOM_TOOLS_PATH",
            os.path.join(self.tmp, "ct.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_file_returns_empty(self):
        self.assertEqual(app.load_custom_tools(), [])

    def test_bad_json_returns_empty(self):
        with open(app.CUSTOM_TOOLS_PATH, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(app.load_custom_tools(), [])

    def test_list_format_accepted(self):
        with open(app.CUSTOM_TOOLS_PATH, "w", encoding="utf-8") as f:
            json.dump([{"name": "A", "versions": [
                {"label": "1", "url": "https://a.com/x.exe"}]}], f)
        self.assertEqual(len(app.load_custom_tools()), 1)

    def test_wrapped_format_accepted(self):
        """兼容导出文件格式"""
        with open(app.CUSTOM_TOOLS_PATH, "w", encoding="utf-8") as f:
            json.dump({"version": "1.0", "tools": [
                {"name": "A", "versions": [
                    {"label": "1", "url": "https://a.com/x.exe"}]}]}, f)
        self.assertEqual(len(app.load_custom_tools()), 1)

    def test_invalid_items_filtered(self):
        with open(app.CUSTOM_TOOLS_PATH, "w", encoding="utf-8") as f:
            json.dump({"tools": [
                {"name": "Good", "versions": [
                    {"label": "1", "url": "https://a.com/x.exe"}]},
                {"name": "Bad", "versions": []},
                "junk",
            ]}, f)
        got = app.load_custom_tools()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["name"], "Good")

    def test_empty_tools_key(self):
        with open(app.CUSTOM_TOOLS_PATH, "w", encoding="utf-8") as f:
            json.dump({"tools": []}, f)
        self.assertEqual(app.load_custom_tools(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
