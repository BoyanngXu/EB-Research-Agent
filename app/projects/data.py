# -*- coding: utf-8 -*-
"""Data 项目：数据源自动下载 + 每日成交/估值总表重建。

两块能力（对应两个 skill，互不干扰）：
    下载：eb-data-download（xxxxx中证估值 / 深交所逐笔）
    重建：eb-data-rebuild（4 份源文件 → 一张 15 列总表）
"""
import os
import re
import time

from . import base

DATE_RE = re.compile(r"^\d{8}$")


def list_dates(data_dir=None):
    """列出数据根目录下的日期目录（YYYYMMDD），新的在前。"""
    d = data_dir or base.workspace("data")
    items = [s for s in base.subdirs(d) if DATE_RE.match(s["name"])]
    items.sort(key=lambda x: x["name"], reverse=True)
    return {"root": (d or "").replace("\\", "/"), "dates": items}


def latest_date(data_dir=None):
    r = list_dates(data_dir)
    return r["dates"][0]["name"] if r["dates"] else ""


# ---------------------------------------------------------------- 下载
def download_xx(download_dir=None, headless=False):
    """xxxxx：中证可交换债券估值（需登录 + 验证码识别）。"""
    d = download_dir or base.workspace("data")
    cmd = [base.python_exe(), base.script_path("eb-data-download", "AutoDownload_xx.py"),
           "--download-dir", d]
    if headless:
        cmd.append("--headless")
    started = time.time()

    def on_done(task):
        return _picked_outputs(d, {"中证可交换债券估值"}, started)

    return base.run("下载中证可交换债估值（xxxxx）", "data", cmd, on_done=on_done)


def download_sz(download_dir=None, headless=True):
    """深交所：现券交易信息（逐笔），免登录。"""
    d = download_dir or base.workspace("data")
    cmd = [base.python_exe(), base.script_path("eb-data-download", "AutoDownload_sz.py"),
           "--download-dir", d]
    if headless:
        cmd.append("--headless")

    started = time.time()

    def on_done(task):
        return _picked_outputs(d, {"现券交易信息"}, started)

    return base.run("下载深交所逐笔成交", "data", cmd, on_done=on_done)


def _picked_outputs(root, keywords, started):
    """下载脚本会把文件放进 <root>/<数据日期>/，递归找最近产出。"""
    hits = []
    for name in sorted(os.listdir(root), reverse=True) if os.path.isdir(root) else []:
        sub = os.path.join(root, name)
        if not os.path.isdir(sub):
            continue
        for f in base.newest_files(sub, {".xlsx"}, limit=20, since=started):
            if any(k in f["name"] for k in keywords):
                hits.append(f)
    if not hits:
        for f in base.newest_files(root, {".xlsx"}, limit=20, since=started):
            if any(k in f["name"] for k in keywords):
                hits.append(f)
    return {"outputs": hits}


# ---------------------------------------------------------------- 重建
def rebuild(date_dir=None, base_dir=None, no_template=False):
    """重建某日总表。date_dir 可为 YYYYMMDD 或完整路径。"""
    if not date_dir:
        date_dir = latest_date(base_dir)
    if not date_dir:
        raise ValueError("没有可用的日期目录，请先下载数据或手动指定")
    cmd = [base.python_exe(), base.script_path("eb-data-rebuild", "可交换债数据.py"), date_dir]
    if base_dir:
        cmd += ["--base", base_dir]
    if no_template:
        cmd.append("--no-template")
    started = time.time()

    def on_done(task):
        out_dir = date_dir if os.path.isdir(date_dir) else os.path.join(
            base_dir or base.workspace("data"), date_dir)
        return {"outputs": base.newest_files(out_dir, {".xlsx"}, since=started)}

    return base.run("重建 %s 成交估值总表" % os.path.basename(str(date_dir)),
                    "data", cmd, cwd=(base_dir or base.workspace("data")),
                    on_done=on_done)


def source_status(date_dir=None, base_dir=None):
    """检查某日目录下 4 份源文件齐不齐 —— 缺哪份前端就提示去下哪份。"""
    root = base_dir or base.workspace("data")
    if not date_dir:
        date_dir = latest_date(root)
    d = date_dir if os.path.isdir(date_dir) else os.path.join(root, date_dir)
    need = ["上证固收成交明细.xlsx", "可交债.xlsx", "现券交易信息（逐笔）.xlsx",
            "中证可交换债券估值.xlsx"]
    items = []
    for n in need:
        p = os.path.join(d, n)
        exist = os.path.exists(p)
        items.append({"name": n, "exists": exist,
                      "path": p.replace("\\", "/"),
                      "size": os.path.getsize(p) if exist else 0,
                      "mtime": os.path.getmtime(p) if exist else 0})
    # 允许带日期后缀的估值文件也算数
    if not items[3]["exists"] and os.path.isdir(d):
        for f in os.listdir(d):
            if f.startswith("中证可交换债券估值") and f.endswith(".xlsx"):
                items[3]["exists"] = True
                items[3]["name"] = f
                items[3]["path"] = os.path.join(d, f).replace("\\", "/")
                items[3]["size"] = os.path.getsize(os.path.join(d, f))
                break
    return {"dir": str(d).replace("\\", "/"), "sources": items,
            "ready": all(i["exists"] for i in items)}
