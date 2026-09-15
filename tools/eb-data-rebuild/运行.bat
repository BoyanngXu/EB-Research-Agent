@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

echo ============================================
echo   可交换债数据.xlsx 合并重建
echo ============================================
echo.

set /p day=请输入日期目录（如 20260817，或完整路径），直接回车列出最新: 
set /p root=日期目录所在根目录（直接回车用本 skill 目录）: 

if "%root%"=="" (
    python "scripts\可交换债数据.py" %day%
) else (
    python "scripts\可交换债数据.py" %day% --base "%root%"
)

echo.
pause
