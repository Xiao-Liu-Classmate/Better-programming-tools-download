@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   编程工具下载器
echo ============================================
where python >nul 2>nul
if %errorlevel%==0 (
    python app.py
) else (
    py -3 app.py
)
if errorlevel 1 (
    echo.
    echo [错误] 未找到 Python,请先安装 Python 3 后重试。
    echo 下载地址: https://www.python.org/downloads/
)
pause
