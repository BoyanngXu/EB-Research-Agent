# -*- coding: utf-8 -*-
"""LLM 客户端（OpenAI 兼容接口，纯标准库 urllib）。

默认指向商汤 SenseNova（https://token.sensenova.cn/v1），换任何 OpenAI 兼容
平台只需改 config 的 base_url/model。为什么不用 requests：平台服务器进程要求
「零依赖、拷走就能跑」，urllib 足够发 HTTPS + 解析 SSE 流式。

能力：
1. chat()        非流式，一次拿全，带模型兜底重试。
2. chat_stream() 流式生成器，逐段吐字，前端可以边跑边看。
3. 错误分类：把 HTTP 状态码翻成「人看得懂的中文原因」，前端据此给操作建议。
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.request
import uuid

from . import config

# 可重试的错误类型：换下一个模型再试一次
# 注意：quota(含 429 限流/余额不足) 已从可重试移除——429 多为系统侧抖动，换模型（共用同一 Key）毫无意义，
# 直接由调用方降级到桥接模式 + 本地资料总结，而不是空转重试。
RETRYABLE = ("model", "timeout", "network", "server")


def _cfg(override=None):
    """取 LLM 连接配置。

    override：一次性覆盖（首页对话助手用）。全局后端是 workbuddy 桥接时，
    助手问答仍要直连云 API —— 传 override={"backend":"api", ...} 即可绕开桥接，
    且精读的桥接行为完全不受影响。
    """
    c = config.load()
    z = dict(c.get("llm") or {})
    backend = z.get("backend", "api")
    if backend == "workbuddy":
        # 文件桥接：不联网，prompt 落盘等 WorkBuddy 回传结果
        pass
    else:
        # 云端：Key 优先级 config 手填 > 环境变量（默认 SENSENOVA_API_KEY）
        if not z.get("api_key"):
            env_key = z.get("env_key") or "SENSENOVA_API_KEY"
            z["api_key"] = os.environ.get(env_key, "")
    if override:
        for k, v in override.items():
            if v is None:        # None 表示「不覆盖」
                continue
            z[k] = v
        # 覆盖后若是云端后端，Key 可能还没填（例如全局是桥接模式）
        if z.get("backend") not in ("workbuddy",) and not z.get("api_key"):
            env_key = z.get("env_key") or "SENSENOVA_API_KEY"
            z["api_key"] = os.environ.get(env_key, "")
    return z


def _bridge_dirs():
    """桥接模式的收件箱/发件箱：runtime/bridge/{inbox,outbox}。"""
    base = config.runtime_dir("bridge")
    inbox = os.path.join(base, "inbox")
    outbox = os.path.join(base, "outbox")
    os.makedirs(inbox, exist_ok=True)
    os.makedirs(outbox, exist_ok=True)
    return inbox, outbox


def _bridge_root():
    return config.runtime_dir("bridge")


def bridge_write(system, user, name="", model="", meta=None):
    """把一份 prompt 落盘到 inbox，返回任务 id（outbox 同名 json 出现即视为完成）。

    model：桥接时希望 WorkBuddy 使用的模型名（如 hy3）。非空则写入 prompt 头部，
    让用户清楚该用哪个模型运行；为空则保留通用措辞。

    meta：额外元数据（dict），合并进 `<id>.meta.json`，会经 /api/bridge/pending
    暴露给驱动方。扫描件场景约定写入 {"scanned": true, "images": [...]}，
    使「需按路径读图」这个要求出现在元信息里，而不只藏在 prompt 正文中
    （否则只看 pending 元数据的自动化驱动容易漏掉读图，直接提交占位行）。
    """
    bid = uuid.uuid4().hex[:12]
    inbox, _ = _bridge_dirs()
    lead = ("请使用 **%s** 模型运行以下完整内容" % model) if model else \
           "请把以下完整内容交给 WorkBuddy 运行"
    header = ("# EB 公告精读 · WorkBuddy 桥接 prompt\n\n"
              "%s，并把**返回的 JSON** 贴回 EB-Agent 平台的「桥接」面板\n"
              "（或把含 {\"content\": \"...\"} 的 json 放到 outbox 目录）。只需返回 JSON，不要解释。\n\n"
              "---\n\n") % lead
    prompt = header + (system or "") + "\n\n" + (user or "")
    with open(os.path.join(inbox, bid + ".prompt.md"), "w", encoding="utf-8") as fh:
        fh.write(prompt)
    meta_obj = {"id": bid, "name": name, "created": time.time(),
                "seq": _next_seq()}
    if meta:
        try:
            meta_obj.update(meta)
        except Exception:
            pass
    with open(os.path.join(inbox, bid + ".meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta_obj, fh, ensure_ascii=False)
    return bid


def bridge_prompt_text(bid):
    """读回某个桥接 prompt 的正文（落盘在 inbox/<bid>.prompt.md）。

    用于对话助手桥接问答时在气泡内联展示/复制，免去跳到「公告」页的桥接面板。
    """
    inbox, _ = _bridge_dirs()
    p = os.path.join(inbox, bid + ".prompt.md")
    try:
        with open(p, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


def _seq_path():
    return os.path.join(_bridge_root(), ".seq")


def _read_seq():
    try:
        p = _seq_path()
        if os.path.exists(p):
            return int(open(p, encoding="utf-8").read().strip() or "0")
    except Exception:
        pass
    return 0


def _next_seq():
    n = _read_seq() + 1
    try:
        with open(_seq_path(), "w", encoding="utf-8") as fh:
            fh.write(str(n))
    except Exception:
        pass
    return n


def reset_bridge_seq():
    # 注意：用「覆盖写入 0」而非 os.remove —— 运行环境对删除有批量守卫，
    # 无头进程删除会被阻断请求；覆盖写入等价把序号归零，且不触发守卫。
    try:
        with open(_seq_path(), "w", encoding="utf-8") as fh:
            fh.write("0")
    except Exception:
        pass


def write_batch_total(n):
    try:
        with open(os.path.join(_bridge_root(), ".batch_total"), "w", encoding="utf-8") as fh:
            fh.write(str(int(n)))
    except Exception:
        pass


def read_batch_total():
    try:
        p = os.path.join(_bridge_root(), ".batch_total")
        if os.path.exists(p):
            return int(open(p, encoding="utf-8").read().strip() or "0")
    except Exception:
        pass
    return 0


def bridge_wait(bid, timeout=3600, on_log=None, should_abort=None):
    """轮询 outbox，直到出现结果或超时。返回结果文本或 None。

    should_abort：可选回调，返回 True 时立刻放弃等待（「停止」按钮用）。
    没有它，停止一个正在等回填的精读任务要等到超时才生效。
    """
    _, outbox = _bridge_dirs()
    path = os.path.join(outbox, bid + ".json")
    deadline = time.time() + timeout
    last_tip = 0
    while time.time() < deadline:
        if should_abort and should_abort():
            if on_log:
                on_log("【桥接】收到停止信号，放弃等待（id=%s）" % bid)
            return None
        if os.path.exists(path):
            try:
                obj = json.load(open(path, encoding="utf-8"))
                c = obj.get("content", "")
                # 桥接回填的 content 可能是「行 dict」（前端直接贴 JSON 对象），
                # 而下游 _extract_json 需要字符串；这里统一归一化为字符串。
                if isinstance(c, (dict, list)):
                    return json.dumps(c, ensure_ascii=False)
                return c if isinstance(c, str) else ("" if c is None else str(c))
            except Exception:
                return ""
        if on_log and time.time() - last_tip > 15:
            on_log("【桥接】等待 WorkBuddy 结果回传（id=%s）…" % bid)
            last_tip = time.time()
        time.sleep(3)
    return None


def bridge_pending_names():
    """返回当前 inbox 中尚未回传（待处理）的 prompt 文件名集合（meta.name）。

    用于精读去重：同一份公告若已写好 prompt 在等结果，再次点「开始精读」
    应跳过，避免桥接面板堆积重复输入框。
    """
    inbox, outbox = _bridge_dirs()
    names = set()
    try:
        for fn in os.listdir(inbox):
            if not fn.endswith(".meta.json"):
                continue
            try:
                meta = json.load(open(os.path.join(inbox, fn), encoding="utf-8"))
            except Exception:
                continue
            bid = meta.get("id")
            if not bid or os.path.exists(os.path.join(outbox, bid + ".json")):
                continue
            if meta.get("name"):
                names.add(os.path.basename(meta["name"]))
    except Exception:
        pass
    return names


def _mask(key):
    if not key:
        return ""
    return key[:6] + "*" * max(0, len(key) - 10) + key[-4:] if len(key) > 12 else "***"


def _ssl_context():
    ctx = ssl.create_default_context()
    try:
        import certifi  # 有就优先用 certifi 的证书，Windows 上更稳
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


def _official_message(body):
    """从模型平台返回体里抠出官方错误原文，比我们自己猜的更准。"""
    if not body:
        return ""
    try:
        data = json.loads(body)
        err = data.get("error") or {}
        return err.get("message") or ""
    except Exception:
        return ""


# 智谱 GLM 的业务错误码：它不用 HTTP 状态码区分限流，而是把 code 放在返回体里。
# 不认识这些码，就会把「过载」也误判成限流、把「欠费」当成临时抖动。
_ZHIPU_CODES = {
    "1113": ("quota", "账户欠费或余额不足", "去智谱控制台充值，或改用免费模型 / 兜底厂商。"),
    "1302": ("quota", "达到账户速率限制（RPM / 并发）", "稍等 10~30 秒重试；配置了兜底厂商会自动换过去。"),
    "1305": ("server", "智谱平台侧过载", "平台临时过载，重试通常能过（会被当作可重试错误换下一个候选）。"),
    "1308": ("quota", "达到周期使用上限", "本周期额度已用尽，等下个周期或换厂商。"),
    "1310": ("quota", "达到周期使用上限", "本周期额度已用尽，等下个周期或换厂商。"),
}


def _biz_code(body):
    """从返回体里取业务错误码（智谱等平台用 code 字段）。取不到返回空串。"""
    try:
        d = json.loads(body or "")
    except Exception:
        return ""
    if not isinstance(d, dict):
        return ""
    err = d.get("error")
    if isinstance(err, dict):
        c = err.get("code")
        if c not in (None, ""):
            return str(c)
    c = d.get("code")
    return "" if c in (None, "") else str(c)


def _classify(err, status=None, body=""):
    """把异常/状态码翻译成结构化错误，kind 决定前端怎么提示。"""
    official = _official_message(body)
    code = _biz_code(body)
    if code in _ZHIPU_CODES:
        kind, what, hint = _ZHIPU_CODES[code]
        return {"kind": kind, "status": status, "code": code,
                "message": "%s（业务码 %s）。%s" % (what, code, official),
                "hint": hint}

    if status == 401 or status == 403:
        return {"kind": "auth", "status": status,
                "message": "API Key 无效或没有该模型的权限（HTTP %s）。%s" % (status, official),
                "hint": "去模型平台控制台确认 Key 有效、且已开通对应模型。"}
    if status == 429:
        # 429 多半是「余额不足/无资源包」，不是真的限流，必须提示充值
        if "余额" in official or "资源包" in official or "充值" in official:
            return {"kind": "quota", "status": status,
                    "message": "账户余额不足：%s" % (official or "无可用资源包"),
                    "hint": "去模型平台控制台充值，或换一个有余量的 Key。AI 精读依赖它，其余功能不受影响。"}
        return {"kind": "quota", "status": status,
                "message": "触发限流（HTTP 429）。%s" % official,
                "hint": "免费额度一般按 RPM 限流，隔 10~30 秒重试即可。"}
    if status == 404:
        return {"kind": "model", "status": status,
                "message": "模型不存在或当前 Key 无权调用（HTTP 404）。%s" % official,
                "hint": "换一个模型名，或在设置里调整「模型兜底链」。"}
    if status and 500 <= status < 600:
        return {"kind": "server", "status": status,
                "message": "模型平台服务端异常（HTTP %s），稍后重试。%s" % (status, official),
                "hint": "服务端临时故障，重试通常能过。"}
    if isinstance(err, urllib.error.URLError):
        reason = getattr(err, "reason", err)
        if "timed out" in str(reason).lower() or "timeout" in str(reason).lower():
            return {"kind": "timeout", "status": None,
                    "message": "请求超时。公告精读属于长文本任务，可适当调大超时时间。",
                    "hint": "在设置里把「超时(秒)」调到 300 以上。"}
        return {"kind": "network", "status": None,
                "message": "网络连接失败：%s" % reason,
                "hint": "检查网络或代理设置；确认 base_url 可达。"}
    return {"kind": "other", "status": status,
            "message": "调用失败：%s" % err, "hint": ""}


def _payload(messages, model, temperature, stream, max_tokens):
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def _request(messages, model, temperature, timeout, stream, max_tokens, z=None):
    """发一次请求。stream=True 时返回响应流，否则返回解析后的 dict。"""
    z = z or _cfg()
    url = z["base_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
    }
    # 有 Key 才带鉴权头（云端 API 需要；桥接模式本就不走 HTTP）
    if z.get("api_key"):
        headers["Authorization"] = "Bearer %s" % z["api_key"]
    req = urllib.request.Request(
        url,
        data=_payload(messages, model, temperature, stream, max_tokens),
        headers=headers,
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())


def _iter_sse(resp):
    """解析 SSE 流：data: {...} 逐行产出 dict。"""
    buf = b""
    while True:
        chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            raw, buf = buf.split(b"\n\n", 1)
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                yield json.loads(data)
            except Exception:
                continue


def _read_body(e):
    try:
        return e.read().decode("utf-8", "replace")[:800]
    except Exception:
        return ""


def _pick_candidates(model=None, z=None):
    """构建有序候选链，每个候选自带完整连接信息（支持**跨厂商**兜底）。

    顺序：
      ① 主 provider 的 [请求模型, *fallback_models]（同一 base_url/key，换模型名）
      ② fallback_providers 里每个厂商的模型（不同 base_url/key，换**厂商**）

    为什么需要跨厂商：同一 provider 共用同一 Key，429 限流时换模型名毫无意义
    （还会一起被限）；只有换到**另一家**的 Key 才可能顶上去。所以 quota 错误
    只在「后面存在不同 base_url 的候选」时才继续，否则立即返回（见 _should_advance）。

    候选结构：{"name","backend","base_url","api_key","env_key","model"}
    """
    z = z or _cfg()
    cands = []

    def _add(base_url, api_key, env_key, backend, m, name):
        if not m:
            return
        if not api_key and env_key:
            api_key = os.environ.get(env_key, "")
        if any(c["base_url"] == base_url and c["model"] == m for c in cands):
            return                       # 去重
        cands.append({"name": name, "backend": backend or "api",
                      "base_url": base_url, "api_key": api_key,
                      "env_key": env_key, "model": m})

    # ① 主 provider
    for m in [model or z.get("model")] + list(z.get("fallback_models") or []):
        _add(z.get("base_url"), z.get("api_key"), z.get("env_key"),
             z.get("backend"), m, z.get("provider_name") or "主模型")
    # ② 跨厂商兜底
    for p in (z.get("fallback_providers") or []):
        if not isinstance(p, dict):
            continue
        for m in ([p.get("model")] + list(p.get("models") or [])):
            _add(p.get("base_url"), p.get("api_key"), p.get("env_key"),
                 p.get("backend"), m, p.get("name") or p.get("base_url") or "兜底")
    return cands


def _should_advance(err, cands, idx):
    """是否应换下一个候选再试。

    - model/timeout/network/server（RETRYABLE）→ 有机会就换下一个。
    - quota（429 限流/余额）→ **仅当后面有不属于同一 base_url 的候选**才换，
      因为同 provider 共用 Key，换模型名逃不掉同一个限流额度。
    """
    if idx + 1 >= len(cands):
        return False
    kind = (err or {}).get("kind")
    if kind in RETRYABLE:
        return True
    if kind == "quota":
        cur = cands[idx].get("base_url")
        return any(c.get("base_url") != cur for c in cands[idx + 1:])
    return False


def chat_stream(messages, model=None, temperature=None, timeout=None,
                max_tokens=None, on_model=None, name=None, override=None):
    """流式对话。yield 事件 dict：

    {"type":"start","model":..} / {"type":"delta","text":..}
    {"type":"done","model":..,"usage":..} / {"type":"error",..}

    override：一次性覆盖连接配置（见 _cfg），不改变全局设置。
    """
    z = _cfg(override)
    temperature = z["temperature"] if temperature is None else temperature
    timeout = z.get("timeout", 180) if timeout is None else timeout
    if z.get("backend") == "workbuddy":
        system = (messages[0].get("content") if messages and messages[0].get("role") == "system"
                  else messages[0].get("content") if messages else "")
        user = messages[-1].get("content") if messages else ""
        bid = bridge_write(system, user, name=name, model=model)
        yield {"type": "start", "model": "workbuddy"}
        yield {"type": "info", "text": "【WorkBuddy 桥接】已写出 prompt（id=%s），请在平台「桥接」面板复制并交给 WorkBuddy 运行，把返回的 JSON 贴回。" % bid}
        content = bridge_wait(bid, timeout=max(1800, int(timeout) * 10))
        if content is None:
            yield {"type": "error", "kind": "timeout", "message": "等待 WorkBuddy 结果超时。"}
            return
        yield {"type": "delta", "text": content, "model": "workbuddy"}
        yield {"type": "done", "model": "workbuddy", "usage": {}}
        return
    if z.get("backend", "api") == "api" and not z.get("api_key"):
        yield {"type": "error", "kind": "auth", "message": "尚未配置模型 API Key。",
               "hint": "打开右上角「设置」填入 Key。"}
        return

    cands = _pick_candidates(model, z)
    last_err = None
    for idx, cand in enumerate(cands):
        m = cand["model"]
        try:
            resp = _request(messages, m, temperature, timeout, True, max_tokens, cand)
        except urllib.error.HTTPError as e:
            last_err = _classify(e, e.code, _read_body(e))
            if _should_advance(last_err, cands, idx):
                continue
            yield dict({"type": "error"}, **last_err)
            return
        except Exception as e:
            last_err = _classify(e)
            if _should_advance(last_err, cands, idx):
                continue
            yield dict({"type": "error"}, **last_err)
            return

        if on_model:
            on_model(m)
        yield {"type": "start", "model": m}
        usage = {}
        try:
            for evt in _iter_sse(resp):
                for ch in (evt.get("choices") or []):
                    delta = ch.get("delta") or {}
                    txt = delta.get("content") or ""
                    if txt:
                        yield {"type": "delta", "text": txt, "model": m}
                if evt.get("usage"):
                    usage = evt["usage"]
        except Exception as e:
            err = _classify(e)
            if _should_advance(err, cands, idx):
                last_err = err
                continue
            yield dict({"type": "error"}, **err)
            return
        finally:
            try:
                resp.close()
            except Exception:
                pass
        yield {"type": "done", "model": m, "usage": usage}
        return

    yield dict({"type": "error"}, **(last_err or {"kind": "other", "message": "全部模型均失败"}))


def chat(messages, model=None, temperature=None, timeout=None, max_tokens=None,
         on_log=None, name=None, meta=None, should_abort=None, override=None):
    """非流式对话，返回 {"ok":bool, ...}。带模型兜底重试。

    should_abort：仅桥接模式用到，透传给 bridge_wait，让「停止」立即生效。
    override：一次性覆盖连接配置（见 _cfg），首页对话助手靠它直连云 API。
    """
    z = _cfg(override)
    temperature = z["temperature"] if temperature is None else temperature
    timeout = z.get("timeout", 180) if timeout is None else timeout
    if z.get("backend") == "workbuddy":
        system = (messages[0].get("content") if messages and messages[0].get("role") == "system"
                  else messages[0].get("content") if messages else "")
        user = messages[-1].get("content") if messages else ""
        if on_log:
            on_log("【WorkBuddy 桥接】已写出 prompt，请在平台「桥接」面板复制并交给 WorkBuddy 运行，把 JSON 贴回。")
        bid = bridge_write(system, user, name=name, model=model, meta=meta)
        if on_log:
            on_log("    prompt 文件：runtime/bridge/inbox/%s.prompt.md（id=%s）" % (bid, bid))
            if meta and meta.get("scanned"):
                warn = ("    ⚠ 扫描件（无文字层）：本份**必须按 prompt 内的图片路径用 Read 工具逐页读图识别**，"
                        "不要直接提交占位行。共 %d 张图。"
                        % len(meta.get("images") or []))
                try:
                    on_log(warn, level="warn")
                except TypeError:
                    on_log(warn)
        content = bridge_wait(bid, timeout=max(1800, int(timeout) * 10), on_log=on_log,
                              should_abort=should_abort)
        if content is None:
            if should_abort and should_abort():
                return {"ok": False, "kind": "stopped", "message": "已手动停止，放弃等待结果。"}
            return {"ok": False, "kind": "timeout",
                    "message": "等待 WorkBuddy 结果超时。请在平台「桥接」面板提交结果后重试该份公告。",
                    "hint": "或在设置里调大「超时(秒)」。"}
        return {"ok": True, "model": "workbuddy", "content": content,
                "usage": {}, "elapsed": 0, "raw": {}}
    if z.get("backend", "api") == "api" and not z.get("api_key"):
        return {"ok": False, "kind": "auth", "message": "尚未配置模型 API Key。",
                "hint": "打开右上角「设置」填入 Key。"}

    cands = _pick_candidates(model, z)
    last_err = None
    for idx, cand in enumerate(cands):
        m = cand["model"]
        t0 = time.time()
        try:
            resp = _request(messages, m, temperature, timeout, False, max_tokens, cand)
            raw = resp.read().decode("utf-8", "replace")
            data = json.loads(raw)
            content = ""
            choices = data.get("choices") or []
            if choices:
                content = (choices[0].get("message") or {}).get("content") or ""
            return {"ok": True, "model": m, "content": content,
                    "usage": data.get("usage") or {},
                    "elapsed": round(time.time() - t0, 2),
                    "raw": data}
        except urllib.error.HTTPError as e:
            body = _read_body(e)
            last_err = _classify(e, e.code, body)
            last_err["body"] = body
            if _should_advance(last_err, cands, idx):
                continue
            return dict({"ok": False}, **last_err)
        except Exception as e:
            last_err = _classify(e)
            if _should_advance(last_err, cands, idx):
                continue
            return dict({"ok": False}, **last_err)
    return dict({"ok": False}, **(last_err or {"kind": "other", "message": "全部模型均失败"}))


def quick_test():
    """连通性自检：用最小 token 打一发，验证 Key + 模型可用。"""
    z = _cfg()
    if z.get("backend") == "workbuddy":
        return {"ok": True, "model": "workbuddy", "content": "", "elapsed": 0,
                "message": "桥接模式：不联网，无需连通性测试。运行 AI 精读时会在「桥接」面板生成 prompt，交给 WorkBuddy 运行后把 JSON 贴回即可。"}
    if z.get("backend", "api") == "api" and not z.get("api_key"):
        return {"ok": False, "kind": "auth", "message": "尚未配置 API Key"}
    t0 = time.time()
    r = chat([{"role": "user", "content": "只回复两个字：正常"}],
             max_tokens=16, timeout=min(60, z.get("timeout", 180)))
    r["elapsed"] = round(time.time() - t0, 2)
    r["api_key_masked"] = _mask(z.get("api_key", ""))
    return r
