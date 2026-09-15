# -*- coding: utf-8 -*-
"""运行环境自检：挑一个能用的 Python 解释器，并报告依赖齐不齐。

无代码经验的同事最常卡在这一步，所以这里要给出「看得懂的提示」而不是
一串 ImportError。缺什么就在前端一键装。
"""
import os
import subprocess
import sys

# 各能力所需依赖 → pip 包名 / import 名 / 用途 / 是否必须
DEPS = [
    {"key": "openpyxl", "pip": "openpyxl", "import": "openpyxl",
     "label": "Excel 读写", "required": True,
     "why": "重建总表、预览表格、生成公告整理表都要用它"},
    {"key": "requests", "pip": "requests", "import": "requests",
     "label": "网络请求", "required": True,
     "why": "调用模型 API、抓取公众号文章正文"},
    {"key": "pdfplumber", "pip": "pdfplumber", "import": "pdfplumber",
     "label": "PDF 文本提取", "required": False,
     "why": "公告 PDF 转文字，AI 提炼公告要点必须先转储"},
    {"key": "pypdfium2", "pip": "pypdfium2", "import": "pypdfium2",
     "label": "扫描件 PDF 渲染", "required": False,
     "why": "无文字层的扫描版公告，渲染成图片后由模型识别文字"},
    {"key": "playwright", "pip": "playwright", "import": "playwright",
     "label": "网页自动化", "required": False,
     "why": "自动下载数据源、抓取公众号文章（另需装浏览器内核）"},
    {"key": "docx", "pip": "python-docx", "import": "docx",
     "label": "Word 读写", "required": False,
     "why": "公众号文章导出成 docx；平台读取正文不依赖它"},
    {"key": "bs4", "pip": "beautifulsoup4", "import": "bs4",
     "label": "网页解析", "required": False,
     "why": "公众号爬虫解析文章正文"},
    {"key": "lxml", "pip": "lxml", "import": "lxml",
     "label": "HTML 解析器", "required": False,
     "why": "配合 bs4 使用"},
]

_CANDIDATES = None


def _candidate_paths():
    """收集机器上可能存在的 Python 解释器（按优先级）。"""
    found = []

    def add(p):
        if p and os.path.exists(p):
            rp = os.path.realpath(p)
            if rp not in [os.path.realpath(x) for x in found]:
                found.append(p)

    add(sys.executable)
    for env_var in ("PYTHON", "PYTHON_HOME"):
        v = os.environ.get(env_var)
        if v:
            add(v)
    # 常见安装位置
    local = os.path.expanduser("~")
    guesses = [
        os.path.join(local, "AppData", "Local", "Programs", "Python"),
        os.path.join(local, "AppData", "Local", "Microsoft", "WindowsApps"),
        os.path.join(local, "anaconda3"),
        os.path.join(local, "miniconda3"),
        os.path.join(local, ".workbuddy-ai", "binaries", "python", "versions"),
        r"C:\Python313", r"C:\Python312", r"C:\Python311", r"C:\Python310",
        r"C:\ProgramData\Anaconda3",
    ]
    import glob as _g
    for g in guesses:
        if not os.path.isdir(g):
            continue
        for pat in ("python.exe", "*/python.exe", "*/*/python.exe"):
            for p in sorted(_g.glob(os.path.join(g, pat))):
                low = p.lower()
                if "WindowsApps" in p and not low.endswith(("python3.exe", "python.exe")):
                    continue
                add(p)

    # 沙箱/工具类软件常自带一份「依赖齐全」的 Python，路径层级更深，单独 glob。
    # 实测这类解释器往往已经装好 openpyxl/pdfplumber/playwright，优先命中能省去一堆安装。
    deep_patterns = [
        os.path.join(local, "AppData", "Local", "Doubao", "User Data",
                     "sandbox_runtime", "bases", "*", "python", "python.exe"),
        os.path.join(local, "AppData", "Local", "Doubao", "User Data",
                     "sandbox_runtime", "bases", "*", "*", "python", "python.exe"),
        os.path.join(local, ".workbuddy", "binaries", "python", "versions", "*", "python.exe"),
        os.path.join(local, ".workbuddy-ai", "binaries", "python", "versions", "*", "python.exe"),
        os.path.join(local, "AppData", "Local", "Programs", "Python", "*", "python.exe"),
    ]
    for pat in deep_patterns:
        for p in sorted(_g.glob(pat)):
            add(p)
    # PATH 里的
    for name in ("python.exe", "python3.exe", "py.exe"):
        p = _which(name)
        if p:
            add(p)
    return found


def _which(name):
    import shutil as _s
    p = _s.which(name)
    return p


def _probe(exe):
    """返回 (version_str, 依赖命中集合)。失败返回 None。"""
    # 注意：必须显式 import importlib.util。写成 __import__('importlib').util 在
    # 嵌入式/精简版 Python 上会 AttributeError（子模块未自动加载），
    # 结果就是「明明装了依赖却探测不到」。
    code = (
        "import sys, json\n"
        "import importlib.util as _iu\n"
        "mods = ['openpyxl','requests','pdfplumber','pypdfium2','playwright','docx','bs4','lxml']\n"
        "ok = []\n"
        "for m in mods:\n"
        "    try:\n"
        "        if _iu.find_spec(m):\n"
        "            ok.append(m)\n"
        "    except Exception:\n"
        "        pass\n"
        "print(json.dumps({'v': sys.version.split()[0], 'ok': ok}))\n"
    )
    try:
        out = subprocess.run([exe, "-c", code], capture_output=True,
                             timeout=30, text=True, encoding="utf-8", errors="replace")
        if out.returncode != 0 or not out.stdout.strip():
            return None
        import json
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def detect_python(preferred=None):
    """挑解释器：优先用配置里指定的，其次挑依赖命中最多、版本够新的。"""
    if preferred and os.path.exists(preferred):
        r = _probe(preferred)
        if r:
            return {"executable": preferred, "version": r["v"], "packages": r["ok"]}
    best, best_score = None, -1
    for exe in _candidate_paths():
        r = _probe(exe)
        if not r:
            continue
        try:
            major, minor = (int(x) for x in r["v"].split(".")[:2])
        except Exception:
            continue
        if (major, minor) < (3, 8):
            continue
        score = len(r["ok"]) * 10 + major * 100 + minor
        if score > best_score:
            best, best_score = {"executable": exe, "version": r["v"],
                                "packages": r["ok"]}, score
    if best is None:  # 兜底：当前解释器
        import json
        r = {"v": sys.version.split()[0], "ok": []}
        best = {"executable": sys.executable, "version": r["v"], "packages": []}
    return best


def dependency_report(exe):
    """针对某个解释器给出逐条依赖状态。"""
    info = _probe(exe) or {"v": "?", "ok": []}
    have = set(info.get("ok", []))
    items = []
    for d in DEPS:
        items.append({
            "key": d["key"],
            "label": d["label"],
            "pip": d["pip"],
            "required": d["required"],
            "why": d["why"],
            "installed": d["import"] in have,
        })
    return {"python": {"executable": exe, "version": info.get("v", "?")}, "deps": items}


def install_package(exe, package, on_line=None):
    """pip 安装单个包，逐行回调输出（前端实时滚动）。"""
    cmd = [exe, "-m", "pip", "install", package, "--disable-pip-version-check"]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env, text=True, encoding="utf-8", errors="replace",
                            bufsize=1, creationflags=_no_window())
    for line in proc.stdout:
        line = line.rstrip("\r\n")
        if on_line:
            on_line(line)
    proc.wait()
    return proc.returncode


def _no_window():
    if os.name == "nt":
        return subprocess.CREATE_NO_WINDOW  # 0x08000000
    return 0
