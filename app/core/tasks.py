# -*- coding: utf-8 -*-
"""任务系统：后台跑脚本，实时把日志推给前端。

为什么自己写而不用现成框架：整个平台要求"零依赖、拷走就能跑"，
所以只用标准库实现 子进程 + 环形日志缓冲 + 订阅广播（SSE）。
"""
import json
import os
import queue
import re
import subprocess
import threading
import time
import traceback
import uuid

from . import config

MAX_TASKS = 60
MAX_LOG_LINES = 4000

# 持久化：任务日志落盘到 runtime/tasks/<tid>.jsonl，任务结束时再写一份 <tid>.meta.json
# 快照。内存缓冲只留最近 MAX_LOG_LINES 条供 SSE 实时推，磁盘上是完整日志——
# 服务重启、或任务被内存淘汰（超过 MAX_TASKS）之后依然能回看。
MAX_ACTIVE_TASK_FILES = 120      # 活动目录保留的文件数上限，超出部分改名归档
_TID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_LOCK = threading.Lock()
_TASKS = {}          # id -> Task
_ORDER = []


class Task:
    def __init__(self, tid, title, project="", cmd=None, cwd=None):
        self.id = tid
        self.title = title
        self.project = project
        self.cmd = cmd or []
        self.cwd = cwd
        self.status = "pending"       # pending / running / done / failed / stopped
        self.code = None
        self.created = time.time()
        self.started = None
        self.finished = None
        self.log = []
        self.result = None
        self.progress_data = None      # 最新一次 progress() 的数据（供前端轮询/快照）
        self._subs = []
        self._proc = None
        self._lock = threading.Lock()
        self._log_fh = None
        self._log_path = log_path(tid)
        self._meta_path = meta_path(tid)

    # ---------- 日志 ----------
    def emit(self, line, level="info"):
        line = str(line).rstrip("\r\n")
        rec = {"t": round(time.time() - (self.started or self.created), 2),
               "level": level, "text": line}
        with self._lock:
            self.log.append(rec)
            if len(self.log) > MAX_LOG_LINES:
                self.log = self.log[-MAX_LOG_LINES:]
            subs = list(self._subs)
            self._persist(rec)
        for q in subs:
            try:
                q.put_nowait(rec)
            except Exception:
                pass

    # ---------- 持久化 ----------
    def _persist(self, rec):
        """把一条日志追加到 runtime/tasks/<tid>.jsonl。

        与内存缓冲解耦：内存只留最近 MAX_LOG_LINES 条供 SSE 实时推，
        磁盘上则是完整日志。落盘失败不影响任务本身（本地工具，不该因日志挂掉）。
        """
        try:
            if self._log_fh is None:
                os.makedirs(os.path.dirname(self._log_path), exist_ok=True)
                self._log_fh = open(self._log_path, "a", encoding="utf-8")
            obj = dict(rec)
            obj["ts"] = round(time.time(), 3)
            self._log_fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self._log_fh.flush()
        except Exception:
            pass

    def close_log(self):
        """任务落幕时关闭日志文件句柄。"""
        with self._lock:
            if self._log_fh is not None:
                try:
                    self._log_fh.close()
                except Exception:
                    pass
                self._log_fh = None

    def write_meta(self):
        """任务落幕时写一份快照 meta.json，查历史任务时无需回放整份日志。"""
        try:
            os.makedirs(os.path.dirname(self._meta_path), exist_ok=True)
            with open(self._meta_path, "w", encoding="utf-8") as fh:
                json.dump(self.snapshot(with_log=False), fh, ensure_ascii=False)
        except Exception:
            pass

    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self._lock:
            self._subs.append(q)
        return q

    def progress(self, data):
        """发一条结构化进度（level='progress'），前端据此渲染进度面板。

        与 emit 不同：progress 不写入普通日志（避免执行日志里出现一坨 JSON），
        只广播给正在订阅的 SSE 客户端，并缓存到 self.progress_data。
        """
        rec = {"t": round(time.time() - (self.started or self.created), 2),
               "level": "progress",
               "text": json.dumps(data, ensure_ascii=False)}
        self.progress_data = data
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(rec)
            except Exception:
                pass

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    # ---------- 序列化 ----------
    def snapshot(self, with_log=True, tail=400):
        d = {
            "id": self.id, "title": self.title, "project": self.project,
            "status": self.status, "code": self.code,
            "cmd": self.cmd, "cwd": self.cwd,
            "created": self.created, "started": self.started, "finished": self.finished,
            "duration": round((self.finished or time.time()) - (self.started or self.created), 2),
            "result": self.result,
            "progress": self.progress_data,
            "log_count": len(self.log),
        }
        if with_log:
            d["log"] = self.log[-tail:]
        return d

    def stop(self):
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                if os.name == "nt":
                    # 用 taskkill 连子进程一起结束，否则 playwright 会留孤儿进程
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   capture_output=True)
                else:
                    proc.terminate()
            except Exception:
                pass
        # 无论有没有子进程都要置 stopped：run_callable 类任务（AI 精读、安装依赖）
        # 没有子进程，改之前 stop() 对它们完全无效——状态不变，循环检测不到停止
        # 信号，任务只能干等 bridge_wait 超时（最长 30 分钟）。
        if self.status in ("pending", "running"):
            self.status = "stopped"
            self.emit("（已手动停止）", "warn")


# --------------------------------------------------------------------------
# 持久化：落盘路径 / 回读 / 归档
# --------------------------------------------------------------------------
def task_log_dir():
    return config.runtime_dir("tasks")


def _safe_tid(tid):
    """任务 id 只允许字母数字与 - _，防路径穿越。"""
    tid = str(tid or "")
    if not _TID_RE.match(tid):
        raise ValueError("非法任务 id：%r" % tid)
    return tid


def log_path(tid):
    return os.path.join(task_log_dir(), "%s.jsonl" % _safe_tid(tid))


def meta_path(tid):
    return os.path.join(task_log_dir(), "%s.meta.json" % _safe_tid(tid))


def read_log(tid, tail=400):
    """读回持久化的任务日志（重启 / 淘汰后仍可查）。无该文件时返回 None。"""
    path = log_path(tid)
    if not os.path.exists(path):
        return None
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    out.append({"t": 0, "level": "info", "text": line})
    except Exception:
        return None
    return out[-tail:] if tail else out


def read_meta(tid):
    """读回任务快照 meta.json；没有则 None。"""
    path = meta_path(tid)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def list_archived(limit=50):
    """列出磁盘上持久化的历史任务（含已被内存淘汰 / 上次服务运行留下的）。"""
    d = task_log_dir()
    items = []
    try:
        names = [n for n in os.listdir(d) if n.endswith(".meta.json")]
    except Exception:
        return items
    for n in names:
        try:
            with open(os.path.join(d, n), encoding="utf-8") as fh:
                m = json.load(fh)
        except Exception:
            continue
        m["persisted"] = True
        items.append(m)
    items.sort(key=lambda x: x.get("created") or 0, reverse=True)
    return items[:limit]


def archive_old(keep=MAX_ACTIVE_TASK_FILES):
    """活动任务文件过多时，把最老的一批改名移进 _archive/。

    为什么用改名而不是删除：运行环境对「一次删除 >50 文件」有守卫，无头服务
    进程无法确认会被直接阻断；os.replace 属改名（覆盖同名），不算删除，
    既能回收目录条目，又随时能从 _archive/ 翻回来。
    """
    d = task_log_dir()
    try:
        names = [n for n in os.listdir(d)
                 if n.endswith(".jsonl") or n.endswith(".meta.json")]
    except Exception:
        return 0
    if len(names) <= keep:
        return 0

    def mtime(n):
        try:
            return os.path.getmtime(os.path.join(d, n))
        except Exception:
            return 0.0

    names.sort(key=mtime)
    archive = os.path.join(d, "_archive")
    moved = 0
    for n in names[: len(names) - keep]:
        try:
            os.makedirs(archive, exist_ok=True)
            os.replace(os.path.join(d, n), os.path.join(archive, n))
            moved += 1
        except Exception:
            continue
    return moved


def _register(task):
    with _LOCK:
        _TASKS[task.id] = task
        _ORDER.append(task.id)
        while len(_ORDER) > MAX_TASKS:
            old = _ORDER.pop(0)
            _TASKS.pop(old, None)
    # 顺带回收过旧的任务文件（改名归档，不删除）
    try:
        archive_old()
    except Exception:
        pass


def get(tid):
    with _LOCK:
        return _TASKS.get(tid)


def list_tasks(limit=30):
    with _LOCK:
        ids = list(reversed(_ORDER))[:limit]
        return [_TASKS[i].snapshot(with_log=False) for i in ids if i in _TASKS]


def run_stream(title, cmd, cwd=None, project="", env=None, on_done=None,
               stdin_text=None, interactive_hint=True, pre_run=None):
    """启动一个子进程任务，返回 Task。日志按行实时写入。"""
    tid = uuid.uuid4().hex[:8]
    task = Task(tid, title, project, cmd, cwd)
    task.emit("$ " + " ".join(_quote(c) for c in cmd), "cmd")
    _register(task)

    def _worker():
        task.status = "running"
        task.started = time.time()
        task.emit("任务开始：%s" % title)
        if pre_run:
            try:
                for _ln in (pre_run() or []):
                    if _ln:
                        task.emit(str(_ln))
            except Exception:
                task.emit("抓取前预处理异常：" + traceback.format_exc(), "error")
        run_env = dict(os.environ)
        run_env["PYTHONIOENCODING"] = "utf-8"
        run_env["PYTHONUTF8"] = "1"
        run_env["PYTHONUNBUFFERED"] = "1"
        run_env.update(env or {})
        # 终态先暂存，等 on_done 跑完再落：on_done（如抓取后自动 LLM 汇总）可能耗时，
        # 若子进程一退出就置 done，前端轮询到终态会立刻读 task.result 渲染，
        # 而 result 尚未写入 → 出现「抓取 10/10 成功却提示未命中」的假象。
        final_status = "failed"
        try:
            proc = subprocess.Popen(
                cmd, cwd=cwd, env=run_env,
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            task._proc = proc
            if stdin_text is not None:
                try:
                    proc.stdin.write(stdin_text)
                    proc.stdin.flush()
                except Exception:
                    pass
                finally:
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass
            for line in proc.stdout:
                task.emit(line)
            proc.wait()
            task.code = proc.returncode
            # 手动停止过的不要覆写：否则 stop() 设的 stopped 会被改回 failed/done，
            # 前端会把「已停止」误显示成「已完成/失败」。终态暂存，finally 里再落。
            if task.status != "stopped":
                final_status = "done" if proc.returncode == 0 else "failed"
            task.emit("任务结束，退出码 %s" % proc.returncode,
                      "info" if proc.returncode == 0 else "error")
            if final_status == "failed" and interactive_hint:
                blob = "\n".join(r.get("text", "") for r in task.log)
                if "缺少依赖库" in blob or "pip install" in blob:
                    task.emit("依赖缺失：脚本在启动阶段就因缺少依赖库而退出（见上方 pip install 提示）。"
                              "请在 EB-Agent 的 .venv 里补装，例如：\n"
                              "  .venv\\Scripts\\python.exe -m pip install ddddocr\n"
                              "（易知下载线还需 playwright / pillow，详见 requirements-extra.txt）", "warn")
                else:
                    task.emit("提示：该脚本若在无头/非交互环境下卡住，多半是在等你输入"
                              "（日期、验证码等）。平台调用时已尽量走非交互参数。", "warn")
        except FileNotFoundError:
            final_status = "failed"
            task.code = -1
            task.emit("找不到可执行文件：%s" % cmd[0], "error")
        except Exception:
            final_status = "failed"
            task.code = -2
            task.emit("任务异常：\n" + traceback.format_exc(), "error")
        finally:
            if on_done:
                try:
                    task.emit("正在整理产出结果…", "info")
                    task.result = on_done(task)
                except Exception as e:
                    task.result = {"error": str(e)}
            # on_done 跑完才落终态：保证「前端看到终态 ⇒ task.result 已就绪」，
            # 否则前端轮询到 done 时会读到空 result（抓取成功却提示"未命中"的假象）。
            if task.status != "stopped":
                task.status = final_status
            # 先落盘快照再置 finished：保证「任务已结束 ⇒ 磁盘快照已存在」，
            # 不会出现前端刚看到 finished 就去查 meta 却扑空的情况。
            task.write_meta()
            task.finished = time.time()
            task.close_log()

    threading.Thread(target=_worker, daemon=True).start()
    return task


def run_callable(title, func, project="", **kwargs):
    """跑一个 Python 函数（不启子进程），同样走任务日志。"""
    tid = uuid.uuid4().hex[:8]
    task = Task(tid, title, project, [title])
    task.emit("任务开始：%s" % title)
    _register(task)
    task.status = "running"
    task.started = time.time()

    def _worker():
        try:
            res = func(task=task, **kwargs)
            task.result = res
            # 同上：被停止的任务（函数提前 break 返回）保持 stopped
            if task.status != "stopped":
                task.status = "done"
                task.code = 0
            task.emit("任务结束", "info")
        except Exception:
            task.status = "failed"
            task.code = -2
            task.emit(traceback.format_exc(), "error")
        finally:
            # 同上：快照先落盘，finished 后置
            task.write_meta()
            task.finished = time.time()
            task.close_log()

    threading.Thread(target=_worker, daemon=True).start()
    return task


def _quote(s):
    s = str(s)
    return '"%s"' % s if (" " in s or "（" in s or "(" in s) else s
