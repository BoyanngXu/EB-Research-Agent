# -*- coding: utf-8 -*-
"""对话记忆：会话内多轮上下文 + 跨会话历史检索（Agentic RAG 的记忆层）。

存储：runtime/memory/<session_id>.jsonl，每行一条 {ts, role, text, refs, sources}。
- role: user / assistant / tool
- refs:  这条回答引用了哪些来源（前端据此展示「已检索」徽标）
- 只存对话与引用路径，不存文件正文全文、不存密钥。

清理约束：运行环境对「一次删除 >50 文件」要求人工确认，无头服务进程无法确认会被
直接阻断。所以**所有清理都用 os.rename 把目录/文件移进 _archive/，绝不删除**。
"""
import json
import os
import time

from . import config

_DIRTY_TITLE = 42


def dir_path():
    return config.runtime_dir("memory")


def enabled():
    c = config.load().get("memory") or {}
    return bool(c.get("enabled", True))


def new_session_id():
    return time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()


def _path(session):
    return os.path.join(dir_path(), str(session) + ".jsonl")


def _safe_session(session):
    """防目录穿越：只认「文件名」形态的会话 id。"""
    s = str(session or "")
    if not s or "/" in s or "\\" in s or s in (".", "..") or not s.replace("-", "").isalnum():
        raise ValueError("非法会话 id：%s" % s)
    return s


def append(session, role, text, refs=None, sources=None):
    """写一条记忆。返回写入的记录（失败返回 None）。"""
    if not enabled() or not session:
        return None
    try:
        s = _safe_session(session)
    except ValueError:
        return None
    rec = {
        "ts": time.time(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "role": "user" if role == "user" else ("assistant" if role == "assistant" else "tool"),
        "text": (text or "").strip(),
        "refs": refs or [],
        "sources": sources or [],
    }
    if not rec["text"]:
        return None
    try:
        with open(_path(s), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec
    except Exception:
        return None


def read(session, limit=200):
    try:
        s = _safe_session(session)
    except ValueError:
        return []
    p = _path(s)
    if not os.path.isfile(p):
        return []
    try:
        with open(p, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except Exception:
        return []
    out = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def _title_of(path):
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                try:
                    rec = json.loads(ln)
                except Exception:
                    continue
                if rec.get("role") == "user" and rec.get("text"):
                    t = rec["text"].replace("\n", " ").strip()
                    return t[:_DIRTY_TITLE] + ("…" if len(t) > _DIRTY_TITLE else "")
    except Exception:
        pass
    return "（无标题）"


def list_sessions(limit=30):
    """列出历史会话，新的在前。"""
    d = dir_path()
    if not os.path.isdir(d):
        return []
    items = []
    try:
        for fn in os.listdir(d):
            if not fn.endswith(".jsonl"):
                continue
            p = os.path.join(d, fn)
            if not os.path.isfile(p):
                continue
            mtime = os.path.getmtime(p)
            turns = 0
            try:
                with open(p, encoding="utf-8") as fh:
                    turns = sum(1 for ln in fh if ln.strip())
            except Exception:
                pass
            items.append({"id": fn[:-6], "updated": mtime,
                          "updated_str": time.strftime("%m-%d %H:%M", time.localtime(mtime)),
                          "turns": turns, "title": _title_of(p)})
    except Exception:
        return []
    items.sort(key=lambda x: -x["updated"])
    return items[:limit]


def _tokens(q):
    toks = []
    for m in __import__("re").findall(r"[A-Za-z0-9._]{2,}", q or ""):
        toks.append(m.lower())
    cn = __import__("re").sub(r"[^\u4e00-\u9fa5]+", "", q or "")
    if cn:
        toks.append(cn)
        if len(cn) <= 16:
            toks += [cn[i:i + 2] for i in range(len(cn) - 1)]
    seen, out = set(), []
    for t in toks:
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def search(query, top_k=None, exclude=None):
    """跨会话检索：所有会话里找与 query 相关的历史发言（新的优先）。"""
    c = config.load().get("memory") or {}
    top_k = top_k or int(c.get("search_topk", 5) or 5)
    toks = _tokens(query)
    if not toks:
        return []
    d = dir_path()
    if not os.path.isdir(d):
        return []
    hits = []
    try:
        files = [f for f in os.listdir(d) if f.endswith(".jsonl")]
    except Exception:
        return []
    # 新的会话先看
    files.sort(key=lambda f: -os.path.getmtime(os.path.join(d, f)))
    for fn in files:
        sid = fn[:-6]
        p = os.path.join(d, fn)
        try:
            with open(p, encoding="utf-8") as fh:
                for ln in fh:
                    try:
                        rec = json.loads(ln)
                    except Exception:
                        continue
                    text = rec.get("text") or ""
                    low = text.lower()
                    sc = sum(len(t) for t in toks if t in low)
                    if not sc:
                        continue
                    if exclude and sid == exclude:
                        sc = sc * 0.5          # 当前会话降权，但不排除（多轮指代需要）
                    hits.append({"session": sid, "ts": rec.get("ts", 0),
                                 "time": rec.get("time", ""), "role": rec.get("role", ""),
                                 "text": text[:600], "score": sc})
        except Exception:
            continue
    hits.sort(key=lambda x: (-x["score"], -x["ts"]))
    return hits[:top_k]


def recent_user_prompts(limit=30, days=30):
    """跨会话取最近的用户提问（时间倒序、全局去重），供前端「历史 prompt」回填。

    返回 [{session, ts, time, text}]，text 为原文（未截断，前端自行截断）。
    """
    c = config.load().get("memory") or {}
    limit = limit or int(c.get("prompts_limit", 30) or 30)
    days = days if days is not None else int(c.get("prompts_days", 30) or 30)
    d = dir_path()
    if not os.path.isdir(d):
        return []
    cutoff = time.time() - days * 86400
    items = []
    try:
        files = [f for f in os.listdir(d) if f.endswith(".jsonl")]
    except Exception:
        return []
    for fn in files:
        sid = fn[:-6]
        p = os.path.join(d, fn)
        try:
            with open(p, encoding="utf-8") as fh:
                for ln in fh:
                    try:
                        rec = json.loads(ln)
                    except Exception:
                        continue
                    if rec.get("role") != "user":
                        continue
                    ts = rec.get("ts", 0)
                    if ts < cutoff:
                        continue
                    txt = (rec.get("text") or "").strip()
                    if not txt:
                        continue
                    items.append({"session": sid, "ts": ts,
                                  "time": rec.get("time", ""), "text": txt})
        except Exception:
            continue
    items.sort(key=lambda x: -x["ts"])
    seen, out = set(), []
    for it in items:
        if it["text"] in seen:
            continue
        seen.add(it["text"])
        out.append(it)
        if len(out) >= limit:
            break
    return out


def prune(keep_days=None):
    """把超过保留天数的会话改名移进 _archive/（不删除，见模块 docstring）。"""
    c = config.load().get("memory") or {}
    keep_days = keep_days if keep_days is not None else int(c.get("keep_days", 60) or 60)
    d = dir_path()
    if not os.path.isdir(d) or keep_days <= 0:
        return 0
    deadline = time.time() - keep_days * 86400
    archive = os.path.join(d, "_archive")
    moved = 0
    try:
        for fn in os.listdir(d):
            if not fn.endswith(".jsonl"):
                continue
            p = os.path.join(d, fn)
            if not os.path.isfile(p) or os.path.getmtime(p) > deadline:
                continue
            try:
                os.makedirs(archive, exist_ok=True)
                os.rename(p, os.path.join(archive, fn))
                moved += 1
            except Exception:
                continue
    except Exception:
        pass
    return moved


def clear():
    """清空全部对话记忆：整个目录改名移进 _archive/，再建空目录。"""
    d = dir_path()
    if not os.path.isdir(d):
        return 0
    count = 0
    try:
        count = len([f for f in os.listdir(d) if f.endswith(".jsonl")])
    except Exception:
        pass
    ts = time.strftime("%Y%m%d_%H%M%S")
    try:
        os.rename(d, d.rstrip("/\\") + "_arch_" + ts)
    except Exception:
        return 0
    dir_path()          # 重建空目录
    return count
