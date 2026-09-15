# -*- coding: utf-8 -*-
"""Anno 项目：公告 PDF → 结构化情报整理表。

分工（SKILL.md 定死的，不要改）：
    第1步 脚本转储 PDF（pdf_dump.py）
    第2步 【模型精读】逐份提炼 9 个字段  ← 本模块的 AI 部分，LLM 在这里
    第3步 脚本校验 + 排版出表（build_anno_xlsx.py）
"""
import json
import os
import re
import time

from ..core import config, llm
from . import base

FIELDS = ["公告日期", "上市公司", "可交换债", "证券代码", "标的股票",
          "股票代码", "换股价格", "公告性质", "内容摘要"]

# 精读提示词不再写死在代码里：唯一来源是 tools/eb-anno-digest/prompt.md
# （与 SKILL.md 同级）。平台运行时读取，改完文件下一次精读自动生效，无需重启。
PROMPT_FILE = "prompt.md"
PROMPT_SECTIONS = ("SYSTEM_PROMPT", "USER_TEMPLATE", "SCAN_USER_TEMPLATE")
_PROMPT_CACHE = {"mtime": None, "data": None}


class PromptLoadError(Exception):
    """提示词文件缺失或章节不全。"""


def prompt_path():
    """提示词唯一来源的绝对路径。"""
    return os.path.join(base.skill_dir("eb-anno-digest"), PROMPT_FILE)


def load_prompts(force=False):
    """读取精读提示词，返回 {段名: 文本}。

    按文件 mtime 做进程内缓存：改完 prompt.md 下一次精读自动生效，不必重启平台。
    缺文件或缺章节时抛 PromptLoadError（调用方转成可读错误，不让整批任务崩掉）。
    """
    path = prompt_path()
    try:
        mtime = os.stat(path).st_mtime
    except OSError as e:
        raise PromptLoadError("找不到提示词文件 %s（%s）" % (path, e))
    if not force and _PROMPT_CACHE["data"] and _PROMPT_CACHE["mtime"] == mtime:
        return _PROMPT_CACHE["data"]

    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    data, cur, buf = {}, None, []
    for line in text.splitlines():
        head = line.strip()
        name = head[2:].strip() if head.startswith("# ") else ""
        if name in PROMPT_SECTIONS:
            if cur:
                data[cur] = "\n".join(buf).strip("\n")
            cur, buf = name, []
        elif cur:
            buf.append(line)
    if cur:
        data[cur] = "\n".join(buf).strip("\n")

    missing = [s for s in PROMPT_SECTIONS if not data.get(s)]
    if missing:
        raise PromptLoadError("提示词文件缺少章节 %s：%s" % ("、".join(missing), path))

    _PROMPT_CACHE["mtime"] = mtime
    _PROMPT_CACHE["data"] = data
    return data


def _extract_json(text):
    """从模型输出里抠出 JSON：容忍 ```json 围栏和前后废话。"""
    if not text:
        return None
    if isinstance(text, (dict, list)):
        # 桥接回填时 content 可能已是 dict/list，先序列化回字符串再解析
        try:
            text = json.dumps(text, ensure_ascii=False)
        except Exception:
            return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    s = s.strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # 退一步：抓第一个 { 到最后一个 }
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(s[i:j + 1])
        except Exception:
            return None
    return None


def dump(anno_dir=None, clean=True):
    """第1步：PDF 转储成 txt（默认转储前清除原有 txt）。"""
    d = anno_dir or base.workspace("anno")
    cmd = [base.python_exe(), base.script_path("eb-anno-digest", "pdf_dump.py"), d]
    if clean:
        cmd.append("--clean")
    started = time.time()

    def on_done(task):
        dump_dir = os.path.join(d, "_txt_dump")
        return {"dump_dir": dump_dir.replace("\\", "/"),
                "files": base.newest_files(dump_dir, {".txt"}, limit=200, since=started)}

    return base.run("转储公告 PDF", "anno", cmd, on_done=on_done)


def list_txt(anno_dir=None):
    """列出已转储的文本，供前端勾选精读。扫描件附上图片目录信息。"""
    d = anno_dir or base.workspace("anno")
    dump_dir = os.path.join(d, "_txt_dump")
    if not os.path.isdir(dump_dir):
        return {"dump_dir": dump_dir.replace("\\", "/"), "files": []}
    files = base.newest_files(dump_dir, {".txt"}, limit=500)
    for f in files:
        base_name = os.path.splitext(f["name"])[0]
        pages_dir = os.path.join(dump_dir, base_name + "_pages")
        if os.path.isdir(pages_dir):
            pngs = sorted(p for p in os.listdir(pages_dir) if p.lower().endswith(".png"))
            f["scanned"] = True
            f["pages"] = len(pngs)
            f["pages_dir"] = pages_dir.replace("\\", "/")
            f["images"] = [os.path.join(pages_dir, p).replace("\\", "/") for p in pngs]
        else:
            f["scanned"] = (f["size"] < 200)
            f["pages"] = 0
            f["images"] = []
    return {"dump_dir": dump_dir.replace("\\", "/"), "files": files}


def digest_one(txt_path, name=None, created="", model=None, on_log=None,
               should_abort=None):
    """第2步：调 LLM 精读单份公告，返回 9 字段 dict。

    should_abort：桥接等待期间的停止检查（由批量任务传入「任务是否已 stopped」）。
    """
    c = config.load()
    try:
        with open(txt_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except Exception as e:
        return {"ok": False, "error": "读取转储文本失败：%s" % e}
    text = text[: int(c["anno"].get("max_pdf_chars", 60000))]
    name = name or os.path.basename(txt_path)

    # 精读（桥接）默认使用 hy3 模型；用户在「精读模型」下拉里改了则以用户选的为准
    model = model or c["anno"].get("model") or "hy3"

    # 精读模式：anno.backend 独立控制（默认 workbuddy 桥接；可切 api 直连 SenseNova）
    anno_backend = (c["anno"].get("backend") or "workbuddy").strip().lower()
    ov = None
    if anno_backend == "api":
        ov = {"backend": "api", "base_url": c["llm"].get("base_url"),
              "api_key": c["llm"].get("api_key") or None}
        # 'hy3' 只是桥接侧占位模型名，SenseNova 无此模型 → 直连模式自动换用主模型
        if model == "hy3":
            model = c["llm"].get("model") or "deepseek-v4-flash"
            tip = "    ⚠ 精读模式=云端直连：模型 hy3 不存在于 SenseNova，已改用主模型 %s。" % model
            try:
                on_log(tip, level="warn") if on_log else None
            except TypeError:
                on_log(tip) if on_log else None
    elif anno_backend == "workbuddy":
        ov = {"backend": "workbuddy"}

    # 提示词唯一来源：tools/eb-anno-digest/prompt.md（改完文件下次精读即生效）
    try:
        prompts = load_prompts()
    except PromptLoadError as e:
        return {"ok": False, "error": "加载提示词失败：%s" % e}

    # 扫描件：检查同目录的 <名>_pages/ 是否有渲染图，有则改用「看图精读」prompt
    dump_dir = os.path.dirname(txt_path)
    base_name = os.path.splitext(name)[0]
    pages_dir = os.path.join(dump_dir, base_name + "_pages")
    images = []
    if os.path.isdir(pages_dir):
        images = sorted(os.path.join(pages_dir, p).replace("\\", "/")
                        for p in os.listdir(pages_dir) if p.lower().endswith(".png"))
    if images:
        user_content = prompts["SCAN_USER_TEMPLATE"].format(
            name=name, created=created,
            images="\n".join("- %s" % p for p in images))
    else:
        user_content = prompts["USER_TEMPLATE"].format(name=name, created=created, text=text)

    messages = [
        {"role": "system", "content": prompts["SYSTEM_PROMPT"]},
        {"role": "user", "content": user_content},
    ]
    # 扫描件信息随 prompt 一起落进 meta.json，使 /api/bridge/pending 能直接读出
    # 「本份是扫描件、需按路径读图」——驱动方不必读 prompt 正文就不会漏掉读图。
    scan_meta = {"scanned": bool(images), "images": images,
                 "pages_dir": pages_dir.replace("\\", "/") if images else ""}
    r = llm.chat(messages, model=model, override=ov, on_log=on_log, name=name,
                 meta=scan_meta, should_abort=should_abort)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("message"), "kind": r.get("kind"),
                "hint": r.get("hint", "")}
    data = _extract_json(r.get("content", ""))
    if data is None:
        return {"ok": False, "error": "模型返回的不是合法 JSON，无法自动填表。",
                "raw": (r.get("content") or "")[:500]}
    if data.get("skip"):
        return {"ok": True, "skipped": True, "reason": data.get("reason", ""),
                "model": r.get("model"), "name": name}
    row = {k: (data.get(k) or "") for k in FIELDS}
    row["_source"] = os.path.basename(txt_path)
    return {"ok": True, "row": row, "model": r.get("model"),
            "usage": r.get("usage", {}), "name": name}


def _bar(cur, total, width=22):
    """进度条字符：填充 ━、头部 ╸、剩余轨道 ─。"""
    total = total if total and total > 0 else 1
    cur = max(0, min(int(round(cur)), total))
    if cur >= total:
        return "━" * width
    if cur <= 0:
        return "╸" + "─" * (width - 1)
    return "━" * cur + "╸" + "─" * (width - 1 - cur)


def _dur(sec):
    sec = int(round(sec or 0))
    if sec < 0:
        sec = 0
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


def digest_batch(txt_paths, model=None, on_progress=None):
    """批量精读（走任务系统，前端能看进度）。"""
    from ..core import tasks
    return tasks.run_callable(
        "AI 精读公告（%d 份）" % len(txt_paths),
        lambda task=None: _digest_batch_job(txt_paths, model, task, on_progress),
        project="anno",
    )


def _digest_batch_job(txt_paths, model, task, on_progress):
    rows, failed, skipped = [], [], []
    total = len(txt_paths)
    job_start = time.time()
    seen, pending = set(), llm.bridge_pending_names()
    WIDTH = 22

    def emit_progress(done, name, fs):
        """emit 单行文件进度 + 结构化 progress（只保留文件进度，不做时间/ETA 预估）。"""
        name = name or ""
        line = "%s %d/%d [%s]" % (_bar(done, total, WIDTH), done, total, name)
        if task:
            task.emit(line, "info")
            task.progress({
                "phase": "AI 精读", "done": done, "total": total, "name": name,
            })

    if total == 0:
        return {"rows": [], "failed": [], "skipped": [], "total": 0, "ok_count": 0}

    for i, p in enumerate(txt_paths, start=1):
        name = os.path.basename(p)
        if task and getattr(task, "status", None) == "stopped":
            task.emit("（检测到停止信号，终止批量精读）", "warn")
            break
        if task:
            emit_progress(i - 1, name, job_start)   # 进入第 i 份前刷新进度
        if name in seen:
            if task:
                task.emit("    跳过（本次已处理）：%s" % name, "warn")
            continue
        seen.add(name)
        if name in pending:
            if task:
                task.emit("    跳过（已有待处理 prompt，去重）：%s" % name, "warn")
            continue

        fs = time.time()

        def on_log(msg):
            # bridge 等待期间每 15s 调一次，借机刷新一次文件进度
            if task:
                task.emit(msg)
            emit_progress(i - 1, name, fs)

        r = digest_one(p, name=name, model=model, on_log=on_log,
                       should_abort=(lambda: getattr(task, "status", None) == "stopped")
                       if task else None)
        if r.get("kind") == "stopped":
            if task:
                task.emit("（已停止，结束批量精读）", "warn")
            break
        if not r.get("ok"):
            failed.append({"file": p, "error": r.get("error")})
            if task:
                task.emit("    失败：%s" % r.get("error"), "error")
        elif r.get("skipped"):
            skipped.append({"file": p, "reason": r.get("reason")})
            if task:
                task.emit("    跳过（%s）" % r.get("reason"), "warn")
        else:
            rows.append(r["row"])
            if task:
                task.emit("    完成：%s / %s" % (r["row"].get("可交换债", "-"),
                                                r["row"].get("公告日期", "-")))
        if on_progress:
            try:
                on_progress(i, total, r)
            except Exception:
                pass
        if task:
            emit_progress(i, "", job_start)         # 第 i 份完成刷新进度

    if task:
        if getattr(task, "status", None) == "stopped":
            task.emit("（已停止：汇总已完成的部分，未处理的可下次重跑）", "warn")
        else:
            task.emit("（精读全部完成，正在汇总结果）", "info")
    return {"rows": rows, "failed": failed, "skipped": skipped,
            "total": total, "ok_count": len(rows)}


def save_input(rows, anno_dir=None):
    """把精读结果存成 build_anno_xlsx.py 认的 input.json（{"rows":[...], "meta":{...}}）。"""
    d = anno_dir or base.workspace("anno")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "input.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"rows": rows, "meta": {}}, fh, ensure_ascii=False, indent=2)
    return path.replace("\\", "/")


def build(input_path=None, strict=False, anno_dir=None, out=None):
    """第3步：校验 + 生成整理表。out 指定输出 xlsx 路径（默认落在 input 同目录）。"""
    if not input_path:
        d = anno_dir or base.workspace("anno")
        input_path = os.path.join(d, "input.json")
    cmd = [base.python_exe(), base.script_path("eb-anno-digest", "build_anno_xlsx.py"), input_path]
    if strict:
        cmd.append("--strict")
    if out:
        cmd += ["-o", out]
    started = time.time()

    def on_done(task):
        return {"outputs": base.newest_files(os.path.dirname(input_path), {".xlsx"},
                                             since=started)}

    return base.run("生成公告整理表", "anno", cmd, on_done=on_done)


def check(input_path=None, anno_dir=None):
    """只校验不生成。"""
    if not input_path:
        d = anno_dir or base.workspace("anno")
        input_path = os.path.join(d, "input.json")
    cmd = [base.python_exe(), base.script_path("eb-anno-digest", "build_anno_xlsx.py"),
           "--check", input_path]
    return base.run("校验整理表数据", "anno", cmd)


# 「一键分析」控制指令模板。用 .replace 注入目录，避免 JSON 示例里的花括号干扰 format。
ANALYZE_PROMPT_TPL = """你是 EB 投研 Agent 平台（地址 http://127.0.0.1:8765）的操作员。下面是一份「一键分析」控制指令，请用你可用的工具（浏览器 / HTTP 请求 / 文件读取）自动驱动该平台，把公告目录里的 PDF 整理成《可交换债公告整理表》，落到输出目录。全程无需等我二次确认，按步骤推进即可。

【输入】
- 公告目录（PDF 所在）：__ANNO_DIR__
- 输出目录（整理表落盘）：__OUTPUT_DIR__
- 精读模型：__MODEL__

【前置检查】
1. GET http://127.0.0.1:8765/ ，确认平台在线（返回 200）；不在线就提示用户先启动平台。
2. 打开「设置 → 模型后端」，确认是「WorkBuddy 桥接」。不是的话，调成 workbuddy（这样 AI 精读会把每份公告的 prompt 写进平台「桥接」面板，由你来读并执行）。

【步骤 A · 转储 PDF】
- POST /api/anno/dump  body: {"dir":"__ANNO_DIR__","clean":true}
- 拿到 task_id 后，订阅 GET /api/tasks/<task_id>/stream 看日志，等到 status=done。
- 转储完成后，GET /api/anno/txt?dir=__ANNO_DIR__ 得到 files 列表，记下全部 txt 的【绝对路径】清单（共 N 份）。

【步骤 B · AI 精读（桥接，由你执行）】
- POST /api/anno/digest  body: {"files":[<步骤A 的全部 txt 绝对路径>],"model":"__MODEL__","restart":true}
  该接口会为每份公告在平台「桥接」面板生成一条待处理 prompt，并阻塞等待你回填结果。
- 循环，直到 GET /api/bridge/pending 返回的 items 为空：
  - 取 items[0]（当前待处理项）。若其 scanned=true，用 Read 工具按 images 字段里的绝对路径逐页读图识别文字；否则直接读 prompt 里的公告正文。
  - 按平台 EB-Agent/tools/eb-anno-digest/prompt.md 的【摘要写法】与 SKILL.md 的【提交前自检清单】，把该份公告提炼成 9 字段 JSON：
    公告日期 / 上市公司 / 可交换债 / 证券代码 / 标的股票 / 股票代码 / 换股价格 / 公告性质 / 内容摘要
    （摘要主线 = EB 违约风险 + 财务状况，事件/要点式 130~360 字；定期报告顺序 = 财务 → 风险判断 → EB 条款，绝不可把发行规模/期限/票面顶在段首。）
  - POST /api/bridge/submit  body: {"id": items[0].id, "content": <上面的 JSON 对象>}
  - 提交后等约 1 秒再刷新 pending，继续下一条。
- 每处理一份，在【执行日志】里打印进度条（当前已处理/总数）：
  ╸━━━━━━━━━━━━━━ 0/1 [1.txt]

【步骤 C · 保存并生成整理表】
- POST /api/anno/save  body: {"rows":[<步骤B 你提交的全部 JSON>],"dir":"__ANNO_DIR__"}
  （把 rows 落到 __INPUT_JSON__）
- POST /api/anno/build  body: {"dir":"__ANNO_DIR__","input":"__INPUT_JSON__","out":"__OUT_XLSX__","strict":false}
  订阅日志等到 status=done。
- 若 build 报错，先确认 __INPUT_JSON__ 已生成，再重试。

【完成】
- 确认 __OUT_XLSX__ 已生成（GET /api/files?path=__OUTPUT_DIR__ 能看到）。
- 向用户汇报：共处理 N 份公告，成功 / 跳过（担保人财报等）/ 失败 各多少；整理表路径。"""


def build_analyze_prompt(anno_dir, output_dir, model="hy3"):
    """生成「一键分析」控制指令：交给 AI 工作台，由它驱动平台跑完整流程。"""
    anno_dir = (anno_dir or "").replace("\\", "/").rstrip("/")
    output_dir = (output_dir or "").replace("\\", "/").rstrip("/")
    return ANALYZE_PROMPT_TPL.replace("__ANNO_DIR__", anno_dir) \
        .replace("__OUTPUT_DIR__", output_dir) \
        .replace("__MODEL__", model or "hy3") \
        .replace("__INPUT_JSON__", anno_dir + "/input.json") \
        .replace("__OUT_XLSX__", output_dir + "/公告整理.xlsx")
