# -*- coding: utf-8 -*-
r"""Report 项目（第 4 个项目页）：晨会分享 → 结构化入库 → 观点命中回测。

**本模块不再自己跑管线**。Report 页只做三件事：
    ① 概览         status()       各产物是否就位
    ② 生成指令     build_ingest_prompt()  触发 morning-note-ingest skill 的一键入库提示词
    ③ 展示报告     list_htmls() / asset() 把 _analysis 下的三级 HTML 报告（主题→板块→个股）
                   当静态资源喂给页面里的 iframe

真正的处理流程（docx 转 txt → LLM 提取 → 并入总表 → 补代码行情 → 重建 HTML）
由 WorkBuddy 侧加载 `C:\Users\<用户名>\.workbuddy\skills\morning-note-ingest` 执行，
指令模板见 tools/eb-report/ingest_prompt.md。
"""
import mimetypes
import os

from ..core import config
from . import base

TOOL = "eb-report"
DOCX_PREFIX = "晨会分享"

# 「一键入库」触发提示词：tools/eb-report/ingest_prompt.md（改完刷新页面即生效）
INGEST_PROMPT_FILE = "ingest_prompt.md"
_INGEST_CACHE = {"mtime": None, "data": None}

# 报告静态资源：只放行这些扩展名，避免把 xlsx/json 数据文件也暴露出去
ASSET_EXTS = {".html", ".htm", ".js", ".css", ".png", ".jpg", ".jpeg",
              ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".map"}
ASSET_MAX_DEPTH = 3


class PromptLoadError(Exception):
    """提示词文件缺失或章节不全。"""


# ---------------------------------------------------------------- 路径


def root():
    """Report 根目录（放晨会 docx 的地方）。"""
    return base.workspace("report")


def analysis_dir():
    """_analysis：总表 / 行情缓存 / anno_json / 产物 HTML 都在这里。"""
    return os.path.join(root(), "_analysis")


def source_txt_dir():
    return os.path.join(analysis_dir(), "source_txt")


def anno_dir():
    return os.path.join(analysis_dir(), "anno_json")


def xlsx_path():
    return os.path.join(analysis_dir(), "晨会分享分析总表.xlsx")


# ---------------------------------------------------------------- ① 检测


def list_new():
    """找出还没有对应 txt 的晨会 docx（增量入口）。"""
    d = root()
    have = set()
    tdir = source_txt_dir()
    if os.path.isdir(tdir):
        have = {os.path.splitext(n)[0] for n in os.listdir(tdir)
                if n.lower().endswith(".txt")}
    items = []
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if not name.lower().endswith(".docx"):
                continue
            if name.startswith("~"):          # Word 临时锁文件
                continue
            if not name.startswith(DOCX_PREFIX):
                continue
            stem = os.path.splitext(name)[0]
            full = os.path.join(d, name)
            items.append({
                "name": name,
                "stem": stem,
                "path": full.replace("\\", "/"),
                "size": os.path.getsize(full),
                "mtime": os.stat(full).st_mtime,
                "done": stem in have,
            })
    items.sort(key=lambda x: x["name"])
    return {"root": d.replace("\\", "/"),
            "total": len(items),
            "pending": len([i for i in items if not i["done"]]),
            "items": items}


# ---------------------------------------------------------------- ② 三级报告


def list_htmls():
    """列出 _analysis 下的回测报告 HTML（可嵌进 iframe 展示）。"""
    a = analysis_dir()
    out = []
    if not os.path.isdir(a):
        return {"analysis": a.replace("\\", "/"), "files": out}
    base_len = len(a.rstrip("\\/")) + 1
    for dirpath, dirnames, filenames in os.walk(a):
        depth = 0 if dirpath == a else dirpath[base_len:].count(os.sep) + 1
        if depth >= ASSET_MAX_DEPTH:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "_"))]
        for n in filenames:
            if os.path.splitext(n)[1].lower() not in (".html", ".htm"):
                continue
            full = os.path.join(dirpath, n)
            rel = full[base_len:].replace("\\", "/")
            try:
                st = os.stat(full)
            except OSError:
                continue
            out.append({"name": n, "rel": rel, "size": st.st_size,
                        "mtime": st.st_mtime})
    out.sort(key=lambda x: (-x["mtime"], x["rel"]))
    return {"analysis": a.replace("\\", "/"), "files": out}


def asset(rel):
    """取 _analysis 下的静态资源（HTML / chart.js / 图片…）。

    返回 (bytes, content_type)。越界、类型不在白名单、文件不存在都抛 ValueError。
    """
    a = os.path.abspath(analysis_dir())
    rel = (rel or "").strip("/").replace("\\", "/")
    if not rel:
        raise ValueError("未指定文件")
    full = os.path.abspath(os.path.join(a, rel))
    if full != a and not full.startswith(a + os.sep):
        raise ValueError("路径越界：%s" % rel)
    ext = os.path.splitext(full)[1].lower()
    if ext not in ASSET_EXTS:
        raise ValueError("不允许的文件类型：%s" % (ext or rel))
    if not os.path.isfile(full):
        raise FileNotFoundError("文件不存在：%s" % rel)
    with open(full, "rb") as fh:
        data = fh.read()
    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
    if ext in (".html", ".htm", ".js", ".css", ".svg"):
        ctype += "; charset=utf-8"
    return data, ctype


# ---------------------------------------------------------------- ③ 概览


def status():
    """给前端的概览：各步产物是否就位。"""
    a = analysis_dir()
    def _p(*parts):
        return os.path.join(a, *parts)
    return {
        "root": root().replace("\\", "/"),
        "analysis": a.replace("\\", "/"),
        "xlsx": _p("晨会分享分析总表.xlsx"),
        "has_xlsx": os.path.exists(_p("晨会分享分析总表.xlsx")),
        "has_quotes": os.path.exists(_p("_bt_quote_cache_full.json")),
        "has_codemap": os.path.exists(_p("codemap_qt.json")),
        "has_html": os.path.exists(_p("F观点命中回测_板块.html")),
        "n_txt": len([n for n in os.listdir(source_txt_dir())
                      if n.lower().endswith(".txt")]) if os.path.isdir(source_txt_dir()) else 0,
        "n_anno": len([n for n in os.listdir(anno_dir())
                       if n.lower().endswith(".json")]) if os.path.isdir(anno_dir()) else 0,
    }


# ------------------------------------------------------- 一键入库触发提示词


def ingest_prompt_path():
    return os.path.join(base.skill_dir(TOOL), INGEST_PROMPT_FILE)


def load_ingest_prompt(force=False):
    """读 tools/eb-report/ingest_prompt.md，按 mtime 缓存（改完文件下次即生效）。"""
    path = ingest_prompt_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        raise PromptLoadError("找不到提示词文件：%s" % path)
    if not force and _INGEST_CACHE["data"] and _INGEST_CACHE["mtime"] == mtime:
        return _INGEST_CACHE["data"]
    with open(path, "r", encoding="utf-8") as f:
        tpl = f.read()
    # 文件开头的 `# ` 行是给人看的注释，不进提示词
    tpl = _strip_leading_comments(tpl)
    _INGEST_CACHE["mtime"] = mtime
    _INGEST_CACHE["data"] = tpl
    return tpl


def _strip_leading_comments(tpl):
    lines = tpl.splitlines()
    i = 0
    while i < len(lines) and lines[i].lstrip().startswith("#"):
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    return "\n".join(lines[i:])


def build_ingest_prompt():
    """生成「处理新晨会」的触发指令：复制给 WorkBuddy，由它按 morning-note-ingest skill 跑全流程。

    页面不自己跑管线，只负责把当前待处理清单拼进提示词，交给 skill 执行。
    """
    tpl = load_ingest_prompt()
    new = list_new()
    st = status()

    pend = [i for i in new["items"] if not i["done"]]
    if pend:
        lines = "\n".join("  - %s（%s）" % (i["path"], i["name"]) for i in pend)
    else:
        lines = "  （检测时未发现待转的晨会 docx；以 detect_new.py 实时结果为准）"

    return (tpl.replace("__ROOT__", st["root"])
               .replace("__ANALYSIS__", st["analysis"])
               .replace("__N_TXT__", str(st["n_txt"]))
               .replace("__N_ANNO__", str(st["n_anno"]))
               .replace("__PENDING__", str(len(pend)))
               .replace("__NEW_LIST__", lines))
