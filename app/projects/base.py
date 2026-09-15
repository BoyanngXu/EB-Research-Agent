# -*- coding: utf-8 -*-
"""项目模块公共底座：挑解释器、拼脚本路径、发任务、找产物。"""
import os

from ..core import config, env, tasks


def python_exe():
    """挑一个装了依赖的解释器来跑工具脚本。"""
    c = config.load()
    return env.detect_python(c["python"].get("executable"))["executable"]


def script_path(tool, rel):
    """tools/<tool>/scripts/<rel>"""
    return os.path.join(config.tools_dir(tool), "scripts", rel)


def skill_dir(tool):
    return config.tools_dir(tool)


def workspace(key):
    return config.workspace_root(key)


def run(title, project, cmd, cwd=None, on_done=None, env_extra=None, pre_run=None):
    """统一入口：起任务，返回 task。pre_run 在子进程启动前执行（如抓取前清理旧文件），
    其产出的每行日志会写入任务。"""
    return tasks.run_stream(title, cmd, cwd=cwd, project=project,
                            env=env_extra, on_done=on_done, pre_run=pre_run)


def newest_files(directory, exts, limit=20, since=None):
    """找目录下最近产出的文件（任务结束后用来告诉用户「生成了什么」）。"""
    if not directory or not os.path.isdir(directory):
        return []
    out = []
    for name in os.listdir(directory):
        full = os.path.join(directory, name)
        if not os.path.isfile(full):
            continue
        if exts and os.path.splitext(name)[1].lower() not in exts:
            continue
        st = os.stat(full)
        if since and st.st_mtime < since:
            continue
        out.append({"name": name, "path": full.replace("\\", "/"),
                    "size": st.st_size, "mtime": st.st_mtime})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out[:limit]


def subdirs(directory):
    """列出目录下的子目录（用于选日期目录）。"""
    if not directory or not os.path.isdir(directory):
        return []
    items = []
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        if os.path.isdir(full) and not name.startswith("."):
            items.append({"name": name, "path": full.replace("\\", "/")})
    return items
