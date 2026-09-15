@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

echo ============================================
echo   微信公众号 A 股文章爬虫（微信读书版）
echo ============================================
echo.
echo 说明：首次运行会弹出浏览器，需用微信扫码登录。
echo       登录态保存在 login_state.json，之后自动复用。
echo.

set /p n=抓取篇数（直接回车用 10 篇）: 
set /p kw=搜索关键词（直接回车按当前时间自动研判）: 
set /p dir=输出目录（直接回车用当前目录）: 

if "%n%"=="" set n=10
if "%dir%"=="" set dir=%cd%

if "%kw%"=="" (
    python "scripts\wechat_gzh_crawler_weread.py" -n %n% -o "%dir%"
) else (
    python "scripts\wechat_gzh_crawler_weread.py" -n %n% -k "%kw%" -o "%dir%"
)

echo.
pause
