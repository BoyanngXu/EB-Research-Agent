# -*- coding: utf-8 -*-
"""采集「链接」列表里昨天的所有条目（来源 + 标题 + 时间）。"""
import sys, os, time, re, json, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"

MAXPAGE = int(sys.argv[1]) if len(sys.argv) > 1 else 40
NOTCH = int(sys.argv[2]) if len(sys.argv) > 2 else 10

SEP_RE = re.compile(r"^(?:\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日|昨天|前天|星期[一二三四五六日天])$")
CLK_RE = re.compile(r"^(?:\d{4}年\d{1,2}月\d{1,2}日|昨天|前天)?\s*\d{1,2}:\d{2}$")


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def wtitle(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def find_rec(pid):
    res = []

    def cb(hh, _):
        if pid_of(hh) == pid and u32.IsWindowVisible(hh) and "聊天记录" in wtitle(hh):
            rc = wintypes.RECT()
            u32.GetWindowRect(hh, ctypes.byref(rc))
            res.append({"h": hh, "rect": (rc.left, rc.top,
                                          rc.right - rc.left, rc.bottom - rc.top)})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return res


def parse(items, rw):
    """返回 (seps, entries)。entry = {src,title,time,y}"""
    seps = []
    rows = []
    for it in items:
        t = it["text"].strip()
        if it["y"] < 210:            # 标题栏 + 筛选器
            continue
        if SEP_RE.match(t):
            seps.append((it["y"], t))
            continue
        if t.startswith("搜索") or t.startswith("品"):
            continue
        rows.append(it)

    # 时间标签 x>700
    entries = []
    for it in rows:
        t = it["text"].strip()
        if it["x"] > 700 and CLK_RE.match(t):
            entries.append({"y": it["y"], "time": t, "src": "", "title": ""})
    # 对每个时间标签，向上找最近的 src(x<100) 和 title(x 100..700)
    for e in entries:
        band = [r for r in rows if abs(r["y"] - e["y"]) < 60 and r["x"] <= 700]
        band.sort(key=lambda r: r["y"])
        srcs = [r["text"].strip() for r in band if r["x"] < 110]
        tits = [r["text"].strip() for r in band if 110 <= r["x"] <= 700]
        e["src"] = srcs[0] if srcs else ""
        e["title"] = max(tits, key=len) if tits else ""
    return seps, entries


h = R.find_wechat_window()
pid = pid_of(h)
recs = find_rec(pid)
if not recs:
    sys.exit("没有聊天记录窗口")
rec = recs[0]
rl, rt, rw, rh = rec["rect"]
print("记录窗 =", rec["h"], rec["rect"])
R.activate_window(rec["h"])
time.sleep(0.5)

# 滚到顶部
R.scroll_at(rl + rw // 2, rt + rh // 2, 300, hwnd=rec["h"])
time.sleep(1.2)

seen = {}
order = []
stop = False
for page in range(MAXPAGE):
    img = R.capture_window(rec["h"], restore=False, size=(rw, rh))
    if page < 3:
        img.save(os.path.join(OUT, "linkcol_p%d.png" % page))
    items = R.ocr_items(img)
    seps, entries = parse(items, rw)
    sepset = [s[1] for s in seps]
    newn = 0
    for e in entries:
        key = (e["time"], e["title"][:40])
        if key not in seen:
            seen[key] = e
            order.append(key)
            newn += 1
    print("第%2d屏: 分隔=%s 条目=%d 新增=%d" % (page, sepset, len(entries), newn))
    if any(s in ("前天",) for s in sepset):
        stop = True
    if any(("月" in s and "日" in s) for s in sepset) and page > 0:
        stop = True
    if stop and newn == 0:
        break
    R.scroll_at(rl + rw // 2, rt + rh // 2, -NOTCH, hwnd=rec["h"])
    time.sleep(1.0)

data = [seen[k] for k in order]
with open(os.path.join(OUT, "links_all.json"), "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=1)
print("共 %d 条，已存 links_all.json" % len(data))
print("--- 全部 ---")
for d in data:
    print("  %-12s | %-14s | %s" % (d["time"], d["src"][:14], d["title"][:52]))
print("done")
