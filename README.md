# 编程工具下载器

一款 Windows 平台的编程工具一键下载与静默部署工具。内置 28 款主流开发工具的官方直链，支持版本选择、批量部署、已安装状态检测。

**[Gitee](https://gitee.com/xiao-xiao-liuA/Better-programming-tools-download) · [GitHub](https://github.com/Xiao-Liu-Classmate/Better-programming-tools-download)**

| 平台 | 状态 |
| --- | --- |
| Gitee (master) | [![Gitee](https://gitee.com/xiao-xiao-liuA/Better-programming-tools-download/badge.svg)](https://gitee.com/xiao-xiao-liuA/Better-programming-tools-download) |
| GitHub (main) | [![CI](https://github.com/Xiao-Liu-Classmate/Better-programming-tools-download/actions/workflows/ci.yml/badge.svg)](https://github.com/Xiao-Liu-Classmate/Better-programming-tools-download/actions/workflows/ci.yml) |

![Python](https://img.shields.io/badge/python-3.11%2B-3776ab?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue?logo=open-source-initiative&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)
![Deps](https://img.shields.io/badge/dependencies-stdlib%20%2B%20optional%20Pillow-informational)

## 快速开始

从源码执行 `run.bat` 即可运行；也可自行打包为独立 exe（见下方「打包为 EXE」，约 33 MB，无需安装 Python 环境）。

## 下载

**v4.1.0 发行版**（液态玻璃界面）

| 平台 | 附件 | 链接 |
| --- | --- | --- |
| GitHub | `Programming-Tools-Downloader.exe` | [下载](https://github.com/Xiao-Liu-Classmate/Better-programming-tools-download/releases/tag/v4.1.0) |
| Gitee | `Programming-Tools-Downloader.exe` | [下载](https://gitee.com/xiao-xiao-liuA/Better-programming-tools-download/releases/tag/v4.1.0) |

双击即可运行，无需安装 Python 环境。本版界面全面重做为液态玻璃风格，
程序体积从 11.06 MB 增至 19–33 MB（差异来自两侧构建环境的 Pillow 版本）。

**校验值**

| 平台 | 大小 | SHA256 |
| --- | --- | --- |
| GitHub | 19.45 MB | `7D8AB014BD0004B233FEB6494317CF0D61110E4E586FBF0073A1AAF51339A23A` |
| Gitee | 33.19 MB | `0655D2C03DF6A992E04B5BB78F6E33E2CEDEE3403B3661D39C0A0DB4B953460F` |

> 两侧附件均为 ASCII 文件名，以避免部分 Windows 环境下的中文文件名乱码与杀毒软件误报。
> 二进制由各自平台独立构建，功能完全一致，故哈希不同。

> 仓库不存储二进制文件（`.gitignore` 已排除 `dist/` 与 `*.exe`），可执行文件通过 Releases 或本地构建获取。

## 功能特性

### 工具库

| 分类 | 数量 | 工具 |
| --- | --- | --- |
| 语言运行时 | 8 | Python、Node.js、OpenJDK (Temurin)、Go、Rust、.NET SDK、Miniconda3、Flutter SDK |
| 开发环境 (IDE) | 6 | VS Code、IntelliJ IDEA、PyCharm、Eclipse、Visual Studio Community、Android Studio |
| 构建工具 | 2 | Apache Maven、Gradle |
| 版本控制与命令行 | 5 | Git for Windows、GitHub Desktop、Windows Terminal、PowerShell 7、7-Zip |
| 数据库与容器 | 7 | MySQL、PostgreSQL、MongoDB、SQLite、Docker Desktop、DBeaver、HeidiSQL |

> 绿色版工具（Maven、Gradle、Flutter、Eclipse）解压即用，`deploy.type` 为 `extract`；官方安装器不支持静默参数的工具（Android Studio）为 `none`，程序会引导至官网。

### 关于版本号

工具库中的版本为**固定快照**，标签不标「最新」——因为直链锁定在特定版本，相对发布时点可能已有更新。标注「最新稳定版」的条目（Miniconda3）使用滚动 URL，始终指向官方当前版本。需要更新的版本时，请以各工具官网为准，或直接修改 `tools.py` 中的 `versions` 列表。

### 核心能力

- **一键部署**：下载 + 静默安装一步完成，自动处理 MSI / EXE / 压缩包 / 自定义命令
- **批量部署**：多选工具依次安装，单项失败自动跳过，完成时汇总成功与失败数
- **多版本选择**：每个工具提供多个官方版本，按需切换
- **已安装检测**：自动扫描注册表与磁盘，绿色 ✓ 标记已装工具
- **下载引擎**：urllib 优先，Docker 等 CDN 自动降级 curl，断点信息与速度实时显示
- **自动重试**：下载失败自动重试 2 次，仍失败可手动重试或跳转官网
- **故障诊断**：下载失败时自动检测本机 hosts 是否屏蔽了目标域名并给出提示
- **部署日志**：实时滚动日志，支持导出为文本文件

### 界面操作

- 搜索框支持**跨全部分类**搜索（输入关键词后自动突破当前分类）
- 排序支持：默认 / 名称 A-Z / 名称 Z-A / 分类
- 工具列表**右键菜单**：部署、下载、复制链接、查看详情、打开官网
- 支持导入/导出自定义工具（JSON 格式），扩展工具库

## 快捷键

| 快捷键 | 功能 |
| --- | --- |
| `Ctrl+F` | 聚焦搜索框 |
| `↑` `↓` | 切换选中工具 |
| `Enter` | 一键部署（焦点在工具列表时） |
| `Esc` | 取消当前下载 |
| `Ctrl+O` | 打开下载目录 |
| `Ctrl+E` | 导出工具列表 |
| `Ctrl+I` | 导入自定义工具 |
| `Ctrl+B` | 批量部署 |
| `Ctrl+0` ~ `Ctrl+9` | 切换分类 |
| 双击工具行 | 下载选中工具 |
| `Ctrl+点击` | 多选工具 |

## 自定义工具格式

通过「导入工具」按钮加载 JSON 文件，支持两种结构：

```json
[
  {
    "name": "My Tool",
    "category": "自定义",
    "description": "工具说明",
    "versions": [
      { "label": "1.0.0", "url": "https://example.com/tool.zip" }
    ],
    "deploy": {
      "type": "extract",
      "verify": "C:\\Program Files\\My Tool\\*"
    }
  }
]
```

或包裹格式 `{ "tools": [ ... ] }`。

`deploy.type` 取值：

| 类型 | 说明 |
| --- | --- |
| `msi` | MSI 包，`msiexec /quiet /norestart` 静默安装 |
| `exe` | EXE 安装包，`args` 为静默参数，`need_admin` 触发 UAC |
| `msi` | MSI 包，`msiexec /quiet /norestart` 静默安装；`need_admin` 同样生效 |
| `extract` | ZIP 压缩包，解压到同名目录 |
| `custom` | 自定义命令，`cmd` 中可用 `{file}` `{user}` `{appdata}` 占位符 |
| `none` | 不支持自动安装，跳转官网 |

所有导入数据均经过强校验（名称、版本 URL 协议、部署类型白名单），非法项会被过滤。

## 从源码运行

```bash
python app.py
```

核心功能仅依赖 Python 标准库（tkinter、urllib、subprocess 等），无需 pip 安装任何第三方包。

**可选依赖**：安装 [Pillow](https://pypi.org/project/Pillow/) 可获得液态玻璃界面特效（毛玻璃卡片、渐变按钮与进度条、折射光晕背景）：

```bash
pip install pillow
```

未安装时程序自动降级为纯色界面，功能完全不受影响。

## 开发与测试

```bash
# 运行单元测试（151 项，不触网、不创建 GUI 窗口，约 0.03 秒）
python -m unittest discover -s tests -v

# 或使用 pytest
python -m pytest tests -v

# 代码卫生自检（语法、编码、未使用导入，仅标准库）
python -m tests.selfcheck
```

测试覆盖文件名净化、自定义工具强校验、占位符替换、hosts 屏蔽诊断、CDN 站点判定、响应头与进度解析、已安装检测容错、工具数据层一致性与 README 一致性。

```bash
# 校验内置工具库（不依赖 tkinter，可在任意 Python 环境运行）
python tooldata.py
```

CI 说明：

| 平台 | 配置 | 内容 |
| --- | --- | --- |
| GitHub | `.github/workflows/ci.yml` | windows-latest：语法检查 + 151 项单元测试 + 工具库校验 + 卫生自检 |
| Gitee | `.workflow/tools-data-check.yml` | Linux 容器：语法检查 + 工具库校验 |

Gitee 免费版流水线仅提供 Linux 容器，而本项目是 Windows 专用工具（需要 tkinter），因此 Gitee 侧只跑不依赖图形环境的数据层校验；完整单元测试以 GitHub 侧为准。

### 新增工具

编辑 `tools.py`，在 `TOOLS` 列表中追加：

```python
{
    "name": "工具名",
    "category": "开发环境 (IDE)",
    "description": "简介",
    "versions": [
        {"label": "1.0.0 (最新)", "url": "https://example.com/tool.zip"},
    ],
    "deploy": {"type": "extract", "verify": "C:\\Program Files\\Tool\\*"},
    "homepage": "https://example.com",
}
```

`validate_tool()` 会在启动与测试中校验全部定义，字段类型不符或协议非 http(s) 会被拒绝。

## 打包为 EXE

推荐使用 `build.spec`（其中声明了 `PIL.ImageTk` 等延迟导入模块的 `hiddenimports`，缺了会导致玻璃特效静默失效）：

```bash
pip install pyinstaller pillow
pyinstaller build.spec
```

产物位于 `dist\Programming-Tools-Downloader.exe`（约 33 MB，含 Pillow）。

> 也可用命令行：`pyinstaller --onefile --windowed --noupx --name "Programming-Tools-Downloader" --icon app_icon.ico app.py`，但这样不会应用 spec 里的 `hiddenimports`，需自行确认 Pillow 已打包（产物应 ≥ 20 MB）。

二进制产物不入库，请通过 Releases 或本地构建获取。

## 配置文件

| 文件 | 用途 |
| --- | --- |
| `config.json` | 保存下载目录等设置 |
| `custom_tools.json` | 导入的自定义工具 |

## 项目结构

```
Better-programming-tools-download/
├── app.py                  # 主程序：GUI + 下载引擎 + 部署器
├── tools.py                # 28 个工具的版本与部署配置
├── tooldata.py             # 零依赖数据层：工具校验与读写（CI 可独立运行）
├── ui_theme.py             # 液态玻璃主题引擎（渐变背景/毛玻璃面板/渐变控件）
├── ui_widgets.py           # 自绘玻璃控件（兼容 ttk 接口）
├── app_icon.ico            # 应用图标
├── run.bat                 # 启动脚本
├── build.spec              # PyInstaller 打包配置（含 Pillow hiddenimports）
├── CHANGELOG.md            # 更新日志
├── tests/
│   ├── test_app.py         # 单元测试（151 项）
│   ├── selfcheck.py        # 代码卫生自检
│   └── __init__.py
├── .github/
│   └── workflows/ci.yml    # GitHub CI：完整测试（windows-latest）
├── .workflow/
│   └── tools-data-check.yml # Gitee Go：数据层校验（Linux 容器）
└── dist/                   # 打包输出（已 gitignore）
    └── 编程工具下载器.exe
```

## 故障排查

| 现象 | 原因与处理 |
| --- | --- |
| 日志提示「被本机 hosts 屏蔽」 | 本机 hosts 把该域名指向了 `127.0.0.1`（常见于网络/拦截软件）。请检查 `C:\Windows\System32\drivers\etc\hosts` 或对应软件设置 |
| JetBrains / Docker 下载很慢或首次报 404 | 这些 CDN 会拒绝「非浏览器 TLS 指纹 + 浏览器 UA」的组合，程序已内置 `prefer_curl` 直接用 curl 模式跳过失败尝试 |
| GitHub 相关工具全部下载失败 | 多为 hosts 屏蔽或网络受限，同上；程序会在失败时自动诊断并提示 |
| 安装时弹出 UAC 窗口 | 需管理员权限的安装属正常现象，点「是」即可。Node.js、Go、OpenJDK、PowerShell 7、Python、Visual Studio、Docker 均会自动走提权通道 |
| MSI 安装失败(退出码 1603/1925) | 权限不足。程序对已标记 `need_admin` 的工具会自动弹 UAC；若仍失败，请以管理员身份运行本程序 |

## 安全说明

- 下载文件名统一经过白名单净化（`safe_filename`），防止路径穿越与命令注入
- 解压使用 Python 标准库，校验 Zip Slip 路径并限制解压总量（20 GB），防 zip bomb
- 提权安装通过 PowerShell `-EncodedCommand` 传递，不拼接 shell 字符串；`-PassThru` 回传真实退出码，失败不会误报成功
- 需管理员权限的工具（装入 `C:\Program Files` 的 Node.js、Go、OpenJDK、PowerShell 7、Python、Visual Studio、Docker）由程序自动走 UAC 提权通道，无需手动以管理员身份运行
- 自定义安装命令的占位符按上下文自动补引号，避免路径含空格被 shell 拆词
- 导入数据经 `validate_tool()` 强校验：URL 仅允许 http(s)，杜绝 `file://` 读取本地文件
- 需管理员权限的安装（如 Docker）会触发标准 UAC 弹窗

## 贡献指南

欢迎提交 Issue 与 PR：

1. 保持改动聚焦，每个 PR 解决一件事
2. 新增逻辑请在 `tests/test_app.py` 补充测试，确保 `python -m unittest discover -s tests` 通过
3. 提交前运行 `python -m tests.selfcheck`
4. 报告 bug 时请附上系统版本与日志面板输出

## 许可

见 [LICENSE](LICENSE)。
