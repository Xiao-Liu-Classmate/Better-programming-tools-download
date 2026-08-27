# -*- coding: utf-8 -*-
"""编程工具下载器 (Windows / Python + Tkinter)"""

import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from tkinter import (
    PanedWindow, StringVar, Tk,
    filedialog, messagebox, ttk,
)

from tools import TOOLS, CATEGORIES

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
CHUNK_SIZE = 128 * 1024


def human_size(num):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} TB"


def _unit_value(val, suffix):
    return int(float(val) * {"": 1, "k": 1024, "K": 1024,
                             "m": 1024 ** 2, "M": 1024 ** 2,
                             "g": 1024 ** 3, "G": 1024 ** 3}.get(suffix, 1))


CURL_PROGRESS_RE = re.compile(
    rb"^\s*(\d+(?:\.\d+)?)([kKmMgG]?)\s+(\d+)%\s+([0-9.]+)([kKmMgG]?)[bB]?/s")


def parse_curl_progress(line):
    """解析 curl -# 的进度行,返回 (已下载字节, 总字节或0, 速度字节/秒)"""
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


def guess_filename_from_cd(header_text):
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', header_text, re.IGNORECASE)
    if m:
        name = urllib.parse.unquote(m.group(1).strip())
        if name:
            return os.path.basename(name.replace("\\", "/"))
    return None


class ToolDownloader:
    """在后台线程中下载文件,通过回调上报进度
    优先使用 urllib;若服务器拒绝(如部分 CDN 屏蔽 urllib),
    自动回退到 Windows 自带的 curl.exe。"""

    def __init__(self, url, dest_dir, cancel_event, on_progress=None, on_done=None):
        self.url = url
        self.dest_dir = dest_dir
        self.cancel_event = cancel_event
        self.on_progress = on_progress
        self.on_done = on_done
        self.filename = None

    def _guess_filename(self, resp):
        cd = resp.headers.get("Content-Disposition", "")
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.IGNORECASE)
        if m:
            name = urllib.parse.unquote(m.group(1).strip())
            if name:
                return os.path.basename(name.replace("\\", "/"))
        name = os.path.basename(urllib.parse.urlparse(self.url).path)
        if name:
            return urllib.parse.unquote(name)
        return "download.bin"

    def _download_urllib(self):
        """urllib 下载,成功返回文件路径,失败抛异常"""
        req = urllib.request.Request(self.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            filename = self._guess_filename(resp)
            self.filename = filename
            path = os.path.join(self.dest_dir, filename)
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
        """curl.exe 下载(自动跟随跳转),成功返回文件路径,失败抛异常"""
        tmp = os.path.join(self.dest_dir, ".partial_download")
        if os.path.exists(tmp):
            os.remove(tmp)
        header_file = os.path.join(self.dest_dir, ".partial_headers")
        cmd = ["curl.exe", "-L", "--fail", "-sS", "-A", USER_AGENT,
               "--connect-timeout", "30", "-C", "-", "-#",
               "-D", header_file,
               "-o", tmp,
               "-w", "%{url_effective}", self.url]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def monitor():
            while True:
                chunk = proc.stderr.read(4096)
                if not chunk:
                    break
                for line in chunk.split(b"\r"):
                    parsed = parse_curl_progress(line)
                    if parsed and self.on_progress:
                        size, total, speed = parsed
                        self.on_progress(size, total, speed)

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()

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
        monitor_thread.join(timeout=1)
        if proc.returncode != 0 or not os.path.exists(tmp):
            for f in (tmp, header_file):
                if os.path.exists(f):
                    os.remove(f)
            raise DownloadError(f"curl 下载失败(退出码 {proc.returncode})")

        final_url = final_url.decode("utf-8", "ignore")
        filename = None
        try:
            with open(header_file, "r", encoding="utf-8", errors="ignore") as hf:
                filename = guess_filename_from_cd(hf.read())
        except OSError:
            pass
        if not filename and final_url:
            filename = urllib.parse.unquote(os.path.basename(
                urllib.parse.urlparse(final_url).path))
        if not filename:
            filename = self._guess_filename_dummy()
        self.filename = filename
        final_path = os.path.join(self.dest_dir, filename)
        if os.path.abspath(tmp) != os.path.abspath(final_path):
            if os.path.exists(final_path):
                os.remove(final_path)
            os.rename(tmp, final_path)
        if os.path.exists(header_file):
            os.remove(header_file)
        return final_path

    def _guess_filename_dummy(self):
        name = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(self.url).path))
        return name or "download.bin"

    def run(self):
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
            if not shutil.which("curl.exe"):
                if self.on_done:
                    self.on_done(False, f"下载失败: {urllib_err}", None)
                return
            try:
                if self.on_progress:
                    self.on_progress(0, 0, 0.0)
                path = self._download_curl()
                if self.on_done:
                    self.on_done(True, "下载完成 (curl 模式)", path)
            except Exception as curl_err:
                if self.cancel_event.is_set():
                    if self.on_done:
                        self.on_done(False, "已取消下载", None)
                elif self.on_done:
                    detail = str(curl_err) or str(urllib_err)
                    self.on_done(False, f"下载失败: {detail}", None)


class CancelledError(Exception):
    pass


class DownloadError(Exception):
    pass


class App:
    def __init__(self, root):
        self.root = root
        self.cancel_event = threading.Event()
        self.downloader = None
        self.download_thread = None
        self.current_tool = None
        self.current_category = "全部"
        self.current_keyword = ""

        root.title("编程工具下载器")
        root.geometry("980x620")
        root.minsize(820, 540)

        style = ttk.Style(root)
        style.configure("Treeview", font=("Microsoft YaHei UI", 9), rowheight=26)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

        self.save_dir = StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
        self.keyword = StringVar()

        self._build_top()
        self._build_main()
        self._build_bottom()

        self.load_category()
        self.filter_tools()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- 界面构建 ----------------
    def _build_top(self):
        top = ttk.Frame(self.root, padding=(10, 8, 10, 0))
        top.pack(fill="x")

        ttk.Label(top, text="保存目录:").grid(row=0, column=0, sticky="w")
        self.dir_entry = ttk.Entry(top, textvariable=self.save_dir)
        self.dir_entry.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(top, text="浏览...", command=self._browse_dir).grid(row=0, column=2)

        ttk.Label(top, text="搜索:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.search_entry = ttk.Entry(top, textvariable=self.keyword)
        self.search_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        self.keyword.trace_add("write", lambda *_: self.filter_tools())

        top.columnconfigure(1, weight=1)

    def _build_main(self):
        pane = PanedWindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=10, pady=8)

        left = ttk.Frame(pane)
        self.cat_tree = ttk.Treeview(left, columns=("cat",), show="headings",
                                     selectmode="browse")
        self.cat_tree.heading("cat", text="分类")
        self.cat_tree.column("cat", width=170, anchor="w", stretch=True)
        self.cat_tree.pack(fill="both", expand=True)
        self.cat_tree.bind("<<TreeviewSelect>>", self._on_category_select)
        pane.add(left)

        right = ttk.Frame(pane)
        self.tool_tree = ttk.Treeview(right, columns=("name", "ver", "desc"),
                                      show="headings", selectmode="browse")
        self.tool_tree.heading("name", text="工具")
        self.tool_tree.heading("ver", text="版本")
        self.tool_tree.heading("desc", text="说明")
        self.tool_tree.column("name", width=190, anchor="w", stretch=False)
        self.tool_tree.column("ver", width=130, anchor="w", stretch=False)
        self.tool_tree.column("desc", width=380, anchor="w", stretch=True)
        vsb = ttk.Scrollbar(right, orient="vertical", command=self.tool_tree.yview)
        self.tool_tree.configure(yscrollcommand=vsb.set)
        self.tool_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tool_tree.bind("<Double-1>", lambda _: self.start_download())
        self.tool_tree.bind("<<TreeviewSelect>>", self._on_tool_select)
        pane.add(right)

    def _build_bottom(self):
        bottom = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")

        self.status = StringVar(value="就绪 - 双击工具即可开始下载")
        ttk.Label(bottom, textvariable=self.status, anchor="w").pack(fill="x")

        bar_row = ttk.Frame(bottom)
        bar_row.pack(fill="x", pady=4)
        self.progress = ttk.Progressbar(bar_row, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_label = ttk.Label(bar_row, text="", width=28, anchor="e")
        self.progress_label.pack(side="right", padx=(8, 0))

        btn_row = ttk.Frame(bottom)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Label(btn_row, text="版本:").pack(side="left")
        self.version_combo = ttk.Combobox(btn_row, state="readonly", width=24)
        self.version_combo.pack(side="left", padx=(4, 10))
        self.download_btn = ttk.Button(btn_row, text="开始下载", command=self.start_download)
        self.download_btn.pack(side="left")
        self.cancel_btn = ttk.Button(btn_row, text="取消下载", command=self.cancel_download,
                                     state="disabled")
        self.cancel_btn.pack(side="left", padx=8)
        ttk.Button(btn_row, text="打开下载目录", command=self.open_folder).pack(side="right")

    # ---------------- 逻辑 ----------------
    def load_category(self):
        self.cat_tree.delete(*self.cat_tree.get_children())
        self.cat_tree.insert("", "end", iid="all", values=("全部",))
        for cat in CATEGORIES:
            self.cat_tree.insert("", "end", iid=cat, values=(cat,))
        self.cat_tree.selection_set("all")

    def _on_category_select(self, _):
        sel = self.cat_tree.selection()
        if sel:
            self.current_category = self.cat_tree.item(sel[0], "values")[0]
            self.filter_tools()

    def filter_tools(self):
        kw = self.keyword.get().strip().lower()
        self.tool_tree.delete(*self.tool_tree.get_children())
        for tool in TOOLS:
            if self.current_category != "全部" and tool["category"] != self.current_category:
                continue
            if kw and kw not in (tool["name"] + tool["versions"][0]["label"]
                                 + tool["description"]).lower():
                continue
            self.tool_tree.insert("", "end",
                                  values=(tool["name"], tool["versions"][0]["label"],
                                          tool["description"]),
                                  iid=str(id(tool)))

    def get_selected_tool(self):
        sel = self.tool_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选择一个工具")
            return None
        return next(t for t in TOOLS if str(id(t)) == sel[0])

    def _on_tool_select(self, _):
        try:
            if not self.version_combo.winfo_exists():
                return
            tool = self.get_selected_tool()
            if not tool:
                self.version_combo["values"] = []
                self.current_versions = []
                return
            self.current_tool = tool
            self.current_versions = tool["versions"]
            labels = [v["label"] for v in self.current_versions]
            self.version_combo["values"] = labels
            self.version_combo.current(0)
        except Exception:
            return

    def _browse_dir(self):
        path = filedialog.askdirectory(initialdir=self.save_dir.get())
        if path:
            self.save_dir.set(path)

    def open_folder(self):
        path = self.save_dir.get()
        if os.path.isdir(path):
            os.startfile(path)
        else:
            messagebox.showerror("错误", f"目录不存在:\n{path}")

    def start_download(self):
        if self.downloader and self.download_thread and self.download_thread.is_alive():
            messagebox.showinfo("提示", "当前已有下载任务正在进行")
            return
        tool = self.get_selected_tool()
        if not tool:
            return
        versions = tool.get("versions") or self.current_versions
        idx = self.version_combo.current()
        if idx < 0 or idx >= len(versions):
            idx = 0
        version = versions[idx]
        url = version["url"]

        dest_dir = self.save_dir.get().strip()
        if not dest_dir:
            dest_dir = os.path.join(os.path.expanduser("~"), "Downloads")
            self.save_dir.set(dest_dir)
        os.makedirs(dest_dir, exist_ok=True)

        self.current_tool = tool
        self.cancel_event = threading.Event()
        self.downloader = ToolDownloader(
            url, dest_dir, self.cancel_event,
            on_progress=self._on_progress, on_done=self._on_done,
        )
        self.status.set(f"正在下载: {tool['name']} ({version['label']}) ...")
        self.download_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.configure(value=0)

        self.download_thread = threading.Thread(target=self.downloader.run, daemon=True)
        self.download_thread.start()

    def cancel_download(self):
        self.cancel_event.set()
        self.status.set("正在取消...")

    def _on_progress(self, downloaded, total, speed):
        self.root.after(0, lambda: self._update_progress(downloaded, total, speed))

    def _update_progress(self, downloaded, total, speed):
        if total > 0:
            self.progress.configure(maximum=total, value=downloaded)
            pct = downloaded * 100 / total
            text = f"{human_size(downloaded)} / {human_size(total)} ({pct:.1f}%)"
        else:
            self.progress.configure(maximum=downloaded or 1, value=downloaded)
            text = f"{human_size(downloaded)}"
        if speed > 0:
            text += f"  {human_size(speed)}/s"
        self.progress_label.configure(text=text)

    def _on_done(self, ok, msg, path):
        self.root.after(0, lambda: self._finish(ok, msg, path))

    def _finish(self, ok, msg, path):
        self.download_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.status.set(msg)
        if ok and path and os.path.exists(path):
            if messagebox.askyesno("完成", f"{msg}:\n{path}\n\n是否打开所在文件夹?"):
                os.startfile(os.path.dirname(path))
        elif not ok and "失败" in msg:
            homepage = self.current_tool.get("homepage") if self.current_tool else None
            text = f"{msg}"
            if homepage:
                text += (f"\n\n该软件的官方服务器可能屏蔽了直接下载。\n"
                         f"是否在浏览器中打开官网下载页?")
                if messagebox.askyesno("下载失败", text):
                    webbrowser.open(homepage)
            else:
                messagebox.showerror("下载失败", text)

    def _on_close(self):
        self.cancel_event.set()
        self.root.destroy()


def main():
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
