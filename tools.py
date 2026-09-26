# -*- coding: utf-8 -*-
"""内置工具列表:每个工具支持多版本直链 + 一键部署

deploy 字段说明:
  type       安装方式
    msi      → msiexec /quiet /i <file>
    exe      → 静默安装器 (各工具参数不同)
    extract  → 解压到 <dest>/{name}/ 目录
    custom   → 使用 cmd 自定义命令
    none     → 无自动安装(仅下载)
  cmd        可选,自定义安装命令 (type=custom 时使用)
  args       可选,exe 静默安装参数
  need_admin 是否需要管理员权限(会弹 UAC 提示)
  verify     安装完成后检查该路径是否存在
  homepage   可选,直接下载失败时引导到浏览器
"""

CATEGORIES = [
    "语言运行时",
    "开发环境 (IDE)",
    "版本控制与命令行",
    "数据库与容器",
]

TOOLS = [
    # ━━━━━━━━━━━━━━━ 语言运行时 ━━━━━━━━━━━━━━━
    {
        "category": "语言运行时",
        "name": "Python",
        "description": "官方安装包,含 pip",
        "deploy": {
            "type": "exe",
            "args": "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0",
            "verify": r"C:\Program Files\Python312\python.exe",
        },
        "versions": [
            {"label": "3.12.5 (最新)", "url": "https://www.python.org/ftp/python/3.12.5/python-3.12.5-amd64.exe"},
            {"label": "3.11.9", "url": "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"},
            {"label": "3.10.11", "url": "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"},
        ],
    },
    {
        "category": "语言运行时",
        "name": "Node.js",
        "description": "JavaScript 运行时,含 npm",
        "deploy": {
            "type": "msi",
            "verify": r"C:\Program Files\nodejs\node.exe",
        },
        "versions": [
            {"label": "v20.17.0 (LTS)", "url": "https://nodejs.org/dist/v20.17.0/node-v20.17.0-x64.msi"},
            {"label": "v22.11.0", "url": "https://nodejs.org/dist/v22.11.0/node-v22.11.0-x64.msi"},
            {"label": "v18.20.4 (LTS)", "url": "https://nodejs.org/dist/v18.20.4/node-v18.20.4-x64.msi"},
        ],
    },
    {
        "category": "语言运行时",
        "name": "OpenJDK (Temurin)",
        "description": "Eclipse 基金会官方构建,含 JRE",
        "deploy": {
            "type": "msi",
            "verify": r"C:\Program Files\Eclipse Adoptium",
        },
        "versions": [
            {"label": "21.0.4+7 (LTS)", "url": "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.4%2B7/OpenJDK21U-jdk_x64_windows_hotspot_21.0.4_7.msi"},
            {"label": "17.0.12+7 (LTS)", "url": "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.12%2B7/OpenJDK17U-jdk_x64_windows_hotspot_17.0.12_7.msi"},
            {"label": "11.0.24+8 (LTS)", "url": "https://github.com/adoptium/temurin11-binaries/releases/download/jdk-11.0.24%2B8/OpenJDK11U-jdk_x64_windows_hotspot_11.0.24_8.msi"},
        ],
    },
    {
        "category": "语言运行时",
        "name": "Go",
        "description": "Google 官方 MSI 安装包",
        "deploy": {
            "type": "msi",
            "verify": r"C:\Program Files\Go\bin\go.exe",
        },
        "versions": [
            {"label": "1.23.1 (最新)", "url": "https://go.dev/dl/go1.23.1.windows-amd64.msi"},
            {"label": "1.22.7", "url": "https://go.dev/dl/go1.22.7.windows-amd64.msi"},
        ],
    },
    {
        "category": "语言运行时",
        "name": "Rust (rustup)",
        "description": "官方安装器,命令行交互安装",
        "deploy": {
            "type": "custom",
            "cmd": 'cmd.exe /c "echo. | {file} -y --default-toolchain stable"',
            "verify": r"C:\Users\{user}\.cargo\bin\rustc.exe",
        },
        "versions": [
            {"label": "最新版", "url": "https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe"},
        ],
    },
    {
        "category": "语言运行时",
        "name": ".NET SDK",
        "description": "微软官方 SDK,含 dotnet CLI",
        "deploy": {
            "type": "exe",
            "args": "/quiet /install /norestart",
            "verify": r"C:\Program Files\dotnet\dotnet.exe",
        },
        "versions": [
            {"label": "9.0.100 (最新)", "url": "https://builds.dotnet.microsoft.com/dotnet/Sdk/9.0.100/dotnet-sdk-9.0.100-win-x64.exe"},
            {"label": "8.0.400 (LTS)", "url": "https://builds.dotnet.microsoft.com/dotnet/Sdk/8.0.400/dotnet-sdk-8.0.400-win-x64.exe"},
        ],
    },

    # ━━━━━━━━━━━━━━━ 开发环境 (IDE) ━━━━━━━━━━━━━━━
    {
        "category": "开发环境 (IDE)",
        "name": "Visual Studio Code",
        "description": "微软官方安装包(用户版)",
        "deploy": {
            "type": "exe",
            "args": "/verysilent /mergetasks=!runcode",
            "verify": r"{appdata}\..\Local\Programs\Microsoft VS Code\Code.exe",
        },
        "versions": [
            {"label": "最新稳定版", "url": "https://update.code.visualstudio.com/latest/win32-x64-user/stable"},
        ],
    },
    {
        "category": "开发环境 (IDE)",
        "name": "IntelliJ IDEA (社区版)",
        "description": "JetBrains 官方免费社区版",
        "deploy": {
            "type": "exe",
            "args": "/S",
            "verify": r"C:\Program Files\JetBrains",
        },
        "versions": [
            {"label": "2025.3 (最新)", "url": "https://download.jetbrains.com/idea/idea-2025.3.exe"},
        ],
    },
    {
        "category": "开发环境 (IDE)",
        "name": "PyCharm (社区版)",
        "description": "JetBrains 官方免费社区版",
        "deploy": {
            "type": "exe",
            "args": "/S",
            "verify": r"C:\Program Files\JetBrains",
        },
        "versions": [
            {"label": "2025.2.6 (最新)", "url": "https://download.jetbrains.com/python/pycharm-community-2025.2.6.exe"},
            {"label": "2025.2.5", "url": "https://download.jetbrains.com/python/pycharm-community-2025.2.5.exe"},
            {"label": "2025.1.6", "url": "https://download.jetbrains.com/python/pycharm-community-2025.1.6.exe"},
        ],
    },
    {
        "category": "开发环境 (IDE)",
        "name": "Eclipse IDE for Java",
        "description": "官方镜像下载(zip 压缩包)",
        "deploy": {
            "type": "extract",
            "verify": r"Eclipse",
        },
        "versions": [
            {"label": "2024-09 R (最新)", "url": "https://www.eclipse.org/downloads/download.php?file=/technology/epp/downloads/release/2024-09/R/eclipse-java-2024-09-R-win32-x86_64.zip"},
            {"label": "2024-06 R", "url": "https://www.eclipse.org/downloads/download.php?file=/technology/epp/downloads/release/2024-06/R/eclipse-java-2024-06-R-win32-x86_64.zip"},
        ],
    },

    # ━━━━━━━━━━━━━━━ 版本控制与命令行 ━━━━━━━━━━━━━━━
    {
        "category": "版本控制与命令行",
        "name": "Git for Windows",
        "description": "官方 64 位安装包",
        "deploy": {
            "type": "exe",
            "args": "/VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /COMPONENTS=icons,ext,ext\\shellhere,ext\\guihere,gitlfs,assoc,assoc_sh",
            "verify": r"C:\Program Files\Git\bin\git.exe",
        },
        "versions": [
            {"label": "2.46.0 (最新)", "url": "https://github.com/git-for-windows/git/releases/download/v2.46.0.windows.1/Git-2.46.0-64-bit.exe"},
            {"label": "2.45.2", "url": "https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-64-bit.exe"},
            {"label": "2.44.0", "url": "https://github.com/git-for-windows/git/releases/download/v2.44.0.windows.1/Git-2.44.0-64-bit.exe"},
        ],
    },
    {
        "category": "版本控制与命令行",
        "name": "GitHub Desktop",
        "description": "官方安装器",
        "deploy": {
            "type": "exe",
            "args": "/verysilent",
            "verify": r"{appdata}\..\Local\GitHubDesktop\GitHubDesktop.exe",
        },
        "versions": [
            {"label": "最新版", "url": "https://central.github.com/deployments/desktop/desktop/latest/win32"},
        ],
    },
    {
        "category": "版本控制与命令行",
        "name": "Windows Terminal",
        "description": "微软官方终端(msixbundle)",
        "deploy": {
            "type": "custom",
            "cmd": "powershell.exe -Command \"Add-AppxPackage -Path '{file}'\"",
            "verify": r"C:\Program Files\WindowsApps\Microsoft.WindowsTerminal",
        },
        "versions": [
            {"label": "1.24.11911 (最新)", "url": "https://github.com/microsoft/terminal/releases/download/v1.24.11911.0/Microsoft.WindowsTerminal_1.24.11911.0_8wekyb3d8bbwe.msixbundle"},
            {"label": "1.22.11141", "url": "https://github.com/microsoft/terminal/releases/download/v1.22.11141.0/Microsoft.WindowsTerminal_1.22.11141.0_8wekyb3d8bbwe.msixbundle"},
        ],
    },
    {
        "category": "版本控制与命令行",
        "name": "PowerShell 7",
        "description": "微软官方 MSI 安装包",
        "deploy": {
            "type": "msi",
            "verify": r"C:\Program Files\PowerShell\7\pwsh.exe",
        },
        "versions": [
            {"label": "7.5.1 (最新)", "url": "https://github.com/PowerShell/PowerShell/releases/download/v7.5.1/PowerShell-7.5.1-win-x64.msi"},
            {"label": "7.4.5", "url": "https://github.com/PowerShell/PowerShell/releases/download/v7.4.5/PowerShell-7.4.5-win-x64.msi"},
        ],
    },
    {
        "category": "版本控制与命令行",
        "name": "7-Zip",
        "description": "官方压缩解压工具(64位)",
        "deploy": {
            "type": "exe",
            "args": "/S",
            "verify": r"C:\Program Files\7-Zip\7z.exe",
        },
        "versions": [
            {"label": "24.08 (最新)", "url": "https://www.7-zip.org/a/7z2408-x64.exe"},
        ],
    },

    # ━━━━━━━━━━━━━━━ 数据库与容器 ━━━━━━━━━━━━━━━
    {
        "category": "数据库与容器",
        "name": "MySQL Installer",
        "description": "官方社区版安装器,含 MySQL Server",
        "homepage": "https://dev.mysql.com/downloads/installer/",
        "deploy": {"type": "none"},
        "versions": [
            {"label": "8.0.46 (最新)", "url": "https://dev.mysql.com/get/Downloads/MySQLInstaller/mysql-installer-community-8.0.46.0.msi"},
        ],
    },
    {
        "category": "数据库与容器",
        "name": "PostgreSQL",
        "description": "EDB 官方 Windows 安装包",
        "deploy": {
            "type": "exe",
            "args": "--mode unattended --superpassword postgres --serverport 5432",
            "verify": r"C:\Program Files\PostgreSQL",
        },
        "versions": [
            {"label": "17.2 (最新)", "url": "https://get.enterprisedb.com/postgresql/postgresql-17.2-1-windows-x64.exe"},
            {"label": "16.4", "url": "https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64.exe"},
        ],
    },
    {
        "category": "数据库与容器",
        "name": "MongoDB",
        "description": "官方社区版(zip 压缩包)",
        "deploy": {
            "type": "extract",
            "verify": r"MongoDB",
        },
        "versions": [
            {"label": "8.0.0 (最新)", "url": "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-8.0.0.zip"},
            {"label": "7.0.14", "url": "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-7.0.14.zip"},
        ],
    },
    {
        "category": "数据库与容器",
        "name": "SQLite Tools",
        "description": "官方命令行工具(sqlite3.exe 等)",
        "deploy": {
            "type": "extract",
            "verify": r"sqlite3.exe",
        },
        "versions": [
            {"label": "3.49.0 (最新)", "url": "https://www.sqlite.org/2025/sqlite-tools-win-x64-3490100.zip"},
            {"label": "3.46.0", "url": "https://www.sqlite.org/2024/sqlite-tools-win-x64-3460100.zip"},
        ],
    },
    {
        "category": "数据库与容器",
        "name": "Docker Desktop",
        "description": "官方安装器",
        "homepage": "https://www.docker.com/products/docker-desktop/",
        "deploy": {
            "type": "exe",
            "args": "--quiet --accept-license",
            "need_admin": True,
            "verify": r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
        },
        "versions": [
            {"label": "最新版", "url": "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"},
        ],
    },
    {
        "category": "数据库与容器",
        "name": "DBeaver Community",
        "description": "开源多数据库客户端(zip 压缩包)",
        "deploy": {
            "type": "extract",
            "verify": r"dbeaver.exe",
        },
        "versions": [
            {"label": "24.2.1 (最新)", "url": "https://github.com/dbeaver/dbeaver/releases/download/24.2.1/dbeaver-ce-24.2.1-win32.win32.x86_64.zip"},
            {"label": "24.1.5", "url": "https://github.com/dbeaver/dbeaver/releases/download/24.1.5/dbeaver-ce-24.1.5-win32.win32.x86_64.zip"},
        ],
    },
    {
        "category": "数据库与容器",
        "name": "HeidiSQL",
        "description": "轻量级 MySQL/PostgreSQL 客户端",
        "deploy": {
            "type": "exe",
            "args": "/SILENT",
            "verify": r"C:\Program Files\HeidiSQL\heidisql.exe",
        },
        "versions": [
            {"label": "12.21 (最新)", "url": "https://github.com/HeidiSQL/HeidiSQL/releases/download/v12.21/HeidiSQL_12.21.0.7344_Setup.exe"},
            {"label": "12.20", "url": "https://github.com/HeidiSQL/HeidiSQL/releases/download/v12.20/HeidiSQL_12.20.0.7320_Setup.exe"},
        ],
    },
]
