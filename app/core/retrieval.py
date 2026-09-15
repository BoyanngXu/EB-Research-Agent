# -*- coding: utf-8 -*-
"""多源检索（Agentic RAG 的检索层）：规划要查哪些源 → 并发取回片段。

首版用**规则规划**（零 LLM 成本、可控）：按关键词命中源，命中不全时按默认组合兜底。
规划结果会回给前端展示「已检索：历史对话 / 公告表 / 任务日志」，让用户知道依据从哪来。
"""
import os
import re

from . import config, datareader, memory, tasks

SOURCE_LABELS = {
    "memory": "历史对话",
    "anno": "公告整理",
    "data": "成交估值",
    "morning": "晨会观点",
    "backtest": "观点回测",
    "wechat": "舆情文章",
    "digest": "舆情记忆",
    "tasks": "任务日志",
    "prompt": "精读口径",
}

CODE_RE = re.compile(r"\d{6}\.(?:SH|SZ)", re.I)

# (关键词, 源) —— 顺序即优先级
_RULES = [
    (("上次", "之前", "以前", "历史", "你说过", "记得", "那次", "当时"), "memory"),
    (("任务", "失败", "报错", "为什么", "卡住", "进度", "日志", "跑完"), "tasks"),
    (("口径", "规则", "怎么写", "有什么要求", "铁律", "字数", "格式要求"), "prompt"),
    # 命中率/原话只有回测 HTML 里有（xlsx 总表没有），必须单独成源，否则会答「查无此项」
    (("命中率", "回测", "胜率", "兑现", "准不准", "事后", "验证", "说中了"), "backtest"),
    (("晨会", "板块", "细分", "看多", "看空", "强推", "推荐", "评级", "首推", "看好",
      "命中", "锚点", "纪要", "最被", "观点原话", "标的池"), "morning"),
    (("舆情", "公众号", "文章", "情绪", "热文", "市场怎么", "市场觉得", "市场认为",
      "大家觉得", "大家认为", "大家怎么", "怎么看", "看法", "观点", "舆论", "机构怎么"), "wechat"),
    (("成交", "估值", "净价", "收益率", "数据总表", "总表", "行情", "价格"), "data"),
    (("债", "eb", "换股", "担保", "风险", "公告", "摘要", "整理表", "标的", "发行人"), "anno"),
]

_LATEST = ("最新", "最近", "今天", "今日", "昨日", "昨天", "刚")

# 命中这些词时，「板块聚合」片段排在个股片段之前
_SECTOR_AGG_MARK = ("哪个板块", "哪些板块", "板块热度", "最看好", "最被", "最推荐",
                    "分布", "统计", "排名", "汇总", "排序", "前几", "前十")
# 可交换债专属词：出现这些才算真的在问 EB，否则「标的」这类通用词不该把公告源带进来
_EB_MARK = ("可交换债", "换股", "eb", "担保", "净价", "到期", "赎回", "回售", "发行人")


def plan(question):
    """返回 {"sources":[...], "signals":[...], "latest":bool}。"""
    q = (question or "")
    low = q.lower()
    srcs, signals = [], []

    if CODE_RE.search(q):
        code = CODE_RE.search(q).group(0).upper()
        srcs += ["anno", "data"]
        signals.append("识别到证券代码 %s → 查公告 + 数据" % code)

    for kws, src in _RULES:
        if src in srcs:
            continue
        if any(k in low for k in kws):
            srcs.append(src)
            signals.append("命中「%s」→ 查%s" % (kws[0], SOURCE_LABELS[src]))

    latest = any(k in low for k in _LATEST)
    if latest:
        signals.append("识别为「最新/最近」类问题 → 优先取最新记录")
        for s in ("anno", "data", "wechat", "morning"):
            if s not in srcs:
                srcs.append(s)

    # 晨会问题里的「标的/风险/公告」等词会误命中公告源（latest 分支也会补进来）：
    # 命中晨会且没有 EB 专属词时把 anno 摘掉，免得 EB 公告把晨会片段挤没
    if "morning" in srcs and "anno" in srcs and not any(k in low for k in _EB_MARK):
        srcs.remove("anno")
        signals.append("晨会问题未出现可交换债关键词 → 不查公告整理")

    if not srcs:
        srcs = ["memory", "anno", "data"]
        signals.append("未命中特定源 → 默认查历史对话 + 公告 + 数据")

    return {"sources": srcs, "signals": signals, "latest": latest}


def _latest_rows(table, n=5):
    """取表格最后 n 行（成品表按日期倒序时，尾部才是最新；这里两种都覆盖：取前 3 + 后 5）。"""
    if not table or not table.get("rows"):
        return []
    rows = table["rows"]
    picked = rows[:3] + (rows[-n:] if len(rows) > 3 else [])
    seen, out = set(), []
    for r in picked:
        key = " ".join(str(c) for c in r)
        if key and key not in seen:
            seen.add(key)
            out.append(r)
    return out[:n + 3]


def tasks_lookup(query, limit=4):
    """最近任务状态；问「为什么失败」时附带失败任务日志尾部。"""
    low = (query or "").lower()
    want_fail = any(k in low for k in ("失败", "报错", "为什么", "卡住"))
    try:
        items = tasks.list_tasks(limit=20) or []
    except Exception:
        return []
    if want_fail:
        items = [t for t in items if t.get("status") == "failed"] or items
    out = []
    for t in items[:limit]:
        tid = t.get("id") or ""
        line = "任务「%s」状态=%s 项目=%s" % (t.get("title") or "-", t.get("status") or "-",
                                            t.get("project") or "-")
        if t.get("duration"):
            line += " 耗时%.1fs" % t["duration"]
        if want_fail and tid:
            try:
                logs = tasks.read_log(tid, tail=12) or []
                errs = [r.get("text", "") for r in logs
                        if (r.get("level") in ("error", "warn"))]
                if errs:
                    line += "\n  日志尾部：" + " ｜ ".join(errs[-4:])[:600]
            except Exception:
                pass
        out.append({"source": "tasks", "title": "任务 %s" % (tid or "-"),
                    "ref": "runtime/tasks/%s" % tid, "text": line, "score": 1})
    return out


def prompt_lookup(query, limit=2):
    """精读口径：直接给 prompt.md 的骨架（摘要字数、顺序铁律、字段定义）。"""
    p = datareader.prompt_file()
    if not os.path.isfile(p):
        return []
    try:
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return []
    hits, low = [], (query or "").lower()
    for kw in ("字数", "顺序", "铁律", "上市公司", "代码", "排除", "口径", "怎么写"):
        if kw in low:
            for m in re.finditer(re.escape(kw), text):
                s = max(0, m.start() - 160)
                hits.append(text[s: m.start() + 260].strip())
                break
    if not hits:
        hits = [text[:900]]
    return [{"source": "prompt", "title": "精读口径 prompt.md", "ref": p.replace("\\", "/"),
             "text": "\n---\n".join(hits)[:2000], "score": 1}]


def gather(question, plan_obj, session=None):
    """按规划取回片段，返回 {"snippets":[...], "used":[...], "budget":...}。"""
    c = config.load()
    dr = c.get("datareader") or {}
    per_snip = int(dr.get("snippet_chars", 1200) or 1200)
    budget = int((c.get("assistant") or {}).get("max_ctx_chars", 12000) or 12000)

    sources = (plan_obj or {}).get("sources") or []
    latest = bool((plan_obj or {}).get("latest"))
    snippets = []

    for src in sources:
        try:
            if src == "memory":
                for h in memory.search(question, exclude=session):
                    snippets.append({"source": "memory", "title": "历史对话 %s" % h.get("time", ""),
                                     "ref": "memory:%s" % h.get("session", ""),
                                     "text": ("我：" if h.get("role") == "user" else "助手：")
                                             + (h.get("text") or "")[:per_snip],
                                     "score": h.get("score", 0)})
            elif src == "anno":
                if latest:
                    rows = datareader.anno_input_rows()
                    if rows:
                        headers = ["公告日期", "上市公司", "可交换债", "证券代码", "标的股票",
                                   "股票代码", "换股价格", "公告性质", "内容摘要"]
                        for r in rows[-5:]:
                            snippets.append({"source": "anno", "title": "最新精读结果",
                                             "ref": "Anno/input.json",
                                             "text": datareader.fmt_row(
                                                 headers, [r.get(k, "") for k in headers], per_snip),
                                             "score": 2})
                snippets += datareader.anno_lookup(question, limit=5)
            elif src == "data":
                if latest:
                    for p in datareader.data_tables(limit=1):
                        t = datareader.read_xlsx(p, max_rows=200)
                        for row in _latest_rows(t, 5):
                            snippets.append({"source": "data", "title": "最新数据行",
                                             "ref": t["path"],
                                             "text": datareader.fmt_row(t["headers"], row, per_snip),
                                             "score": 2})
                        snippets.append({"source": "data", "title": "表头", "ref": t["path"],
                                         "text": " | ".join(str(h) for h in t["headers"])[:600],
                                         "score": 1})
                snippets += datareader.data_lookup(question, limit=5)
            elif src == "morning":
                # 问「哪个板块最被看好/分布/排名」这类汇总问题时，板块聚合放前面
                if any(k in question for k in _SECTOR_AGG_MARK):
                    snippets += datareader.report_sector_stats(question)
                    snippets += datareader.report_lookup(question, limit=5)
                else:
                    snippets += datareader.report_lookup(question, limit=5)
                    snippets += datareader.report_sector_stats(question)
            elif src == "backtest":
                snippets += datareader.backtest_lookup(question)
            elif src == "wechat":
                snippets += datareader.wechat_lookup(question, limit=3)
                snippets += datareader.digest_lookup(question, limit=2)
            elif src == "tasks":
                snippets += tasks_lookup(question, limit=4)
            elif src == "prompt":
                snippets += prompt_lookup(question)
        except Exception as e:          # 单个源挂掉不能拖垮整轮回答
            snippets.append({"source": src, "title": "读取失败", "ref": "",
                             "text": "（%s 源读取异常：%s）" % (SOURCE_LABELS.get(src, src), e),
                             "score": 0})

    # 去重 + 截断到预算
    seen, uniq, used = set(), [], []
    for s in snippets:
        key = (s.get("ref", ""), (s.get("text") or "")[:80])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
        if s.get("source") not in used:
            used.append(s["source"])

    total = 0
    final = []
    for s in uniq:
        t = (s.get("text") or "")[:per_snip]
        if total + len(t) > budget:
            break
        total += len(t)
        s["text"] = t
        final.append(s)

    return {"snippets": final, "used": used, "used_labels": [SOURCE_LABELS.get(u, u) for u in used],
            "budget": budget, "chars": total}
