# -*- coding: utf-8 -*-
"""一键分析全流程驱动 + 实时监控（桥接模式，自动回填）。

流程：dump(clean) -> digest(restart) -> 桥接循环(按文件名匹配自动回填 9 字段)
      -> save -> build，全程每 3s 打印 状态/进度/最近日志。
"""
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8765"
# 路径从脚本位置推导：本文件位于 EB-Agent/ 下，工作区根是其上一级
_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.environ.get("EB_WORKSPACE_ROOT") or os.path.dirname(_HERE)
ANNO = os.path.join(_WS, "Anno").replace("\\", "/")
OUT = ANNO

FIELDS = ["公告日期", "上市公司", "可交换债", "证券代码", "标的股票",
          "股票代码", "换股价格", "公告性质", "内容摘要"]

# 公告的 9 字段答案（占位示例；实际使用时替换为你自己的抽取结果）
ANSWERS = {
    "示例": {
        "公告日期": "2026-01-01",
        "上市公司": "",
        "可交换债": "26示例EB",
        "证券代码": "137000.SH",
        "标的股票": "示例股份",
        "股票代码": "600000",
        "换股价格": "10.00元/股（示例占位）",
        "公告性质": "换股价格调整提示性公告",
        "内容摘要": "此处填写公告要点摘要（示例占位，非真实数据）。",
    },
}


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


def match_key(name):
    # 按公告文件名关键词映射到 ANSWERS 的 key（此处仅示例）
    if "示例" in name or "137000" in name:
        return "示例"
    return None


def print_task(t, n=4):
    st = t.get("status")
    prog = t.get("progress") or {}
    line = "  [状态] %s" % st
    if prog.get("phase"):
        line += "  [进度] %s %s/%s %s" % (prog.get("phase"), prog.get("done"),
                                          prog.get("total"), prog.get("name", "")[:40])
    print(line)
    logs = t.get("log") or []
    for r in logs[-n:]:
        lvl = r.get("level", "")
        txt = (r.get("text") or "").replace("\n", " ")
        print("    ·(%s) %s" % (lvl, txt[:140]))


def monitor_until(tid, timeout=400):
    """轮询任务到 done/failed/stopped，期间每 3s 打印进度+日志；遇到 bridge pending 自动回填。"""
    deadline = time.time() + timeout
    last = 0
    submitted = set()
    while time.time() < deadline:
        t = _get("/api/tasks/" + tid).get("task", {})
        st = t.get("status")
        if st in ("done", "failed", "stopped"):
            print("=== TASK %s ===" % st)
            print_task(t, 8)
            return t
        # 桥接回填
        pend = _get("/api/bridge/pending").get("items", [])
        for it in pend:
            bid = it.get("id")
            if bid in submitted:
                continue
            key = match_key(it.get("name", ""))
            if not key:
                print("  [桥接] 未匹配到答案：%s" % it.get("name"))
                continue
            ans = {f: ANSWERS[key].get(f, "") for f in FIELDS}
            r = _post("/api/bridge/submit", {"id": bid, "content": ans})
            submitted.add(bid)
            print("  [桥接] 提交 %s <- %s (%s)" % (bid, key, "ok" if r.get("ok") else r.get("error")))
        # 周期打印
        if time.time() - last > 3:
            print_task(t, 3)
            last = time.time()
        time.sleep(2)
    print("MONITOR_TIMEOUT")
    return None


def main():
    # 1) dump
    print("### STEP 1/4 dump(clean) ###")
    r = _post("/api/anno/dump", {"dir": ANNO, "clean": True})
    if not r.get("ok"):
        print("DUMP_FAIL", r); return
    tid = r["task"]["id"]
    print("DUMP task_id=%s" % tid)
    monitor_until(tid, 180)

    # 2) digest
    print("\n### STEP 2/4 digest(restart) ###")
    files = [f["path"] for f in (_get("/api/anno/txt?dir=" + urllib.parse.quote(ANNO)).get("files") or [])]
    print("txt files=%d" % len(files))
    rr = _post("/api/anno/digest", {"files": files, "model": "hy3", "restart": True})
    if not rr.get("ok"):
        print("DIGEST_FAIL", rr); return
    dtid = rr["task"]["id"]
    print("DIGEST task_id=%s" % dtid)

    # 3) 桥接循环 + 监控
    print("\n### STEP 3/4 bridge loop + 实时监控 ###")
    t = monitor_until(dtid, 400)
    if not t or t.get("status") != "done":
        print("DIGEST 未正常完成：", t.get("status") if t else None); return
    rows = (t.get("result") or {}).get("rows", [])
    print("ROWS=%d" % len(rows))

    # 4) save + build
    print("\n### STEP 4/4 save + build ###")
    rs = _post("/api/anno/save", {"rows": rows, "dir": ANNO})
    print("SAVE ok=%s path=%s" % (rs.get("ok"), rs.get("path", "")))
    rb = _post("/api/anno/build", {"dir": ANNO, "input": ANNO + "/input.json",
                                   "out": OUT + "/公告整理.xlsx", "strict": False})
    if not rb.get("ok"):
        print("BUILD_FAIL", rb); return
    btid = rb["task"]["id"]
    print("BUILD task_id=%s" % btid)
    monitor_until(btid, 180)
    print("\n=== 全流程结束 ===")


if __name__ == "__main__":
    import urllib.parse
    main()
