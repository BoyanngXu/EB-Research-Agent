@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

echo ============================================
echo   xxxxx - 中证可交换债券估值 自动下载
echo ============================================
echo.

if not exist "config.ini" (
    echo [提示] 首次使用，正在从模板创建 config.ini ...
    copy "config.example.ini" "config.ini" >nul
    echo [提示] 已创建 config.ini，请用记事本打开填写账号密码后重新运行本脚本。
    echo.
    notepad "config.ini"
    pause
    exit /b 0
)

set /p mode=无头模式后台运行？输入 headless 并回车；直接回车为有窗口模式: 
set /p dir=保存到哪个目录？直接回车用当前目录: 

if "%dir%"=="" set dir=%cd%

if "%mode%"=="headless" (
    python "scripts\AutoDownload_xx.py" --headless --download-dir "%dir%"
) else (
    python "scripts\AutoDownload_xx.py" --download-dir "%dir%"
)

echo.
pause
