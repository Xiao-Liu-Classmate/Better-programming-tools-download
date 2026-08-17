# -*- coding: utf-8 -*-
"""内置工具列表:全部使用官方直链,均为 Windows x64 版本"""

CATEGORIES = [
    "语言运行时",
    "开发环境 (IDE)",
    "版本控制与命令行",
    "数据库与容器",
]

TOOLS = [
    # ---------------- 语言运行时 ----------------
    {
        "category": "语言运行时",
        "name": "Python",
        "version": "3.12.5 (64位)",
        "description": "官方安装包,含 pip",
        "url": "https://www.python.org/ftp/python/3.12.5/python-3.12.5-amd64.exe",
    },
    {
        "category": "语言运行时",
        "name": "Node.js",
        "version": "v20.17.0 LTS",
        "description": "JavaScript 运行时,含 npm",
        "url": "https://nodejs.org/dist/v20.17.0/node-v20.17.0-x64.msi",
    },
    {
        "category": "语言运行时",
        "name": "OpenJDK 21 (Temurin)",
        "version": "21.0.4+7",
        "description": "Eclipse 基金会官方构建,含 JRE",
        "url": "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.4%2B7/OpenJDK21U-jdk_x64_windows_hotspot_21.0.4_7.msi",
    },
    {
        "category": "语言运行时",
        "name": "Go",
        "version": "1.23.1",
        "description": "Google 官方 MSI 安装包",
        "url": "https://go.dev/dl/go1.23.1.windows-amd64.msi",
    },
    {
        "category": "语言运行时",
        "name": "Rust (rustup)",
        "version": "最新版",
        "description": "官方安装器,命令行交互安装",
        "url": "https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe",
    },
    {
        "category": "语言运行时",
        "name": ".NET SDK 8",
        "version": "8.0.400",
        "description": "微软官方 SDK,含 dotnet CLI",
        "url": "https://builds.dotnet.microsoft.com/dotnet/Sdk/8.0.400/dotnet-sdk-8.0.400-win-x64.exe",
    },

    # ---------------- 开发环境 (IDE) ----------------
    {
        "category": "开发环境 (IDE)",
        "name": "Visual Studio Code",
        "version": "最新稳定版",
        "description": "微软官方安装包(用户版)",
        "url": "https://update.code.visualstudio.com/latest/win32-x64-user/stable",
    },
    {
        "category": "开发环境 (IDE)",
        "name": "IntelliJ IDEA (社区版)",
        "version": "2025.3",
        "description": "JetBrains 官方免费社区版",
        "url": "https://download.jetbrains.com/idea/idea-2025.3.exe",
    },
    {
        "category": "开发环境 (IDE)",
        "name": "PyCharm (社区版)",
        "version": "2025.2.6",
        "description": "JetBrains 官方免费社区版",
        "url": "https://download.jetbrains.com/python/pycharm-community-2025.2.6.exe",
    },
    {
        "category": "开发环境 (IDE)",
        "name": "Eclipse IDE for Java",
        "version": "2024-06 R",
        "description": "官方镜像下载(zip 压缩包)",
        "url": "https://www.eclipse.org/downloads/download.php?file=/technology/epp/downloads/release/2024-06/R/eclipse-java-2024-06-R-win32-x86_64.zip",
    },

    # ---------------- 版本控制与命令行 ----------------
    {
        "category": "版本控制与命令行",
        "name": "Git for Windows",
        "version": "2.46.0",
        "description": "官方 64 位安装包",
        "url": "https://github.com/git-for-windows/git/releases/download/v2.46.0.windows.1/Git-2.46.0-64-bit.exe",
    },
    {
        "category": "版本控制与命令行",
        "name": "GitHub Desktop",
        "version": "最新版",
        "description": "官方安装器(自动跳转最新版)",
        "url": "https://central.github.com/deployments/desktop/desktop/latest/win32",
    },
    {
        "category": "版本控制与命令行",
        "name": "Windows Terminal",
        "version": "1.24.11911",
        "description": "微软官方终端(msixbundle)",
        "url": "https://github.com/microsoft/terminal/releases/download/v1.24.11911.0/Microsoft.WindowsTerminal_1.24.11911.0_8wekyb3d8bbwe.msixbundle",
    },
    {
        "category": "版本控制与命令行",
        "name": "PowerShell 7",
        "version": "7.4.5",
        "description": "微软官方 MSI 安装包",
        "url": "https://github.com/PowerShell/PowerShell/releases/download/v7.4.5/PowerShell-7.4.5-win-x64.msi",
    },
    {
        "category": "版本控制与命令行",
        "name": "7-Zip",
        "version": "24.08",
        "description": "官方压缩解压工具(64位)",
        "url": "https://www.7-zip.org/a/7z2408-x64.exe",
    },

    # ---------------- 数据库与容器 ----------------
    {
        "category": "数据库与容器",
        "name": "MySQL Installer",
        "version": "8.0.46",
        "description": "官方社区版安装器,含 MySQL Server",
        "url": "https://dev.mysql.com/get/Downloads/MySQLInstaller/mysql-installer-community-8.0.46.0.msi",
        "homepage": "https://dev.mysql.com/downloads/installer/",
    },
    {
        "category": "数据库与容器",
        "name": "PostgreSQL",
        "version": "16.4",
        "description": "EDB 官方 Windows 安装包",
        "url": "https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64.exe",
    },
    {
        "category": "数据库与容器",
        "name": "MongoDB",
        "version": "8.0.0",
        "description": "官方社区版(zip 压缩包)",
        "url": "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-8.0.0.zip",
    },
    {
        "category": "数据库与容器",
        "name": "SQLite Tools",
        "version": "3.49.0",
        "description": "官方命令行工具(sqlite3.exe 等)",
        "url": "https://www.sqlite.org/2025/sqlite-tools-win-x64-3490100.zip",
    },
    {
        "category": "数据库与容器",
        "name": "Docker Desktop",
        "version": "最新版",
        "description": "官方安装器(自动跳转最新版)",
        "url": "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe",
        "homepage": "https://www.docker.com/products/docker-desktop/",
    },
    {
        "category": "数据库与容器",
        "name": "DBeaver Community",
        "version": "24.2.1",
        "description": "开源多数据库客户端(zip 压缩包)",
        "url": "https://github.com/dbeaver/dbeaver/releases/download/24.2.1/dbeaver-ce-24.2.1-win32.win32.x86_64.zip",
    },
    {
        "category": "数据库与容器",
        "name": "HeidiSQL",
        "version": "12.21",
        "description": "轻量级 MySQL/PostgreSQL 客户端",
        "url": "https://github.com/HeidiSQL/HeidiSQL/releases/download/v12.21/HeidiSQL_12.21.0.7344_Setup.exe",
    },
]