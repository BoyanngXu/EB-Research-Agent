@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

echo ============================================
echo   深交所 - 现券交易信息（逐笔）自动下载
echo ============================================
echo.
echo 说明：深交所页面无需登录，导出时会自动把证券类别
echo       筛选为「非公开发行可交换公司债券」。
echo.

set /p mode=无头模式后台运行？输入 headless 并回车；直接回车为有窗口模式: 
set /p dir=保存到哪个目录？直接回车用当前目录: 

if "%dir%"=="" set dir=%cd%

if "%mode%"=="headless" (
    python "scripts\AutoDownload_sz.py" --headless --download-dir "%dir%"
) else (
    python "scripts\AutoDownload_sz.py" --download-dir "%dir%"
)

echo.
pause
