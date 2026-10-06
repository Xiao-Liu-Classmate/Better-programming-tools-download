@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"

echo ============================================
echo   编程工具下载器
echo ============================================
echo.

REM ============ 1. 定位 Python 解释器 ============
REM 用 goto 顺序流程而非 if/else 块: 括号块中的 %var% 在解析期就全部
REM 展开, 块内 set 的结果后面读不到。
REM 所有调用加 call: cmd 调用 .bat 时不加 call 会替换当前批处理
REM 上下文而不返回; PATH 中若存在 python.bat(虚拟环境/旧安装),
REM 脚本会静默停在标题行。对 .exe 加 call 无副作用。
set "PY="
call python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto :have_python

call py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto :have_python

call py -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py"
if defined PY goto :have_python

goto :no_python

:have_python
echo 使用解释器: %PY%
call %PY% --version
echo.

REM ============ 2. 检查界面依赖 ============
REM PySide6 自界面层迁移至 Qt 后成为**必需**依赖(旧版仅可选的
REM Pillow)。缺失会直接 ModuleNotFoundError, 故在此拦截并自动安装。
call %PY% -c "import PySide6" >nul 2>nul
if not errorlevel 1 goto :run_app

echo [提示] 缺少界面依赖 PySide6 ^(Qt 6^), 正在自动安装...
echo.
call %PY% -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :dep_failed

REM ============ 3. 启动 ============
:run_app
call %PY% app.py
set "RC=%errorlevel%"
if "%RC%"=="0" goto :ok
goto :failed

:ok
echo.
echo 已正常退出。
pause
exit /b 0

:no_python
echo [错误] 未找到可用的 Python 3。
echo.
echo 请先安装: https://www.python.org/downloads/
echo 安装时务必勾选 "Add python.exe to PATH"。
echo.
pause
exit /b 1

:dep_failed
echo.
echo [错误] PySide6 安装失败。
echo.
echo 可手动执行以下命令后重试:
echo     %PY% -m pip install -r requirements.txt
echo.
echo 若下载缓慢, 可改用国内镜像:
echo     %PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
pause
exit /b 1

:failed
echo.
echo [错误] 程序异常退出, 退出码 %RC%
echo 如需查看完整错误, 请在命令行执行:  %PY% app.py
echo.
pause
exit /b %RC%
