# -*- coding: utf-8 -*-
"""首页对话助手：意图识别 → 动作执行 / Agentic RAG 问答。

三种回答方式：
1. **动作（action）**：自然语言驱动现有功能（重建数据、抓舆情、转储、精读…），
   走任务系统，前端订阅日志直播进度。默认先给确认卡，防误触。
2. **问答（qa）**：先规划要查哪些源（历史对话 / 公告 / 数据 / 舆情 / 任务 / 口径），
   检索出片段后交给模型归纳，回答里带引用源。
3. **降级（local）**：模型不可用时（没 Key / 余额不足 / 超时），直接把检索到的原始
   证据列出来作答 —— 不报错、不空答，用户照样能看到数据。

精读仍然是 workbuddy 桥接（要人回填），助手不假装全自动，会在卡片上标「需桥接」。
"""
import os
import re
import threading
import time

from . import config, datareader, llm, memory, retrieval, tasks
from ..projects import anno, data, wechat, base, report

# ---------------------------------------------------------------- 动作注册表
# mode: auto=全自动跑完 / bridge=需人在桥接面板回填 / sync=立刻返回数据，不建任务
ACTIONS = [
    {"name": "anno_digest", "label": "AI 精读公告", "icon": "🤖", "mode": "bridge",
     "keywords": ["精读", "一键精读", "ai精读", "提炼公告", "提炼"],
     "desc": "把已转储的公告交给模型提炼 9 个字段"},
    {"name": "anno_dump", "label": "转储公告 PDF", "icon": "📄", "mode": "auto",
     "keywords": ["转储", "转储公告", "抽正文", "转txt"],
     "desc": "把公告目录下的 PDF 转成 txt（扫描件自动渲染成图）"},
    {"name": "anno_build", "label": "生成整理表", "icon": "📊", "mode": "auto",
     "keywords": ["生成整理表", "出表", "生成表", "build"],
     "desc": "校验 input.json 并生成 9 列整理表 xlsx"},
    {"name": "anno_check", "label": "校验公告", "icon": "✅", "mode": "auto",
     "keywords": ["校验公告", "校验数据", "check"],
     "desc": "只校验不排版：缺字段 / 摘要字数 / 重复行"},
    {"name": "anno_analyze", "label": "生成一键分析指令", "icon": "🧭", "mode": "sync",
     "keywords": ["一键分析", "分析指令", "生成指令"],
     "desc": "生成交给 AI 工作台的完整控制指令"},
    {"name": "report_ingest", "label": "生成晨会入库指令", "icon": "🧭", "mode": "sync",
     "keywords": ["处理新晨会", "处理晨会", "新晨会", "晨会入库", "加晨会", "晨会新增",
                  "入库晨会", "晨会更新", "生成晨会指令", "晨会一键入库"],
     "desc": "生成触发 morning-note-ingest skill 的一键入库指令（复制后交给 WorkBuddy 执行）"},
    {"name": "data_rebuild", "label": "重建数据总表", "icon": "🔧", "mode": "auto",
     "keywords": ["重建", "重建数据", "重建总表", "数据整合", "整合数据"],
     "desc": "把 4 份源文件合成 15 列总表"},
    {"name": "data_download_xx", "label": "下载中证估值", "icon": "⬇️", "mode": "auto",
     "keywords": ["下载估值", "下载中证", "xxxxx", "中证估值"],
     "desc": "xxxxx下载中证可交换债估值（需弹窗登录）"},
    {"name": "data_download_sz", "label": "下载深交所逐笔", "icon": "⬇️", "mode": "auto",
     "keywords": ["下载逐笔", "下载深交所", "深交所"],
     "desc": "深交所现券交易逐笔（免登录）"},
    {"name": "wechat_crawl", "label": "抓取公众号热文", "icon": "📰", "mode": "auto",
     "keywords": ["抓取舆情", "抓取公众号", "爬公众号", "抓公众号", "跑舆情", "抓热文"],
     "desc": "按盘前/午盘/复盘自动研判关键词抓热文"},
    {"name": "wechat_summarize", "label": "汇总舆情/看法", "icon": "📰", "mode": "auto",
     "keywords": ["舆情", "看法", "态度", "观点", "评价", "怎么看", "怎么评价",
                  "怎么看待", "大家怎么", "市场怎么", "舆论", "公众号热文", "公众号整理",
                  "汇总舆情", "午盘舆情", "盘前舆情", "复盘舆情", "午盘", "盘前", "复盘"],
     "desc": "对某领域的舆情/看法/态度，先查公众号目录，无则自动抓取（按话题或午盘/盘前/复盘）再汇总"},
    {"name": "task_status", "label": "查看最近任务", "icon": "🧾", "mode": "sync",
     "keywords": ["最近任务", "任务状态", "任务列表", "查看任务"],
     "desc": "列出最近任务及状态"},
    {"name": "overview", "label": "工作台总览", "icon": "🗂️", "mode": "sync",
     "keywords": ["总览", "工作台状态", "概况", "有多少", "多少个"],
     "desc": "三个目录的库存与最新产出"},
]

ACTION_MAP = {a["name"]: a for a in ACTIONS}


def _anno_digest_mode(c=None):
    """公告精读运行模式：anno.backend（默认 workbuddy 桥接）→ 'bridge'；切 api → 'auto'。"""
    if c is None:
        c = config.load()
    ab = ((c.get("anno") or {}).get("backend") or "workbuddy").strip().lower()
    return "bridge" if ab == "workbuddy" else "auto"

# 祈使/执行语气：出现这些词，说明用户是让我干活而不是问我问题
IMPERATIVE = ("帮我", "请", "执行", "跑一下", "跑一遍", "开始", "启动", "生成", "重建",
              "下载", "抓取", "转储", "精读", "校验", "出表", "整合", "做一下", "来一", "弄一")
# 疑问语气
QA_SIGNAL = ("吗", "？", "?", "如何", "怎样", "为什么", "什么", "哪些", "多少", "区别",
             "怎么看", "是不是", "有没有", "如何", "咋")

# 舆情/看法类意图：用户想了解某领域「公众/市场」的观点、态度、情绪 → 走公众号查/抓
OPINION_MARKERS = ("舆情", "看法", "态度", "观点", "评价", "怎么看", "怎么评价",
                   "怎么看待", "如何看", "如何评价", "大家怎么", "市场怎么", "机构怎么",
                   "舆论",
                   # 公众/市场主语 + 觉得/认为（口语化观点词，须带主语才能和「你觉得」区分）
                   "大家觉得", "大家认为", "市场觉得", "市场认为", "机构觉得",
                   "机构认为", "外界觉得", "外界认为", "网友觉得", "券商认为")
# 但若是问「我（助手）」的看法，应走普通问答，不要触发抓取
SELF_ADDR = ("你觉得", "你认为", "你怎么看", "你怎么评", "你的看法", "你的态度",
             "你怎么看待", "你怎么解读", "我觉得", "我们认为")
# 晨会类问题专属词：命中就走「检索晨会观点」，别被「怎么看」等舆情词带去抓公众号
MORNING_MARKERS = ("晨会", "板块", "细分板块", "强推", "评级", "命中", "观点原话",
                   "纪要", "首推", "标的池", "预测锚点", "看多", "看空")
# 这些短语是「去处理新晨会」的意图，不是「问晨会内容」→ 放行给动作处理，别被 MORNING 拦截成 qa
MORNING_INGEST = ("处理新晨会", "处理晨会", "新晨会", "晨会入库", "加晨会", "晨会新增",
                  "入库晨会", "晨会更新", "生成晨会指令", "晨会一键入库")

DATE_RE = re.compile(r"(20\d{6})")
COUNT_RE = re.compile(r"(\d+)\s*篇")


def _cfg_assistant():
    c = config.load()
    return c.get("assistant") or {}, c.get("llm") or {}, c


# ---------------------------------------------------------------- 意图识别
def classify(message):
    """返回 {kind: action|qa, action, label, mode, score, reason, params}。"""
    msg = (message or "").strip()
    low = msg.lower()
    if not msg:
        return {"kind": "qa", "action": None, "score": 0, "reason": "空消息", "params": {}}

    # 舆情/看法类意图：用户想了解某领域「公众/市场」的观点、态度、情绪时，
    # 优先走 wechat_summarize（先查公众号目录，无则自动抓取后再汇总），
    # 不再走普通问答——即使句子带问号也如此。但我们问「我（助手）」的看法时放行问答。
    # 晨会优先：问晨会/板块/评级这类，是查内部晨会记录，不是去抓公众号
    if any(k in low for k in MORNING_MARKERS) and not any(k in low for k in IMPERATIVE) \
            and not any(k in low for k in SELF_ADDR) \
            and not any(k in low for k in MORNING_INGEST):
        return {"kind": "qa", "action": None, "score": 6, "params": {},
                "reason": "命中晨会类关键词 → 走问答，检索《晨会分享分析总表》标的明细"}

    if any(k in low for k in OPINION_MARKERS) and not any(k in low for k in SELF_ADDR):
        return {"kind": "action", "action": "wechat_summarize", "label": "汇总舆情/看法",
                "mode": "auto", "score": 6, "params": {},
                "reason": "命中舆情/看法类意图 → 先查公众号目录，无则抓取后汇总"}

    best, best_score = None, 0
    for a in ACTIONS:
        sc = sum(1 for k in a["keywords"] if k in low)
        # 长关键词权重更高（"一键分析" 比 "分析" 更具体）
        sc += sum(1 for k in a["keywords"] if k in low and len(k) >= 4)
        if sc > best_score:
            best, best_score = a, sc

    params = {}
    m = DATE_RE.search(msg)
    if m:
        params["date"] = m.group(1)
    m = COUNT_RE.search(msg)
    if m:
        params["count"] = int(m.group(1))

    has_imp = any(k in low for k in IMPERATIVE)
    has_qa = any(k in msg for k in QA_SIGNAL)

    if best and best_score > 0:
        if has_qa and not has_imp:
            return {"kind": "qa", "action": None, "score": best_score, "params": params,
                    "reason": "命中「%s」但同时是疑问句 → 按问答处理" % best["label"]}
        return {"kind": "action", "action": best["name"], "label": best["label"],
                "mode": best["mode"], "score": best_score, "params": params,
                "reason": "命中动作「%s」" % best["label"]}

    return {"kind": "qa", "action": None, "score": 0, "params": params,
            "reason": "未命中任何动作 → 按问答处理"}


def describe(action_name, params=None):
    """确认卡上的「将要执行什么」说明。"""
    a = ACTION_MAP.get(action_name)
    if not a:
        return {"title": "未知动作", "lines": [], "mode": "sync"}
    params = params or {}
    lines = [a["desc"]]

    if action_name == "anno_digest":
        dumps = datareader.anno_dumps(limit=200)
        lines.append("待精读：%d 份已转储文本" % len(dumps))
        if not dumps:
            lines.append("⚠ 公告目录里还没有转储文本，建议先「转储公告 PDF」")
    elif action_name == "anno_dump":
        lines.append("目录：%s（转储前会把旧 _txt_dump 改名备份）" % config.workspace_root("anno"))
    elif action_name == "anno_build":
        lines.append("输入：%s/input.json" % config.workspace_root("anno"))
        lines.append("输出：%s/公告整理.xlsx" % config.workspace_root("output"))
    elif action_name == "data_rebuild":
        d = params.get("date") or ""
        try:
            d = d or data.latest_date()
        except Exception:
            d = ""
        lines.append("日期目录：%s" % (d or "（自动取最新）"))
    elif action_name == "wechat_crawl":
        lines.append("篇数：%s" % params.get("count", "默认"))
    mode = _anno_digest_mode() if action_name == "anno_digest" else a["mode"]
    if action_name == "anno_digest":
        lines.append("精读模式：" + ("WorkBuddy 桥接 · 每份需在「桥接」面板回填结果"
                     if mode == "bridge" else "云端直连（SenseNova）· 全自动"))
    return {"title": a["label"], "lines": lines, "mode": mode, "icon": a.get("icon", "▶")}


# ---------------------------------------------------------------- 动作执行
def execute_action(action_name, params=None):
    """执行动作，返回 {ok, kind:'action', action, label, mode, message, task|data}。"""
    a = ACTION_MAP.get(action_name)
    if not a:
        return {"ok": False, "error": "未知动作：%s" % action_name}
    params = params or {}
    try:
        return _run(action_name, a, params)
    except Exception as e:
        return {"ok": False, "error": "执行失败：%s" % e, "action": action_name,
                "label": a["label"], "mode": a["mode"]}


def _task_out(t, a, message):
    return {"ok": True, "kind": "action", "action": a["name"], "label": a["label"],
            "mode": a["mode"], "icon": a.get("icon", "▶"), "message": message,
            "task": t.snapshot(with_log=False)}


def _sync_out(a, message, data_obj):
    return {"ok": True, "kind": "action", "action": a["name"], "label": a["label"],
            "mode": "sync", "icon": a.get("icon", "▶"), "message": message, "data": data_obj}


def _extract_topic(msg):
    """从「对某领域的看法/态度」类问句里抽出领域词，用作公众号抓取关键词。

    例：「对于美联储加息概率的看法」→「美联储加息概率」；
        「大家对总统讲话怎么看的？」→「总统讲话」。
    抽不出有意义的词时返回空串，交由调用方回退到时段研判。
    """
    import re
    s = (msg or "").strip()
    if not s:
        return ""
    # 去掉引导词（含公众/市场主语 + 觉得/认为）
    s = re.sub(r'^(对于|关于|针对|大家对|大家对于|市场对于|市场对|机构对|券商对|你们对|你们对于|'
               r'大家觉得|大家认为|市场觉得|市场认为|机构觉得|机构认为|'
               r'外界觉得|外界认为|网友觉得|券商认为)\s*', '', s)
    # 去掉「……的看法/态度/观点/评价/怎么看/如何」等框架（含其前可能的「的」）
    s = re.sub(r'\s*的?\s*(看法|态度|观点|评价|解读|怎么看|怎么看待|怎么评价|如何看|如何评价|怎么解读|如何|怎么|怎样)\s*', '', s)
    # 去掉疑问/标点/空白
    s = re.sub(r'[\s？?！!。，,.、~～\-\—:：]', '', s)
    # 去掉头部/尾部多余助词与问句尾巴（概率大吗 / 大不大 / 怎么样 等）
    s = re.sub(r'^(的|了|吗|呢)', '', s)
    s = re.sub(r'(的|了|吗|呢|如何|怎么|怎样|大吗|大不大|大不|高吗|低吗|高不高|'
               r'怎么样|如何看|会怎样|会涨吗|会跌吗)$', '', s)
    return s.strip()


def _derive_wechat_keyword(msg):
    """从用户问题推导抓取关键词：守住「午盘/盘前/复盘」三段；否则抽领域词；
    抽不出时按当前时段研判。"""
    m = (msg or "")
    if "午盘" in m:
        return "今日午盘"
    if "盘前" in m:
        return "A股盘前"
    if "复盘" in m:
        return "今日A股复盘"
    topic = _extract_topic(m)
    topic = _clean_crawl_keyword(topic)
    if topic and 2 <= len(topic) <= 16:
        return topic
    try:
        return wechat.suggest_keyword()[0]
    except Exception:
        return "A股午盘"


# 抓取关键词里必须剥掉的问句尾巴/比较词，否则会把「谁占优」这类整句当关键词去搜
_KW_TAIL = ("谁占优", "谁更强", "谁更强一些", "谁更", "哪个更", "孰优孰劣", "孰优", "对比",
           "比较", "排名", "怎么样", "如何", "怎么看", "是什么", "有哪些")


def _clean_crawl_keyword(topic):
    """把抽出的领域词清洗成可用的抓取关键词（去掉问句尾巴与比较词）。"""
    s = (topic or "").strip()
    for t in _KW_TAIL:
        s = s.replace(t, "")
    s = re.sub(r"[\s？?！!。，,.、~～\-—:：]+$", "", s)
    return s.strip()


def _has_relevant_wechat(keyword, limit=15):
    """公众号目录里是否已有所需时段的舆情文章（今天产出 + 命中关键词）。

    返回 True 时走「直接汇总」；否则走「先抓取」。只看今天的 docx，避免把历史文章
    当成今日午盘舆情误判。读不到目录/解析失败时保守返回 False（宁可再去抓一次）。
    """
    try:
        import datetime as _dt
        toks = datareader._tokens(keyword)
        today = _dt.date.today()
        arts = (wechat.list_articles() or {}).get("files") or []
        for f in arts[:limit]:
            try:
                mt = _dt.datetime.fromtimestamp(f.get("mtime", 0))
            except Exception:
                continue
            if mt.date() != today:
                continue
            d = datareader.read_docx(f.get("path"), max_chars=4000)
            if d.get("error") or not d.get("paragraphs"):
                continue
            text = (d.get("title", "") + "\n" + "\n".join(d.get("paragraphs", [])[:15]))
            if datareader.score_text(text, toks) > 0:
                return True
    except Exception:
        pass
    return False


def _run(name, a, params):
    _, z, _c = _cfg_assistant()
    anno_dir = config.workspace_root("anno")
    out_dir = config.workspace_root("output")

    if name == "anno_dump":
        t = anno.dump(anno_dir, clean=True)
        return _task_out(t, a, "已启动转储任务，日志实时显示在下方可折叠区域。")

    if name == "anno_digest":
        dumps = datareader.anno_dumps(limit=200)
        if not dumps:
            return {"ok": False, "error": "公告目录里没有转储文本，请先执行「转储公告 PDF」。",
                    "action": name, "label": a["label"], "mode": a["mode"]}
        model = z.get("model")
        try:
            model = (_c.get("anno") or {}).get("model") or model
        except Exception:
            pass
        t = anno.digest_batch(dumps, model=model)
        mode = _anno_digest_mode(_c)
        msg = ("已启动精读任务（%d 份）。进度与日志实时显示；桥接模式下每一份会在"
               "「公告 → WorkBuddy 桥接」面板生成待处理 prompt，需把 JSON 贴回才能继续。"
               % len(dumps)) if mode == "bridge" else ("已启动精读任务（%d 份）。" % len(dumps))
        out = _task_out(t, a, msg)
        out["mode"] = mode
        return out

    if name == "anno_build":
        t = anno.build(None, anno_dir=anno_dir, out=None)
        return _task_out(t, a, "已启动出表任务：校验字段 → 排版 → 生成 xlsx。")

    if name == "anno_check":
        t = anno.check(None, anno_dir)
        return _task_out(t, a, "已启动校验任务（只校验不排版）。")

    if name == "anno_analyze":
        model = (_c.get("anno") or {}).get("model") or z.get("model")
        prompt = anno.build_analyze_prompt(anno_dir, out_dir, model)
        return _sync_out(a, "已生成控制指令，复制后粘贴进 AI 工作台即可自动跑完整流程。",
                         {"kind": "prompt", "text": prompt})

    if name == "report_ingest":
        try:
            prompt = report.build_ingest_prompt()
        except Exception as e:
            return {"ok": False, "error": "生成失败：%s" % e, "action": name,
                    "label": a["label"], "mode": "sync"}
        return _sync_out(a, "已生成晨会入库指令，复制后粘贴进 WorkBuddy 对话框即可跑完整流程"
                            "（docx→txt→LLM 提取→并入总表→补代码行情→重建 HTML）。",
                         {"kind": "prompt", "text": prompt})

    if name == "data_rebuild":
        date = params.get("date") or data.latest_date()
        if not date:
            return {"ok": False, "error": "没有可用的日期目录，请先下载数据或手动指定日期。",
                    "action": name, "label": a["label"], "mode": a["mode"]}
        t = data.rebuild(date)
        return _task_out(t, a, "已启动重建任务（日期目录 %s）。" % date)

    if name == "data_download_xx":
        t = data.download_xx()
        return _task_out(t, a, "已启动下载（xxxxx）。会弹出浏览器窗口，请完成登录/验证码。")

    if name == "data_download_sz":
        t = data.download_sz()
        return _task_out(t, a, "已启动下载（深交所逐笔，无头模式）。")

    if name == "wechat_crawl":
        t = wechat.crawl(count=params.get("count"), keyword=params.get("keyword"))
        return _task_out(t, a, "已启动抓取任务。")

    if name == "wechat_summarize":
        # 汇总舆情：先查公众号目录，有则直接 RAG 汇总；无则自动以时段关键词抓取，
        # 抓取完在 on_done 里自动汇总，结果写入 task.result.summary 供前端回显。
        msg = (params.get("message") or "").strip()
        kw = _derive_wechat_keyword(msg)
        count = params.get("count") or (_c.get("wechat", {}).get("default_count", 10))
        sess = params.get("session")
        if _has_relevant_wechat(kw):
            ra = rag_answer(msg or ("总结%s舆情" % kw), session=sess)
            ra["ok"] = True
            return ra
        d = config.workspace_root("wechat")
        started = time.time()

        def on_done(task):
            files = base.newest_files(d, {".docx"}, limit=50, since=started)
            summary, smeta = "", {}
            try:
                ra = rag_answer(msg or ("总结%s舆情" % kw), session=sess)
                summary = (ra.get("answer") or "").strip()
                smeta = {"mode": ra.get("mode"), "model": ra.get("model"),
                         "sources": [s.get("label") for s in ra.get("sources", [])],
                         "references": _flat_references(ra.get("sources"))}
            except Exception as e:
                summary = "（汇总失败：%s）" % e
            task.result = {"outputs": files, "summary": summary, "summary_meta": smeta}
            return task.result

        # 微信读书登录必须扫码 → 始终有头模式（headed），不传 headless 即默认 False
        t = wechat.crawl(count=count, keyword=kw, headless=False, on_done=on_done)
        return {"ok": True, "kind": "action", "action": a["name"], "label": a["label"],
                "mode": "auto", "icon": a.get("icon", "▶"),
                "message": ("未找到「%s」相关舆情（公众号目录为空或不匹配），已自动启动抓取"
                            "（关键词：%s，%d 篇）。抓取完成后将自动汇总。" % (kw, kw, count)),
                "task": t.snapshot(with_log=False),
                "followUp": msg or ("总结%s舆情" % kw), "keyword": kw, "crawled": True}

    if name == "task_status":
        items = tasks.list_tasks(limit=10) or []
        return _sync_out(a, "最近 %d 条任务：" % len(items),
                         {"kind": "tasks", "items": items})

    if name == "overview":
        ov = datareader.overview()
        ov["tasks"] = tasks.list_tasks(limit=5) or []
        return _sync_out(a, "工作台总览：", {"kind": "overview", "items": ov})

    return {"ok": False, "error": "动作未实现：%s" % name}


# ---------------------------------------------------------------- Agentic RAG
SYSTEM_PROMPT = """你是「EB 投研工作台」的内置助手，服务一位做可交换债（EB）投研的用户。

规矩：
1. 只依据【检索到的资料】回答，资料里没有的就直说「现有资料里没找到」，绝不编造数字、代码、日期。
2. 每个关键结论末尾用方括号标注引用编号，如 [1][2]；编号对应资料条目。
3. 中文回答，简明扼要（通常 3~8 句）。涉及换股价、代码、日期这类硬信息要原样给出。
4. 用户问"上次/之前"时优先用【历史对话】片段；问风险时结合公告摘要与数据行。
5. 不要复述资料全文，做的是归纳与判断。"""


def _llm_override():
    """助手问答的连接参数：独立于全局后端，可在 api 直连 / workbuddy 桥接间切换。

    assistant.backend：'api'（默认，直连云 SenseNova）→ 即使全局是桥接也走云端；
    'workbuddy' → 改走文件桥接（prompt 写入「桥接」面板，由 WorkBuddy 跑完贴回）。
    其它取值（如 local）→ 不覆盖 backend，跟随全局配置。
    """
    a, z, _ = _cfg_assistant()
    mode = (a.get("backend") or "api").strip().lower()
    ov = {}
    if mode == "api":
        ov["backend"] = "api"
        ov["base_url"] = z.get("base_url")
        ov["api_key"] = z.get("api_key") or None
    elif mode == "workbuddy":
        ov["backend"] = "workbuddy"
    if a.get("model"):
        ov["model"] = a["model"]
    ov["temperature"] = a.get("temperature", 0.3)
    return ov


# ---------------------------------------------------------------- 检索充分度复判
# CRAG/Self-RAG 简化版：生成后复判「答案是否匮乏」，匮乏则补取一次再答（最多一轮）。
# 判定为纯规则（零额外 LLM 调用，不撞限流），阈值/开关可在 config.assistant 里调。
_EMPTY_PHRASES = ("未明确", "没找到", "未找到", "资料里没有", "现有资料未", "未给出",
                  "无法判断", "不足以", "暂无", "不包含", "缺乏", "无从", "没有相关",
                  "未提及", "资料不足", "信息不足", "暂未", "未收录")
# 对比/排名类意图：这类问题要求「谁占优/排名/对比」必须有结构化支撑，更容易判匮乏
_COMPARE_MARKERS = ("谁占优", "谁更", "对比", "比较", "排名", "排序", "哪个更", "孰优",
                    "优劣", "排行", "top", "前几", "哪家", "谁强")


def _sufficiency(question, answer, snips, cfg=None):
    """复判回答是否「资料不足以支撑」。返回 (ok:bool, reason:str)。

    ok=False 表示答案匮乏、值得补取一次。纯规则、零联网：
    - 有明显回避措辞（"未明确/没找到/资料不足"…）→ 不足
    - 检索片段过少（低于 min_snippets）→ 不足
    - 对比/排名类问题但答案过短/无结构化支撑 → 不足
    """
    a = cfg or {}
    if not a.get("sufficiency_check", True):
        return True, "复判已关闭"
    txt = (answer or "").strip()
    if not txt:
        return False, "答案为空"
    n = len(snips or [])
    min_sn = int(a.get("min_snippets", 3) or 3)
    # 1) 回避措辞：出现即判不足
    hit = next((p for p in _EMPTY_PHRASES if p in txt), None)
    if hit:
        return False, "答案出现回避措辞「%s」且仅 %d 条片段" % (hit, n)
    # 2) 片段过少
    if n < min_sn:
        return False, "仅检索到 %d 条片段（低于阈值 %d）" % (n, min_sn)
    # 3) 对比/排名类：要"谁占优"却没成表/没排名结构 → 不足
    low_q = (question or "").lower()
    if any(k in low_q for k in _COMPARE_MARKERS):
        has_struct = ("|" in txt) or ("：" in txt and "\n" in txt) or \
                     any(c in txt for c in ("第一", "其次", "排名", "居首", "①", "1."))
        # 有结构化排名即认为够；否则看长度，过短才判不足（避免误伤"简短但有结论"的回答）
        if not has_struct and len(txt) < 60:
            return False, "对比类问题但答案缺乏结构化排名/对比"
    return True, ""


def _retrieval_sufficiency(question, snips, cfg=None):
    """**生成前**判「检索到的资料够不够」，不够就别先生成那个瑕疵答案（先补后答）。

    与 `_sufficiency`（生成后复判、看答案措辞）不同，这里只看检索侧证据：
    - 片段过少（低于 min_snippets）→ 不足
    - 对比/排名类问题（谁占优/对比/排名…）但没有任何可支撑"对比"的高分片段 → 不足
    返回 (ok:bool, reason:str)。纯本地、零 LLM 调用。
    """
    a = cfg or {}
    if not a.get("pre_check", True):
        return True, "前置判定已关闭"
    n = len(snips or [])
    min_sn = int(a.get("min_snippets", 3) or 3)
    if n < min_sn:
        return False, "仅检索到 %d 条片段（低于阈值 %d）" % (n, min_sn)
    low_q = (question or "").lower()
    if any(k in low_q for k in _COMPARE_MARKERS):
        # 对比类问题：看是否有"像样"的片段（有实质正文而非仅标题/元信息）
        rich = [s for s in (snips or []) if len((s.get("text") or "").strip()) >= 120]
        if len(rich) < 2:
            return False, "对比类问题但可支撑对比的资料片段不足（%d 条有实质正文）" % len(rich)
    return True, ""


def _build_context(snippets):
    if not snippets:
        return "（没有检索到任何资料）"
    parts = []
    for i, s in enumerate(snippets, start=1):
        parts.append("[%d] 来源：%s（%s）\n%s" % (
            i, retrieval.SOURCE_LABELS.get(s.get("source"), s.get("source", "")),
            s.get("ref") or s.get("title") or "", (s.get("text") or "").strip()))
    return "\n\n".join(parts)


def _group_sources(snippets):
    groups = {}
    for s in snippets:
        key = s.get("source", "?")
        g = groups.setdefault(key, {"source": key,
                                    "label": retrieval.SOURCE_LABELS.get(key, key),
                                    "count": 0, "refs": []})
        g["count"] += 1
        ref = s.get("ref") or ""
        if ref and not any(x.get("ref") == ref for x in g["refs"]):
            g["refs"].append({"ref": ref, "title": s.get("title") or "",
                              "url": s.get("url") or ""})
    return list(groups.values())


def _flat_references(sources):
    """把 rag_answer.sources 压平成参考文献清单（去重，带标题/原文链接/来源）。"""
    refs, seen = [], set()
    for g in (sources or []):
        for it in g.get("refs", []):
            t = (it.get("title") or "").strip()
            if t and t not in seen:
                seen.add(t)
                refs.append({"title": t, "url": it.get("url") or "",
                             "path": it.get("ref") or "", "source": g.get("label") or ""})
    return refs


def _resolve_ref_file(ref):
    """把 snippet.ref 解析成真实存在的本地文件绝对路径；无法定位（记忆/任务日志）返回 None。"""
    if not ref:
        return None
    if ref.startswith("memory:") or ref.startswith("runtime/tasks"):
        return None          # 这些是会话/任务元信息，没有独立可打开的文件
    p = ref
    if not os.path.isabs(p):
        # 仅 "Anno/input.json" 这类相对工作区的写法需要拼根
        if ref.startswith("Anno/"):
            p = os.path.join(config.workspace_root("anno"), ref[len("Anno/"):])
        else:
            return None
    p = os.path.abspath(p)
    return p if os.path.isfile(p) else None


def _degraded_bridge(question, snips, reason):
    """模型不可用（如 429 限流）时的降级作答：只给「本地资料路径」，不打包正文。

    返回 {"text", "paths"}。text 是一份「桥接 prompt」——列出命中资料的本地绝对路径 +
    用户问题 + 阅读指示，交由助手（WorkBuddy，具备文件读取工具）或用户本人直接打开阅读。
    资料按得分取前 6 条（历史瘦身），避免提示词过长；正文绝不内联，因为太笨重。

    注意：普通 LLM 可用时走 _build_context 把正文喂给模型，此函数只在「降级」分支调用。
    """
    picked = sorted(snips, key=lambda s: -s.get("score", 0))[:6]
    rows, paths, nonfile = [], [], 0
    seen, big = set(), []
    for s in picked:
        label = retrieval.SOURCE_LABELS.get(s.get("source"), s.get("source", ""))
        fp = _resolve_ref_file(s.get("ref") or "")
        if not fp:
            nonfile += 1
            continue
        if fp in seen:      # 同一文件常被多条片段引用，去重后再列，免得阅读者重复打开
            continue
        seen.add(fp)
        rows.append("[%d] %s · %s\n    %s" % (len(rows) + 1, label, s.get("title") or "", fp))
        paths.append(fp)
        try:                # 大文件提示一下，别让人通读 800KB 的 HTML
            if os.path.getsize(fp) > 300 * 1024:
                big.append(os.path.basename(fp))
        except OSError:
            pass
    if not rows:
        text = ("⚠ 模型暂时不可用（%s）。而且我在现有资料里也没找到可定位的本地文件。\n"
                "可以试试：先「转储公告 PDF」或「重建数据总表」，让我有东西可查。" % reason)
    else:
        text = ("⚠ 模型暂时不可用（%s）。未打包正文（太长），已为你定位到以下本地资料路径，"
                "请直接打开阅读后回答该问题：\n\n"
                "【用户问题】%s\n\n"
                "【本地资料（请逐一打开阅读）】\n%s" % (reason, question, "\n".join(rows)))
        if nonfile:
            text += ("\n\n（另有 %d 条命中来自对话记忆 / 任务日志，无独立文件可定位。）" % nonfile)
        if big:
            text += ("\n\n注意：%s 体积较大（>300KB），建议先检索/定位关键段落再读，不必通读全文。"
                     % "、".join(big))
        text += "\n\n提示：基于以上文件内容归纳回答即可，无需再检索。"
    return {"text": text, "paths": paths}


def _make_bridge_qa(question, snips, ov, name):
    """构造并落盘一份「检索片段 + 问题」的桥接 prompt，返回 (bid, prompt_text, sources)。"""
    ctx = _build_context(snips)
    user_msg = "【用户问题】%s\n\n【检索到的资料】\n%s" % (question, ctx)
    bid = llm.bridge_write(SYSTEM_PROMPT, user_msg, name=name, model=ov.get("model", ""))
    return bid, llm.bridge_prompt_text(bid), _group_sources(snips)


def _clean_reason(reason):
    """去掉英文报错尾巴（如 "。inference exceeds tpm/rpm limit"），让提示更口语化。"""
    r = (reason or "").strip()
    if "。" in r:
        head, tail = r.rsplit("。", 1)
        # 后半段不含任何中文 → 视为英文尾巴，丢弃
        if tail and not re.search(r"[\u4e00-\u9fff]", tail):
            r = head
    return r


_FIELD_RE = re.compile(r"【([^】]{1,12})】\s*([\s\S]*?)(?=【|$)")


def _extract_fields(text):
    """从结构化片段（如舆情记忆精华的固定七节格式）里抽 【节】→内容。

    返回 [(label, value)]，只保留非空且非「原文未提及」的字段。纯本地、不依赖 LLM，
    用于限流降级时把结构化源直接拆成可读字段，而不是把整段原文甩给用户。
    """
    out = []
    for m in _FIELD_RE.finditer(text or ""):
        k, v = m.group(1).strip(), m.group(2).strip()
        if not v or v == "原文未提及":
            continue
        out.append((k, v[:320] + ("…" if len(v) > 320 else "")))
    return out


def _local_intel_card(snips, reason):
    """限流降级（纯本地、不联网）的情报卡：把已检索到的片段按源分组，对结构化源抽字段，
    拼成一份用户可直接阅读的答案。完全不调用 LLM——LLM 挂了也能用。

    桥接 prompt 由调用方另行提供（作为「可选升级」），本函数只负责本地可读内容。
    """
    if not snips:
        return ("⚠ 模型暂时不可用（%s），且未检索到本地相关资料。\n"
                "可先「转储公告 PDF」或「重建数据总表」让我有东西可查。" % _clean_reason(reason))
    # 按源分组（组内保持 score 降序）
    groups = {}
    for s in sorted(snips, key=lambda x: -x.get("score", 0)):
        groups.setdefault(s.get("source") or "unknown", []).append(s)
    parts = []
    for src, items in groups.items():
        label = retrieval.SOURCE_LABELS.get(src, src)
        lines = ["### 📂 %s · %d 条" % (label, len(items))]
        for i, s in enumerate(items, 1):
            title = s.get("title") or s.get("ref") or "（无标题）"
            text = (s.get("text") or "").strip().replace("\r", "")
            fields = _extract_fields(text)
            if fields:                       # 结构化源（如舆情记忆精华）：抽字段竖排
                body = "\n".join("· **%s**：%s" % (k, v) for k, v in fields)
            else:                           # 非结构化源：截取前文，避免整段甩给用户
                body = text[:400] + ("…" if len(text) > 400 else "")
            lines.append("**%d. %s**\n%s" % (i, title, body))
        parts.append("\n".join(lines))
    header = ("⚠ 模型暂时不可用（%s），已为你定位以下**本地资料**（纯本地检索，无需联网）：\n\n"
              % _clean_reason(reason))
    card = header + "\n\n".join(parts)
    card += ("\n\n— 以上为本地片段直接拼装，未经 AI 归纳。如需精确综合回答，"
             "可复制下方「桥接 prompt」提交在线 AI 平台。")
    return card


def _bridge_qa(question, snips, ov):
    """workbuddy 桥接模式下的问答：不阻塞，直接返回检索片段 + 桥接提示。

    把「检索到的资料 + 用户问题」写成一份桥接 prompt（交给 WorkBuddy 归纳后贴回），
    并即时返回一条带说明的气泡，避免首页问答卡死在 bridge_wait 里。
    """
    bid, prompt_text, sources = _make_bridge_qa(question, snips, ov, "首页对话助手问答")
    return {
        "kind": "qa",
        "mode": "bridge",
        "model": "",
        "prompt_id": bid,
        "prompt_text": prompt_text,
        "answer": ("（已生成桥接 prompt，可直接在**本对话框**里操作：点「复制 prompt」交给 WorkBuddy 运行，"
                   "把返回的 JSON/文本贴到下方框提交，归纳回答会显示在本对话中，无需去「公告」页。）"),
        "sources": sources,
        "used": sorted({s.get("source") for s in snips}),
        "used_labels": [retrieval.SOURCE_LABELS.get(s, s) for s in
                        sorted({s.get("source") for s in snips})],
        "signals": [],
        "retrieved": len(snips),
        "elapsed": 0,
    }


def _degraded_to_bridge(question, snips, reason, ov, hint=""):
    """429/配额等系统侧抖动：不换模型重试。
    默认返回【纯本地情报卡】（按源分组 + 字段抽取，不联网即可读）；
    同时保留桥接 prompt（prompt_text）作为「可选升级」——想拿 AI 归纳回答就复制提交在线平台。
    """
    bid, prompt_text, sources = _make_bridge_qa(question, snips, ov, "首页对话助手问答(限流降级)")
    # 默认给「纯本地情报卡」：按源分组 + 字段抽取，不联网即可读；
    # 桥接 prompt 仍保留（prompt_text）作为「可选升级」——想拿 AI 归纳就复制提交在线平台。
    answer = _local_intel_card(snips, reason)
    return {
        "kind": "qa",
        "mode": "bridge",
        "model": "",
        "prompt_id": bid,
        "prompt_text": prompt_text,
        "answer": answer,
        "sources": sources,
        "used": sorted({s.get("source") for s in snips}),
        "used_labels": [retrieval.SOURCE_LABELS.get(s, s) for s in
                        sorted({s.get("source") for s in snips})],
        "signals": [],
        "retrieved": len(snips),
        "note": reason,
        "hint": hint,
        "elapsed": 0,
    }


# ---------------------------------------------------------------- 后台补答登记簿
# 「先补后答」/「生成后复判」补抓是异步长任务（几分钟）。任务跑完时 on_done 钩子会做一次
# 二次生成，把补全答案写进 task.result["followup_qa"]；前端在进度卡上调用
# /api/assistant/followup?task=<tid> 轮询取回（无需刷新页面）。登记簿只存内存 +
# task.result（tasks 有界淘汰），无需落盘。
_FOLLOWUP = {}          # task_id -> {"question":..., "session":...}
_FOLLOWUP_LOCK = threading.Lock()
_FOLLOWUP_LIMIT = 40


def _register_followup(tid, question, session):
    """登记「某抓取任务完成后要做二次生成」，供 on_done 钩子回查问题与会话。"""
    if not tid:
        return
    with _FOLLOWUP_LOCK:
        _FOLLOWUP[tid] = {"question": question, "session": session}
        while len(_FOLLOWUP) > _FOLLOWUP_LIMIT:
            _FOLLOWUP.pop(next(iter(_FOLLOWUP)), None)


def _pop_followup(tid):
    with _FOLLOWUP_LOCK:
        return _FOLLOWUP.pop(tid, None)


def _make_followup_hook(question, session, a):
    """构造传给 wechat.crawl 的 on_done：抓取一结束就用新资料再生成一次，
    结果写进 task.result['followup_qa']（"先补后答"取不到的那部分答案在这里补齐）。"""
    def _hook(task):
        try:
            out = _generate_only(question, session, a)
            out.pop("_snips", None)
            out.pop("_plan", None)
            task.result = dict(task.result or {})
            task.result["followup_qa"] = out
            task.emit("补取完成，已用新资料重新生成答案", "info")
        except Exception as e:
            task.emit("补取后重新生成失败：%s" % e, "warn")
        return task.result
    return _hook


def rag_answer(question, session=None, history=None):
    """Agentic RAG 问答：规划 → 检索 → 生成（失败降级本地）。

    流程（CRAG/Self-RAG 简化版 + 先补后答）：
      1. 规划 → 检索
      2. **前置判定**：检索侧证据不足（片段少 / 对比类缺支撑）→ 先补抓再生成
         （补抓完成则用新资料生成；若仍未完成，则立刻返回「补抓中」进度卡，**不生成瑕疵答案**）
      3. 生成
      4. **后置复判**：答案匮乏 → 再补取一次（最多一轮）
    """
    a, z, _ = _cfg_assistant()
    t0 = time.time()
    if history is None:
        hist_recs = (memory.read(session, limit=40) if session else [])
        hist = []
        for r in hist_recs[-(int(a.get("max_history", 12)) * 2):]:
            hist.append({"role": "user" if r.get("role") == "user" else "assistant",
                         "content": (r.get("text") or "")[:1200]})
    else:
        hist = history

    ov = _llm_override()
    do_retry = bool(a.get("sufficiency_retry", True))
    do_pre = bool(a.get("pre_check", True))

    def _attempt(q, pre_snips=None):
        """跑一轮：规划 → 检索 → 生成（或降级）。返回 out dict。

        pre_snips 非空时跳过检索，直接用给定片段生成（先补后答复用第一次检索结果）。
        """
        if pre_snips is not None:
            plan_obj = {"sources": [], "signals": []}
            used = sorted({s.get("source") for s in pre_snips})
            g = {"snippets": pre_snips, "used": used,
                 "used_labels": [retrieval.SOURCE_LABELS.get(u, u) for u in used]}
        else:
            plan_obj = retrieval.plan(q)
            g = retrieval.gather(q, plan_obj, session=session)
        snips = g["snippets"]
        ctx = _build_context(snips)
        user_msg = "【用户问题】%s\n\n【检索到的资料】\n%s" % (q, ctx)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + hist + \
                   [{"role": "user", "content": user_msg}]
        if ov.get("backend") == "workbuddy":
            o = _bridge_qa(q, snips, ov)
            o["_snips"], o["_plan"] = snips, plan_obj
            return o
        r = llm.chat(messages, override=ov,
                     timeout=min(int(a.get("timeout", 120) or 120), 60))
        o = {
            "kind": "qa",
            "sources": _group_sources(snips),
            "used": g["used"],
            "used_labels": g["used_labels"],
            "signals": plan_obj.get("signals") or [],
            "retrieved": len(snips),
            "elapsed": round(time.time() - t0, 2),
        }
        if r.get("ok"):
            o.update({"answer": (r.get("content") or "").strip(), "mode": "llm",
                      "model": r.get("model", ""), "note": ""})
        else:
            reason = r.get("message") or r.get("error") or "未知原因"
            if r.get("kind") == "quota" or "429" in str(reason):
                deg = _degraded_to_bridge(q, snips, reason, ov, r.get("hint", ""))
                o.update(deg)
            else:
                deg = _degraded_bridge(q, snips, reason)
                o.update({"answer": deg["text"], "mode": "local", "model": "",
                          "note": reason, "hint": r.get("hint", ""), "local_paths": deg["paths"]})
        o["_snips"], o["_plan"] = snips, plan_obj
        return o

    # —— 步骤 1：先检索一次（供前置判定与生成共用，避免重复检索）
    plan_obj = retrieval.plan(question)
    g0 = retrieval.gather(question, plan_obj, session=session)
    snips0 = g0["snippets"]

    # —— 步骤 2：前置判定（先补后答）——检索侧证据不足就先补抓，**不生成瑕疵答案**。
    # 只有「舆情类 + 有登录态」才可能补抓；其余不足情况直接进入正常生成。
    if do_pre and ov.get("backend") != "workbuddy":
        p_ok, p_why = _retrieval_sufficiency(question, snips0, a)
        if not p_ok:
            crawl = None
            try:
                crawl = _supplement_and_retry(question, session, a)
            except Exception:
                crawl = None
            if crawl and crawl.get("added", 0) > 0:
                # 抓完了且有新增 → 用新资料直接生成（一步到位，用户看到的就是补全答案）
                snips0 = (retrieval.gather(question, plan_obj, session=session)
                          .get("snippets") or snips0)
                out = _attempt(question, pre_snips=snips0)
                out["sufficiency"] = {"ok": True, "reason": p_why, "pre_supplied": True,
                                      "crawl": crawl}
                out["signals"] = list(out.get("signals") or []) + \
                                 ["前置判定：%s → 已先补取（%s，+%d 篇）再作答"
                                  % (p_why, crawl.get("keyword", ""), crawl.get("added", 0))]
                out.pop("_snips", None)
                out.pop("_plan", None)
                return out
            if crawl and crawl.get("status") == "running":
                # 抓取尚未完成 → **返回进度卡，不回显任何瑕疵答案**；完成经 SSE 自动补答
                tid = (crawl.get("task") or {}).get("id") or ""
                _register_followup(tid, question, session)
                return {
                    "kind": "qa", "mode": "supplementing",
                    "answer": "", "sources": _group_sources(snips0),
                    "used": g0.get("used"), "used_labels": g0.get("used_labels"),
                    "signals": ["前置判定：%s → 正在补取（%s），完成后自动补全答案"
                                % (p_why, crawl.get("keyword", ""))],
                    "retrieved": len(snips0), "elapsed": round(time.time() - t0, 2),
                    "sufficiency": {"ok": False, "reason": p_why, "supplementing": True,
                                    "crawl": crawl},
                    "crawl_task": tid, "keyword": crawl.get("keyword", ""),
                    "model": "", "note": "",
                }
            # 补不了（无登录态 / 非舆情类）→ 落回正常生成，由后置复判兜底
            snips0 = (retrieval.gather(question, plan_obj, session=session)
                      .get("snippets") or snips0)

    out = _attempt(question, pre_snips=snips0)

    # —— 步骤 3：后置复判闭环（最多补取 1 轮）：答案匮乏 → 再补取一次并重答。
    # 仅对 LLM 正常作答的结果复判；降级/桥接结果不做（本来就没走通模型）。
    if do_retry and out.get("mode") == "llm":
        ok, why = _sufficiency(question, out.get("answer"), out.get("_snips"), a)
        if not ok:
            out["sufficiency"] = {"ok": False, "reason": why, "retried": False}
            out["signals"] = list(out.get("signals") or []) + ["复判：%s → 尝试补取" % why]
            try:
                crawled = _supplement_and_retry(question, session, a)
            except Exception as e:
                crawled = None
                out["signals"].append("补取失败：%s" % e)
            if crawled and crawled.get("added", 0) > 0:
                # 抓取已完成且有新增 → 立刻用新资料重答
                out2 = _attempt(question)
                out2["sufficiency"] = {"ok": True, "reason": why, "retried": True,
                                       "crawl": crawled}
                out2["signals"] = list(out2.get("signals") or []) + \
                                  ["复判不足 → 已补取（%s，+%d 篇）并重答"
                                   % (crawled.get("keyword", ""), crawled.get("added", 0))]
                out = out2
            elif crawled and crawled.get("status") == "running":
                # 抓取仍在跑 → **改用进度卡**（不把这道复判出的瑕疵答案当最终结果给用户），
                # 抓完由 on_done 二次生成、前端经 SSE 自动补全。
                tid = (crawled.get("task") or {}).get("id") or ""
                _register_followup(tid, question, session)
                out = {
                    "kind": "qa", "mode": "supplementing",
                    "answer": "", "sources": _group_sources(out.get("_snips") or []),
                    "used": out.get("used"), "used_labels": out.get("used_labels"),
                    "signals": list(out.get("signals") or []) +
                               ["复判不足 → 正在补取（%s），完成后自动补全答案"
                                % crawled.get("keyword", "")],
                    "retrieved": out.get("retrieved"), "elapsed": round(time.time() - t0, 2),
                    "sufficiency": {"ok": False, "reason": why, "supplementing": True,
                                    "crawl": crawled},
                    "crawl_task": tid, "keyword": crawled.get("keyword", ""),
                    "model": "", "note": "",
                }
            else:
                out["sufficiency"] = {"ok": False, "reason": why, "retried": False}
        else:
            out["sufficiency"] = {"ok": True, "reason": why, "retried": False}
    out.pop("_snips", None)
    out.pop("_plan", None)
    return out


def _generate_only(question, session, a):
    """只做「检索 → 生成」一步（不补取、不复判），供后台补答钩子复用。"""
    ov = _llm_override()
    plan_obj = retrieval.plan(question)
    g = retrieval.gather(question, plan_obj, session=session)
    snips = g["snippets"]
    ctx = _build_context(snips)
    user_msg = "【用户问题】%s\n\n【检索到的资料】\n%s" % (question, ctx)
    hist_recs = (memory.read(session, limit=40) if session else [])
    hist = []
    for r in hist_recs[-(int(a.get("max_history", 12)) * 2):]:
        hist.append({"role": "user" if r.get("role") == "user" else "assistant",
                     "content": (r.get("text") or "")[:1200]})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + hist + \
               [{"role": "user", "content": user_msg}]
    o = {"kind": "qa", "sources": _group_sources(snips), "used": g.get("used"),
         "used_labels": g.get("used_labels"), "signals": list(plan_obj.get("signals") or []),
         "retrieved": len(snips), "elapsed": 0, "_snips": snips, "_plan": plan_obj}
    r = llm.chat(messages, override=ov, timeout=min(int(a.get("timeout", 120) or 120), 60))
    if r.get("ok"):
        o.update({"answer": (r.get("content") or "").strip(), "mode": "llm",
                  "model": r.get("model", ""), "note": ""})
    else:
        reason = r.get("message") or r.get("error") or "未知原因"
        deg = _degraded_bridge(question, snips, reason)
        o.update({"answer": deg["text"], "mode": "local", "model": "",
                  "note": reason, "local_paths": deg["paths"]})
    return o


def _supplement_and_retry(question, session, a):
    """复判判不足后，补取一次舆情资料。返回 dict（含 keyword/added/status）或 None。

    约束（避免打断用户）：
    - **只用无头模式**：有登录态才跑，没有则直接放弃（不弹扫码窗口卡住问答）。
    - 只补「舆情类」问题：推导出关键词才抓；纯本地问题（公告/数据）不抓公众号。
    - **有界等待**（sufficiency_wait，默认 45s）：抓取通常要几分钟，超时就**不阻塞问答**，
      返回 status='running'——本次答案照常返回（标「抓取中」），用户稍后再问即可命中新资料。
    """
    if not (a.get("sufficiency_crawl", True)):
        return None
    kw = _derive_wechat_keyword(question)
    if not kw:
        return None
    # 无登录态就别抓：无头会直接失败，非无头会弹码卡死
    try:
        from ..projects import wechat as _wx
        st = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "tools", "wechat-gzh-crawler", "login_state.json")
        if not os.path.isfile(st):
            return None
        before = len((_wx.list_articles() or {}).get("files") or [])
        # 注入 on_done：抓完即用新资料再生成一次，写进 task.result['followup_qa']，
        # 供前端在进度卡上轮询取回（「先补后答」/后置复判都能靠它把答案补全）。
        t = _wx.crawl(count=int(a.get("sufficiency_count", 6) or 6), keyword=kw,
                      headless=True, on_done=_make_followup_hook(question, session, a))
        deadline = time.time() + int(a.get("sufficiency_wait", 45) or 45)
        status = "running"
        while time.time() < deadline:
            snap = t.snapshot(with_log=False) if hasattr(t, "snapshot") else {}
            if snap.get("status") in ("done", "error", "stopped", "failed"):
                status = snap.get("status")
                break
            time.sleep(1.0)
        after = len((_wx.list_articles() or {}).get("files") or [])
        added = max(0, after - before)
        return {"keyword": kw, "added": added, "status": status,
                "task": (t.snapshot(with_log=False) if hasattr(t, "snapshot") else {})}
    except Exception:
        return None


# ---------------------------------------------------------------- 统一入口
def handle(message, session=None, confirm=False, action=None, params=None):
    """POST /api/assistant 的处理入口。

    confirm=True 时直接执行 action（用户已在确认卡上点过）。
    否则先分类：动作 → 给确认卡（need_confirm 关闭时直接执行）；问答 → RAG。
    """
    a, _, _ = _cfg_assistant()
    session = session or memory.new_session_id()

    if confirm and action:
        memory.append(session, "user", "（确认执行）%s" % ACTION_MAP.get(action, {}).get("label", action))
        res = execute_action(action, params or {})
        memory.append(session, "tool", res.get("message") or res.get("error") or "",
                      refs=[res.get("action", "")], sources=["action"])
        res["session"] = session
        return res

    if not (message or "").strip():
        return {"ok": False, "error": "消息为空"}

    memory.append(session, "user", message)
    intent = classify(message)
    params = intent.get("params") or {}

    if intent["kind"] == "action":
        # sync 型动作（总览/任务状态/生成指令）立即返回，不弹确认卡
        # 舆情汇总：全自动（先查/抓公众号再汇总），不弹确认卡，避免打断“自动填入关键词抓取”的链路
        if intent["action"] == "wechat_summarize":
            params = dict(params or {})
            params["session"] = session
            params["message"] = message
            res = execute_action(intent["action"], params)
            memory.append(session, "tool", res.get("message") or res.get("error") or "",
                          refs=[intent["action"]], sources=["action"])
            res["session"] = session
            return res
        a_mode = ACTION_MAP.get(intent["action"], {}).get("mode", "sync")
        if a.get("need_confirm", True) and a_mode in ("auto", "bridge"):
            d = describe(intent["action"], params)
            return {"ok": True, "kind": "confirm", "action": intent["action"],
                    "label": d["title"], "mode": d["mode"], "icon": d["icon"],
                    "preview": d["lines"], "params": params,
                    "reason": intent.get("reason", ""), "session": session,
                    "message": "将要执行：**%s**" % d["title"]}
        res = execute_action(intent["action"], params)
        memory.append(session, "tool", res.get("message") or res.get("error") or "",
                      refs=[intent["action"]], sources=["action"])
        res["session"] = session
        return res

    res = rag_answer(message, session=session)
    res["ok"] = True
    res["session"] = session
    memory.append(session, "assistant", res.get("answer", ""),
                  refs=[s["label"] for s in res.get("sources", [])],
                  sources=res.get("used", []))
    return res


def context_brief():
    """首屏「可用数据源」面板：告诉用户现在能查到什么。"""
    ov = datareader.overview()
    items = [
        {"label": "公告整理", "value": "%d 份 PDF / %d 份转储 / %d 行精读结果"
         % (ov["anno"]["pdf_count"], ov["anno"]["dump_count"], ov["anno"]["input_rows"])},
        {"label": "成交估值", "value": "%d 个日期目录（最新 %s）"
         % (ov["data"]["date_count"], ov["data"]["latest_date"] or "无")},
        {"label": "舆情文章", "value": "%d 篇 docx" % ov["wechat"]["doc_count"]},
    ]
    rt = datareader.report_rows()
    if rt and rt.get("rows"):
        secs = {str(r[2]).strip() for r in rt["rows"]
                if len(r) > 2 and str(r[2] or "").strip()}
        items.append({"label": "晨会观点",
                      "value": "%d 条标的观点 / %d 个细分板块" % (len(rt["rows"]), len(secs))})
    if memory.enabled():
        items.append({"label": "对话记忆", "value": "%d 个历史会话" % len(memory.list_sessions())})
    return {"items": items, "overview": ov,
            "actions": [{"name": a["name"], "label": a["label"], "icon": a["icon"],
                         "mode": a["mode"], "desc": a["desc"]} for a in ACTIONS]}
