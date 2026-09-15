#!/bin/bash
cd "$(dirname "$0")" || exit 1

echo "============================================"
echo "  可交换债数据.xlsx 合并重建"
echo "============================================"
echo

read -p "请输入日期目录（如 20260817，或完整路径），直接回车用最新: " day
read -p "日期目录所在根目录（直接回车用本 skill 目录）: " root

if [ -z "$root" ]; then
    python3 "scripts/可交换债数据.py" "$day"
else
    python3 "scripts/可交换债数据.py" "$day" --base "$root"
fi

echo
echo "执行完毕，按回车键退出..."
read
