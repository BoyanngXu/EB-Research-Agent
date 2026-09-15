# -*- coding: utf-8 -*-
"""API 路由表。

约定：所有接口返回 JSON；出错统一 {"ok":false,"error":...}。
长任务一律「先返回 task_id，前端再订阅 SSE 看日志」，避免 HTTP 请求挂死。
"""
import json
import os
import re
import subprocess
import time
from urllib.parse import unquote

from ..core import assistant, config, env, files, llm, memory, tasks, terminal
from ..projects import anno, base, data, report, wechat
from .server import SSE

# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def _ok(**kw):
    out = {"ok": True}
    out.update(kw)
    return out


def _err(msg, **kw):
    out = {"ok": False, "error": str(msg)}
    out.update(kw)
    return out


def _parse_worker(req_dict):
    """重型解析交给装了依赖的解释器（openpyxl/pdfplumber），服务器进程保持零依赖。"""
    exe = base.python_exe()
    script = os.path.join(config.PLATFORM_ROOT, "app", "worker", "parse.py")
    tmpdir = config.runtime_dir("tmp")
    reqpath = os.path.join(tmpdir, "req_%s.json" % int(time.time() * 1000))
    with open(reqpath, "w", encoding="utf-8") as fh:
        json.dump(req_dict, fh, ensure_ascii=False)
    try:
        proc = subprocess.run([exe, script, reqpath], capture_output=True,
                              timeout=180, text=True, encoding="utf-8", errors="replace",
                              creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        out = (proc.stdout or "").strip()
        if not out:
            return {"ok": False, "error": "解析脚本无输出",
                    "stderr": (proc.stderr or "")[:800]}
        return json.loads(out)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "解析超时（180s）"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _task_stream(tid):
    """订阅任务日志：先补发历史，再实时推，结束后发最终状态。"""
    task = tasks.get(tid)
    if not task:
        yield ("error", {"error": "任务不存在：" + tid})
        return
    yield ("snapshot", task.snapshot())
    q = task.subscribe()
    last_beat = time.time()
    try:
        while True:
            try:
                rec = q.get(timeout=0.5)
                yield ("log", rec)
                continue
            except Exception:
                pass
            if task.finished is not None:
                while True:
                    try:
                        yield ("log", q.get_nowait())
                    except Exception:
                        break
                break
            if time.time() - last_beat > 12:
                last_beat = time.time()
                yield ("ping", {"t": last_beat})
    finally:
        task.unsubscribe(q)
    yield ("status", task.snapshot(with_log=False))


# --------------------------------------------------------------------------
# 配置 / 环境
# --------------------------------------------------------------------------
def h_config_get(req):
    return _ok(config=config.public_view())


def h_config_save(req):
    patch = req.body or {}
    if "llm" in patch and isinstance(patch["llm"], dict):
        # 前端回传的是打码串，没改就别覆盖真 Key
        key = patch["llm"].get("api_key")
        if not key or "*" in str(key):
            patch["llm"].pop("api_key", None)
    return _ok(config=config.save(patch) and config.public_view())


def h_env(req):
    exe = base.python_exe()
    return _ok(**env.dependency_report(exe))


def h_env_detect(req):
    exe = base.python_exe()
    info = env.detect_python(config.load()["python"].get("executable"))
    return _ok(**info)


def h_env_install(req):
    package = (req.body or {}).get("package")
    if not package:
        return _err("缺少 package")

    def job(task=None):
        rc = env.install_package(base.python_exe(), package,
                                 on_line=lambda line: task.emit(line) if task else None)
        if task:
            task.emit("安装退出码：%s" % rc)
        return {"package": package, "code": rc}

    t = tasks.run_callable("安装依赖 %s" % package, job, project="env")
    return _ok(task=t.snapshot(with_log=False))


# --------------------------------------------------------------------------
# 文件
# --------------------------------------------------------------------------
def h_roots(req):
    c = config.load()
    ws = c["workspace"]
    return _ok(roots=[
        {"key": "data", "label": "Data（数据）", "path": ws["data"]},
        {"key": "anno", "label": "Anno（公告）", "path": ws["anno"]},
        {"key": "wechat", "label": "Wechat（舆情）", "path": ws["wechat"]},
        {"key": "output", "label": "平台产出", "path": ws["output"]},
        {"key": "platform", "label": "平台目录", "path": config.PLATFORM_ROOT.replace("\\", "/")},
    ])


def h_files(req):
    path = req.q("path")
    if not path:
        c = config.load()
        path = c["workspace"]["data"]
    try:
        return _ok(**files.list_dir(path, only_docs=req.qbool("docs")))
    except Exception as e:
        return _err(e)


def h_preview(req):
    path = req.q("path")
    if not path:
        return _err("缺少 path")
    try:
        files.safe_path(path)
    except Exception as e:
        return _err(e)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        r = _parse_worker({"op": "read_xlsx", "path": path,
                           "max_rows": req.qint("max_rows", 300),
                           "sheet": req.q("sheet") or None})
    elif ext == ".docx":
        r = _parse_worker({"op": "read_docx", "path": path})
    elif ext == ".pdf":
        r = _parse_worker({"op": "read_pdf", "path": path,
                           "max_pages": req.qint("max_pages", 0) or None})
    elif ext in (".txt", ".md", ".json", ".log", ".ini", ".csv"):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            r = {"ok": True, "text": text[:300000], "chars": len(text)}
        except Exception as e:
            r = {"ok": False, "error": str(e)}
    else:
        return _err("暂不支持预览该类型：%s" % ext)
    if not r.get("ok") and r.get("error") == "missing_dep":
        r["hint"] = "缺依赖 %s，去「设置 → 环境自检」一键安装" % r.get("pip")
    return r


def h_download(req):
    path = req.q("path")
    try:
        ap = files.safe_path(path)
    except Exception as e:
        return _err(e)
    try:
        with open(ap, "rb") as fh:
            data = fh.read()
    except Exception as e:
        return _err(e)
    ctype = "application/octet-stream"
    return (200, data, ctype,
            {"Content-Disposition": 'attachment; filename="%s"' % files.download_name(ap)})


def h_open(req):
    path = (req.body or {}).get("path")
    try:
        files.open_in_explorer(path)
        return _ok()
    except Exception as e:
        return _err(e)


def h_file_dirs(req):
    """列目录（供前端网页内「目录选择器」导航）。

    path=@computer 或 view=drives 时返回「此电脑」层级（各盘符）。
    盘符已在 files.allowed_roots 内放开，故可从 C:/ 等根目录开始浏览。
    """
    try:
        raw = req.q("path") or None
        if raw == files.COMPUTER or req.q("view") == "drives":
            return _ok(**files.list_computer())
        return _ok(**files.list_dirs(raw))
    except Exception as e:
        return _err(e)


def h_select_dir(req):
    """弹出系统文件夹选择框（本地平台专用），返回选中绝对路径。

    由前端「浏览…」按钮 POST 调用（initial 为当前输入框值，用于定位初始目录）。
    后端 spawn 独立子进程跑 app/worker/folder_dialog.py：优先用现代
    IFileOpenDialog（资源管理器风格），不可用则回退旧版 SHBrowseForFolder。
    取消或当前环境无法弹框时返回 None -> 前端提示「未选择目录…」。
    """
    body = req.body or {}
    path = files.select_dir(initial=body.get("initial") or "",
                            title=body.get("title") or "选择目录")
    if not path:
        return _err("未选择目录，或当前环境无法弹出选择框")
    return _ok(path=path.replace("\\", "/"))


# --------------------------------------------------------------------------
# 任务
# --------------------------------------------------------------------------
def h_task_list(req):
    return _ok(tasks=tasks.list_tasks(limit=req.qint("limit", 40)))


def h_task_get(req, tid):
    t = tasks.get(tid)
    if not t:
        # 内存已淘汰、或服务重启过：回落到磁盘上持久化的 meta 快照
        try:
            m = tasks.read_meta(tid)
        except ValueError as e:
            return _err(e)
        if m:
            return _ok(task=m, persisted=True)
        return _err("任务不存在")
    return _ok(task=t.snapshot())


def h_task_stream(req, tid):
    return SSE(_task_stream(tid))


def h_task_log(req, tid):
    """读回持久化的任务日志（服务重启 / 任务被内存淘汰后仍可查）。

    与 /stream 不同：这个接口是「事后回看」，不订阅实时事件，直接读 jsonl 尾部。
    """
    try:
        lines = tasks.read_log(tid, tail=req.qint("tail", 400))
    except ValueError as e:
        return _err(e)
    if lines is None:
        return _err("该任务没有持久化日志：" + tid)
    return _ok(id=tid, count=len(lines), log=lines)


def h_task_stop(req, tid):
    t = tasks.get(tid)
    if not t:
        return _err("任务不存在")
    t.stop()
    return _ok(task=t.snapshot(with_log=False))


# --------------------------------------------------------------------------
# LLM
# --------------------------------------------------------------------------
def h_llm_test(req):
    return llm.quick_test()


def h_llm_chat(req):
    body = req.body or {}
    messages = body.get("messages") or []
    if not messages:
        return _err("messages 为空")

    def gen():
        for evt in llm.chat_stream(messages, model=body.get("model")):
            yield ("chunk", evt)
            if evt.get("type") == "error":
                return

    return SSE(gen())


# --------------------------------------------------------------------------
# 桥接（WorkBuddy 模式）：inbox 写 prompt，outbox 收结果
# --------------------------------------------------------------------------
def h_bridge_pending(req):
    inbox, outbox = llm._bridge_dirs()
    all_metas = []
    for fn in sorted(os.listdir(inbox)):
        if not fn.endswith(".meta.json"):
            continue
        try:
            all_metas.append(json.load(open(os.path.join(inbox, fn), encoding="utf-8")))
        except Exception:
            continue
    max_seq = max([m.get("seq", 0) for m in all_metas], default=0)
    items = []
    for meta in all_metas:
        bid = meta.get("id")
        if not bid or os.path.exists(os.path.join(outbox, bid + ".json")):
            continue
        prompt_path = os.path.join(inbox, bid + ".prompt.md")
        prompt = ""
        try:
            prompt = open(prompt_path, encoding="utf-8").read()
        except Exception:
            pass
        images = meta.get("images") or []
        items.append({"id": bid, "name": meta.get("name", ""),
                      "created": meta.get("created", 0),
                      "seq": meta.get("seq", 0), "prompt": prompt,
                      # 扫描件标记：即便驱动方不解析 prompt 正文，也能一眼看到
                      # 「本份是无文字层扫描件、需按 images 路径读图识别」。
                      "scanned": bool(meta.get("scanned") or images),
                      "images": images,
                      "image_count": len(images)})
    items.sort(key=lambda x: x["created"])
    total = llm.read_batch_total() or max_seq or len(items)
    return _ok(items=items, total=total)


def h_bridge_clear(req):
    """清空「活动信箱」：把 inbox / outbox 整个目录改名移走（非删除）到 _archive/。

    之所以用「改名移走」而非删除：运行环境对「一次删除 >50 文件」要求人工确认，
    无头服务进程无法确认会被直接阻断请求（实测会 RemoteDisconnected）。rename 是移动、
    不算删除，可安全绕过，同时保证活动信箱每次都被清空、不再堆积历史 meta/outbox。
    旧文件全部进入 runtime/bridge/_archive/（按时间戳归档、可恢复），不影响活动目录。

    同时停掉仍在跑的 anno 精读任务（其线程靠 task.status==stopped 检测后 break）。
    """
    inbox, outbox = llm._bridge_dirs()
    root = llm._bridge_root()
    archive = os.path.join(root, "_archive")
    os.makedirs(archive, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    moved = 0
    for src, nm in ((inbox, "inbox"), (outbox, "outbox")):
        try:
            if os.listdir(src):   # 仅当非空才搬走，避免产生空的归档目录
                dst = os.path.join(archive, "%s_%s" % (nm, ts))
                os.rename(src, dst)
                moved += 1
        except Exception:
            pass
    # 重建空的活动收件箱/发件箱
    inbox, outbox = llm._bridge_dirs()
    # 停掉正在跑的 anno 精读任务
    for t in tasks.list_tasks(limit=200):
        if t.get("project") == "anno" and t.get("status") == "running" \
           and "精读" in (t.get("title") or ""):
            try:
                tasks.get(t["id"]).stop()
            except Exception:
                pass
    llm.reset_bridge_seq()
    llm.write_batch_total(0)
    return _ok(removed=moved)


def h_bridge_submit(req):
    body = req.body or {}
    bid = (body.get("id") or "").strip()
    content = body.get("content")
    if not bid or content is None:
        return _err("缺少 id 或 content")
    if not re.match(r"^[A-Za-z0-9]+$", bid):
        return _err("非法 id")
    _, outbox = llm._bridge_dirs()
    path = os.path.join(outbox, bid + ".json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"id": bid, "content": content, "submitted_at": time.time()}, fh, ensure_ascii=False)
        return _ok(id=bid)
    except Exception as e:
        return _err(str(e))


# --------------------------------------------------------------------------
# Anno
# --------------------------------------------------------------------------
def h_anno_dump(req):
    body = req.body or {}
    t = anno.dump(body.get("dir"), clean=bool(body.get("clean", True)))
    return _ok(task=t.snapshot(with_log=False))


def h_anno_txt(req):
    return _ok(**anno.list_txt(req.q("dir")))


def h_anno_digest(req):
    body = req.body or {}
    paths = body.get("files") or []
    if not paths:
        return _err("请先选择要精读的转储文本")
    if body.get("restart"):
        # 重新开始：先清掉旧 prompt 并停掉仍在跑的旧任务（保持「只留最新一批」）
        h_bridge_clear(req)
    llm.write_batch_total(len(paths))
    t = anno.digest_batch(paths, model=body.get("model"))
    return _ok(task=t.snapshot(with_log=False))


def h_anno_save(req):
    body = req.body or {}
    rows = body.get("rows") or []
    path = anno.save_input(rows, body.get("dir"))
    return _ok(path=path, count=len(rows))


def h_anno_check(req):
    body = req.body or {}
    t = anno.check(body.get("input"), body.get("dir"))
    return _ok(task=t.snapshot(with_log=False))


def h_anno_build(req):
    body = req.body or {}
    t = anno.build(body.get("input"), strict=bool(body.get("strict")),
                   anno_dir=body.get("dir"), out=body.get("out"))
    return _ok(task=t.snapshot(with_log=False))


def h_anno_analyze(req):
    """一键分析：按「公告目录 + 输出目录」生成交给 AI 工作台的控制指令。"""
    body = req.body or {}
    anno_dir = (body.get("anno_dir") or "").strip()
    output_dir = (body.get("output_dir") or "").strip()
    if not anno_dir:
        return _err("请填写公告目录")
    if not output_dir:
        return _err("请填写输出目录")
    model = body.get("model") or (config.load().get("anno") or {}).get("model") or "hy3"
    prompt = anno.build_analyze_prompt(anno_dir, output_dir, model)
    return _ok(prompt=prompt, anno_dir=anno_dir, output_dir=output_dir, model=model)


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def h_data_dates(req):
    return _ok(**data.list_dates(req.q("dir")))


def h_data_sources(req):
    return _ok(**data.source_status(req.q("date"), req.q("dir")))


def h_data_download_xx(req):
    body = req.body or {}
    # xxxxx需弹窗处理验证码，始终有窗口（headless=False）
    t = data.download_xx(body.get("dir"))
    return _ok(task=t.snapshot(with_log=False))


def h_data_download_sz(req):
    body = req.body or {}
    # 深交所免登录，始终无头（headless=True）
    t = data.download_sz(body.get("dir"))
    return _ok(task=t.snapshot(with_log=False))


def h_data_rebuild(req):
    body = req.body or {}
    try:
        # 始终套模板（no_template=False）
        t = data.rebuild(body.get("date"), body.get("base"))
    except ValueError as e:
        return _err(e)
    return _ok(task=t.snapshot(with_log=False))


# --------------------------------------------------------------------------
# Wechat
# --------------------------------------------------------------------------
def h_wechat_articles(req):
    return _ok(**wechat.list_articles(req.q("dir")))


def h_wechat_crawl(req):
    body = req.body or {}
    kw, period = wechat.suggest_keyword()
    # 微信读书登录必须扫码，无头模式无法完成 → 全部走有头模式（headed=False）。
    t = wechat.crawl(count=body.get("count"), keyword=body.get("keyword"),
                     out_dir=body.get("dir"), headless=False)
    return _ok(task=t.snapshot(with_log=False), suggested=kw, period=period)


def h_wechat_suggest(req):
    kw, period = wechat.suggest_keyword()
    return _ok(keyword=kw, period=period)


# --------------------------------------------------------------------------
# Report（晨会分享 → 结构化入库 → 观点命中回测）
# --------------------------------------------------------------------------
def h_report_status(req):
    return _ok(**report.status())


def h_report_new(req):
    """GET /api/report/new：还没转 txt 的晨会 docx。"""
    return _ok(**report.list_new())


def h_report_prompt(req):
    """GET /api/report/prompt：生成触发 morning-note-ingest skill 的一键入库指令。"""
    try:
        text = report.build_ingest_prompt()
    except report.PromptLoadError as e:
        return _err(str(e))
    new = report.list_new()
    return _ok(prompt=text, pending=new["pending"], total=new["total"])


def h_report_htmls(req):
    """GET /api/report/htmls：_analysis 下可内嵌展示的回测报告 HTML。"""
    return _ok(**report.list_htmls())


def h_report_asset(req, rel):
    """GET /report_view/<rel>：把 _analysis 下的报告当静态资源吐出去（给 iframe 用）。

    中文文件名在 URL 里是百分号编码（浏览器不会帮你解），这里先 unquote。
    """
    try:
        data, ctype = report.asset(unquote(rel or ""))
    except FileNotFoundError as e:
        return (404, b"not found: " + str(e).encode("utf-8"), "text/plain; charset=utf-8")
    except ValueError as e:
        return (400, b"bad request: " + str(e).encode("utf-8"), "text/plain; charset=utf-8")
    return (200, data, ctype)


# --------------------------------------------------------------------------
# 首页对话助手（统一智能入口：问答 / 动作驱动 / Agentic RAG）
# --------------------------------------------------------------------------
def h_assistant(req):
    """POST /api/assistant：处理一条用户消息。

    body: {message, session?, confirm?, action?, params?}
    - 无 confirm：先走 intent 分类——动作给确认卡（kind=confirm）；问答走 RAG（kind=qa）。
    - confirm=true：确认执行动作（kind=action，长任务附 task.id 供前端订阅 SSE）。
    所有分支都带 session，前端存下来用于多轮上下文与历史会话。
    """
    body = req.body or {}
    message = (body.get("message") or "").strip()
    confirm = bool(body.get("confirm"))
    if not message and not confirm:
        return _err("消息为空")
    try:
        res = assistant.handle(
            message,
            session=body.get("session") or None,
            confirm=confirm,
            action=body.get("action"),
            params=body.get("params") or {},
        )
    except Exception as e:
        return _err("助手处理失败：%s" % e)
    if not isinstance(res, dict):
        return _err("助手返回异常")
    return res


def h_assistant_context(req):
    """首屏「数据源概况 + 快捷指令」面板数据（不用翻目录就知道能查什么）。"""
    try:
        return _ok(**assistant.context_brief())
    except Exception as e:
        return _err("读取数据源概况失败：%s" % e)


def h_assistant_sessions(req):
    """历史会话列表（用于「查看历史 / 切换会话」）。"""
    try:
        return _ok(sessions=memory.list_sessions(limit=req.qint("limit", 30)),
                   enabled=memory.enabled())
    except Exception as e:
        return _err(str(e))


def h_assistant_session(req):
    """读取某个历史会话的完整消息（用于点历史会话时回放对话）。"""
    sid = (req.q("id") or req.q("session") or "").strip()
    if not sid:
        return _err("缺少会话 id")
    try:
        recs = memory.read(sid, limit=req.qint("limit", 300))
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(str(e))
    return _ok(session=sid, messages=recs)


def h_assistant_prompts(req):
    """GET /api/assistant/prompts：跨会话取最近的用户提问，供前端「历史 prompt」回填。"""
    try:
        limit = req.qint("limit", 40)
    except Exception:
        limit = 40
    return _ok(prompts=memory.recent_user_prompts(limit=limit))


# --------------------------------------------------------------------------
# 终端交互窗口（设置页内嵌命令行）
# --------------------------------------------------------------------------
def h_terminal_run(req):
    """POST /api/terminal：启动一条命令，返回 tid。"""
    body = req.body or {}
    cmd = (body.get("command") or "").strip()
    cwd = (body.get("cwd") or "").strip() or None
    try:
        tid = terminal.run(cmd, cwd=cwd)
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err("启动失败：%s" % e)
    return _ok(tid=tid, command=cmd)


def h_terminal_stream(req):
    """GET /api/terminal/stream?tid=：SSE 实时推送输出。"""
    tid = req.q("tid") or ""
    if not tid:
        return _err("缺少 tid")
    return SSE(terminal.stream(tid))


def h_terminal_stop(req):
    """POST /api/terminal/stop 或 GET：终止进程。body/tid 均可。"""
    tid = (req.body or {}).get("tid") or req.q("tid") or ""
    if not tid:
        return _err("缺少 tid")
    ok = terminal.stop(tid)
    return _ok(stopped=ok) if ok else _err("会话不存在或已结束")


# --------------------------------------------------------------------------
ROUTES = [
    ("GET", re.compile(r"^/api/config$"), h_config_get),
    ("POST", re.compile(r"^/api/config$"), h_config_save),
    ("GET", re.compile(r"^/api/env$"), h_env),
    ("POST", re.compile(r"^/api/env/detect$"), h_env_detect),
    ("POST", re.compile(r"^/api/env/install$"), h_env_install),

    ("GET", re.compile(r"^/api/roots$"), h_roots),
    ("GET", re.compile(r"^/api/files$"), h_files),
    ("GET", re.compile(r"^/api/file/preview$"), h_preview),
    ("GET", re.compile(r"^/api/file/download$"), h_download),
    ("POST", re.compile(r"^/api/file/open$"), h_open),
    ("GET", re.compile(r"^/api/file/dirs$"), h_file_dirs),
    ("POST", re.compile(r"^/api/file/select-dir$"), h_select_dir),

    ("GET", re.compile(r"^/api/tasks$"), h_task_list),
    ("GET", re.compile(r"^/api/tasks/(?P<tid>[^/]+)$"), h_task_get),
    ("GET", re.compile(r"^/api/tasks/(?P<tid>[^/]+)/stream$"), h_task_stream),
    ("GET", re.compile(r"^/api/tasks/(?P<tid>[^/]+)/log$"), h_task_log),
    ("POST", re.compile(r"^/api/tasks/(?P<tid>[^/]+)/stop$"), h_task_stop),

    ("POST", re.compile(r"^/api/llm/test$"), h_llm_test),
    ("POST", re.compile(r"^/api/llm/chat$"), h_llm_chat),
    ("GET", re.compile(r"^/api/bridge/pending$"), h_bridge_pending),
    ("POST", re.compile(r"^/api/bridge/submit$"), h_bridge_submit),
    ("POST", re.compile(r"^/api/bridge/clear$"), h_bridge_clear),

    ("POST", re.compile(r"^/api/anno/dump$"), h_anno_dump),
    ("GET", re.compile(r"^/api/anno/txt$"), h_anno_txt),
    ("POST", re.compile(r"^/api/anno/digest$"), h_anno_digest),
    ("POST", re.compile(r"^/api/anno/save$"), h_anno_save),
    ("POST", re.compile(r"^/api/anno/check$"), h_anno_check),
    ("POST", re.compile(r"^/api/anno/build$"), h_anno_build),
    ("POST", re.compile(r"^/api/anno/analyze$"), h_anno_analyze),

    ("GET", re.compile(r"^/api/data/dates$"), h_data_dates),
    ("GET", re.compile(r"^/api/data/sources$"), h_data_sources),
    ("POST", re.compile(r"^/api/data/download-xx$"), h_data_download_xx),
    ("POST", re.compile(r"^/api/data/download-sz$"), h_data_download_sz),
    ("POST", re.compile(r"^/api/data/rebuild$"), h_data_rebuild),

    ("GET", re.compile(r"^/api/wechat/articles$"), h_wechat_articles),
    ("POST", re.compile(r"^/api/wechat/crawl$"), h_wechat_crawl),
    ("GET", re.compile(r"^/api/wechat/suggest$"), h_wechat_suggest),

    ("GET", re.compile(r"^/api/report/status$"), h_report_status),
    ("GET", re.compile(r"^/api/report/new$"), h_report_new),
    ("GET", re.compile(r"^/api/report/prompt$"), h_report_prompt),
    ("GET", re.compile(r"^/api/report/htmls$"), h_report_htmls),
    ("GET", re.compile(r"^/report_view/(?P<rel>.+)$"), h_report_asset),

    ("POST", re.compile(r"^/api/assistant$"), h_assistant),
    ("GET", re.compile(r"^/api/assistant/context$"), h_assistant_context),
    ("GET", re.compile(r"^/api/assistant/sessions$"), h_assistant_sessions),
    ("GET", re.compile(r"^/api/assistant/session$"), h_assistant_session),
    ("GET", re.compile(r"^/api/assistant/prompts$"), h_assistant_prompts),

    ("POST", re.compile(r"^/api/terminal$"), h_terminal_run),
    ("GET", re.compile(r"^/api/terminal/stream$"), h_terminal_stream),
    ("POST", re.compile(r"^/api/terminal/stop$"), h_terminal_stop),
]
