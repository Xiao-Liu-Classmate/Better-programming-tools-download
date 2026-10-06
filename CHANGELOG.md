# 更新日志

本文件记录「编程工具下载器」的显著变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 变更

- **界面层迁移至 PySide6（Qt 6）**：自绘渲染层全部移除，控件、布局、
  样式、绘制均改由 Qt 原生 API 承担
  - 新增 `ui_qt.py`：主题引擎（QSS 样式表、玻璃卡片、渐变控件、
    径向光晕背景）与 Qt 原生控件封装
  - 新增 `ui_bind.py`：tkinter → Qt 适配层，使下载、部署、批量队列
    等业务逻辑保持原样
  - 新增 `check_qt_runtime.py`：打包产物自检（确认 Qt 运行时完整、
    WebEngine 等大件已裁剪）
  - 删除 `ui_theme.py`、`ui_widgets.py`（合计 930 行手写渲染）
  - 新增 `tests/test_runbat.py`（run.bat 实跑测试）、`requirements.txt`
  - 打包体积 33.19 MB → 35.95 MB

### 修复

- **`run.bat` 完全无法运行**：换行符为 LF（`cmd.exe` 要求 CRLF），
  多行被错误拼接，报出 `'0' 不是内部或外部命令`
  - 新增 `.gitattributes`，显式约束 `.bat`/`.cmd`/`.ps1` 用 CRLF、
    源码用 LF，从根源防止再犯
  - 改用 `goto` 顺序流程替代 `if/else` 块（块内 `%var%` 在解析期
    一次性展开，原 `if %errorlevel%==0` 即因此出错）
  - 所有解释器调用加 `call` 前缀：`cmd` 调用 `.bat` 若不加 `call`
    会替换当前批处理上下文而不返回，PATH 中存在 `python.bat` 时
    脚本会静默停在标题行、退出码却是 0
  - 探测 `python` / `py -3` / `py` 三种入口；**自动安装缺失的
    PySide6**（迁移 Qt 后由可选依赖变为必需，旧脚本无此提示）
  - 传递真实退出码，失败分支给出可操作指引
- 分类标签点击无法切换：`TreeShim._on_view_selection`（Qt
  `itemSelectionChanged` 的槽，即用户点击的唯一入口）只更新内部状态
  而不派发 `<<TreeviewSelect>>` 回调。程序化 `selection_set` 恰好会
  补发，故此前测试全绿而真实点击失效

### 计划中

- 断点续传：当前 `.partial_download` 每次启动即删除，无法续传
- 镜像源回退：官方源不可达时尝试备用镜像（需权衡供应链风险）
- 多线程分片下载
- 工具版本自动巡检：定期探测官方直链是否失效或跳转到新版本

## [4.1.0] - 2026-09-30

液态玻璃界面。核心业务逻辑（下载引擎、部署器、任务状态机、事件绑定、
快捷键）零改动。

发布标签 `v4.1.0`。预编译产物见双平台 Releases，附件名统一为
`Programming-Tools-Downloader.exe`。两侧体积不同（GitHub 19.45 MB、
Gitee 33.19 MB），因各自独立构建且 Pillow 版本不同 —— 功能一致。

SHA256：GitHub `7D8AB014BD0004B233FEB6494317CF0D61110E4E586FBF0073A1AAF51339A23A`
Gitee `0655D2C03DF6A992E04B5BB78F6E33E2CEDEE3403B3661D39C0A0DB4B953460F`

### 新增

- **液态玻璃界面**（可选依赖 Pillow，缺失时自动降级为纯色，功能不受影响）
  - `ui_theme.py` — 主题引擎：深色渐变 + 彩色光晕背景、圆角毛玻璃面板
    （半透明 + 顶部高光 + 边缘反光 + 柔和投影）、渐变按钮、渐变进度条
  - `ui_widgets.py` — 自绘控件 `GlassPanel` / `GlassButton` / `GlassEntry` /
    `GlassProgress`，全部兼容 ttk 接口（`state` / `text` / `configure` /
    `value` / `maximum` / `mode` / `start` / `stop`），故现有业务逻辑零改动
  - 玻璃卡片通过**裁切窗口背景**作为底衬实现"透出"，与卡片外背景连续
  - 界面元素：标题区、搜索栏、分类侧栏、工具列表、状态与进度、操作区、
    日志面板全部重做；深色右键菜单、细滚动条、无边框表头
  - 图标（对勾、下拉箭头）用矢量绘制 —— 微软雅黑缺 `✓` `▾` 字形会渲染成方块

### 修复

- `cancel_btn["state"]` 读到的是底层 Canvas 的 `-state`（恒为 normal），
  导致 **ESC 在空闲时也会触发取消**，写假日志并吃掉状态恢复回调。
  已为 `GlassButton` 补 `cget` / `__getitem__`
- 玻璃面板的投影留白被重复计算，导致每块面板右侧/底部的描边与圆角被裁掉
- 拖动窗口时背景按像素重建会阻塞主线程 —— 改为 1/4 分辨率生成 +
  180ms 去抖
- 图片缓存只按条数限流（最坏可达 1GB），改为按类型 + 累计像素双限流
- 进度条 `maximum` 传非法值时会把值塞回 kwargs，导致 `TclError` 沿调用链冒泡
- `retry_btn` 三处显示间距不一致（8/4/4），失败重显时按钮会跳动
- 深色主题下 `installed` / `downloading` 行仍用适配白底的深绿与浅蓝，刺眼且对比不足
- `ttk.Label` 在 clam 主题下带默认 focus 边框，文字后出现深色矩形

### 说明

- 依赖变化：核心功能仍**仅用标准库**（该版本引入的 Pillow 已在下一版被 PySide6 取代）
- 打包体积从 11.06 MB 增至约 33 MB（含 Pillow）
- 窗口默认尺寸 1180×820

## [4.0.0] - 2026-09-26

发布标签 `v4.0.0`。预编译产物见 GitHub Releases
（附件名 `Programming-Tools-Downloader-v4.0.0.exe`，11.06 MB，
SHA256 `3B5934E0E1E55A3411F33F9B02D17C642122DD47895911958CD5B3099B407375`）。

### 新增

- **28 款工具**（原 22 款），48 条官方直链
  - 语言运行时：Miniconda3、Flutter SDK
  - 开发环境：Visual Studio Community、Android Studio
  - 构建工具（新增分类）：Apache Maven、Gradle
  - 新增工具均取自非 GitHub 源，优先保证国内可用性
- **数据层抽离** `tooldata.py`：工具校验与读写不含任何 GUI 行为，可在无图形
  环境（CI 的 Linux 容器）运行，避免校验规则出现两份副本
- **`python tooldata.py [--stats]` 命令行入口**：校验内置工具库内在一致性
  （定义合法、工具名不重复、版本标签不重复、分类已声明且非空），
  供 CI 直接调用
- **Gitee Go 流水线**（`.workflow/`）：与 GitHub Actions 并存的双平台 CI
- **故障诊断** `check_hosts_blocking()`：下载失败时自动检测本机 hosts
  是否把目标域名指向回环地址，并回显具体域名与 IP
- **CDN 指纹适配** `prefer_curl`：JetBrains、Docker、Flutter、Gradle 等 CDN
  会按 TLS 指纹拒绝 urllib，这些域名直接走 curl 模式并省略自定义 User-Agent
- **任务世代号机制** `_task_seq`：取消或切换任务后，旧线程的迟到回调被
  丢弃，不再污染新任务的进度条与状态栏
- 单元测试 168 项（`tests/test_app.py`），不触网、不创建 GUI 窗口
- 代码卫生自检（`tests/selfcheck.py`），仅依赖标准库
- `CHANGELOG.md`

### 安全

- `validate_tool()` 强校验 `deploy` 字段类型与顶层 `homepage`，非法项剔除；
  杜绝损坏的自定义 JSON 导致启动崩溃
- `validate_tool()` 对 `category` 去除首尾空白，避免 `" 构建工具 "` 这类
  值通过校验后在界面出现空白分类页签
- 文件名白名单净化 `safe_filename()`，防路径穿越与命令注入
- 解压校验 Zip Slip 路径，并限制解压总量 20 GB，防 zip bomb
- 自定义安装命令的占位符按上下文自动补引号，兼容单/双引号模板，
  避免路径含空格被 shell 拆词
- 提权安装抽出 `Deployer._run_elevated()` 公共通道，MSI 与 EXE 共用；
  `-PassThru` 回传真实退出码，并处理进程对象为空的情况，
  修复安装失败被误报为成功
- 导入数据仅允许 `http(s)` 协议，杜绝 `file://` 读取本地文件
- 导出工具时过滤 `_` 前缀的运行时内部字段
- 导入自定义工具时若落盘失败会明确报错，不再谎报「导入成功」

### 修复

- **MSI 静默安装缺少提权通道**：Node.js、Go、OpenJDK、PowerShell 7 均安装到
  `C:\Program Files`，未提权时 msiexec 返回 1603/1925 必然失败。
  现已支持 `need_admin` 走 UAC 通道；Python（`InstallAllUsers=1`）一并补上
- 取消或切换任务后旧线程回调污染新任务状态（可能致并行下载、按钮错乱）
- 版本列表取自上一个工具，导致下载错误 URL 并按新工具的部署配置安装
- 首页首屏先显示「未安装」再全量重绘的状态闪烁
- `_install_custom` 二次净化文件名，把 `xxx (1).exe` 的括号替换为下划线
- 窗口关闭后后台线程访问已销毁控件
- **IntelliJ IDEA 与 PyCharm 的 `verify` 路径完全相同**，装其中一个会让
  另一个也显示「已装」；现精确到产品名
- `tools.py` 文档字符串中的无效转义序列（未来 Python 会升级为 SyntaxError）
- 复制 URL 的临时状态提示会覆盖任务进行中的状态

### 工程

- 新增 `.gitignore`，排除 `__pycache__/`、`build/`、`dist/`、二进制产物与
  运行时配置；`dist/*.exe`（11 MB）已移出版本库
- README 重写：徽章、功能、快捷键、自定义工具格式、故障排查、
  开发与测试、贡献指南、安全说明
- 「关于」对话框的工具数量改为引用 `len(TOOLS)`，不再硬编码
- 版本标签去除会误导的「最新」字样，README 增加「关于版本号」说明
- GitHub / Gitee 双平台同步

## [3.x 及更早]

见提交历史。早期版本提供工具直链下载、静默安装、批量部署与已安装检测。
