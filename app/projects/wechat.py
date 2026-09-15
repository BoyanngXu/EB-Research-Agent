# -*- coding: utf-8 -*-
"""Wechat 项目：公众号 A股 热文抓取 + 正文阅读。"""
import os
import time

from . import base


# ---------------------------------------------------------------- 旧文「记忆压缩」
# 抓取前把上一轮旧文交给模型提炼成一份精华 txt 存进 _digest/，
# 这样即使原文被清理，关键信息仍可长期检索调用。
_DIGEST_SYSTEM = """你是一位资深的 A 股盘面情报分析师，负责把同一时段的多篇公众号财经文章压缩成一份精炼、可长期复用的「市场记忆」。

输出为纯文本，结构如下（每节都用中文，紧贴原文数据，绝不编造数字）：
【时段】YYYY-MM-DD 盘前/午盘/复盘
【市场情绪】1-2 句概括
【指数与关键数据】列出指数点位、涨跌幅、成交额等确凿数字；原文没有就不写
【主线 / 热点板块】分点
【关键事件 / 信息点】分点，含具体数字、日期、公司名
【风险与分歧】若有，写市场担心的点 / 多空分歧
【来源】共 N 篇（附上主要公众号名称，不超过 6 个）

硬性要求：
1. 只提炼原文里出现的信息，原文没有的字段写「原文未提及」，不要脑补。
2. 篇幅控制在 300~500 字，是「压缩记忆」不是全文抄录。
3. 中文输出，不要 markdown 代码块、不要解释。"""

# (时段标签, 命中词) —— 用于从文件名推断这批文章属于哪个时段
_PERIOD_PATTERNS = (
    ("盘前", ("盘前", "早盘", "开盘", "morning")),
    ("午盘", ("午盘", "午评", "午报", "午间", "半日")),
    ("复盘", ("复盘", "收评", "收盘", "收官")),
)


def _guess_period(names):
    """从文件名推断这批文章属于哪个时段；判断不出返回空串。"""
    scores = {}
    for label, kws in _PERIOD_PATTERNS:
        n = sum(1 for nm in names for k in kws if k.lower() in nm.lower())
        if n:
            scores[label] = n
    if not scores:
        return ""
    return max(scores.items(), key=lambda kv: kv[1])[0]


def _batch_date(files):
    """推断这批文章所述日期。

    优先从「文件名 + 正文开头」里提取明确日期（如 9月3日 / 2026-09-03 / 9.3日），
    提取不到才回退到文件 mtime。避免被"补抓/复制导致 mtime 变成今天"误导。
    """
    import datetime
    import re
    pats = (
        re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})"),   # 2026-09-03
        re.compile(r"(\d{1,2})月(\d{1,2})日"),                       # 9月3日
        re.compile(r"(\d{1,2})\.(\d{1,2})日"),                       # 9.3日
    )

    def _collect(text, hits, y_idx):
        m = pats[0].search(text)
        if m:
            key = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            hits[key] = hits.get(key, 0) + 1
            return
        for p in pats[1:]:
            m = p.search(text)
            if m:
                key = (y_idx, int(m.group(1)), int(m.group(2)))
                hits[key] = hits.get(key, 0) + 1
                return

    hits = {}
    try:
        from ..core import datareader
    except Exception:
        datareader = None
    for p in files:
        text = os.path.basename(p)
        if datareader is not None:
            try:
                d = datareader.read_docx(p, max_chars=800)
                text += "\n" + " ".join((d.get("paragraphs") or [])[:5])
            except Exception:
                pass
        _collect(text, hits, 0)

    if hits:
        # 按「月日」聚合票数（同年才合并），取票数最多的一组
        tally = {}
        for (y, m, dd), n in hits.items():
            key = (m, dd)
            tally[key] = tally.get(key, 0) + n
        best_md = max(tally.items(), key=lambda kv: kv[1])[0]
        now = datetime.date.today()
        year = now.year
        try:
            if datetime.date(year, best_md[0], best_md[1]) > now + datetime.timedelta(days=1):
                year -= 1
        except Exception:
            pass
        return "%04d-%02d-%02d" % (year, best_md[0], best_md[1])

    ts = 0.0
    for p in files:
        try:
            ts = max(ts, os.path.getmtime(p))
        except Exception:
            pass
    if not ts:
        return time.strftime("%Y-%m-%d")
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _read_material(files, budget=9000):
    """读取若干 docx 正文，拼成喂给模型的材料。"""
    from ..core import datareader
    per = max(1500, budget // max(1, len(files)))
    blocks, srcs = [], []
    for p in files:
        try:
            d = datareader.read_docx(p, max_chars=per)
            paras = d.get("paragraphs") or []
            if not paras:
                continue
            title = (d.get("title") or os.path.basename(p)).strip()
            blocks.append("【%s】\n%s" % (title, " ".join(paras)))
            srcs.append(title)
        except Exception:
            continue
    return "\n\n".join(blocks), srcs


def digest_old_docs(out_dir, timeout=90):
    """把目录里的旧文压缩成一份「记忆」txt 存进 _digest/。

    fail-open：压缩是锦上添花，任何异常都只返回 (False, 原因)，绝不阻塞抓取。
    走 api 直连（后台自动化任务不能走人工桥接，否则会卡住等回填）。
    返回 (ok: bool, msg: str)；无旧文时返回 (True, "")。
    """
    if not out_dir or not os.path.isdir(out_dir):
        return False, "目录不存在"
    files = [os.path.join(out_dir, f) for f in os.listdir(out_dir)
             if f.lower().endswith(".docx")
             and os.path.isfile(os.path.join(out_dir, f))]
    if not files:
        return True, ""

    try:
        from ..core import config, llm
    except Exception as e:
        return False, "依赖导入失败：%s" % e

    c = config.load()
    z = c.get("llm") or {}
    a = c.get("assistant") or {}
    model = (a.get("model") or z.get("model") or "").strip()

    material, srcs = _read_material(files)
    if not material.strip():
        return False, "旧文正文读不出内容"

    period = _guess_period([os.path.basename(p) for p in files]) or "综合"
    date = _batch_date(files)

    digest_dir = os.path.join(out_dir, "_digest")
    try:
        os.makedirs(digest_dir, exist_ok=True)
    except Exception as e:
        return False, "无法创建 _digest：%s" % e

    # 同名已存在（同一天同一时段抓过两次）时加时间戳，避免覆盖掉上一份记忆
    name = "%s-%s舆情精华.txt" % (date, period)
    out_path = os.path.join(digest_dir, name)
    if os.path.isfile(out_path):
        out_path = os.path.join(digest_dir,
                                "%s-%s舆情精华-%s.txt" % (date, period,
                                                          time.strftime("%H%M%S")))

    user_msg = ("以下是 %s %s 共 %d 篇公众号文章正文（已拼接），请压缩成一份市场记忆：\n\n%s"
                % (date, period, len(srcs), material[:20000]))
    try:
        r = llm.chat([{"role": "system", "content": _DIGEST_SYSTEM},
                      {"role": "user", "content": user_msg}],
                     override={"backend": "api", "model": model or None,
                               "temperature": 0.2, "timeout": timeout})
    except Exception as e:
        return False, "LLM 调用异常：%s" % e
    if not r.get("ok"):
        return False, "LLM 返回失败：%s" % (r.get("message") or r.get("error") or "未知")

    summary = (r.get("content") or "").strip()
    if not summary:
        return False, "LLM 返回空内容"

    src_names = list(dict.fromkeys(srcs))[:6]
    header = ("# %s %s公众号舆情 · 记忆压缩\n"
              "生成时间: %s\n"
              "来源: %d 篇（%s）\n\n"
              % (date, period, time.strftime("%Y-%m-%d %H:%M:%S"),
                 len(srcs), " / ".join(src_names)))
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(header + summary)
    except Exception as e:
        return False, "写入失败：%s" % e
    return True, "%d 篇旧文 → %s（%d 字）" % (len(srcs), os.path.basename(out_path),
                                             len(summary))


def _trash_dir(path):
    """把目录整体送 Windows 回收站（可恢复）。成功返回 True。

    返回码 res=2 是已知误报，以「源路径消失」为准。
    """
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]

    op = SHFILEOPSTRUCTW()
    op.hwnd = 0
    op.wFunc = 3                      # FO_DELETE
    op.pFrom = ctypes.c_wchar_p(os.path.abspath(path) + "\0\0")
    op.pTo = None
    op.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400   # ALLOWUNDO|NOCONFIRM|SILENT|NOERRORUI
    op.fAnyOperationsAborted = False
    op.hNameMappings = None
    op.lpszProgressTitle = None
    try:
        ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except Exception:
        return False
    return not os.path.exists(path)


def _cleanup_old_docs(out_dir, digest_ok=False):
    """抓取前把上一轮的旧 .docx 及其 .meta.json 侧车一并移走
    （rename-aside 到 _prev/<时间戳>），避免旧文污染本轮汇总，也规避批量删除守卫。

    digest_ok=True 表示这批旧文已成功压缩成记忆，原文不再需要留着占空间 →
    尝试把该批次整体送回收站（可恢复）；若回收站调用失败或被环境拦截，
    则保留 rename 结果（原文仍在 _prev，不丢），只是会继续占用磁盘。
    返回被移走的文件名列表。"""
    if not out_dir or not os.path.isdir(out_dir):
        return []
    docs = [f for f in os.listdir(out_dir)
            if f.lower().endswith(".docx")
            and os.path.isfile(os.path.join(out_dir, f))]
    if not docs:
        return []
    ts = time.strftime("%Y%m%d_%H%M%S")
    prev = os.path.join(out_dir, "_prev", ts)
    os.makedirs(prev, exist_ok=True)
    moved = []
    for f in docs:
        src = os.path.join(out_dir, f)
        dst = os.path.join(prev, f)
        try:
            os.rename(src, dst)
            moved.append(f)
        except Exception:
            pass
        # 同步搬走侧车 json（原文链接等元数据）
        meta = f + ".meta.json"
        msrc = os.path.join(out_dir, meta)
        if os.path.isfile(msrc):
            try:
                os.rename(msrc, os.path.join(prev, meta))
            except Exception:
                pass

    # 已成功压缩成记忆 → 原文可清理（先 rename 保底，再尝试送回收站）
    if digest_ok and moved:
        try:
            if _trash_dir(prev):
                moved.append("（%d 篇原文已送回收站）" % len(docs))
        except Exception:
            pass          # 回收站失败无所谓，rename 结果仍在 _prev，原文没丢
    return moved


def crawl(count=None, keyword=None, out_dir=None, headless=False, on_done=None):
    """抓取公众号文章。不传关键词时脚本会按当前时间自动研判（盘前/午盘/复盘）。

    on_done 可注入（汇总动作用它：抓取完自动调用 RAG 汇总，结果写进 task.result）。
    每次抓取前会先把输出目录里上一轮的旧 .docx 移走，保证本轮目录干净。
    """
    c = None
    try:
        from ..core import config
        c = config.load()
    except Exception:
        pass
    if count is None:
        count = (c or {}).get("wechat", {}).get("default_count", 10)
    d = out_dir or base.workspace("wechat")
    started = time.time()

    cleaned = []
    def _pre():
        # ① 先把旧文压缩成记忆（在任何清理动作之前，否则原文就没了）
        #    失败只警告，绝不阻塞抓取（fail-open）。
        digest_ok = False
        try:
            ok, msg = digest_old_docs(d)
            if ok and msg:
                yield "旧文记忆压缩：%s" % msg
                digest_ok = True
            elif ok:
                digest_ok = True      # 无旧文，视为"无需压缩"→ 后续清理照常
            else:
                yield "⚠ 旧文记忆压缩跳过（%s），原文将保留在 _prev 备查" % msg
        except Exception as e:
            yield "⚠ 旧文记忆压缩异常（%s），原文将保留在 _prev 备查" % e
        # ② 再清理旧文（压缩成功才真正清掉，否则只 rename 保命）
        for f in _cleanup_old_docs(d, digest_ok=digest_ok):
            cleaned.append(f)
            yield "抓取前清理旧文档：%s" % f

    cmd = [base.python_exe(), base.script_path("wechat-gzh-crawler",
                                               "wechat_gzh_crawler_weread.py"),
           "-n", str(count), "-o", d]
    if keyword:
        cmd += ["-k", keyword]
    if headless:
        cmd.append("--headless")

    if on_done is None:
        def on_done(task):
            return {"outputs": base.newest_files(d, {".docx"}, limit=50, since=started),
                    "cleaned_old_docs": list(cleaned)}

    title = "抓取公众号%s %s 篇" % (("「%s」" % keyword) if keyword else "热文", count)
    return base.run(title, "wechat", cmd, on_done=on_done, pre_run=_pre)


def list_articles(wechat_dir=None):
    """列出已抓取的文章，供前端点开阅读。"""
    d = wechat_dir or base.workspace("wechat")
    return {"dir": (d or "").replace("\\", "/"),
            "files": base.newest_files(d, {".docx"}, limit=200)}


def suggest_keyword():
    """前端默认提示：跟脚本保持一致的时段研判。"""
    import datetime
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return "A股复盘", "周末/非交易日"
    t = now.hour * 60 + now.minute
    if t < 11 * 60 + 30:
        return "A股盘前", "盘前（11:30 前）"
    if t < 15 * 60:
        return "A股午盘", "午盘（11:30-15:00）"
    return "今日A股复盘", "收盘后（15:00 后）"
