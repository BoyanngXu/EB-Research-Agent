@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

echo ============================================
echo   公告 PDF 批量转储为文本
echo ============================================
echo.

set /p dir=PDF 所在目录（直接回车用当前目录）: 
set /p cln=转储前是否删除原有 txt？直接回车=删除；输入 keep 并回车=保留: 

if "%dir%"=="" set dir=%cd%

if "%cln%"=="keep" (
    python "scripts\pdf_dump.py" "%dir%"
) else (
    python "scripts\pdf_dump.py" "%dir%" --clean
)

echo.
pause
