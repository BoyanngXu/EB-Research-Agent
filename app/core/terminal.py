# -*- coding: utf-8 -*-
"""终端交互窗口（设置页内嵌命令行）。

仅监听 127.0.0.1，等同在本机打开的命令行，供开发者跑 pip / python 等指令。

接口约定（见 app/web/routes.py）：
- POST /api/terminal        启动命令，返回 {ok, tid}
- GET  /api/terminal/stream?tid=   SSE 实时推送（event: output / meta / status / error）
- POST /api/terminal/stop   终止进程 {tid}

设计要点（与平台「长任务先给 tid、前端订阅 SSE」一致）：
- 子进程 stdout/stderr 合并，由一个 daemon 线程逐行推进 queue.Queue；
- SSE generator 从队列取行实时 yield，进程结束放哨兵 None；
- 硬性超时 + 输出上限，超限一律强杀，避免某个命令把服务拖死或内存撑爆；
- 少量「不可逆/破坏性」指令做轻量拦截（cmd.exe 语境下仍有危害的）；
  其余指令等同于本机命令行，请自行甄别。
"""
import os
import queue
import re
import subprocess
import sys
import threading
import time

from . import config, env

# ---------------------------------------------------------------- 安全护栏
_HARD_TIMEOUT = 600                      # 单条命令最长 10 分钟，超时强杀
_OUTPUT_CAP = 800 * 1024                 # 输出上限 800KB，超出即截断并杀进程
_MAX_SESSIONS = 20                       # 内存里最多保留的会话数
_CMD_MAX = 4000                          # 单条命令长度上限

# 极少量「不可逆/破坏性」指令拦截（落 cmd.exe 语境仍有危害的）
_BLOCK = (r"\brm\s+-rf", r"\brm\s+-fr", r"\brd\s+/s", r"\bdel\s+/[sq]",
          r"\bformat\s+[a-z]:", r"\bshutdown\b", r"\bmkfs", r":\(\)\s*\{",
          r"\bdiskpart\b")

_SESSIONS = {}
_LOCK = threading.Lock()


def _gen_tid():
    return time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()


def _safe_cwd(cwd):
    if cwd and os.path.isdir(cwd):
        return cwd
    try:
        return config.PLATFORM_ROOT
    except Exception:
        return os.getcwd()


def _blocked(cmd):
    low = cmd.lower()
    for pat in _BLOCK:
        if re.search(pat, low):
            return pat
    return None


# ------------------------------------------------- 解释器/pip 环境对齐
# 平台跑脚本用的是「装了依赖」的解释器（见 env.detect_python），
# 但终端子进程的 PATH 里排在最前的往往是空的 managed python 或应用商店 shim，
# 直接敲 pip / python 会装到错的解释器上。这里把它对齐并缓存。
_PY_CACHE = {}
_PIP_RE = re.compile(r"^\s*(pip3|pip)(\s|$)", re.I)


def _preferred_python():
    """返回项目认定的「有依赖」的解释器绝对路径，结果缓存。"""
    if "exe" in _PY_CACHE:
        return _PY_CACHE["exe"]
    exe = sys.executable
    try:
        r = env.detect_python()
        cand = (r or {}).get("executable")
        if cand and os.path.exists(cand):
            exe = cand
    except Exception:
        pass
    _PY_CACHE["exe"] = exe
    return exe


def _normalize_pip(cmd, py):
    """裸 pip 在多数 Python 目录下没有 pip.exe（只有 python -m pip），这里做等价改写。"""
    m = _PIP_RE.match(cmd)
    if not m:
        return cmd
    rest = cmd[m.end():]
    return ('"%s" -m pip %s' % (py, rest)).rstrip()


def _child_env(py):
    """把目标解释器目录（含 Scripts）前置到 PATH，并统一 Python 输出编码。"""
    e = os.environ.copy()
    pydir = os.path.dirname(py)
    scripts = os.path.join(pydir, "Scripts")
    parts = [pydir]
    if os.path.isdir(scripts):
        parts.append(scripts)
    if e.get("PATH"):
        parts.append(e["PATH"])
    e["PATH"] = os.pathsep.join(parts)
    e["PYTHONIOENCODING"] = "utf-8"      # 避免子进程 print 中文时撞上 GBK 控制台
    return e


def run(cmd, cwd=None):
    """启动一条命令，返回 tid。出错抛 ValueError。"""
    cmd = (cmd or "").strip()
    if not cmd:
        raise ValueError("命令为空")
    if len(cmd) > _CMD_MAX:
        raise ValueError("命令过长（≤%d 字符）" % _CMD_MAX)
    cmd = _normalize_pip(cmd, _preferred_python())
    hit = _blocked(cmd)
    if hit:
        raise ValueError("出于安全拦截了疑似破坏性指令（命中规则：%s）" % hit)
    tid = _gen_tid()
    s = _Session(tid, cmd, _safe_cwd(cwd))
    s.start()
    with _LOCK:
        _SESSIONS[tid] = s
        _trim()
    return tid


def stop(tid):
    with _LOCK:
        s = _SESSIONS.get(tid)
    if not s:
        return False
    s.kill()
    return True


def get_session(tid):
    with _LOCK:
        return _SESSIONS.get(tid)


def stream(tid):
    """SSE 生成器：实时把子进程输出推给前端。"""
    s = get_session(tid)
    if not s:
        yield ("error", {"error": "会话不存在或已结束（可能已超时被回收）"})
        return
    yield ("meta", {"tid": tid, "cmd": s.cmd, "cwd": s.cwd})
    total = [0]
    while True:
        try:
            item = s.q.get(timeout=1.0)
        except queue.Empty:
            if s.finished.is_set():
                break
            yield ("ping", {"t": int(time.time())})   # 保活，避免代理把连接缓冲掉
            continue
        if item is None:                               # 进程结束哨兵
            break
        total[0] += len(item)
        yield ("output", {"text": item})
        if total[0] > _OUTPUT_CAP:
            s.kill()
            yield ("output", {"text": "\n[输出超出 %dKB 上限，已强制终止]\n" % (_OUTPUT_CAP // 1024)})
            break
    yield ("status", {"exit_code": s.exit_code, "killed": s.killed})


def _trim():
    """只保留最近的若干会话，回收内存（不删除，纯内存对象）。"""
    if len(_SESSIONS) <= _MAX_SESSIONS:
        return
    try:
        keys = sorted(_SESSIONS.keys())
        for k in keys[:len(_SESSIONS) - _MAX_SESSIONS]:
            _SESSIONS.pop(k, None)
    except Exception:
        pass


class _Session:
    def __init__(self, tid, cmd, cwd):
        self.tid = tid
        self.cmd = cmd
        self.cwd = cwd
        self.q = queue.Queue()
        self.finished = threading.Event()
        self.exit_code = None
        self.killed = False
        self._proc = None

    def start(self):
        try:
            self._proc = subprocess.Popen(
                self.cmd, shell=True, cwd=self.cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=_child_env(_preferred_python()),
                bufsize=1)
        except Exception as e:
            self.q.put("启动失败：%s\n" % e)
            self.finished.set()
            self.q.put(None)
            return
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=self._watchdog, daemon=True).start()

    @staticmethod
    def _decode(data: bytes) -> str:
        # 中文 Windows 的 cmd/pip/python 输出多为 GBK(cp936)；优先 utf-8，再回退 cp936，最后 latin-1(绝不失败)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            pass
        try:
            return data.decode("cp936")
        except UnicodeDecodeError:
            return data.decode("latin-1", "replace")

    def _pump(self):
        try:
            for raw in self._proc.stdout:
                self.q.put(self._decode(raw))
        except Exception as e:
            self.q.put("(%s)\n" % e)
        finally:
            try:
                self._proc.stdout.close()
            except Exception:
                pass
            try:
                self.exit_code = self._proc.wait()
            except Exception:
                pass
            self.finished.set()
            self.q.put(None)               # 结束哨兵

    def _watchdog(self):
        # 硬性超时强杀
        if self.finished.wait(_HARD_TIMEOUT):
            return
        self.kill()
        self.q.put("\n[超时 %d 秒，已强制终止]\n" % _HARD_TIMEOUT)

    def kill(self):
        self.killed = True
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except Exception:
                    p.kill()
            except Exception:
                pass
