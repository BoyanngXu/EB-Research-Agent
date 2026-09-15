# -*- coding: utf-8 -*-
"""文件访问层：路径安全护栏 + 目录浏览 + 下载。

安全约束：任何文件操作都只能落在「三个工作区 + 平台目录」之内，
越界一律拒绝。平台只监听 127.0.0.1，但仍然守住这层。
"""
import os
import re
import subprocess
import sys
import time
from urllib.parse import quote

from . import config

SKIP_DIRS = {".git", "__pycache__", ".idea", "node_modules", "$RECYCLE.BIN",
             "System Volume Information", ".tmp"}
# Windows 上实际目录名大小写不定（如 $Recycle.Bin / $SysReset），故按小写比对
SKIP_DIRS_LOWER = {s.lower() for s in SKIP_DIRS}
SKIP_FILES_RE = re.compile(r"^~\$|\.pyc$|\.tmp$")

DOC_EXT = {".xlsx", ".xls", ".csv", ".docx", ".pdf", ".txt", ".md", ".json", ".ini", ".log"}

# 「此电脑」层级的哨兵路径：前端传这个值时返回各盘符列表
COMPUTER = "@computer"


def list_drives():
    """返回本机可用盘符根目录（如 C:/ D:/），供「此电脑」层级浏览。

    纯标准库实现：逐个盘符试探 os.path.isdir，不存在的盘（含空光驱/未映射网络盘）
    返回 False，异常一并吞掉。
    """
    drives = []
    if os.name == "nt":
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            p = "%s:/" % ch
            try:
                if os.path.isdir(p):
                    drives.append(p)
            except Exception:
                continue
    else:
        drives.append("/")
    return drives


def allowed_roots():
    """允许访问的根目录列表（已规范化）。

    除「三个工作区 + 平台目录」外，再并入本机所有盘符根（C:/、D:/…），
    这样目录选择器可以从任意本地盘根目录开始浏览。平台只监听 127.0.0.1、
    单用户本地使用，故此放开可接受；仍然把网络/UNC 路径挡在外面。
    """
    roots = []
    c = config.load()
    for k in ("data", "anno", "wechat", "output"):
        p = c["workspace"].get(k, "")
        if p:
            roots.append(os.path.abspath(p))
    roots.append(os.path.abspath(config.PLATFORM_ROOT))
    for d in list_drives():
        roots.append(os.path.abspath(d))
    return roots


def safe_path(path, must_exist=True):
    """校验路径合法并返回绝对路径；越界抛 ValueError。"""
    if not path:
        raise ValueError("路径为空")
    ap = os.path.abspath(os.path.expanduser(path))
    for root in allowed_roots():
        try:
            rel = os.path.relpath(ap, root)
        except ValueError:
            continue
        if rel == os.curdir or not rel.startswith(os.pardir + os.sep) and not rel == os.pardir:
            if must_exist and not os.path.exists(ap):
                raise FileNotFoundError("文件不存在：%s" % ap)
            return ap
    raise ValueError("路径不在允许的工作区内：%s" % path)


def is_allowed(path):
    try:
        safe_path(path, must_exist=False)
        return True
    except Exception:
        return False


def list_dir(path, only_docs=False):
    """列目录。返回 {path, entries:[{name,is_dir,size,mtime,ext}]}"""
    ap = safe_path(path, must_exist=True)
    if not os.path.isdir(ap):
        raise ValueError("不是目录：%s" % ap)
    entries = []
    for name in sorted(os.listdir(ap)):
        full = os.path.join(ap, name)
        if os.path.isdir(full):
            if name.lower() in SKIP_DIRS_LOWER or name.startswith("."):
                continue
            entries.append({"name": name, "is_dir": True, "path": full.replace("\\", "/"),
                            "size": 0, "mtime": os.path.getmtime(full), "ext": ""})
        else:
            if SKIP_FILES_RE.search(name):
                continue
            if only_docs and os.path.splitext(name)[1].lower() not in DOC_EXT:
                continue
            try:
                st = os.stat(full)
            except OSError:
                continue
            entries.append({"name": name, "is_dir": False, "path": full.replace("\\", "/"),
                            "size": st.st_size, "mtime": st.st_mtime,
                            "ext": os.path.splitext(name)[1].lower()})
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return {"path": ap.replace("\\", "/"), "entries": entries}


def list_computer():
    """「此电脑」层级：列出本机所有可用盘符。

    返回结构与 list_dirs 一致，dirs 里每项是一个盘符根目录。
    """
    drives = []
    for d in list_drives():
        letter = d.rstrip("/")
        label = ("本地磁盘 (%s)" % letter) if len(letter) == 2 else letter
        drives.append({"name": label, "path": d})
    return {
        "path": COMPUTER,
        "parent": None,
        "roots": [r.replace("\\", "/") for r in allowed_roots()],
        "dirs": drives,
        "is_computer": True,
    }


def list_dirs(path=None):
    """只列子目录（供前端「目录浏览器」导航用）。

    返回 {path, parent, roots, dirs:[{name,path}]}。
    path 为 COMPUTER('@computer') 时返回盘符层级。
    走 safe_path 护栏：越界直接抛 ValueError（盘符已在 allowed_roots 内）。
    """
    if path == COMPUTER:
        return list_computer()
    if not path:
        roots = allowed_roots()
        path = roots[0] if roots else config.PLATFORM_ROOT
    ap = safe_path(path, must_exist=True)
    if not os.path.isdir(ap):
        raise ValueError("不是目录：%s" % ap)
    dirs = []
    err = None
    try:
        names = sorted(os.listdir(ap))
    except PermissionError:
        names = []
        err = "没有权限访问该目录"
    for name in names:
        full = os.path.join(ap, name)
        try:
            if not os.path.isdir(full):
                continue
        except Exception:
            continue
        if name.lower() in SKIP_DIRS_LOWER or name.startswith("."):
            continue
        dirs.append({"name": name, "path": full.replace("\\", "/")})
    dirs.sort(key=lambda d: d["name"].lower())
    # 盘符根目录（如 C:\）的上一级 = 「此电脑」；os.path.dirname 对盘符根返回自身，需特判
    _drive, tail = os.path.splitdrive(ap)
    if tail in ("\\", "/", ""):
        parent_disp = COMPUTER
    else:
        parent_disp = os.path.dirname(ap).replace("\\", "/")
        if not is_allowed(parent_disp):
            parent_disp = None
    out = {
        "path": ap.replace("\\", "/"),
        "parent": parent_disp,
        "roots": [r.replace("\\", "/") for r in allowed_roots()],
        "dirs": dirs,
    }
    if err:
        out["error"] = err
    return out


def stat_info(path):
    ap = safe_path(path, must_exist=True)
    st = os.stat(ap)
    return {"name": os.path.basename(ap), "path": ap.replace("\\", "/"),
            "size": st.st_size, "mtime": st.st_mtime,
            "is_dir": os.path.isdir(ap),
            "ext": os.path.splitext(ap)[1].lower()}


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def open_in_explorer(path):
    """用系统默认方式打开（文件夹→资源管理器，文件→关联程序）。"""
    ap = safe_path(path, must_exist=True)
    try:
        if os.name == "nt":
            if os.path.isdir(ap):
                os.startfile(ap)  # noqa: S606 - 用户主动触发的本地打开
            else:
                os.startfile(ap)  # noqa: S606
        else:
            import subprocess
            cmd = ["open", ap] if sys.platform == "darwin" else ["xdg-open", ap]
            subprocess.Popen(cmd)
        return True
    except Exception as e:
        raise RuntimeError("打开失败：%s" % e)


def select_dir(initial=None, title="选择目录"):
    """弹出系统文件夹选择对话框，返回选中路径；取消/不可用返回 None。

    本地平台专用（仅监听 127.0.0.1）。用独立子进程跑 app/worker/folder_dialog.py ——
    该脚本通过 ctypes 调现代 IFileOpenDialog（文件资源管理器风格的文件夹选择框，
    带左侧导航栏/地址栏/网络位置）。子进程有自己的 STA 主线程与消息泵，且继承
    用户的桌面会话，能稳定弹出原生选择框；不依赖 tkinter（标准 Python 自带 ctypes）。
    """
    if sys.platform != "win32":
        return None
    init = os.path.abspath(os.path.expanduser(initial)) if initial else ""
    if init and not os.path.isdir(init):
        init = os.path.dirname(init) or ""
    worker = os.path.join(config.PLATFORM_ROOT, "app", "worker", "folder_dialog.py")
    if not os.path.isfile(worker):
        return None
    try:
        cmd = [sys.executable, worker, "--title", title]
        if init:
            cmd += ["--initial", init]
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
        # 把子进程诊断信息落盘，便于排查「现代弹窗为何没出来」
        try:
            logdir = os.path.join(config.PLATFORM_ROOT, "runtime")
            os.makedirs(logdir, exist_ok=True)
            with open(os.path.join(logdir, "folder_dialog_debug.log"), "ab") as fh:
                fh.write(("\n=== %s initial=%r title=%r rc=%s ===\n" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"), init, title,
                    proc.returncode)).encode("utf-8", "replace"))
                if proc.stderr:
                    fh.write(proc.stderr.encode("utf-8", "replace"))
                fh.write(b"\n")
        except Exception:
            pass
        out = (proc.stdout or "").strip()
        if not out:
            return None
        return os.path.abspath(out)
    except Exception:
        return None


def download_name(path):
    return quote(os.path.basename(path))
