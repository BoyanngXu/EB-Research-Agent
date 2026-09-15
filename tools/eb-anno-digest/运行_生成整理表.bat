@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

echo ============================================
echo   公告整理表生成（JSON / CSV → xlsx）
echo ============================================
echo.

set /p input=输入文件路径（如 input.json 或 input.csv）: 
set /p mode=严格模式（有问题就中止）？输入 strict 并回车；直接回车跳过: 

if "%mode%"=="strict" (
    python "scripts\build_anno_xlsx.py" "%input%" --strict
) else (
    python "scripts\build_anno_xlsx.py" "%input%"
)

echo.
pause
