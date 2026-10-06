# -*- coding: utf-8 -*-
"""编程工具下载器 (Windows / Python + PySide6)

功能:
- 28 款主流编程工具,官方直链,支持选择版本
- 一键部署:下载完成后自动静默安装/解压,全程无需手动操作
- 批量部署:多选工具后一键全部部署
- 已安装检测:列表中自动标记已安装的工具
- 设置持久化:下载目录等配置自动保存
- 自动识别系统,优先 urllib 下载,CDN 屏蔽时自动切换 curl.exe
- 下载失败时引导打开官网下载页,并诊断本机 hosts 屏蔽
- 搜索/分类筛选,进度条,已用时间/预估剩余时间

界面层由 PySide6(Qt 6) 承载: 渲染、控件、布局全部使用 Qt 原生
API, 仅业务层与界面之间的交互经 ``ui_bind`` 适配, 以保持下载、
部署、批量队列等业务逻辑与视觉实现解耦。
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

from PySide6 import QtCore, QtGui, QtWidgets

import ui_bind
import ui_qt as UI
from tooldata import (
    DEPLOY_TYPES,
    load_custom_tools as _load_custom_tools,
    save_custom_tools as _save_custom_tools,
    validate_tool,
)
from tools import TOOLS, CATEGORIES

# 与原 tkinter 版本同名的入口, 统一走 Qt 实现
Var = ui_bind.Var
StringVar = ui_bind.Var
messagebox = ui_bind.messagebox
filedialog = ui_bind.filedialog

# ─────────────────────── 常量 ───────────────────────

APP_VERSION = "4.2.0"
APP_TITLE = f"编程工具下载器 v{APP_VERSION}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
CHUNK_SIZE = 128 * 1024

# 配置文件路径 (exe 旁边或用户目录)
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config.json")
CUSTOM_TOOLS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "custom_tools.json")

# ─────────────────────── 工具函数 ───────────────────────


def human_size(num):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} TB"


def human_time(seconds):
    if seconds < 0 or seconds != seconds:
        return ""
    if seconds < 60:
        return f"{int(seconds)}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def parse_cd_filename(header_text):
    m = re.search(
        r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?',
        header_text, re.IGNORECASE,
    )
    if m:
        name = urllib.parse.unquote(m.group(1).strip())
        if name:
            return os.path.basename(name.replace("\\", "/"))
    return None


def safe_filename(name):
    """净化文件名: 去除路径成分与 shell 元字符"""
    if not name:
        return "download.bin"
    name = urllib.parse.unquote(str(name))
    name = name.replace("\\", "/")
    name = os.path.basename(name)          # 去掉路径
    name = name.replace("..", "_")         # 防路径穿越
    # 只保留常见安全字符, 其余替换为下划线
    name = re.sub(r"[^A-Za-z0-9._\- \u4e00-\u9fff]", "_", name)
    name = name.strip("._") or "download.bin"
    if len(name) > 180:
        base, ext = os.path.splitext(name)
        name = base[:180 - len(ext)] + ext
    return name


def _sub_placeholder(cmd_str, placeholder, value):
    """替换命令模板占位符。

    若占位符已被引号包裹(单/双引号均可), 保持原引号只替换内容;
    否则自动补双引号, 避免路径含空格时被 shell 拆分。
    """
    for q in ('"', "'"):
        wrapped = f"{q}{placeholder}{q}"
        if wrapped in cmd_str:
            return cmd_str.replace(wrapped, f"{q}{value}{q}")
    return cmd_str.replace(placeholder, f'"{value}"')


def unique_filepath(dest_dir, filename):
    filename = safe_filename(filename)
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(dest_dir, filename)
    if not os.path.exists(candidate):
        return candidate
    i = 1
    while True:
        candidate = os.path.join(dest_dir, f"{base} ({i}){ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


def _unit_value(val, suffix):
    return int(float(val) * {"": 1, "k": 1024, "K": 1024,
                             "m": 1024 ** 2, "M": 1024 ** 2,
                             "g": 1024 ** 3, "G": 1024 ** 3}.get(suffix, 1))


CURL_PROGRESS_RE = re.compile(
    rb"^\s*(\d+(?:\.\d+)?)([kKmMgG]?)\s+(\d+)%\s+([0-9.]+)([kKmMgG]?)[bB]?/s"
)


def parse_curl_progress(line):
    m = CURL_PROGRESS_RE.match(line.strip())
    if m:
        size = _unit_value(m.group(1).decode(), m.group(2).decode())
        pct = int(m.group(3))
        speed = _unit_value(m.group(4).decode(), m.group(5).decode())
        total = size * 100 // pct if pct else 0
        return size, total, speed
    try:
        return int(line.strip()), 0, 0.0
    except ValueError:
        return None


# ─────────────────────── 配置持久化 ───────────────────────


def load_config():
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(config):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_custom_tools():
    """加载自定义工具 (过滤非法项, 兼容导出格式)"""
    return _load_custom_tools(CUSTOM_TOOLS_PATH)


def save_custom_tools(tools):
    """保存自定义工具, 返回是否成功"""
    return _save_custom_tools(tools, CUSTOM_TOOLS_PATH)


# ─────────────────────── 异常 ───────────────────────


class CancelledError(Exception):
    pass


class DownloadError(Exception):
    pass


# ─────────────────────── 部署引擎 ───────────────────────


def check_hosts_blocking(url, hosts_path=None):
    """检测本机 hosts 是否把目标域名指向回环地址。

    某些网络工具/拦截软件会把域名写进 hosts 指向 127.0.0.1,
    导致下载必然失败且 curl 只报 "000"。
    返回 (被屏蔽的域名, 指向的回环 IP) 或 None。

    hosts_path 仅供测试注入, 默认读取系统 hosts。
    """
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return None
    if not host:
        return None
    if hosts_path is None:
        hosts_path = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32", "drivers", "etc", "hosts")
    try:
        with open(hosts_path, "r",
                  encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                if parts[0] in ("127.0.0.1", "0.0.0.0", "::1",
                                "localhost"):
                    # 一行可写多个别名, 需逐个比对
                    for target in parts[1:]:
                        target = target.lower().rstrip(".")
                        if host == target or \
                                host.endswith("." + target):
                            return host, parts[0]
    except OSError:
        return None
    return None


class Deployer:
    """处理下载后的静默安装/解压"""

    @staticmethod
    def _resolve_path(path):
        path = path.replace("{user}", os.path.expanduser("~").split("\\")[-1])
        path = path.replace("{appdata}", os.environ.get("APPDATA", ""))
        return path

    @staticmethod
    def is_installed(verify_path):
        """检查工具是否已安装 (任何异常都视为未安装, 不阻断启动)"""
        try:
            if not verify_path:
                return False
            resolved = Deployer._resolve_path(str(verify_path))
            # 支持通配符路径
            if "*" in resolved:
                import glob
                return bool(glob.glob(resolved))
            return os.path.exists(resolved)
        except Exception:
            return False

    @staticmethod
    def run_install(file_path, deploy_config):
        deploy_type = deploy_config.get("type", "none")
        if deploy_type == "none":
            return True, "已下载(需手动安装)"

        try:
            need_admin = bool(deploy_config.get("need_admin"))
            if deploy_type == "msi":
                ok, msg = Deployer._install_msi(file_path, need_admin)
            elif deploy_type == "exe":
                ok, msg = Deployer._install_exe(file_path, deploy_config)
            elif deploy_type == "extract":
                ok, msg = Deployer._install_extract(file_path)
            elif deploy_type == "custom":
                ok, msg = Deployer._install_custom(file_path, deploy_config)
            else:
                return False, f"不支持的安装方式: {deploy_type}"

            # 安装后验证
            if ok:
                verify = deploy_config.get("verify")
                if verify and not Deployer.is_installed(verify):
                    return True, f"{msg}(注意: 未找到安装路径,请手动确认)"
            return ok, msg
        except Exception as e:
            return False, f"安装出错: {e}"

    @staticmethod
    def _run_elevated(cmd, timeout):
        """以管理员身份运行命令, 回传子进程真实退出码。

        用 PowerShell -EncodedCommand 传递, 避免路径/参数被 shell 解析。
        -PassThru + exit $p.ExitCode 是必要的: Start-Process -Wait
        不会把退出码带回, 直接判断会恒为 0 导致失败被误报成功。
        """
        arg_str = " ".join(f'"{a}"' for a in cmd[1:])
        q = chr(39)
        inner = (
            "$ErrorActionPreference = 'Stop'; "
            f"$p = Start-Process -FilePath '{cmd[0].replace(q, q * 2)}' "
            f"-ArgumentList '{arg_str.replace(q, q * 2)}' "
            "-Verb RunAs -PassThru -Wait -WindowStyle Hidden; "
            "if ($null -eq $p) { exit 1 }; "
            "exit $p.ExitCode"
        )
        encoded = base64.b64encode(
            inner.encode("utf-16-le")).decode("ascii")
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    @staticmethod
    def _install_msi(file_path, need_admin=False):
        cmd = ["msiexec.exe", "/quiet", "/norestart", "/i", file_path]
        # 装到 C:\Program Files 的 msi 必须提权, 否则 msiexec
        # 返回 1603/1925 权限错误
        if need_admin:
            proc = Deployer._run_elevated(cmd, timeout=1800)
        else:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=600,
                creationflags=getattr(
                    subprocess, "CREATE_NO_WINDOW", 0),
            )
        # 3010 = 安装成功但需重启
        if proc.returncode in (0, 3010):
            return True, "安装成功"
        if need_admin and proc.returncode != 0:
            return False, (f"MSI 安装失败(退出码 {proc.returncode})。"
                           f"若为权限问题, 请以管理员身份运行本程序")
        return False, f"MSI 安装失败(退出码 {proc.returncode})"

    @staticmethod
    def _install_exe(file_path, config):
        args = config.get("args", "/S")
        cmd = [file_path] + args.split()
        need_admin = config.get("need_admin", False)

        if need_admin:
            proc = Deployer._run_elevated(cmd, timeout=1800)
        else:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=1800,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

        if proc.returncode == 0:
            return True, "安装成功"
        return False, f"安装失败(退出码 {proc.returncode})"

    @staticmethod
    def _install_extract(file_path):
        # 用标准库解压, 避免 shell 拼接
        import zipfile
        dest_dir = os.path.dirname(file_path)
        name = os.path.splitext(os.path.basename(file_path))[0]
        extract_dir = os.path.join(dest_dir, name)
        try:
            if not zipfile.is_zipfile(file_path):
                return False, "文件不是有效的 zip 压缩包"
            # 解压总量上限, 防 zip bomb 撑爆磁盘
            max_total = 20 * 1024 ** 3
            with zipfile.ZipFile(file_path) as zf:
                # 先全量校验(路径穿越 + 总量), 全部通过才建目录,
                # 避免校验失败时留下空目录
                total = 0
                for info in zf.infolist():
                    target = os.path.realpath(
                        os.path.join(extract_dir, info.filename))
                    if not target.startswith(
                            os.path.realpath(extract_dir)
                            + os.sep):
                        return False, "压缩包包含非法路径"
                    total += info.file_size
                    if total > max_total:
                        return False, "压缩包解压后超出大小上限"
                os.makedirs(extract_dir, exist_ok=True)
                for info in zf.infolist():
                    zf.extract(info, extract_dir)
            return True, f"解压成功 → {extract_dir}"
        except (zipfile.BadZipFile, OSError) as e:
            return False, f"解压失败: {e}"

    @staticmethod
    def _install_custom(file_path, config):
        cmd_template = config.get("cmd", "")
        if not cmd_template:
            return False, "缺少自定义安装命令"
        # file_path 已由 unique_filepath/safe_filename 净化,
        # 不可再次 safe_filename (会把 "xxx (1).exe" 的括号
        # 换成下划线, 指向不存在的文件)
        full_path = file_path
        cmd_str = _sub_placeholder(cmd_template, "{file}", full_path)
        cmd_str = _sub_placeholder(
            cmd_str, "{user}",
            os.path.expanduser("~").split("\\")[-1])
        cmd_str = _sub_placeholder(
            cmd_str, "{appdata}", os.environ.get("APPDATA", ""))
        proc = subprocess.run(
            cmd_str, shell=True, capture_output=True, timeout=1800,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode == 0:
            return True, "安装成功"
        return False, f"安装失败(退出码 {proc.returncode})"


# ─────────────────────── 下载器 ───────────────────────


class ToolDownloader:
    # 已知拒绝 urllib TLS 指纹的站点 (中国 CDN 按 UA/指纹返回 404)
    CURL_PREFERRED_HOSTS = (
        "download.jetbrains.com",
        "desktop.docker.com",
        "storage.googleapis.com",
        "services.gradle.org",
    )

    def __init__(self, url, dest_dir, cancel_event,
                 on_progress=None, on_done=None):
        self.url = url
        self.dest_dir = dest_dir
        self.cancel_event = cancel_event
        self.on_progress = on_progress
        self.on_done = on_done
        self.filename = None
        self.prefer_curl = self._needs_curl(url)

    @classmethod
    def _needs_curl(cls, url):
        try:
            host = urllib.parse.urlparse(url).hostname or ""
        except Exception:
            return False
        # 要求精确域名或子域名, 避免 evildownload.jetbrains.com
        # 这类同后缀域名误命中
        host = host.lower().rstrip(".")
        return any(host == h or host.endswith("." + h)
                   for h in cls.CURL_PREFERRED_HOSTS)

    def _download_urllib(self):
        req = urllib.request.Request(
            self.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            cd = resp.headers.get("Content-Disposition", "")
            name = parse_cd_filename(cd)
            if not name:
                name = os.path.basename(
                    urllib.parse.unquote(
                        urllib.parse.urlparse(self.url).path))
            self.filename = name or "download.bin"
            path = unique_filepath(self.dest_dir, self.filename)

            downloaded = 0
            last_t, last_b = time.time(), 0
            if self.on_progress:
                self.on_progress(0, total, 0.0)

            with open(path, "wb") as f:
                while True:
                    if self.cancel_event.is_set():
                        raise CancelledError()
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if now - last_t >= 0.2:
                        speed = (downloaded - last_b) / (now - last_t)
                        last_t, last_b = now, downloaded
                        if self.on_progress:
                            self.on_progress(downloaded, total, speed)
            return path

    def _download_curl(self):
        tmp = os.path.join(self.dest_dir, ".partial_download")
        if os.path.exists(tmp):
            os.remove(tmp)
        header_file = os.path.join(self.dest_dir, ".partial_headers")
        cmd = [
            "curl.exe", "-L", "--fail", "-sS",
            "--connect-timeout", "30",
            "-#", "-D", header_file, "-o", tmp,
            "-w", "%{url_effective}", self.url,
        ]
        # prefer_curl 站点: CDN 会拒绝「非浏览器 TLS 指纹 +
        # 浏览器 UA」的组合(返回 404), 此时不自定义 UA
        if not self.prefer_curl:
            cmd[3:3] = ["-A", USER_AGENT]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def monitor():
            while True:
                chunk = proc.stderr.read(4096)
                if not chunk:
                    break
                for line in chunk.split(b"\r"):
                    parsed = parse_curl_progress(line)
                    if parsed and self.on_progress:
                        self.on_progress(*parsed)

        mt = threading.Thread(target=monitor, daemon=True)
        mt.start()

        while proc.poll() is None:
            if self.cancel_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            time.sleep(0.1)

        final_url = b""
        if proc.stdout:
            final_url = proc.stdout.read().strip()
        mt.join(timeout=1)

        if proc.returncode != 0 or not os.path.exists(tmp):
            for f in (tmp, header_file):
                if os.path.exists(f):
                    os.remove(f)
            raise DownloadError(
                f"curl 下载失败(退出码 {proc.returncode})")

        final_url = final_url.decode("utf-8", "ignore")
        filename = None
        try:
            with open(header_file, "r", encoding="utf-8",
                      errors="ignore") as hf:
                filename = parse_cd_filename(hf.read())
        except OSError:
            pass
        if not filename and final_url:
            filename = safe_filename(
                urllib.parse.urlparse(final_url).path)
        if not filename:
            filename = safe_filename(
                urllib.parse.urlparse(self.url).path)
        self.filename = safe_filename(filename)

        final_path = unique_filepath(self.dest_dir, self.filename)
        if os.path.abspath(tmp) != os.path.abspath(final_path):
            if os.path.exists(final_path):
                os.remove(final_path)
            os.rename(tmp, final_path)
        if os.path.exists(header_file):
            os.remove(header_file)
        return final_path

    def run(self):
        # 已知拒绝 urllib 的站点直接走 curl, 省去一次必然失败的尝试
        if self.prefer_curl and shutil.which("curl.exe"):
            self._run_with_fallback(
                urllib_err="该站点要求 curl 模式")
            return
        try:
            path = self._download_urllib()
            if self.on_done:
                self.on_done(True, "下载完成", path)
        except CancelledError:
            if self.on_done:
                self.on_done(False, "已取消下载", None)
        except Exception as urllib_err:
            if self.cancel_event.is_set():
                if self.on_done:
                    self.on_done(False, "已取消下载", None)
                return
            self._run_with_fallback(urllib_err=urllib_err)

    def _run_with_fallback(self, urllib_err):
        """urllib 不可用时降级 curl"""
        if not shutil.which("curl.exe"):
            if self.on_done:
                self.on_done(
                    False, f"下载失败: {urllib_err}", None)
            return
        try:
            if self.on_progress:
                self.on_progress(0, 0, 0.0)
            path = self._download_curl()
            if self.on_done:
                self.on_done(
                    True, "下载完成 (curl 模式)", path)
        except Exception as curl_err:
            if self.cancel_event.is_set():
                if self.on_done:
                    self.on_done(False, "已取消下载", None)
            elif self.on_done:
                detail = str(curl_err) or str(urllib_err)
                self.on_done(
                    False, f"下载失败: {detail}", None)


# ─────────────────────── 应用主窗口 ───────────────────────


class App:
    def __init__(self, root):
        self.root = root
        self.cancel_event = threading.Event()
        self.downloader = None
        self.download_thread = None
        self.current_tool = None
        self.current_versions = []
        # 任务快照: 下载/安装期间不受用户点击改选影响
        self._active_tool = None
        self._active_version = None
        # 任务阶段: idle/downloading/installing/retry_wait/batch_gap
        self._task_phase = "idle"
        # 任务世代号: 取消/新任务时自增, 作废旧线程的迟到回调
        self._task_seq = 0
        self._closing = False          # 窗口关闭中标志
        self._pending_after_id = None
        self._status_restore_id = None  # 复制 URL 的状态栏恢复
        self.current_category = "全部"
        self.download_start_time = 0.0
        self._last_file_path = None
        self._deploy_mode = False
        self._batch_queue = []      # 批量部署队列
        self._batch_index = 0
        self._batch_success = 0     # 批量成功计数
        self._batch_versions = {}   # 批量任务的版本映射
        self._retry_count = 0       # 自动重试计数
        self._max_retries = 2       # 最大自动重试次数
        self._config = load_config()

        root.title(APP_TITLE)
        root.minsize(1000, 700)
        # Qt 主窗口句柄: UI 构建阶段需要真实 QWidget 作为 parent
        self._qwin = root._w if isinstance(root, ui_bind.RootShim) \
            else root
        self._set_icon(root)
        self._init_theme(root)
        self._build_background(self._qwin)
        self._apply_ttk_styles()

        default_dir = self._config.get(
            "save_dir",
            os.path.join(os.path.expanduser("~"), "Downloads"))

        self._build_top()
        self._build_main()
        self._build_bottom()
        self._assemble()
        # Var 需在控件建好后再绑定文本
        self.save_dir.set(default_dir)

        # 加载自定义工具
        custom = load_custom_tools()
        for ct in custom:
            if not any(x.get("name") == ct.get("name")
                       for x in TOOLS):
                TOOLS.append(ct)

        # 先建 _installed 缓存再渲染, 避免首屏先显示"未安装"
        # 随后又重绘一次的闪烁
        self.load_category()
        self._refresh_installed()
        self._log(f"[{time.strftime('%H:%M:%S')}] "
                  f"程序启动, {len(TOOLS)} 个工具可用")

        self._bind_shortcuts()

    def _assemble(self):
        """把三个区域按上/中/下顺序放进主窗口布局。

        背景层不加入 layout: QVBoxLayout 会按sizeHint 分配空间, 而
        背景层的 sizeHint 为 -1, 会被压成零高度(实测 bg 高度 0, 光晕
        完全不显示)。改为以中央区域为 parent、用绝对几何铺满, 由
        _ResizeSync 在尺寸变化时同步。
        """
        win = self._qwin
        central = QtWidgets.QWidget(win)
        lay = QtWidgets.QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 背景层: 先入中央区域, 再置于底层
        bg = self.bg_canvas
        # setParent 会隐式隐藏子控件, 必须显式 show(), 否则整块光晕
        # 背景不显示(本次迁移的核心视觉目标)
        bg.setParent(central)
        bg.setGeometry(central.rect())
        bg.lower()
        bg.show()

        lay.addWidget(self._top_wrap)
        lay.addWidget(self._main_pane, 1)
        lay.addWidget(self._bottom_wrap)
        win.setCentralWidget(central)

        self._resize_filter = _ResizeSync(self)
        central.installEventFilter(self._resize_filter)
        bg.refresh()

    # ──────────── 快捷键 ────────────

    def _bind_shortcuts(self):
        """键盘快捷键(替代 tkinter bind)"""
        def sc(seq, fn):
            s = QtGui.QShortcut(QtGui.QKeySequence(seq), self._qwin)
            s.activated.connect(fn)

        sc("Ctrl+F", lambda: self.search_entry.setFocus())
        sc("Esc", lambda: self.cancel_download()
           if "disabled" not in self.cancel_btn.state() else None)
        sc("Ctrl+O", lambda: self.open_folder())
        sc("Ctrl+E", lambda: self._export_tools())
        sc("Ctrl+I", lambda: self._import_tools())
        sc("Ctrl+B", lambda: self.start_batch_deploy())
        sc("Ctrl+Return", lambda: self._on_global_return())
        # 关闭时保存配置并置_closing(closeEvent 非信号, 须用事件过滤器)
        self._close_guard = _CloseGuard(self)
        self._qwin.installEventFilter(self._close_guard)
        # ↑↓ 仅在工具列表获得焦点时移动选择
        for key, delta in (("Up", -1), ("Down", 1)):
            s = QtGui.QShortcut(QtGui.QKeySequence(key), self.tool_view)
            s.setContext(QtCore.Qt.ShortcutContext.WidgetShortcut)
            s.activated.connect(
                lambda d=delta: self._move_selection(d))

    def _on_global_return(self, event=None):
        """全局回车: 仅焦点在工具列表时触发一键部署"""
        try:
            if self.root.focus_get() is not self.tool_view:
                return None
        except Exception:
            return None
        self.start_deploy()
        return "break"

    def _switch_category_by_index(self, idx):
        """Ctrl+数字 快速切换分类"""
        cats = list(self.cat_tree.get_children())
        if 0 <= idx < len(cats):
            self.cat_tree.selection_set(cats[idx])
            self._on_category_select(None)

    def _on_search_return(self, _event=None):
        """搜索框回车: 下载并阻止冒泡到全局绑定"""
        self.start_download()
        return "break"

    @staticmethod
    def _set_icon(root):
        try:
            icon_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "app_icon.ico")
            if os.path.exists(icon_path):
                root.iconbitmap(icon_path)
        except Exception:
            pass

    # ──────────── 主题 / 视觉 ────────────

    def _init_theme(self, root):
        """初始化液态玻璃主题: 字体、配色、全局样式表"""
        self._pal = UI.PAL
        self._fonts = UI.load_fonts()
        self._bg_pending = None
        self._panels = []

    def _build_background(self, root):
        """铺设 Qt 绘制的渐变光晕背景层。

        Tk 版靠 Pillow 逐像素合成(因 Tk 不支持 backdrop-filter);
        Qt 版直接用 ``QPainter`` 画径向光晕, 由引擎负责合成,
        并随窗口尺寸变化重绘。
        """
        self.bg_canvas = UI.BackgroundWidget(root)
        self.bg_canvas.show()
        self.bg_canvas.lower()
        self.root.after(80, self._refresh_background)
        return self.bg_canvas

    def _on_root_resize(self, event=None):
        # Qt 版背景由 BackgroundWidget.resizeEvent 自行重绘,
        # 此处保留空实现以兼容旧调用点。
        pass

    def _refresh_background(self):
        bg = getattr(self, "bg_canvas", None)
        if bg is not None and not self._closing:
            bg.refresh()

    def _glass(self, master, radius=18, shadow=True):
        """构造玻璃卡片(QSS 半透明 + QGraphicsDropShadowEffect)

        ``shadow=False`` 用于嵌套卡片(内层不挂特效, 避免重影)。
        """
        p = UI.GlassCard(master, radius=radius, shadow=shadow)
        self._panels.append(p)
        return p

    def _apply_ttk_styles(self):
        """安装全局 QSS 样式表(Qt 版对应原 ttk 定制)"""
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.setStyleSheet(UI.build_qss(self._fonts))

    def _btn(self, master, text, command, width=104, height=34,
             accent=False):
        """快捷构造玻璃按钮(返回 ui_bind.Button 以兼容 state/set_state)

        ``master`` 可以是 QWidget、Qt 布局对象或 None —— 后两者不作为
        parent, 按钮改由调用方加入布局。
        """
        parent = master if isinstance(master, QtWidgets.QWidget) else None
        b = UI.GradientButton(text, parent, accent=accent)
        b.setMinimumWidth(int(width))
        b.setMinimumHeight(int(height))
        b.clicked.connect(command)
        return ui_bind.Button(b)

    def _status_sub(self):
        """标题下方的副标题(工具总数与分类数)"""
        try:
            n_tool = len(TOOLS)
            n_cat = len([c for c in CATEGORIES])
            n_ver = sum(len(t.get("versions", [])) for t in TOOLS)
            return (f"{n_tool} 款工具 · {n_ver} 条官方直链 · "
                    f"{n_cat} 个分类")
        except Exception:
            return ""

    def _label(self, master, text="", style="Glass.TLabel", **kw):
        """标签: ``style`` 保留旧调用点签名, 由 QSS 统一控制外观。"""
        lab = QtWidgets.QLabel(str(text), master)
        lab.setFont(self._fonts["ui"])
        anchor = kw.get("anchor")
        if anchor:
            amap = {"w": QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                    "e": QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                    "center": QtCore.Qt.AlignCenter}
            lab.setAlignment(amap.get(anchor, amap["w"]))
        if kw.get("width"):
            lab.setFixedWidth(int(kw["width"]))
        if kw.get("takefocus") == 0:
            lab.setFocusPolicy(QtCore.Qt.NoFocus)
        if kw.get("justify"):
            lab.setWordWrap(True)
        if kw.get("cursor"):
            lab.setCursor(QtCore.Qt.PointingHandCursor)
        return lab

    # ──────────── 界面 ────────────

    def _build_top(self):
        wrap = QtWidgets.QWidget(self._qwin)
        lay = QtWidgets.QVBoxLayout(wrap)
        lay.setContentsMargins(18, 16, 18, 0)
        lay.setSpacing(10)

        # ── 标题区
        head = QtWidgets.QWidget(wrap)
        head_lay = QtWidgets.QHBoxLayout(head)
        head_lay.setContentsMargins(4, 0, 4, 0)

        title_box = QtWidgets.QVBoxLayout()
        title_box.setSpacing(0)
        t1 = QtWidgets.QLabel(APP_TITLE.split(" v")[0])
        t1.setFont(self._fonts["size"])
        t2 = QtWidgets.QLabel(self._status_sub())
        t2.setFont(self._fonts["ui"])
        t2.setStyleSheet(f"color: {self._pal.SUBTEXT};")
        title_box.addWidget(t1)
        title_box.addWidget(t2)
        head_lay.addLayout(title_box)
        head_lay.addStretch(1)

        # 右侧工具按钮组
        for text, cmd, w in (
                ("导入工具", self._import_tools, 92),
                ("导出列表", self._export_tools, 92),
                ("刷新状态",
                 lambda: self._refresh_installed(update_status=True), 92)):
            b = self._btn(head, text, cmd, width=w, height=32)
            head_lay.addWidget(b.w)
            head_lay.addSpacing(8)
        lay.addWidget(head)

        # ── 搜索 + 排序 + 保存目录
        bar = self._glass(wrap, radius=16)
        bar_lay = QtWidgets.QVBoxLayout(bar)
        bar_lay.setContentsMargins(16, 12, 16, 12)
        bar_lay.setSpacing(10)

        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(10)
        row1.addWidget(self._label(bar, "搜索"))
        self.search_entry = QtWidgets.QLineEdit(bar)
        self.search_entry.setFont(self._fonts["ui"])
        self.search_entry.setPlaceholderText("工具名 / 版本 / 说明…")
        self.search_entry.returnPressed.connect(self._on_search_return)
        row1.addWidget(self.search_entry, 1)
        self.keyword = Var(self.search_entry, "")
        self.keyword.trace_add(
            "write", lambda *_: self.filter_tools())

        row1.addWidget(self._label(bar, "排序"))
        sort_combo = QtWidgets.QComboBox(bar)
        sort_combo.addItems(["默认", "名称 A-Z", "名称 Z-A", "分类"])
        sort_combo.setFont(self._fonts["ui"])
        # 排序值直接从控件读取。若沿用游离 Var, 必须在回调里显式回写,
        # 否则 filter_tools 读到的永远是初始值, 三种排序全部失效。
        sort_combo.currentIndexChanged.connect(
            lambda _i: self.filter_tools())
        self._sort_combo = sort_combo
        row1.addWidget(sort_combo)
        bar_lay.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(self._label(bar, "保存到"))
        self.dir_entry = QtWidgets.QLineEdit(bar)
        self.dir_entry.setFont(self._fonts["mono"])
        row2.addWidget(self.dir_entry, 1)
        self.save_dir = Var(self.dir_entry, "")
        row2.addWidget(self._btn(bar, "浏览…", self._browse_dir,
                                  width=88, height=32).w)
        bar_lay.addLayout(row2)

        self._top_wrap = wrap

    def _build_main(self):
        pane = QtWidgets.QWidget(self._qwin)
        pane_lay = QtWidgets.QHBoxLayout(pane)
        pane_lay.setContentsMargins(18, 14, 18, 0)
        pane_lay.setSpacing(14)

        # ── 左: 分类(玻璃侧栏)
        left = self._glass(pane, radius=18)
        left_lay = QtWidgets.QVBoxLayout(left)
        left_lay.setContentsMargins(UI.PAD, UI.PAD, UI.PAD, UI.PAD)
        left_lay.setSpacing(8)
        left_lay.addWidget(self._label(left, "分类"))

        self.cat_view = QtWidgets.QTreeWidget(left)
        self.cat_view.setFont(self._fonts["ui"])
        self.cat_view.setRootIsDecorated(False)
        self.cat_tree = ui_bind.TreeShim(
            self.cat_view, columns=("cat", "cnt"))
        self.cat_tree.heading("cat", text="名称")
        self.cat_tree.heading("cnt", text="数量")
        self.cat_tree.column("cat", width=148, anchor="w", stretch=True)
        self.cat_tree.column("cnt", width=46, anchor="e", stretch=False)
        self.cat_tree.bind("<<TreeviewSelect>>", self._on_category_select)
        left_lay.addWidget(self.cat_view)

        hint = QtWidgets.QLabel("Ctrl+数字 快速切换\n双击工具 开始下载")
        hint.setFont(self._fonts["ui"])
        hint.setStyleSheet(f"color: {self._pal.SUBTEXT};")
        hint.setWordWrap(True)
        left_lay.addWidget(hint)
        left_lay.addStretch(1)
        pane_lay.addWidget(left, 0)

        # ── 右: 工具列表
        right = self._glass(pane, radius=18)
        right_lay = QtWidgets.QVBoxLayout(right)
        right_lay.setContentsMargins(UI.PAD, UI.PAD, UI.PAD, UI.PAD)

        self.tool_view = QtWidgets.QTreeWidget(right)
        self.tool_view.setFont(self._fonts["ui"])
        self.tool_tree = ui_bind.TreeShim(
            self.tool_view,
            columns=("name", "ver", "desc", "inst"),
            selectmode="extended")
        # 列宽必须在 TreeShim 之后设置: 其 __init__ 会 setColumnCount
        # 重建表头, 把此前的列宽设定全部清掉。
        header = self.tool_view.header()
        # 关键: 必须关掉 stretchLastSection。它默认为 True, 会与下面
        # 为"说明"列设的 Stretch 叠加, 导致实际列宽被重算成均分
        # (实测设定 196/132/86 却得到 196/132/237/237)。
        # 且 Fixed 模式下要用 resizeSection, setColumnWidth 会被忽略。
        header.setStretchLastSection(False)
        for idx, width in ((0, 196), (1, 132), (3, 86)):
            header.setSectionResizeMode(
                idx, QtWidgets.QHeaderView.Fixed)
            header.resizeSection(idx, width)
        # 说明列占满剩余空间
        header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.Stretch)
        header.setDefaultAlignment(
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.tool_tree.heading("name", text="工具")
        self.tool_tree.heading("ver", text="版本")
        self.tool_tree.heading("desc", text="说明")
        self.tool_tree.heading("inst", text="状态")
        self.tool_tree.bind("<<TreeviewSelect>>", self._on_tool_select)
        self.tool_tree.bind("<Double-1>", lambda _e: self.start_download())
        self.tool_tree.bind("<Button-3>", self._show_context_menu)
        right_lay.addWidget(self.tool_view)
        pane_lay.addWidget(right, 1)

        self._main_pane = pane

    def _show_context_menu(self, event):
        """工具列表右键菜单"""
        iid = self.tool_tree.identify_row(event.y)
        if not iid:
            return
        self.tool_tree.selection_set(iid)
        self._on_tool_select(None)

        tool = self._find_tool_by_iid(iid)
        if not tool:
            return

        # 复用菜单对象, 避免每次右键创建新 widget 导致泄漏
        if getattr(self, "_ctx_menu", None) is not None:
            try:
                self._ctx_menu.destroy()
            except Exception:
                pass
        menu = QtWidgets.QMenu(self._qwin)
        self._ctx_menu = menu

        menu.addAction("一键部署", self.start_deploy)
        menu.addAction("仅下载", self.start_download)
        menu.addSeparator()

        url = (self.current_versions[0]["url"]
               if self.current_versions else "")
        if url:
            menu.addAction(
                "复制下载链接", lambda: self._copy_text(url))

        homepage = tool.get("homepage")
        if homepage:
            menu.addAction(
                "打开官网下载页", lambda: webbrowser.open(homepage))

        menu.addSeparator()
        menu.addAction("查看详情", lambda: self._show_tool_detail(tool))
        menu.addAction("打开保存目录", self.open_folder)

        # 延迟弹出: 当前调用发生在 _MouseFilter.eventFilter 内(事件
        # 过滤回调), 在事件过滤器里 exec() 会开启嵌套事件循环, 期间
        # 再次右键会重入本函数并销毁正在 exec() 的菜单, 导致崩溃。
        pos = QtGui.QCursor.pos()
        self.root.after(0, lambda: self._exec_menu(menu, pos))

    @staticmethod
    def _exec_menu(menu, pos):
        try:
            menu.exec(pos)
        except RuntimeError:
            pass        # 窗口已销毁
        finally:
            menu.deleteLater()

    def _copy_text(self, text):
        QtWidgets.QApplication.clipboard().setText(text)
        ts = time.strftime("%H:%M:%S")
        self._log(f"[{ts}] 已复制: {text[:60]}...")

    def _export_tools(self):
        """导出工具列表为 JSON"""
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json"),
                       ("所有文件", "*.*")],
            initialfile="编程工具列表.json")
        if not path:
            return
        try:
            # 过滤下划线开头的运行时内部字段(如 _installed)
            clean = [{k: v for k, v in t.items()
                      if not k.startswith("_")}
                     for t in TOOLS]
            export_data = {
                "version": APP_VERSION,
                "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "tools": clean,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_data, f,
                          ensure_ascii=False, indent=2)
            ts = time.strftime("%H:%M:%S")
            self._log(f"[{ts}] 工具列表已导出: {path}")
            messagebox.showinfo(
                "导出成功",
                f"已导出 {len(clean)} 个工具到:\n{path}")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {e}")

    def _import_tools(self):
        """导入自定义工具 (JSON 格式)"""
        path = filedialog.askopenfilename(
            filetypes=[("JSON 文件", "*.json"),
                       ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 支持两种格式: 直接数组 或 {tools: [...]}
            if isinstance(data, list):
                new_tools = data
            elif isinstance(data, dict) and "tools" in data:
                new_tools = data["tools"]
            else:
                messagebox.showerror(
                    "错误",
                    "格式不正确: 需要工具数组或 {\"tools\": [...]}")
                return

            # 强校验
            valid = []
            rejected = 0
            for t in new_tools:
                clean = validate_tool(t)
                if clean:
                    valid.append(clean)
                else:
                    rejected += 1

            if not valid:
                messagebox.showerror(
                    "错误",
                    "没有找到有效的工具定义"
                    + (f"\n({rejected} 项未通过校验)"
                       if rejected else ""))
                return

            # 加载已有的自定义工具
            existing = load_custom_tools()
            existing_names = {t.get("name") for t in existing}

            added = 0
            for t in valid:
                if t["name"] not in existing_names:
                    existing.append(t)
                    added += 1

            # 落盘失败须明确告知, 否则用户重启后工具全部消失
            if not save_custom_tools(existing):
                messagebox.showerror(
                    "保存失败",
                    f"无法写入 {CUSTOM_TOOLS_PATH}\n"
                    "请检查文件权限或磁盘空间。\n"
                    "本次导入的工具在关闭程序后将丢失。")
                return

            # 合并到 TOOLS
            for t in existing:
                if not any(x.get("name") == t["name"]
                           for x in TOOLS):
                    TOOLS.append(t)

            self.load_category()
            self.filter_tools()
            self._refresh_installed()

            ts = time.strftime("%H:%M:%S")
            self._log(f"[{ts}] 导入 {added} 个自定义工具")
            messagebox.showinfo(
                "导入成功",
                f"新增 {added} 个工具, "
                f"跳过 {len(valid) - added} 个重复项")
        except json.JSONDecodeError as e:
            messagebox.showerror(
                "错误", f"JSON 解析失败: {e}")
        except OSError as e:
            messagebox.showerror("错误", f"读取失败: {e}")

    def _show_tool_detail(self, tool):
        """显示工具详情对话框"""
        lines = [
            f"工具: {tool['name']}",
            f"分类: {tool['category']}",
            f"说明: {tool['description']}",
            "",
            "可用版本:",
        ]
        for v in tool["versions"]:
            lines.append(f"  • {v['label']}")
            lines.append(f"    {v['url']}")

        deploy = tool.get("deploy", {})
        lines.append("")
        lines.append(f"安装方式: {deploy.get('type', 'N/A')}")
        if deploy.get("verify"):
            lines.append(f"安装路径: {deploy['verify']}")
        if tool.get("homepage"):
            lines.append(f"官网: {tool['homepage']}")

        verify = deploy.get("verify", "")
        installed = Deployer.is_installed(verify)
        lines.append(f"状态: {'✓ 已安装' if installed else '未安装'}")

        messagebox.showinfo(
            f"详情 - {tool['name']}", "\n".join(lines))

    def _build_bottom(self):
        bottom = QtWidgets.QWidget(self._qwin)
        outer = QtWidgets.QVBoxLayout(bottom)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(12)

        # ── 上: 状态 + 进度
        prog_card = self._glass(bottom, radius=18)
        prog_lay = QtWidgets.QVBoxLayout(prog_card)
        prog_lay.setContentsMargins(18, 13, 18, 13)
        prog_lay.setSpacing(6)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        self.status_label = QtWidgets.QLabel(
            "就绪 — 双击工具即可开始下载")
        self.status_label.setFont(self._fonts["ui"])
        self.status = Var(self.status_label,
                          "就绪 — 双击工具即可开始下载")
        row.addWidget(self.status_label, 1)

        self._prog_widget = UI.GradientProgressBar(prog_card)
        self.progress = ui_bind.ProgressShim(self._prog_widget)
        self._prog_widget.setFixedWidth(180)
        row.addWidget(self._prog_widget)

        self.progress_label = QtWidgets.QLabel("")
        self.progress_label.setFont(self._fonts["mono"])
        self.progress_label.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.progress_label.setMinimumWidth(240)
        row.addWidget(self.progress_label)
        prog_lay.addLayout(row)

        # URL 单独一行, 避免长链接挤压进度条
        self.url_label = QtWidgets.QLabel("")
        self.url_label.setFont(self._fonts["mono"])
        self.url_label.setStyleSheet(f"color: {self._pal.FAINT};")
        self.url_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
            | QtCore.Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.url_label.setCursor(QtCore.Qt.PointingHandCursor)
        self.url_var = Var(self.url_label, "")
        # 点击 URL 复制到剪贴板(旧版有此交互, 迁移时若遗漏 _copy_url
        # 会变成死代码)。QLabel 默认不转发鼠标事件, 需显式安装过滤器。
        self._url_click_filter = _UrlClick(self)
        self.url_label.installEventFilter(self._url_click_filter)
        prog_lay.addWidget(self.url_label)
        outer.addWidget(prog_card)

        # ── 下: 操作区 + 日志
        act = self._glass(bottom, radius=18)
        act_lay = QtWidgets.QHBoxLayout(act)
        act_lay.setContentsMargins(16, 12, 16, 12)
        act_lay.setSpacing(16)

        left_col = QtWidgets.QVBoxLayout()
        left_col.setSpacing(10)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(8)
        ver_lbl = QtWidgets.QLabel("版本")
        ver_lbl.setFont(self._fonts["ui"])
        btn_row.addWidget(ver_lbl)

        _version_combo = QtWidgets.QComboBox()
        _version_combo.setFont(self._fonts["ui"])
        _version_combo.setMinimumWidth(150)
        # 对外暴露 shim: 业务侧沿用 ttk Combobox 写法
        self.version_combo = ui_bind.ComboShim(_version_combo)
        btn_row.addWidget(_version_combo)

        self.deploy_btn = self._btn(
            None, "一键部署", self.start_deploy,
            width=108, height=32, accent=True)
        btn_row.addWidget(self.deploy_btn.w)

        self.batch_btn = self._btn(
            None, "批量部署", self.start_batch_deploy,
            width=98, height=32)
        btn_row.addWidget(self.batch_btn.w)

        self.download_btn = self._btn(
            None, "仅下载", self.start_download, width=88, height=32)
        btn_row.addWidget(self.download_btn.w)

        self.retry_btn = self._btn(
            None, "重试", self._retry_current, width=78, height=32)
        btn_row.addWidget(self.retry_btn.w)
        self.retry_btn.w.setVisible(False)   # 失败后才显示

        self.cancel_btn = self._btn(
            None, "取消", self.cancel_download, width=78, height=32)
        btn_row.addWidget(self.cancel_btn.w)
        self.cancel_btn.set_state("disabled")
        left_col.addLayout(btn_row)
        left_col.addStretch(1)
        act_lay.addLayout(left_col, 0)

        # 日志卡片
        log_card = UI.GlassCard(act, radius=14, shadow=False)
        log_lay = QtWidgets.QVBoxLayout(log_card)
        log_lay.setContentsMargins(12, 8, 12, 10)
        log_lay.setSpacing(6)

        log_top = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel("部署日志")
        lbl.setFont(self._fonts["ui"])
        lbl.setStyleSheet(f"color: {self._pal.SUBTEXT};")
        log_top.addWidget(lbl)
        log_top.addStretch(1)
        b_clear = self._btn(log_top, "清空", self._clear_log,
                            width=58, height=24)
        log_top.addWidget(b_clear.w, 0, QtCore.Qt.AlignTop)
        b_exp = self._btn(log_top, "导出", self._export_log,
                          width=58, height=24)
        log_top.addWidget(b_exp.w, 0, QtCore.Qt.AlignTop)
        log_lay.addLayout(log_top)

        self._log_widget = QtWidgets.QPlainTextEdit(log_card)
        self._log_widget.setFont(self._fonts["mono"])
        self._log_widget.setReadOnly(True)
        self._log_widget.setFixedHeight(84)
        self._log_widget.setStyleSheet(
            f"QPlainTextEdit {{ background: {self._pal.LOG_BG};"
            f" color: {self._pal.LOG_FG};"
            " border: 1px solid rgba(255,255,255,26);"
            " border-radius: 8px; }")
        self.log_text = ui_bind.TextShim(self._log_widget)
        log_lay.addWidget(self._log_widget)
        act_lay.addWidget(log_card, 1)
        outer.addWidget(act)

        # ── 页脚
        foot = QtWidgets.QHBoxLayout()
        foot_lbl = QtWidgets.QLabel(
            "界面由 PySide6 (Qt 6) 渲染 · 核心功能仅依赖标准库")
        foot_lbl.setFont(self._fonts["ui"])
        foot_lbl.setStyleSheet(f"color: {self._pal.FAINT};")
        foot.addWidget(foot_lbl)
        foot.addStretch(1)
        foot.addWidget(self._btn(
            foot, "打开下载目录", self.open_folder,
            width=118, height=26).w)
        foot.addSpacing(8)
        foot.addWidget(self._btn(
            foot, "关于", self._show_about, width=72, height=26).w)
        outer.addLayout(foot)

        self._bottom_wrap = bottom

    # ──────────── 分类 ────────────

    def load_category(self):
        self.cat_tree.delete(*self.cat_tree.get_children())
        all_cnt = len(TOOLS)
        self.cat_tree.insert("", "end", iid="all",
                             values=("全部", all_cnt))
        # 内置分类 + 工具中实际出现的其他分类(如"自定义")
        cats = list(CATEGORIES)
        for t in TOOLS:
            c = t.get("category", "自定义")
            if c and c not in cats:
                cats.append(c)
        for cat in cats:
            cnt = sum(
                1 for t in TOOLS
                if t.get("category", "自定义") == cat)
            self.cat_tree.insert("", "end", iid=cat,
                                 values=(cat, cnt))
        self.cat_tree.selection_set("all")
        self._bind_category_shortcuts()
        self._fit_cat_height()

    def _fit_cat_height(self):
        """按分类数收缩分类树高度。

        必须在数据填充后调用 —— 构建期拿不到行高(此时模型为空),
        提前设固定高度会把内容压没(实测分类列表整片消失)。
        留一行余量给滚动条, 避免正好卡在边界上多出一根无用滚动条。
        """
        n = len(self.cat_tree.get_children())
        if n <= 0:
            return
        row = self.cat_view.sizeHintForRow(0)
        if row <= 0:
            row = 24                     # 模型尚未完成布局时的兜底
        head = self.cat_view.header().height()
        target = row * (n + 1) + head + 8
        self.cat_view.setFixedHeight(target)

    def _bind_category_shortcuts(self):
        """按实际分类数绑定 Ctrl+0~9"""
        count = len(self.cat_tree.get_children())
        for old in getattr(self, "_cat_shortcuts", []):
            old.setEnabled(False)
            old.deleteLater()
        self._cat_shortcuts = []
        for i in range(min(count, 10)):
            s = QtGui.QShortcut(
                QtGui.QKeySequence(f"Ctrl+{i}"), self._qwin)
            s.activated.connect(
                lambda idx=i: self._switch_category_by_index(idx))
            self._cat_shortcuts.append(s)

    def _on_category_select(self, _):
        sel = self.cat_tree.selection()
        if sel:
            self.current_category = self.cat_tree.item(
                sel[0], "values")[0]
            self.filter_tools()

    # ──────────── 工具列表 ────────────

    def filter_tools(self, update_status=True):
        kw = self.keyword.get().strip().lower()
        self.tool_tree.delete(*self.tool_tree.get_children())

        # 有关键词时跨全部分类搜索
        search_all = bool(kw)

        candidates = []
        for tool in TOOLS:
            category = tool.get("category", "自定义")
            if (not search_all
                    and self.current_category != "全部"
                    and category != self.current_category):
                continue
            versions = tool.get("versions") or []
            ver_label = (versions[0].get("label", "")
                         if versions else "")
            searchable = (str(tool.get("name", ""))
                          + str(ver_label)
                          + str(tool.get("description", ""))
                          ).lower()
            if kw and kw not in searchable:
                continue
            candidates.append(tool)

        # 排序: 直接读下拉框当前文本(与控件始终同步)
        sort_combo = getattr(self, "_sort_combo", None)
        sort_key = (sort_combo.currentText() if sort_combo is not None
                    else "默认")
        if sort_key == "名称 A-Z":
            candidates.sort(key=lambda t: str(t.get("name", "")))
        elif sort_key == "名称 Z-A":
            candidates.sort(key=lambda t: str(t.get("name", "")),
                            reverse=True)
        elif sort_key == "分类":
            candidates.sort(
                key=lambda t: str(t.get("category", "")))

        count = 0
        for tool in candidates:
            # 读缓存, 避免每次过滤都做磁盘/注册表检测
            installed = bool(tool.get("_installed"))
            status = "✓ 已装" if installed else ""
            versions = tool.get("versions") or []
            ver_label = (versions[0].get("label", "")
                         if versions else "-")
            self.tool_tree.insert(
                "", "end",
                values=(tool.get("name", ""),
                        ver_label,
                        str(tool.get("description", "")),
                        status),
                iid=str(id(tool)),
                tags=("installed",) if installed else ())
            count += 1

        # tag 配色需适配深色玻璃主题: 原先用适配白底的深绿/浅蓝,
        # 在深色底上会刺眼且对比不足
        self.tool_tree.tag_configure(
            "installed", foreground=self._pal.OK)
        self.tool_tree.tag_configure(
            "downloading", background="#2A3550",
            foreground=self._pal.ACCENT_C)

        if not update_status:
            return
        if count == 0:
            self.status.set("未找到匹配的工具")
        elif kw:
            scope = ("全部分类" if search_all
                     else self.current_category)
            self.status.set(
                f"搜索结果: {count} 个工具 ({scope})")
        else:
            self.status.set("就绪 - 双击工具即可开始下载")

    def _refresh_installed(self, update_status=False):
        """重新检测已安装状态"""
        for tool in TOOLS:
            verify = tool.get("deploy", {}).get("verify", "")
            tool["_installed"] = Deployer.is_installed(verify)
        self.filter_tools(update_status=False)
        if update_status:
            n = sum(1 for t in TOOLS if t.get("_installed"))
            self.status.set(
                f"状态已刷新: 已检测 {len(TOOLS)} 个工具, "
                f"其中 {n} 个已安装")

    def _find_tool_by_iid(self, iid):
        for tool in TOOLS:
            if str(id(tool)) == iid:
                return tool
        return None

    def _on_tool_select(self, _):
        try:
            if not self.version_combo.winfo_exists():
                return
            sel = self.tool_tree.selection()
            if not sel:
                return
            tool = self._find_tool_by_iid(sel[0])
            if not tool:
                return
            self.current_tool = tool
            self.current_versions = tool["versions"]
            labels = [v["label"] for v in self.current_versions]
            self.version_combo["values"] = labels
            self.version_combo.current(0)
        except Exception:
            return

    def _get_selected_tool(self):
        sel = self.tool_tree.selection()
        if not sel:
            return None
        return self._find_tool_by_iid(sel[0])

    def _get_selected_version(self):
        tool = self._get_selected_tool()
        if not tool:
            return None, None
        # 版本列表必须取自当前选中工具本身: current_versions 由
        # <<TreeviewSelect>> 异步更新, 事件未派发时会残留上一个
        # 工具的列表, 导致拿错 URL 下载
        versions = tool.get("versions") or []
        if not versions:
            return tool, None
        idx = self.version_combo.current()
        if idx < 0 or idx >= len(versions):
            idx = 0
        return tool, versions[idx]

    # ──────────── 目录 ────────────

    def _browse_dir(self):
        path = filedialog.askdirectory(
            initialdir=self.save_dir.get())
        if path:
            self.save_dir.set(path)
            self._config["save_dir"] = path
            save_config(self._config)

    def open_folder(self):
        path = self.save_dir.get()
        if os.path.isdir(path):
            os.startfile(path)
        else:
            messagebox.showerror(
                "错误", f"目录不存在:\n{path}")

    def _highlight_tool(self, tool):
        """高亮显示正在下载的工具"""
        try:
            iid = str(id(tool))
            # 清除所有 downloading 标签
            for item in self.tool_tree.get_children():
                tags = list(self.tool_tree.item(item, "tags"))
                if "downloading" in tags:
                    tags.remove("downloading")
                    self.tool_tree.item(item, tags=tuple(tags))
            # 给目标加标签
            tags = list(self.tool_tree.item(iid, "tags"))
            if "downloading" not in tags:
                tags.append("downloading")
                self.tool_tree.item(iid, tags=tuple(tags))
        except Exception:
            pass

    def _clear_highlight(self):
        """清除所有下载高亮"""
        try:
            for item in self.tool_tree.get_children():
                tags = list(self.tool_tree.item(item, "tags"))
                if "downloading" in tags:
                    tags.remove("downloading")
                    self.tool_tree.item(item,
                                        tags=tuple(tags))
        except Exception:
            pass

    # ──────────── 键盘导航 ────────────

    def _move_selection(self, delta):
        """↑↓ 键在工具列表中移动选择"""
        children = list(self.tool_tree.get_children())
        if not children:
            return
        sel = self.tool_tree.selection()
        if sel:
            try:
                idx = children.index(sel[0])
            except ValueError:
                idx = -1 if delta > 0 else len(children)
        else:
            # 无选中: ↓ 选第一行, ↑ 选最后一行
            idx = -1 if delta > 0 else len(children)
        new_idx = max(0, min(len(children) - 1, idx + delta))
        self.tool_tree.selection_set(children[new_idx])
        self.tool_tree.see(children[new_idx])

    # ──────────── 日志 ────────────

    def _copy_url(self, _=None):
        """点击/右键 URL 标签复制到剪贴板"""
        url = self.url_var.get()
        if url:
            QtWidgets.QApplication.clipboard().setText(url)
            ts = time.strftime("%H:%M:%S")
            self._log(f"[{ts}] 已复制 URL 到剪贴板")
            # 短暂反馈: 独立 id 管理, 任务启动时会被一并取消
            old = self.status.get()
            self.status.set("URL 已复制到剪贴板")
            if self._status_restore_id is not None:
                try:
                    self.root.after_cancel(self._status_restore_id)
                except Exception:
                    pass
            self._status_restore_id = self.root.after(
                2000, self._restore_status, old)

    def _restore_status(self, old):
        """恢复复制前的状态文字; 期间若已有任务则不覆盖"""
        self._status_restore_id = None
        if self._is_busy():
            return
        self.status.set(old)

    LOG_MAX_LINES = 2000

    def _log(self, message):
        """向日志面板追加一行 (超过上限自动裁剪)"""
        if getattr(self, "_closing", False):
            return
        try:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message + "\n")
            # 裁剪过长日志, 防内存/性能退化
            line_count = int(
                self.log_text.index("end-1c").split(".")[0])
            if line_count > self.LOG_MAX_LINES:
                cut = line_count - self.LOG_MAX_LINES
                self.log_text.delete("1.0", f"{cut + 1}.0")
            self.log_text.see("end")
        except Exception:
            pass
        finally:
            # 无论中途是否异常, 都恢复为只读, 避免用户误编辑
            try:
                self.log_text.configure(state="disabled")
            except Exception:
                pass

    def _clear_log(self):
        try:
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")
        except Exception:
            pass

    def _export_log(self):
        content = self.log_text.get("1.0", "end").strip()
        if not content:
            messagebox.showinfo("提示", "日志为空")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile=f"部署日志_{time.strftime('%Y%m%d_%H%M%S')}.txt")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                self._log(f"[{time.strftime('%H:%M:%S')}] "
                          f"日志已导出: {path}")
            except OSError as e:
                messagebox.showerror("错误", f"导出失败: {e}")

    # ──────────── 下载/部署 ────────────

    def _is_busy(self):
        return self._task_phase != "idle"

    def _set_phase(self, phase):
        self._task_phase = phase

    def _schedule_after(self, ms, fn):
        """调度延迟回调, 记录 id 以便取消"""
        self._cancel_pending_after()
        self._pending_after_id = self.root.after(ms, fn)

    def _cancel_pending_after(self):
        if self._pending_after_id is not None:
            try:
                self.root.after_cancel(self._pending_after_id)
            except Exception:
                pass
            self._pending_after_id = None
        if getattr(self, "_status_restore_id", None) is not None:
            try:
                self.root.after_cancel(self._status_restore_id)
            except Exception:
                pass
            self._status_restore_id = None

    def _set_buttons(self, downloading):
        state = "disabled" if downloading else "normal"
        self.download_btn.configure(state=state)
        self.deploy_btn.configure(state=state)
        self.batch_btn.configure(state=state)
        self.cancel_btn.configure(
            state="normal" if downloading else "disabled")

    def start_download(self):
        if self._is_busy():
            messagebox.showinfo("提示", "当前已有任务正在进行")
            return
        tool, version = self._get_selected_version()
        if not tool:
            messagebox.showinfo(
                "提示", "请先在列表中选择一个工具")
            return
        if not version:
            messagebox.showinfo(
                "提示", "该工具没有可用版本")
            return
        self._deploy_mode = False
        self._batch_queue = []
        self._begin_download(tool, version)

    def _retry_current(self):
        """重试: 沿用原任务的模式与版本快照"""
        if self._is_busy():
            messagebox.showinfo("提示", "当前已有任务正在进行")
            return
        tool = self._active_tool
        version = self._active_version
        if not tool or not version:
            self.start_download()
            return
        self._batch_queue = []
        self._begin_download(tool, version)

    def start_deploy(self):
        if self._is_busy():
            messagebox.showinfo("提示", "当前已有任务正在进行")
            return
        tool, version = self._get_selected_version()
        if not tool:
            messagebox.showinfo(
                "提示", "请先在列表中选择一个工具")
            return
        if not version:
            messagebox.showinfo(
                "提示", "该工具没有可用版本")
            return

        deploy = tool.get("deploy", {})
        if deploy.get("type") == "none":
            homepage = tool.get("homepage")
            if homepage:
                if messagebox.askyesno(
                        "提示",
                        f"{tool['name']} 不支持自动安装。\n"
                        "是否打开官网下载页?"):
                    webbrowser.open(homepage)
            else:
                messagebox.showinfo(
                    "提示",
                    f"{tool['name']} 不支持自动安装。")
            return

        self._deploy_mode = True
        self._batch_queue = []
        self._begin_download(tool, version)

    def start_batch_deploy(self):
        """批量部署:多选工具后依次下载+安装"""
        if self._is_busy():
            messagebox.showinfo("提示", "当前已有任务正在进行")
            return

        sel = self.tool_tree.selection()
        if len(sel) < 2:
            messagebox.showinfo(
                "提示",
                "请在列表中选中多个工具(按住 Ctrl/Shift 多选)")
            return

        tools = []
        for iid in sel:
            tool = self._find_tool_by_iid(iid)
            if tool and tool.get(
                    "deploy", {}).get("type") != "none":
                tools.append(tool)

        if not tools:
            messagebox.showinfo(
                "提示", "所选工具均不支持自动安装")
            return

        names = "\n".join(f"  • {t['name']}" for t in tools)
        if not messagebox.askyesno(
                "批量部署确认",
                f"将依次下载并安装 {len(tools)} 个工具:\n\n"
                f"{names}\n\n是否继续?"):
            return

        self._deploy_mode = True
        self._batch_queue = tools
        self._batch_index = 0
        self._batch_success = 0
        # 记录每个工具要部署的版本 (当前选中工具沿用下拉选择)
        self._batch_versions = {}
        cur_iid = (self.tool_tree.selection() or [""])[0]
        for t in tools:
            if str(id(t)) == cur_iid:
                _, ver = self._get_selected_version()
                self._batch_versions[id(t)] = ver or t["versions"][0]
            else:
                self._batch_versions[id(t)] = t["versions"][0]
        tool = self._batch_queue[0]
        version = self._batch_versions[id(tool)]
        self.status.set(
            f"批量部署: 1/{len(self._batch_queue)} - "
            f"{tool['name']}")
        self._begin_download(tool, version)

    def _batch_version_of(self, tool):
        """取批量任务中该工具的版本, 兜底第一个"""
        return (self._batch_versions.get(id(tool))
                or tool["versions"][0])

    def _begin_download(self, tool, version):
        if not version:
            messagebox.showinfo("提示", "该工具没有可用版本")
            return
        dest_dir = self.save_dir.get().strip()
        if not dest_dir:
            dest_dir = os.path.join(
                os.path.expanduser("~"), "Downloads")
            self.save_dir.set(dest_dir)
        os.makedirs(dest_dir, exist_ok=True)

        # 保存目录到配置
        self._config["save_dir"] = dest_dir
        save_config(self._config)

        # 任务快照: 后续回调只读快照, 不受改选影响
        self._active_tool = tool
        self._active_version = version
        self.current_tool = tool
        self._cancel_pending_after()
        self._set_phase("downloading")
        self.cancel_event = threading.Event()
        self.download_start_time = time.time()
        # 世代号自增: 让本任务启动前的所有迟到回调失效
        self._task_seq += 1
        seq = self._task_seq
        self.downloader = ToolDownloader(
            version["url"], dest_dir, self.cancel_event,
            on_progress=lambda d, t, s, _q=seq:
                self._on_progress(d, t, s, _q),
            on_done=lambda ok, m, p, _q=seq:
                self._on_done(ok, m, p, _q),
        )

        mode = "部署" if self._deploy_mode else "下载"
        self.status.set(
            f"正在{mode}: {tool['name']} "
            f"({version['label']}) ...")
        self.url_var.set(version["url"])
        self._set_buttons(downloading=True)
        self.retry_btn.w.setVisible(False)
        self.progress.configure(value=0)
        self.progress_label.setText("")

        ts = time.strftime("%H:%M:%S")
        self._log(f"[{ts}] {mode}开始: "
                  f"{tool['name']} {version['label']}")

        # 高亮当前下载的工具
        self._highlight_tool(tool)

        # 异步获取文件大小预览 (绑定世代号, 避免污染新任务日志)
        threading.Thread(
            target=self._fetch_size_preview,
            args=(version["url"], seq), daemon=True).start()

        self.download_thread = threading.Thread(
            target=self.downloader.run, daemon=True)
        self.download_thread.start()

    def _fetch_size_preview(self, url, seq=0):
        """HEAD 请求获取文件大小,写入日志"""
        try:
            req = urllib.request.Request(
                url, method="HEAD",
                headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as r:
                size = int(
                    r.headers.get("Content-Length") or 0)
            if size > 0:
                ts = time.strftime("%H:%M:%S")
                if seq != self._task_seq or self._closing:
                    return
                self.root.after(
                    0, lambda: self._log(
                        f"[{ts}] 文件大小: "
                        f"{human_size(size)}"))
        except Exception:
            pass

    def cancel_download(self):
        # 安装进程不响应 cancel, 此时取消会让 phase 卡死在
        # installing 且进度条停不下来, 直接忽略
        if self._task_phase == "installing":
            return
        # 取消已排程的回调(自动重试/批量下一个), 避免取消后自动重启
        self._cancel_pending_after()
        if self.cancel_event:
            self.cancel_event.set()
        self._batch_queue = []
        # 世代号自增: 作废当前任务线程的迟到进度/完成回调,
        # 防止它们污染之后启动的新任务
        self._task_seq += 1
        self._set_phase("idle")
        self._set_buttons(downloading=False)
        self.status.set("已取消")
        ts = time.strftime("%H:%M:%S")
        self._log(f"[{ts}] 用户取消下载")

    # ──────────── 进度 ────────────

    def _on_progress(self, downloaded, total, speed, seq=0):
        if seq != self._task_seq or self._closing:
            return                      # 过期任务的迟到回调
        self.root.after(
            0, lambda: self._update_progress(
                downloaded, total, speed, seq))

    def _update_progress(self, downloaded, total, speed, seq=0):
        if seq != self._task_seq:
            return
        elapsed = time.time() - self.download_start_time
        if total > 0:
            self.progress.configure(
                maximum=total, value=downloaded)
            pct = downloaded * 100 / total
            text = (f"{human_size(downloaded)} / "
                    f"{human_size(total)} ({pct:.1f}%)")
        else:
            self.progress.configure(
                maximum=downloaded or 1, value=downloaded)
            text = human_size(downloaded)

        if speed > 0:
            text += f"  {human_size(speed)}/s"
            # 平均速度
            if elapsed > 1 and downloaded > 1024:
                avg = downloaded / elapsed
                text += f"  均 {human_size(avg)}/s"
            if total > 0 and downloaded > 0:
                remaining = (total - downloaded) / speed
                text += f"  ETA {human_time(remaining)}"
        text += f"  ({human_time(elapsed)})"
        self.progress_label.setText(text)

    # ──────────── 下载完成 ────────────

    def _on_done(self, ok, msg, path, seq=0):
        if self._closing:
            return
        self.root.after(
            0, lambda: self._finish_download(ok, msg, path, seq))

    def _finish_download(self, ok, msg, path, seq=0):
        if seq != self._task_seq:
            return                      # 过期任务的迟到回调
        ts = time.strftime("%H:%M:%S")
        if not ok:
            kind = "已取消" if "取消" in msg else "下载失败"
            self._log(f"[{ts}] {kind}: {msg}")
            if not self._batch_queue:
                self._clear_highlight()
            if self._maybe_auto_retry(ts, msg):
                return
            self._handle_download_failure(msg)
            return

        # 下载成功
        self._retry_count = 0
        if not self._batch_queue:
            self._clear_highlight()
        self._last_file_path = path
        file_size = (os.path.getsize(path)
                     if os.path.exists(path) else 0)
        self._log(f"[{ts}] 下载完成: "
                  f"{os.path.basename(path)} "
                  f"({human_size(file_size)})")

        tool = self._active_tool or self.current_tool
        if self._deploy_mode and tool:
            self.status.set(
                f"已下载 {human_size(file_size)}, "
                f"正在安装: {tool['name']} ...")
            self._start_install(path)
        else:
            self._finish_download_only(msg, path, file_size)

    def _maybe_auto_retry(self, ts, msg):
        """尝试自动重试,返回 True 表示已安排重试"""
        if (self._retry_count >= self._max_retries
                or "取消" in msg
                or not self._active_tool):
            return False
        self._retry_count += 1
        retry_msg = (f"自动重试 "
                     f"{self._retry_count}/"
                     f"{self._max_retries} ...")
        self.status.set(retry_msg)
        self._log(f"[{ts}] {retry_msg}")
        self._set_phase("retry_wait")
        self._schedule_after(2000, self._do_auto_retry)
        return True

    def _handle_download_failure(self, msg):
        """处理下载最终失败"""
        self._retry_count = 0
        tool_name = (self._active_tool or {}).get("name", "")

        # 批量模式: 记为失败并推进到下一个
        if self._batch_queue:
            self._clear_highlight()
            self._log(
                f"[{time.strftime('%H:%M:%S')}] "
                f"批量跳过 {tool_name}: {msg}")
            self.status.set(
                f"跳过 {tool_name} ({msg}), 继续下一项 ...")
            self._advance_batch(delay_ms=1500, success=False)
            return

        self._set_phase("idle")
        self._set_buttons(downloading=False)
        self._clear_highlight()
        self.status.set(msg)
        if "失败" not in msg:
            return
        # 间距须与 _build_bottom 初始 pack 一致, 否则重显时按钮会跳动
        self.retry_btn.w.setVisible(True)
        tool = self._active_tool or self.current_tool
        homepage = tool.get("homepage") if tool else None

        # 诊断: curl 报 000 时常见原因是 hosts 把域名屏蔽到本地
        blocked = None
        if self._active_version:
            blocked = check_hosts_blocking(
                self._active_version.get("url", ""))
        if blocked:
            blocked_host, blocked_ip = blocked
            hint = (f"\n\n⚠ 本机 hosts 将 {blocked_host} "
                    f"指向 {blocked_ip}\n"
                    "  该域名被本机屏蔽, 下载无法进行。\n"
                    "  请检查 hosts 文件或相关网络/拦截软件。")
            msg = f"{msg}{hint}"
            ts = time.strftime("%H:%M:%S")
            self._log(f"[{ts}] 诊断: {blocked_host} "
                      f"被本机 hosts 屏蔽 ({blocked_ip})")

        if homepage:
            text = (f"{msg}\n\n"
                    "可能被服务器屏蔽。\n"
                    "是否打开官网下载页?")
            if messagebox.askyesno("下载失败", text):
                webbrowser.open(homepage)
        else:
            messagebox.showerror("下载失败", msg)

    def _finish_download_only(self, msg, path, file_size):
        """仅下载模式完成"""
        self._set_phase("idle")
        self._set_buttons(downloading=False)
        size_text = (f" ({human_size(file_size)})"
                     if file_size else "")
        self.status.set(f"{msg}{size_text}")
        if messagebox.askyesno(
                "完成",
                f"{msg}{size_text}:\n{path}\n\n"
                "是否打开所在文件夹?"):
            os.startfile(os.path.dirname(path))

    def _do_auto_retry(self):
        """自动重试: 用任务快照, 不受改选影响"""
        tool = self._active_tool
        version = self._active_version
        if not tool or not version:
            return
        # 重置进度
        self.progress.configure(value=0)
        self.progress_label.setText("")
        self._begin_download(tool, version)

    # ──────────── 安装 ────────────

    def _start_install(self, file_path):
        tool = self._active_tool or self.current_tool
        deploy_config = tool.get("deploy", {})
        tool_name = tool["name"]
        self._set_phase("installing")
        # 安装进程不响应 cancel_event, 此阶段禁用取消按钮,
        # 避免"看似取消实则继续安装"的假象 (阶段1, 阶段2由
        # 完成回调恢复)
        self.cancel_btn.configure(state="disabled")
        # 世代号: 安装回调与本次任务绑定
        seq = self._task_seq

        # 安装动画: 不确定进度
        self._install_start = time.time()
        self.progress.configure(mode="indeterminate")
        self.progress.configure(mode="indeterminate")
        self.progress_label.setText("安装中...")

        # 批量进度显示
        if self._batch_queue:
            cur = self._batch_index + 1
            total = len(self._batch_queue)
            self.status.set(
                f"正在安装 ({cur}/{total}): {tool_name} ...")
            self.progress_label.configure(
                text=f"{cur}/{total} 安装中...")

        def _do_install():
            ok, msg = Deployer.run_install(
                file_path, deploy_config)
            elapsed = time.time() - self._install_start
            self.root.after(
                0, lambda: self._finish_install(
                    ok, msg, elapsed, seq))

        t = threading.Thread(target=_do_install, daemon=True)
        t.start()

    def _finish_install(self, ok, msg, elapsed=0, seq=0):
        if seq != self._task_seq:
            return                      # 过期任务的迟到回调
        self.progress.configure(mode="determinate")
        self.progress.configure(mode="determinate")
        self.progress_label.setText("")
        tool = self._active_tool or self.current_tool
        tool_name = tool["name"] if tool else ""
        ts = time.strftime("%H:%M:%S")
        status_text = "成功" if ok else "失败"
        time_text = (f" ({human_time(elapsed)})"
                     if elapsed > 1 else "")
        self._log(f"[{ts}] 安装{status_text}: "
                  f"{tool_name} - {msg}{time_text}")

        if ok:
            self._handle_install_success(tool_name, msg)
        else:
            self._handle_install_failure(tool_name, msg)

    def _advance_batch(self, delay_ms=1000, success=True):
        """批量部署: 推进到下一个工具"""
        if success:
            self._batch_success += 1
        self._batch_index += 1
        total = len(self._batch_queue)
        self.progress.configure(
            maximum=100,
            value=self._batch_index * 100 // total)
        if self._batch_index < total:
            next_tool = self._batch_queue[self._batch_index]
            self.status.set(
                f"批量部署: {self._batch_index + 1}/"
                f"{total} - {next_tool['name']} ...")
            self._set_phase("batch_gap")
            self._schedule_after(
                delay_ms,
                lambda: self._begin_download(
                    next_tool,
                    self._batch_version_of(next_tool)))
            return True
        # 批量完成
        self._batch_queue = []
        self._set_phase("idle")
        self._set_buttons(downloading=False)
        self.progress.configure(value=100)
        self._clear_highlight()
        failed = self._batch_index - self._batch_success
        self.status.set(
            f"批量部署完成: 成功 {self._batch_success} 个"
            + (f", 失败 {failed} 个" if failed else ""))
        messagebox.showinfo(
            "批量部署完成",
            f"成功部署 {self._batch_success} 个工具"
            + (f"\n失败 {failed} 个" if failed else ""))
        self._refresh_installed()
        return False

    def _handle_install_success(self, tool_name, msg):
        if self._batch_queue:
            self._advance_batch(success=True)
            return
        self._set_phase("idle")
        self._set_buttons(downloading=False)
        self._clear_highlight()
        self.status.set(f"{tool_name}: {msg}")
        self._refresh_installed()
        result = messagebox.askyesno(
            "部署完成",
            f"{tool_name} {msg}\n\n是否打开下载目录?")
        if result and self._last_file_path:
            folder = os.path.dirname(self._last_file_path)
            if os.path.isdir(folder):
                os.startfile(folder)

    def _handle_install_failure(self, tool_name, msg):
        if self._batch_queue:
            # 批量模式: 记为失败并推进到下一个
            self._clear_highlight()
            self._advance_batch(delay_ms=1500, success=False)
            return

        self._set_phase("idle")
        self._set_buttons(downloading=False)
        self._clear_highlight()
        self.status.set(f"{tool_name}: {msg}")
        # 与下载失败保持一致: 提供手动重试入口
        self.retry_btn.w.setVisible(True)
        tool = self._active_tool or self.current_tool
        homepage = tool.get("homepage") if tool else None
        text = f"{tool_name} {msg}"
        if homepage:
            text += "\n\n是否打开官网下载页?"
            if messagebox.askyesno("安装失败", text):
                webbrowser.open(homepage)
        else:
            messagebox.showerror("安装失败", text)

    # ──────────── 关于 ────────────

    def _show_about(self):
        import platform
        sys_info = (
            f"系统: Windows {platform.release()} "
            f"({platform.machine()})\n"
            f"Python: {platform.python_version()}"
        )
        about = (
            f"{APP_TITLE}\n\n"
            f"一款 Windows 编程工具一键下载部署工具。\n\n"
            f"功能:\n"
            f"• {len(TOOLS)} 款主流开发工具官方直链\n"
            f"• 一键部署: 下载 + 静默安装\n"
            f"• 批量部署: 多选工具同时安装\n"
            f"• 已安装状态自动检测\n"
            f"• 部署日志实时显示+导出\n"
            f"• 自动重试 (最多2次)\n"
            f"• 自动切换 urllib/curl 下载\n"
            f"• 设置自动持久化\n"
            f"• 液态玻璃界面 (Qt 6 渲染)"
            + f"\n\n"
            f"快捷键:\n"
            f"  Ctrl+F  聚焦搜索框\n"
            f"  ↑/↓     选择工具\n"
            f"  Enter   一键部署\n"
            f"  Esc     取消下载\n"
            f"  Ctrl+O  打开下载目录\n"
            f"  Ctrl+E  导出工具列表\n"
            f"  Ctrl+I  导入自定义工具\n"
            f"  Ctrl+B  批量部署\n"
            f"  Ctrl+0~9 切换分类\n"
            f"  双击    下载选中工具\n"
            f"  右键    打开操作菜单\n"
            f"  Ctrl+点击  多选工具\n\n"
            f"--- 系统信息 ---\n"
            f"{sys_info}\n\n"
            f"技术栈: Python + PySide6 (Qt 6)"
        )
        messagebox.showinfo("关于", about)

    # ──────────── 关闭 ────────────

    def _on_close_event(self, event=None):
        """QMainWindow.closeEvent 入口。"""
        if self._closing:
            if event is not None:
                event.accept()
            return
        self._on_close()
        if event is not None:
            event.accept()

    def _on_close(self):
        # 幂等: _on_close 内部会 destroy -> close -> 再次触发
        # closeEvent, 不加守卫会无限递归
        if self._closing:
            return
        # 标记关闭中: 后台线程的 after 回调不再触碰已销毁的控件
        self._closing = True
        self.cancel_event.set()
        self._cancel_pending_after()
        self._task_seq += 1          # 作废所有在途回调
        try:
            self._config["save_dir"] = self.save_dir.get()
            save_config(self._config)
        except Exception:
            pass
        self.root.destroy()


# ─────────────────────── 入口 ───────────────────────


class _UrlClick(QtCore.QObject):
    """把 URL 标签上的鼠标点击转成"复制链接"。

    QLabel 默认忽略鼠标事件, 迁移后原先 ``<Button-1>`` 绑定的
    点击复制交互会消失, 故用事件过滤器补回。
    """

    def __init__(self, app_ref):
        super().__init__()
        self._app = app_ref

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.MouseButtonPress:
            copy = getattr(self._app, "_copy_url", None)
            if copy:
                try:
                    copy()
                    return True
                except Exception:
                    pass
        return False


class _CloseGuard(QtCore.QObject):
    """拦截窗口关闭: 保存配置、置``_closing``、取消在途任务。

    QWidget.closeEvent 是虚方法而非信号, 不能 ``connect``; 只能通过
    事件过滤器捕获 QEvent.Close。不接线会导致配置不落盘, 且后台
    线程的迟到回调仍会触碰已销毁控件。
    """

    def __init__(self, app_ref):
        super().__init__()
        self._app = app_ref

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.Close:
            handler = getattr(self._app, "_on_close_event", None)
            if handler:
                try:
                    handler(event)
                except Exception:
                    pass
        return False


class _ResizeSync(QtCore.QObject):
    """中央区域尺寸变化时同步背景层几何。

    App 本身不是 QObject, 无法直接充当 eventFilter, 故用本包装器。
    背景层若不跟随窗口尺寸, 光晕会只占初始大小, 拖大窗口后右侧
    露出纯色底。
    """

    def __init__(self, app_ref):
        super().__init__()
        self._app = app_ref

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.Resize:
            bg = getattr(self._app, "bg_canvas", None)
            if bg is not None:
                bg.setGeometry(obj.rect())
        return False


def main():
    """Qt 应用入口。

    - ``QApplication`` 必须在任何 QWidget 之前创建
    - App 只接收窗口与 shim, 自身不依赖具体控件类型
    """
    QApplication = QtWidgets.QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("编程工具下载器")

    win = QtWidgets.QMainWindow()
    win.resize(1180, 820)
    win.setMinimumSize(1000, 700)
    # 窗口本体透明, 由 BackgroundWidget 提供底色
    win.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

    root = ui_bind.RootShim(win)
    App(root)

    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
