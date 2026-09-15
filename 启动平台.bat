@echo off
setlocal EnableExtensions
chcp 65001 >NUL
title EB 投研 Agent 平台
cd /d "%~dp0"

echo.
echo   EB 投研 Agent 平台  —— 启动中
echo ============================================================
echo.

REM 1) 项目自带虚拟环境（推荐：拷目录即走，不依赖本机装没装 Python）
set "PYEXE=%~dp0.venv\Scripts\python.exe"
if exist "%PYEXE%" goto run

REM 2) Doubao 沙箱自带解释器（版本目录会轮换，只能遍历不能写死）
set "PYEXE="
for /d %%D in ("%LOCALAPPDATA%\Doubao\User Data\sandbox_runtime\bases\*") do (
    if not defined PYEXE if exist "%%~D\python\python.exe" set "PYEXE=%%~D\python\python.exe"
)
if defined PYEXE goto run

REM 兜底：依次尝试 PATH 里的常见命令
where python >NUL 2>NUL
if %errorlevel%==0 set "PYEXE=python" & goto run
where py >NUL 2>NUL
if %errorlevel%==0 set "PYEXE=py -3" & goto run
where python3 >NUL 2>NUL
if %errorlevel%==0 set "PYEXE=python3" & goto run

echo.
echo   [未找到 Python]
echo   请先安装 Python 3.8 以上版本（安装时勾选 Add Python to PATH），
echo   然后重新双击本文件。
echo.
echo   下载地址： https://www.python.org/downloads/
echo.
pause
exit /b 1

:run
echo   使用解释器：%PYEXE%
echo.
echo   若端口被占用，脚本会自动换一个端口启动。
echo.
%PYEXE% main.py
if %errorlevel%==0 exit /b 0

echo.
echo   main.py 退出异常。尝试自动换端口 9000 ... 
%PYEXE% main.py --port 9000
if %errorlevel%==0 exit /b 0

echo.
echo   main.py 退出异常。尝试自动换端口 9001 ...
%PYEXE% main.py --port 9001

echo.
echo   ============================================================
echo   服务已停止。按任意键关闭本窗口。
echo ============================================================
pause
