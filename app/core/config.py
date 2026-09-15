# -*- coding: utf-8 -*-
"""配置读写：平台根目录 config.json。

设计原则：
1. 所有路径、密钥都在这一个文件里，投研人员可以直接用记事本改。
2. 读取时自动补全缺失字段（向后兼容），不会因为旧配置缺字段而崩。
3. 密钥只落本地磁盘，不上传任何地方。
"""
import json
import os
import shutil
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))       # app/
PLATFORM_ROOT = os.path.dirname(ROOT)                                     # EB-Agent/
CONFIG_PATH = os.path.join(PLATFORM_ROOT, "config.json")

# 工作区根 = 平台目录的上一级（Data/Anno/Wechat/Report 与 EB-Agent 同级）。
# 从 __file__ 推导而非写死 ~/Desktop，这样整份拷到任何盘符/用户名都能自适应。
# 如需把数据放到别处，用环境变量 EB_WORKSPACE_ROOT 覆盖。
WORKSPACE_PARENT = os.environ.get("EB_WORKSPACE_ROOT") or os.path.dirname(PLATFORM_ROOT)
DESKTOP = WORKSPACE_PARENT  # 兼容旧引用（语义即「工作区根」）

DEFAULT_API_KEY = ""  # 留空：优先读环境变量 SENSENOVA_API_KEY，其次在设置页手填

DEFAULTS = {
    "llm": {
        "backend": "api",                               # api=商汤云端 / workbuddy=文件桥接(交WorkBuddy跑,零外部token)
        "api_key": DEFAULT_API_KEY,
        "base_url": "https://token.sensenova.cn/v1",   # 商汤 SenseNova（OpenAI 兼容）
        "model": "deepseek-v4-flash",
        "fallback_models": ["deepseek-v4-flash"],
        "temperature": 0.2,
        "timeout": 180,
        "env_key": "SENSENOVA_API_KEY",                # 环境变量名，用作 Key 回退
    },
    "python": {
        "executable": "",
    },
    "workspace": {
        "data": os.path.join(WORKSPACE_PARENT, "Data").replace("\\", "/"),
        "anno": os.path.join(WORKSPACE_PARENT, "Anno").replace("\\", "/"),
        "wechat": os.path.join(WORKSPACE_PARENT, "Wechat").replace("\\", "/"),
        "report": os.path.join(WORKSPACE_PARENT, "Report").replace("\\", "/"),
        # 输出目录跟随公告目录本身（与 2026-09-04 起的既有行为一致）
        "output": os.path.join(WORKSPACE_PARENT, "Anno").replace("\\", "/"),
    },
    "server": {
        "host": "127.0.0.1",
        "port": 8765,
        "open_browser": True,
    },
    "anno": {
        "summary_min": 130,
        "summary_max": 320,
        "max_pdf_chars": 60000,
        "backend": "workbuddy",       # api=直连SenseNova / workbuddy=文件桥接（精读默认桥接，省 token）
    },
    "wechat": {
        "default_count": 10,
    },
    # 晨会 Report（第 4 个项目）
    "report": {
        "model": "hy3",           # 提取模型（桥接占位名，与 anno 一致）
        "max_txt_chars": 60000,   # 单篇喂给模型的字符上限
    },
    # 首页对话助手（问答 / 动作驱动 / Agentic RAG）
    "assistant": {
        "enabled": True,
        "backend": "api",        # api=云端直连（默认）/ workbuddy=文件桥接（对话助手可切）
        "model": "",             # 留空=跟随主模型；可单独指定一个便宜模型
        "temperature": 0.3,
        "timeout": 120,          # 问答超时（秒），比精读短得多
        "need_confirm": True,    # 执行动作前先弹确认卡
        "max_ctx_chars": 12000,  # 喂给模型的检索片段总上限
        "max_history": 12,       # 带进模型的当前会话轮数
    },
    # 跨会话记忆（runtime/memory/<session>.jsonl）
    "memory": {
        "enabled": True,
        "keep_days": 60,         # 归档保留天数（展示用）
        "search_topk": 5,        # 跨会话检索返回条数
    },
    # 数据读取器（datareader）：标准库解析 xlsx/docx/txt
    "datareader": {
        "index_enabled": True,   # 按 mtime 缓存解析结果
        "max_rows": 3000,        # 单表最多读入行数
        "snippet_chars": 1200,   # 单个片段字符上限
    },
}

_LOCK = threading.Lock()
_CACHE = None


def _deep_merge(base, patch):
    out = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    """读取配置（带进程内缓存），缺失字段自动用默认值补全。"""
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        data = json.loads(json.dumps(DEFAULTS))  # 深拷贝
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8") as fh:
                    disk = json.load(fh)
                # 旧版配置迁移：v0.1 的 "zhipu" 段 → "llm"（接口只是换了平台，语义没变）
                if "zhipu" in disk and "llm" not in disk:
                    disk["llm"] = disk.pop("zhipu")
                data = _deep_merge(data, disk)
            except Exception:
                # 配置损坏时备份一份，继续用默认值，保证平台还能开
                try:
                    shutil.copy2(CONFIG_PATH, CONFIG_PATH + ".bak")
                except Exception:
                    pass
        data["_path"] = CONFIG_PATH
        data["_root"] = PLATFORM_ROOT
        _CACHE = data
        return _CACHE


def save(patch):
    """合并写入配置。只改传进来的字段，其余保留。"""
    global _CACHE
    with _LOCK:
        cur = json.loads(json.dumps(DEFAULTS))
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8") as fh:
                    cur = _deep_merge(cur, json.load(fh))
            except Exception:
                pass
        # 同 load()：旧 zhipu 段迁移到 llm
        if "zhipu" in cur and "llm" not in cur:
            cur["llm"] = cur.pop("zhipu")
        merged = _deep_merge(cur, patch or {})
        merged.pop("_path", None)
        merged.pop("_root", None)
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
        _CACHE = None
    return load()


def public_view():
    """给前端的配置视图：密钥打码，避免截图外泄。"""
    c = load()
    key = c["llm"].get("api_key", "")
    masked = (key[:6] + "*" * max(0, len(key) - 10) + key[-4:]) if len(key) > 12 else ("已配置" if key else "")
    return {
        "llm": {
            "api_key_masked": masked,
            "has_key": bool(key),
            "backend": c["llm"].get("backend", "api"),
            "base_url": c["llm"]["base_url"],
            "model": c["llm"]["model"],
            "fallback_models": c["llm"]["fallback_models"],
            "temperature": c["llm"]["temperature"],
            "timeout": c["llm"]["timeout"],
            "env_key": c["llm"].get("env_key", ""),
        },
        "python": dict(c["python"]),
        "workspace": dict(c["workspace"]),
        "server": dict(c["server"]),
        "anno": dict(c["anno"]),
        "wechat": dict(c["wechat"]),
        "assistant": dict(c["assistant"]),
        "memory": dict(c["memory"]),
        "datareader": dict(c["datareader"]),
        "paths": {"config": CONFIG_PATH, "root": PLATFORM_ROOT},
    }


# 各工作区键在「工作区根」下对应的目录名（output 与 anno 同目录）
_WORKSPACE_DIRNAME = {
    "data": "Data",
    "anno": "Anno",
    "wechat": "Wechat",
    "report": "Report",
    "output": "Anno",
}


def workspace_root(key):
    """工作区目录（可移植）。

    优先级：
      ① config.json 显式指定，且该目录真实存在 → 用它；
      ② 否则回落到「平台目录的上一级」下的同名目录。

    第 ② 条让整份 EB-Agent 拷到新电脑后，即使 config.json 里还残留旧机器的
    绝对路径（在新机上不存在），也能自动落到新位置，而不是静默指向一个空路径。
    """
    c = load()
    p = c["workspace"].get(key, "")
    if p and os.path.isdir(os.path.abspath(p)):
        return os.path.abspath(p)
    name = _WORKSPACE_DIRNAME.get(key, key.capitalize())
    return os.path.abspath(os.path.join(WORKSPACE_PARENT, name))


def tools_dir(name=""):
    p = os.path.join(PLATFORM_ROOT, "tools")
    return os.path.join(p, name) if name else p


def runtime_dir(name=""):
    p = os.path.join(PLATFORM_ROOT, "runtime")
    os.makedirs(p, exist_ok=True)
    sub = os.path.join(p, name) if name else p
    os.makedirs(sub, exist_ok=True)
    return sub
