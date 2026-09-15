# -*- coding: utf-8 -*-
"""可交换债数据源自动下载 —— 公共工具模块

提供：依赖自检、配置读取、元素点击候选策略、表格日期提取、下载保存。
被 AutoDownload_yz.py / AutoDownload_sz.py 共用。
"""
import configparser
import datetime
import os
import re
import sys

# 本文件位于 <skill>/scripts/ 下
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_FILE = os.path.join(SKILL_DIR, "config.ini")
EXAMPLE_FILE = os.path.join(SKILL_DIR, "config.example.ini")

DEPS = {"playwright": "playwright", "ddddocr": "ddddocr", "PIL": "pillow"}


def check_deps(required):
    """required: 模块名列表，如 ["playwright", "ddddocr", "PIL"]"""
    missing = []
    for mod in required:
        try:
            __import__(mod)
        except ImportError:
            missing.append(DEPS.get(mod, mod))
    if missing:
        print("=" * 58)
        print("缺少依赖库，请先执行以下命令安装：")
        print()
        print(f"    pip install {' '.join(missing)}")
        if "playwright" in missing:
            print("    playwright install chromium")
        print()
        print(f"也可以直接双击上级目录的「安装依赖.bat」一键完成。")
        print("=" * 58)
        pause("\n按回车退出...")
        sys.exit(1)


def pause(prompt=""):
    """仅在交互式终端下暂停；非交互（如计划任务/管道）直接跳过。"""
    try:
        if sys.stdin and sys.stdin.isatty():
            input(prompt)
    except Exception:
        pass


def install_no_input():
    """在非交互环境下把 input 变成空操作，避免 EOFError 打断流程。"""
    if not (sys.stdin and sys.stdin.isatty()):
        try:
            import builtins
            builtins.input = lambda prompt="": ""
        except Exception:
            pass


def load_config(section):
    """读取 config.ini 中指定 section，返回 dict。缺失时给出明确提示。"""
    if not os.path.exists(CONFIG_FILE):
        print("=" * 58)
        print(f"未找到配置文件：{CONFIG_FILE}")
        print()
        if os.path.exists(EXAMPLE_FILE):
            print("请复制 config.example.ini 为 config.ini，并填入自己的账号信息：")
            print(f"    copy config.example.ini config.ini")
        print("=" * 58)
        pause("\n按回车退出...")
        sys.exit(1)

    cp = configparser.ConfigParser()
    cp.read(CONFIG_FILE, encoding="utf-8-sig")
    if not cp.has_section(section):
        print(f"[错误] config.ini 中缺少 [{section}] 配置段")
        pause("\n按回车退出...")
        sys.exit(1)
    return {k: (v or "").strip() for k, v in cp.items(section)}


def launch_browser(p, headless):
    """优先使用系统 Chrome/Edge（窗口醒目、指纹自然），失败回退 Playwright 内置 Chromium。"""
    launch_args = {
        "headless": headless,
        "args": ["--start-maximized", "--window-position=0,0"],
    }
    if not headless:
        for channel in ("chrome", "msedge"):
            try:
                b = p.chromium.launch(channel=channel, **launch_args)
                print(f"[浏览器] 使用系统 {channel}")
                return b
            except Exception:
                continue
    b = p.chromium.launch(**launch_args)
    print("[浏览器] 使用 Playwright 内置 Chromium")
    return b


def click_candidates(page, candidates, timeout=8000):
    """按顺序尝试多种选择器，点击第一个可见可点的元素。

    candidates: [(kind, selector)]，kind ∈ {role, locator, text}
    """
    for kind, sel in candidates:
        try:
            if kind == "role":
                loc = page.get_by_role("button", name=sel)
                if loc.count() > 0:
                    loc.first.click(timeout=timeout)
                    return True
            elif kind == "locator":
                loc = page.locator(sel)
                for i in range(loc.count()):
                    el = loc.nth(i)
                    try:
                        if el.is_visible():
                            el.click(timeout=timeout)
                            return True
                    except Exception:
                        continue
            elif kind == "text":
                loc = page.get_by_text(sel, exact=False)
                for i in range(loc.count()):
                    el = loc.nth(i)
                    try:
                        if el.is_visible():
                            el.click(timeout=timeout)
                            return True
                    except Exception:
                        continue
        except Exception:
            continue
    return False


DATE_PATTERNS = (
    r"(?<!\d)(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?(?!\d)",
    r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)",
)


def extract_table_date(page):
    """从页面表格里抓第一个合法日期，统一返回 YYYYMMDD。"""
    try:
        table_text = " ".join(page.locator("table td, table th").all_text_contents())
    except Exception:
        table_text = ""
    if not table_text.strip():
        try:
            table_text = page.locator("body").inner_text(timeout=5000)
        except Exception:
            table_text = ""
    for pattern in DATE_PATTERNS:
        m = re.search(pattern, table_text)
        if m:
            y, mo, d = (int(v) for v in m.groups())
            try:
                return datetime.date(y, mo, d).strftime("%Y%m%d")
            except ValueError:
                continue
    raise RuntimeError("未能从表格内提取有效日期")


def unique_path(directory, filename):
    """返回不覆盖已有文件的路径：重名时追加 (1) (2) ..."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(path):
        path = f"{base}({i}){ext}"
        i += 1
    return path
