# -*- coding: utf-8 -*-
"""一键分析全流程驱动 + 实时监控（桥接模式）。

子命令：
  dump        转储 PDF -> txt，监控到 done
  txt         列出已转储 txt（绝对路径 + 是否扫描件）
  digest      启动 AI 精读任务（桥接），返回 task_id
  wait        轮询 digest 任务 + /api/bridge/pending：
                - 出现待处理项 -> 抽取正文到 body 文件，打印 PENDING
                - 任务 done/failed -> 打印 DONE
                - 否则周期性打印 状态/进度/最近日志
  result      取 digest 任务 result.rows
  save        把 rows 存 input.json
  build       生成整理表 xlsx，监控到 done
  prompt      生成「一键分析」控制指令（演示一键分析按钮产出）
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

BASE = "http://127.0.0.1:8765"
# 路径从脚本位置推导：本文件位于 EB-Agent/ 下，工作区根是其上一级
_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.environ.get("EB_WORKSPACE_ROOT") or os.path.dirname(_HERE)
ANNO = os.path.join(_WS, "Anno").replace("\\", "/")
OUT = os.path.join(_HERE, "runtime", "output").replace("\\", "/")
BODY_FILE = "/tmp/bridge_body.txt"
META_FILE = "/tmp/bridge_meta.json"
ANS_FILE = "/tmp/bridge_answer.json"


def _req(method, path, body=None, timeout=30):
    url = BASE + path
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "ignore")[:300])}


def _post(path, body=None):
    return _req("POST", path, body)


def _get(path):
    return _req("GET", path)


def _print_task(t, n=4):
    st = t.get("status")
    prog = t.get("progress") or {}
    line = "  [状态] %s" % st
    if prog.get("phase"):
        line += "  [进度] %s %s/%s %s" % (prog.get("phase"), prog.get("done"),
                                          prog.get("total"), prog.get("name", ""))
    print(line)
    logs = t.get("log") or []
    for r in logs[-n:]:
        lvl = r.get("level", "")
        txt = (r.get("text") or "").replace("\n", " ")
        print("    ·(%s) %s" % (lvl, txt[:140]))


def cmd_dump():
    r = _post("/api/anno/dump", {"dir": ANNO, "clean": True})
    if not r.get("ok"):
        print("DUMP_FAIL", r); return
    tid = r["task"]["id"]
    print("DUMP task_id=%s" % tid)
    _monitor(tid, 180)


def cmd_txt():
    r = _get("/api/anno/txt?dir=" + urllib.parse.quote(ANNO))
    files = (r or {}).get("files", [])
    print("TXT_COUNT=%d" % len(files))
    for f in files:
        print("  %s | scanned=%s pages=%s | %s" % (f["name"], f.get("scanned"),
                                                    f.get("pages"), f["path"]))


def cmd_digest():
    # 先拿 txt 清单
    r = _get("/api/anno/txt?dir=" + urllib.parse.quote(ANNO))
    files = (r or {}).get("files", [])
    paths = [f["path"] for f in files]
    print("DIGEST files=%d" % len(paths))
    rr = _post("/api/anno/digest", {"files": paths, "model": "hy3", "restart": True})
    if not rr.get("ok"):
        print("DIGEST_FAIL", rr); return
    print("DIGEST task_id=%s" % rr["task"]["id"])


def cmd_wait():
    # task_id 从上一次 digest 后缓存
    tid = open("/tmp/digest_tid.txt").read().strip()
    deadline = time.time() + 240
    while time.time() < deadline:
        t = _get("/api/tasks/" + tid).get("task", {})
        if t.get("status") in ("done", "failed", "stopped"):
            print("DONE %s" % t.get("status"))
            _print_task(t, 6)
            return
        pend = _get("/api/bridge/pending").get("items", [])
        if pend:
            it = pend[0]
            prompt = it.get("prompt", "")
            m = re.search(r"===== 公告正文 =====\s*(.*?)\s*===== 正文结束 =====",
                          prompt, re.S)
            body = m.group(1) if m else ""
            meta = {"id": it["id"], "name": it.get("name", ""),
                    "scanned": it.get("scanned", False),
                    "images": it.get("images", [])}
            open(BODY_FILE, "w", encoding="utf-8").write(body)
            open(META_FILE, "w", encoding="utf-8").write(json.dumps(meta, ensure_ascii=False, indent=2))
            print("PENDING id=%s name=%s scanned=%s body_chars=%d" %
                  (it["id"], it.get("name"), it.get("scanned"), len(body)))
            return
        # 周期打印
        _print_task(t, 2)
        time.sleep(3)
    print("WAIT_TIMEOUT")


def cmd_result():
    tid = open("/tmp/digest_tid.txt").read().strip()
    t = _get("/api/tasks/" + tid).get("task", {})
    res = t.get("result") or {}
    rows = res.get("rows", [])
    print("ROWS=%d failed=%d skipped=%d" % (len(rows), len(res.get("failed", [])),
                                            len(res.get("skipped", []))))
    open("/tmp/digest_rows.json", "w", encoding="utf-8").write(
        json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_save():
    rows = json.load(open("/tmp/digest_rows.json", encoding="utf-8"))
    r = _post("/api/anno/save", {"rows": rows, "dir": ANNO})
    print("SAVE", r.get("ok"), r.get("path", ""))


def cmd_build():
    r = _post("/api/anno/build", {"dir": ANNO, "input": ANNO + "/input.json",
                                  "out": OUT + "/公告整理.xlsx", "strict": False})
    if not r.get("ok"):
        print("BUILD_FAIL", r); return
    tid = r["task"]["id"]
    print("BUILD task_id=%s" % tid)
    _monitor(tid, 180)


def cmd_prompt():
    r = _post("/api/anno/analyze", {"anno_dir": ANNO, "output_dir": OUT, "model": "hy3"})
    print("ANALYZE ok=%s prompt_len=%d" % (r.get("ok"), len(r.get("prompt", ""))))


def _monitor(tid, timeout):
    deadline = time.time() + timeout
    last = 0
    while time.time() < deadline:
        t = _get("/api/tasks/" + tid).get("task", {})
        st = t.get("status")
        if st in ("done", "failed", "stopped"):
            print("RESULT %s" % st)
            _print_task(t, 8)
            return
        # 每 ~3s 打印一次
        if time.time() - last > 3:
            _print_task(t, 3)
            last = time.time()
        time.sleep(2)
    print("MONITOR_TIMEOUT")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: flow_helper.py <dump|txt|digest|wait|result|save|build|prompt>"); sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "dump":
        cmd_dump()
    elif cmd == "txt":
        cmd_txt()
    elif cmd == "digest":
        cmd_digest()
        # 缓存 task_id
        # 重新取最后一个 anno 精读任务
        ts = _get("/api/tasks?limit=5").get("tasks", [])
        for t in ts:
            if t.get("project") == "anno" and "精读" in (t.get("title") or ""):
                open("/tmp/digest_tid.txt", "w").write(t["id"]); break
        print("cached tid -> /tmp/digest_tid.txt")
    elif cmd == "wait":
        cmd_wait()
    elif cmd == "result":
        cmd_result()
    elif cmd == "save":
        cmd_save()
    elif cmd == "build":
        cmd_build()
    elif cmd == "prompt":
        cmd_prompt()
