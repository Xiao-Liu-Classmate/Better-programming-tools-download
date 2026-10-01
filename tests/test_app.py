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
import re
import sys
import tempfile
import unittest

# QApplication 必须持有强引用, 否则被GC 后解释器退出会访问已销毁的
# Qt 对象, 触发 0xC0000409 崩溃
_QT_APP = None

# 各测试类累积创建的顶层 QWidget, 在 tearDownClass 统一回收
_QTWIDGETS = []


def _dispose_qtwidgets(cls):
    """显式销毁 cls 累积创建的顶层 QWidget。

    不能用 ``deleteLater``: 它只在事件循环跑到时才真正析构, 而
    unittest 收尾时未必再 pump 事件, 控件便以"半存活"状态留到解释器
    退出, 触发 0xC0000409。故用 ``shiboken6.delete`` 立即释放底层
    C++ 对象, 再把 Python 包装引用清空。
    """
    import shiboken6
    from PySide6 import QtWidgets
    for w in reversed(getattr(cls, "_QTWIDGETS", [])):
        try:
            w.setParent(None)
            if shiboken6.isValid(w):
                shiboken6.delete(w)
        except (RuntimeError, AttributeError):
            pass
    cls._QTWIDGETS = []
    QtWidgets.QApplication.processEvents()


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
    """UI 主题层(不依赖显示设备, 可在 CI 无头环境跑)"""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls._QTWIDGETS = []
        # 必须先建 QApplication 再操作 QFont/QImage: 这些对象依赖
        # 应用上下文, 应用不存在时被回收会在解释器退出阶段触发
        # 0xC0000409 崩溃(表现为"单跑通过、连跑必崩")
        global _QT_APP
        from PySide6 import QtWidgets
        if _QT_APP is None:
            _QT_APP = (QtWidgets.QApplication.instance()
                       or QtWidgets.QApplication([]))
        cls.app = _QT_APP
        import ui_qt
        cls.U = ui_qt

    @classmethod
    def tearDownClass(cls):
        _dispose_qtwidgets(cls)

    def test_palette_values_are_qss_safe(self):
        """所有颜色必须是 QSS 可接受的字符串。

        Qt 的 QSS 只接受 #rrggbb / rgba(...) /具名色, 传 RGB 元组
        会导致样式表解析失败(界面整体失去样式)。
        """
        p = self.U.PAL
        names = [n for n in dir(p)
                 if n.isupper() and not n.startswith("_")]
        self.assertTrue(names, "调色板为空")
        for name in names:
            v = getattr(p, name)
            with self.subTest(color=name):
                self.assertIsInstance(v, str, f"{name} 必须是字符串")
                ok = v.startswith("#") or v.startswith("rgba(") \
                    or v.startswith("qlineargradient") or v == "transparent"
                self.assertTrue(ok, f"{name} 不是合法 QSS 颜色: {v}")
                if v.startswith("#"):
                    self.assertRegex(v, r"^#[0-9A-Fa-f]{6}$")

    def test_background_matches_requested_size(self):
        img = self.U.make_background(320, 200)
        self.assertIsNotNone(img)
        self.assertEqual((img.width(), img.height()), (320, 200))

    def test_background_handles_tiny(self):
        for w, h in ((1, 1), (2, 3), (10, 10)):
            img = self.U.make_background(w, h)
            self.assertIsNotNone(img, f"{w}x{h} 生成失败")
            self.assertEqual((img.width(), img.height()), (w, h))

    def test_background_handles_invalid(self):
        self.assertIsNone(self.U.make_background(0, 100))
        self.assertIsNone(self.U.make_background(100, 0))
        self.assertIsNone(self.U.make_background(-5, -5))

    def test_background_is_opaque(self):
        """背景必须不透明, 否则窗口透明处会露出桌面/黑屏。"""
        img = self.U.make_background(64, 64)
        self.assertFalse(img.hasAlphaChannel() and not img.isGrayscale())

    def test_build_qss_returns_text(self):
        fonts = self.U.load_fonts()
        qss = self.U.build_qss(fonts)
        self.assertIsInstance(qss, str)
        self.assertGreater(len(qss), 200, "样式表过短, 可能漏写")
        # 关键控件必须有样式, 否则深色底上文字不可读
        for token in ("QPushButton", "QLineEdit", "QTreeWidget",
                      "QProgressBar", "QComboBox", "QMenu"):
            self.assertIn(token, qss, f"样式表缺少 {token}")

    def test_qss_has_balanced_braces(self):
        """QSS 以花括号分块; 若数量不平衡, 引擎会静默丢弃后续样式。"""
        fonts = self.U.load_fonts()
        qss = self.U.build_qss(fonts)
        self.assertEqual(qss.count("{"), qss.count("}"),
                         "花括号不配对, 样式表会被截断")

    def test_qss_no_unexpanded_placeholder(self):
        """未替换的 f-string 占位会让整段样式失效。"""
        fonts = self.U.load_fonts()
        qss = self.U.build_qss(fonts)
        # QSS 里合法出现 '{' 仅用于分块; 形如 {xxx} 的应视为未展开
        self.assertIsNone(re.search(r"\{[A-Za-z_]+\}", qss),
                          "样式表里存在未展开的占位符")

    def test_load_fonts_returns_all_keys(self):
        fonts = self.U.load_fonts()
        for k in ("ui", "mono", "size"):
            self.assertIn(k, fonts)
            self.assertTrue(fonts[k].family())


class TestQtBindLayer(unittest.TestCase):
    """ui_bind 必须提供 app.py 依赖的 ttk 兼容接口。

    这些接口是业务层与界面层的唯一契约, 缺一个就会让下载/部署
    流程在运行时AttributeError。
    """

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls._QTWIDGETS = []
        global _QT_APP
        from PySide6 import QtWidgets
        if _QT_APP is None:
            _QT_APP = (QtWidgets.QApplication.instance()
                       or QtWidgets.QApplication([]))
        import ui_bind
        cls.B = ui_bind

    @classmethod
    def tearDownClass(cls):
        _dispose_qtwidgets(cls)

    # ── 接口存在性 ──

    def test_var_interface(self):
        for m in ("get", "set", "trace_add"):
            self.assertTrue(callable(getattr(self.B.Var, m, None)),
                            f"Var 缺少 {m}")

    def test_tree_interface(self):
        for m in ("delete", "insert", "item", "selection",
                  "selection_set", "get_children", "heading", "column",
                  "tag_configure", "see", "bind"):
            self.assertTrue(callable(getattr(self.B.TreeShim, m, None)),
                            f"TreeShim 缺少 {m}")

    def test_text_interface(self):
        for m in ("insert", "delete", "get", "see", "configure"):
            self.assertTrue(callable(getattr(self.B.TextShim, m, None)),
                            f"TextShim 缺少 {m}")

    def test_button_interface(self):
        for m in ("state", "set_state", "configure"):
            self.assertTrue(callable(getattr(self.B.Button, m, None)),
                            f"Button 缺少 {m}")

    def test_progress_interface(self):
        self.assertTrue(callable(getattr(self.B.ProgressShim, "configure",
                                         None)))

    def test_dialog_entrypoints(self):
        for name in ("show_info", "show_error", "show_warning",
                     "ask_yesno", "ask_directory", "ask_saveas",
                     "ask_openfilename"):
            self.assertTrue(callable(getattr(self.B, name, None)),
                            f"缺少对话框入口 {name}")
        # 业务层使用的 ttk 风格名也必须存在
        self.assertTrue(callable(self.B.messagebox.showinfo))
        self.assertTrue(callable(self.B.messagebox.askyesno))
        self.assertTrue(callable(self.B.filedialog.asksaveasfilename))
        self.assertTrue(callable(self.B.filedialog.askdirectory))
        self.assertTrue(callable(self.B.filedialog.askopenfilename))

    def test_root_after_signature(self):
        """业务层以 root.after(ms, fn) 调度, 签名不可变。

        还须支持 tkinter 的 ``after(ms, fn, *args)`` 透传形式:
        业务代码 ``root.after(2000, self._restore_status, old)`` 依赖
        把额外参数传给回调。漏掉 *args 会让「复制 URL」直接崩。
        """
        import inspect
        sig = inspect.signature(self.B.RootShim.after)
        params = list(sig.parameters)
        self.assertEqual(params[:3], ["self", "ms", "fn"])
        self.assertIn("args", params, "须支持 *args 透传")
        self.assertEqual(
            sig.parameters["args"].kind,
            inspect.Parameter.VAR_POSITIONAL)

    def test_root_after_runs_with_extra_args(self):
        """after(ms, fn, arg) 必须在主线程把 arg 传给 fn。"""
        self._app()
        from PySide6 import QtWidgets
        # 必须登记: 未登记的顶层控件会被 Python GC 而非显式销毁,
        # 其 C++ 对象仍被信号连接引用, 解释器退出时触发 0xC0000409
        win = self._widget(QtWidgets.QMainWindow)
        root = self.B.RootShim(win)
        got = []
        root.after(0, lambda v: got.append(v), "值")
        for _ in range(80):
            QtWidgets.QApplication.processEvents()
            if got:
                break
        self.assertEqual(got, ["值"], "额外参数未透传或回调未执行")
        root.destroy()

    # ── 行为(离屏 Qt) ──

    def _app(self):
        """取得 QApplication 并保持强引用。

        必须存到模块级变量: PySide6 的 QApplication 若被垃圾回收,
        解释器退出时会访问已销毁的 Qt 对象并触发 0xC0000409 崩溃。
        """
        from PySide6 import QtWidgets
        global _QT_APP
        if _QT_APP is None:
            _QT_APP = (QtWidgets.QApplication.instance()
                       or QtWidgets.QApplication([]))
        return _QT_APP

    def _widget(self, cls, *args, **kw):
        """创建顶层 QWidget, 登记到类级列表统一在类结束时回收。

        无 parent 的 QWidget 若被 Python GC 而底层 C++ 对象仍被
        信号连接引用, 会在解释器退出阶段触发 0xC0000409。

        注意不能用 ``addCleanup(w.deleteLater)``: cleanup 在
        tearDown 阶段执行, 此时控件可能仍挂在视图树上, 提前 delete
        会让视图残留悬空指针, 同样崩溃。改为类级列表 + setUpClass
        的 tearDownClass 统一清理, 保证顺序安全。
        """
        w = cls(*args, **kw)
        self.__class__._QTWIDGETS.append(w)
        return w


    def test_var_roundtrip_without_widget(self):
        self._app()
        v = self.B.Var(value="a")
        self.assertEqual(v.get(), "a")
        v.set("b")
        self.assertEqual(v.get(), "b")
        v.set(None)
        self.assertEqual(v.get(), "", "None 应归一为空串")

    def test_var_trace_fires_on_change_only(self):
        self._app()
        calls = []
        v = self.B.Var(value="x")
        v.trace_add("write", lambda: calls.append(1))
        v.set("x")            # 同值不应触发
        self.assertEqual(len(calls), 0, "同值不应触发回调")
        v.set("y")
        self.assertEqual(len(calls), 1)

    def test_tree_insert_delete_and_selection(self):
        self._app()
        from PySide6 import QtWidgets
        w = self._widget(QtWidgets.QTreeWidget)
        t = self.B.TreeShim(w, columns=("a", "b"))
        t.insert("", "end", iid="1", values=("x", "y"))
        t.insert("", "end", iid="2", values=("p", "q"))
        self.assertEqual(sorted(t.get_children()), ["1", "2"])
        self.assertEqual(t.item("1", "values"), ["x", "y"])
        t.selection_set("1")
        self.assertIn("1", t.selection())
        t.selection_set("missing")          # 未知 iid 不应抛
        t.delete(*t.get_children())
        self.assertEqual(t.get_children(), [])

    def test_tree_item_tags_roundtrip(self):
        """下载高亮依赖 tags 读写。"""
        self._app()
        from PySide6 import QtWidgets
        w = self._widget(QtWidgets.QTreeWidget)
        t = self.B.TreeShim(w, columns=("a",))
        t.insert("", "end", iid="1", values=("x",), tags=("installed",))
        self.assertIn("installed", t.item("1", "tags"))
        t.item("1", tags=("downloading",))
        self.assertEqual(t.item("1", "tags"), ("downloading",))

    def test_tree_missing_iid_raises_like_ttk(self):
        self._app()
        from PySide6 import QtWidgets
        t = self.B.TreeShim(self._widget(QtWidgets.QTreeWidget), columns=("a",))
        with self.assertRaises(KeyError):
            t.item("nope", "values")

    def test_tree_selection_change_notifies_callback(self):
        """回归: 用户点击必须派发 <<TreeviewSelect>>。

        真实缺陷: ``_on_view_selection`` (Qt itemSelectionChanged 的
        槽) 只更新内部 ``_sel`` 而不派发回调, 导致点击分类标签无反应。
        程序化 ``selection_set`` 恰好会补发, 所以只测程序化路径的
        用例全部通过 —— 必须直接模拟视图侧选中来守住这条契约。
        """
        self._app()
        from PySide6 import QtWidgets
        view = self._widget(QtWidgets.QTreeWidget)
        t = self.B.TreeShim(view, columns=("a",))
        for iid in ("1", "2"):
            t.insert("", "end", iid=iid, values=(f"row{iid}",))

        seen = []
        t.bind("<<TreeviewSelect>>", lambda _e: seen.append(
            list(t.selection())))

        # 模拟用户点击第二行: 只改视图选中, 不碰 shim 接口
        view.clearSelection()
        view.topLevelItem(1).setSelected(True)
        QtWidgets.QApplication.processEvents()

        self.assertEqual(t.selection(), ["2"], "选中状态未同步")
        self.assertTrue(seen, "点击未派发 <<TreeviewSelect>>")
        self.assertEqual(seen[-1], ["2"])

    def test_tree_selection_callback_not_duplicated(self):
        """同一次选择变化不应重复派发回调。"""
        self._app()
        from PySide6 import QtWidgets
        view = self._widget(QtWidgets.QTreeWidget)
        t = self.B.TreeShim(view, columns=("a",))
        t.insert("", "end", iid="1", values=("row1",))
        t.insert("", "end", iid="2", values=("row2",))

        seen = []
        t.bind("<<TreeviewSelect>>", lambda _e: seen.append(1))
        t.selection_set("2")
        QtWidgets.QApplication.processEvents()
        n1 = len(seen)
        t.selection_set("2")          # 重复选中同一行
        QtWidgets.QApplication.processEvents()
        self.assertEqual(len(seen), n1,
                         f"重复选中触发了额外回调: {n1} -> {len(seen)}")

    def test_tree_selection_survives_callback_reentrancy(self):
        """回调内再次改选中不得递归爆栈。"""
        self._app()
        from PySide6 import QtWidgets
        view = self._widget(QtWidgets.QTreeWidget)
        t = self.B.TreeShim(view, columns=("a",))
        t.insert("", "end", iid="1", values=("row1",))
        t.insert("", "end", iid="2", values=("row2",))

        def on_select(_e):
            if t.selection() == ["1"]:
                t.selection_set("2")      # 回调内重入

        t.bind("<<TreeviewSelect>>", on_select)
        t.selection_set("1")
        QtWidgets.QApplication.processEvents()
        self.assertEqual(t.selection(), ["2"])

    def test_combo_values_and_current(self):
        self._app()
        from PySide6 import QtWidgets
        c = self.B.ComboShim(self._widget(QtWidgets.QComboBox))
        c["values"] = ["a", "b", "c"]
        self.assertEqual(c["values"], ["a", "b", "c"])
        c.current(1)
        self.assertEqual(c.current(), 1)
        c.current(99)                 # 越界不应抛
        self.assertTrue(c.winfo_exists())

    def test_button_state_roundtrip(self):
        """ESC 快捷键判定依赖 state() 返回 disabled 标记。"""
        self._app()
        from PySide6 import QtWidgets
        b = self.B.Button(QtWidgets.QPushButton("x"))
        b.set_state("disabled")
        self.assertIn("disabled", b.state())
        b.set_state("normal")
        self.assertEqual(b.state(), [])
        b.configure(state="disabled")
        self.assertIn("disabled", b.state())

    def test_progress_clamps_maximum(self):
        """ttk 允许 maximum=0, Qt 会除零 -> 必须钳位。"""
        self._app()
        from PySide6 import QtWidgets
        p = self.B.ProgressShim(self._widget(QtWidgets.QProgressBar))
        p.configure(maximum=0, value=0)
        self.assertGreaterEqual(p.w.maximum(), 1)
        p.configure(maximum=100, value=42)
        self.assertEqual(p.w.maximum(), 100)
        self.assertEqual(p.w.value(), 42)

    def test_text_shim_readonly_semantics(self):
        """日志区必须只读, 且能追加/读取/清空。"""
        self._app()
        from PySide6 import QtWidgets
        tw = self._widget(QtWidgets.QPlainTextEdit)
        t = self.B.TextShim(tw)
        t.insert("end", "line1\n")
        t.insert("end", "line2\n")
        self.assertIn("line1", t.get("1.0", "end"))
        self.assertIn("line2", t.get("1.0", "end"))
        t.delete("1.0", "end")
        self.assertEqual(t.get("1.0", "end").strip(), "")


class TestQtIntegration(unittest.TestCase):
    """静态约束: 迁移后不应再有 tkinter 痕迹与自绘渲染残留"""

    def _src(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_app_has_no_tkinter_import(self):
        """app.py 必须彻底脱离 tkinter。"""
        import ast
        tree = ast.parse(self._src("app.py"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("tkinter", imported, f"仍依赖 tkinter: {imported}")
        self.assertIn("PySide6", imported, "未引入 PySide6")

    def test_no_tkinter_api_calls(self):
        """app.py 不得直接调用 tkinter API。

        这是本次迁移最容易漏的一类问题: ttk/Canvas 的方法名(
        ``pack`` / ``pack_forget`` / ``identify_row`` / ``after``)在
        Qt 控件上不存在, 一旦残留就会在运行时抛 AttributeError ——
        且往往发生在下载主流程里, 单元测试又测不到。

        ``winfo_exists`` 例外: 它是 ttk 的存在性查询, ui_bind 的
        ComboShim 刻意保留了该方法名以兼容既有调用点。
        """
        src = self._src("app.py")
        forbidden = (
            "tk.", "ttk.", "TclError", "tk_popup", "after_idle",
            "StringVar(", "clipboard_clear", "pack_propagate",
            ".pack(", ".pack_forget", ".grid(", ".grid_remove",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, src,
                                 f"仍有 tkinter 调用: {token}")
        # after_cancel / winfo_exists 是 shim 刻意保留的兼容方法名
        # (RootShim.after_cancel / ComboShim.winfo_exists), 属适配层
        # 契约, 允许出现在业务代码里
        for token in (".after_cancel(", ".winfo_exists("):
            for m in re.finditer(re.escape(token), src):
                before = src[max(0, m.start() - 400):m.start()]
                line = before.splitlines()[-1] if before else ""
                with self.subTest(token=token):
                    self.assertTrue(
                        "self.root" in before or "version_combo" in before,
                        f"shim 兼容方法须经 root/shim 调用: {line.strip()}")

    def test_qt_widgets_have_no_configure_method(self):
        """回归: QLabel/QPushButton 没有 ``configure()``。

        代码若从 tkinter 迁过来会写成 ``progress_label.configure(
        text=...)``, 运行时必崩。这里显式断言"确实没有", 让后续
        误用立刻暴露在测试阶段。
        """
        from PySide6 import QtWidgets
        global _QT_APP
        if _QT_APP is None:
            _QT_APP = (QtWidgets.QApplication.instance()
                       or QtWidgets.QApplication([]))
        for cls in (QtWidgets.QLabel, QtWidgets.QPushButton,
                    QtWidgets.QComboBox):
            with self.subTest(cls=cls.__name__):
                self.assertFalse(hasattr(cls, "configure"),
                                 f"{cls.__name__} 不应有 configure")
        self.assertFalse(hasattr(QtWidgets.QProgressBar, "start"),
                         "QProgressBar 没有 start()(那是 QProgressDialog)")

    def test_buttons_always_use_qt_visibility_api(self):
        """回归: 按钮显隐必须用 setVisible, 不能用 pack/pack_forget。"""
        src = self._src("app.py")
        for name in ("retry_btn", "cancel_btn", "deploy_btn"):
            with self.subTest(btn=name):
                hits = re.findall(rf"self\.{name}\.(?!w\.)(\w+)",
                                  src)
                tk_only = {"pack", "pack_forget", "grid",
                           "grid_remove", "place", "lift", "lower"}
                bad = [h for h in hits if h in tk_only]
                self.assertFalse(
                    bad, f"{name} 仍在用 tkinter 布局方法: {bad}")

    def test_old_render_modules_removed(self):
        """自绘渲染层已由Qt 取代, 不应再存在。"""
        for name in ("ui_theme.py", "ui_widgets.py"):
            self.assertFalse((ROOT / name).exists(),
                             f"{name} 应随迁移删除")

    def test_app_does_not_import_old_modules(self):
        src = self._src("app.py")
        for token in ("import ui_theme", "import ui_widgets",
                      "UIW.", "HAS_PIL"):
            self.assertNotIn(token, src, f"仍引用旧模块: {token}")

    def test_no_handrolled_painting_of_widgets(self):
        """约束: 不自绘底层控件, 应交给 Qt。

        QPainter 只允许出现在背景光晕层; 控件一律用 Qt 原生类。
        """
        src = self._src("ui_qt.py")
        classes = re.findall(r"^class (\w+)\(([^)]*)\):", src, re.M)
        for name, base in classes:
            with self.subTest(cls=name):
                if name == "BackgroundWidget":
                    continue    # 背景光晕属装饰, 允许 QPainter
                self.assertTrue(
                    base.strip().startswith("QtWidgets."),
                    f"{name} 应继承 QtWidgets 控件, 实际: {base}")

    def test_qss_installed_globally(self):
        """样式必须走 QSS 全局安装, 而非逐控件设样式。"""
        src = self._src("app.py")
        body = src.split("def _apply_ttk_styles")[1].split("\n    def ")[0]
        self.assertIn("setStyleSheet", body,
                      "需通过 QApplication.setStyleSheet 安装样式表")

    def test_background_widget_is_lowest_layer(self):
        """回归: 背景层若不在最底会被内容遮死, 玻璃特效失效。

        实现方式为 ``setParent`` + ``lower()`` + 绝对几何, 而非加入
        layout —— QVBoxLayout 会按 sizeHint 分配空间, 背景层
        sizeHint 为 -1 会被压成零高度(实测光晕完全不显示)。
        """
        src = self._src("app.py")
        body = src.split("def _assemble")[1].split("\n    def ")[0]
        self.assertIn("bg.setParent(central)", body,
                      "背景层需以中央区域为 parent")
        self.assertIn("bg.lower()", body,
                      "背景层必须 lower 到最底, 否则被内容遮住")
        self.assertIn("bg.setGeometry(central.rect())", body,
                      "背景层需铺满中央区域")
        self.assertNotIn("addWidget(self.bg_canvas", body,
                         "背景层不应加入 layout(会被压成零高)")

    def test_background_resize_follows_window(self):
        """背景层需跟随窗口尺寸, 否则拖大窗口后右侧露出纯色。"""
        src = self._src("app.py")
        self.assertIn("class _ResizeSync", src,
                      "缺少随窗口尺寸同步背景层的过滤器")
        body = src.split("class _ResizeSync")[1].split("\n\ndef ")[0]
        self.assertIn("setGeometry", body)
        self.assertIn("QtCore.QEvent.Type.Resize", body)


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
