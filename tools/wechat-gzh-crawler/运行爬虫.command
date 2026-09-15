#!/bin/bash
cd "$(dirname "$0")" || exit 1

echo "============================================"
echo "  微信公众号 A 股文章爬虫（微信读书版）"
echo "============================================"
echo
echo "说明：首次运行会弹出浏览器，需用微信扫码登录。"
echo "      登录态保存在 login_state.json，之后自动复用。"
echo

read -p "抓取篇数（直接回车用 10 篇）: " n
read -p "搜索关键词（直接回车按当前时间自动研判）: " kw
read -p "输出目录（直接回车用当前目录）: " dir

[ -z "$n" ] && n=10
[ -z "$dir" ] && dir="$(pwd)"

if [ -z "$kw" ]; then
    python3 "scripts/wechat_gzh_crawler_weread.py" -n "$n" -o "$dir"
else
    python3 "scripts/wechat_gzh_crawler_weread.py" -n "$n" -k "$kw" -o "$dir"
fi

echo
echo "执行完毕，按回车键退出..."
read
