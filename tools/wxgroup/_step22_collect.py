# -*- coding: utf-8 -*-
"""完整采集：重开聊天记录窗口 -> 链接筛选 -> 滚动抽取「昨天」全部条目 -> JSON"""
import sys, os, time, json, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"
MAXPAGE = int(sys.argv[1]) if len(sys.argv) > 1 else 14


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def wtitle(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def wins(pid, minw=80):
    out = []

    def cb(hh, _):
        if pid_of(hh) == pid and u32.IsWindowVisible(hh):
            rc = wintypes.RECT()
            u32.GetWindowRect(hh, ctypes.byref(rc))
            if rc.right - rc.left >= minw and rc.bottom - rc.top >= minw:
                out.append({"h": hh, "title": wtitle(hh),
                            "rect": (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def click_screen(sx, sy, hold=0.12):
    u32.SetCursorPos(sx, sy); time.sleep(0.28)
    u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(hold)
    u32.mouse_event(0x0004, 0, 0, 0, 0)


h = R.find_wechat_window()
pid = pid_of(h)
R.activate_window(h)
time.sleep(0.4)
l, t, w, hh = C._safe_rect(h)
print("主窗 =", (l, t, w, hh))

# 重开聊天记录窗口
rec = [x for x in wins(pid) if "聊天记录" in x["title"]]
if not rec:
    print("点 ⋯ 打开聊天记录")
    click_screen(l + 1303, t + 84)
    time.sleep(2.0)
    rec = [x for x in wins(pid) if "聊天记录" in x["title"]]
if not rec:
    sys.exit("打不开聊天记录窗口")
rec = rec[0]
rl, rt, rw, rh = rec["rect"]
print("记录窗 =", rec["h"], rec["rect"])
R.activate_window(rec["h"]); time.sleep(0.6)


def ocr_rec():
    return R.ocr_items(R.capture_window(rec["h"], restore=False, size=(rw, rh)))


def filter_row(items):
    return [x for x in items if 140 <= x["y"] <= 210]


def click_label(label, exact=True):
    items = ocr_rec()
    for x in filter_row(items):
        s = x["text"].strip()
        if (s == label) if exact else (label in s):
            print("  点筛选器 %r" % s)
            click_screen(rl + x["x"] + x["w"] // 2, rt + x["y"] + x["h"] // 2)
            return True
    return False


# 清掉可能生效的 chip
items = ocr_rec()
for x in filter_row(items):
    if ("×" in x["text"] or "x" in x["text"] or "X" in x["text"]):
        print("  清 chip %r" % x["text"])
        click_screen(rl + x["x"] + x["w"] - 10, rt + x["y"] + x["h"] // 2)
        time.sleep(1.0)
        break

if not click_label("链接"):
    print("筛选行:", [x["text"] for x in filter_row(ocr_rec())])
    sys.exit("点不到链接")
time.sleep(1.8)

R.scroll_at(rl + rw // 2, rt + rh // 2, 300, hwnd=rec["h"])
time.sleep(1.2)

seen, order, stop = {}, [], False
for p in range(MAXPAGE):
    img = R.capture_window(rec["h"], restore=False, size=(rw, rh))
    img.save(os.path.join(OUT, "lk_col_%02d.png" % p))
    items = R.ocr_items(img)
    # 时间标签
    labels = [x for x in items if 750 <= x["x"] <= 840 and x["y"] > 215
              and ("昨天" in x["text"] or "前天" in x["text"] or ":" in x["text"])]
    if any("前天" in x["text"] for x in labels):
        stop = True
    n = 0
    for e in labels:
        band = [x for x in items if e["y"] - 26 <= x["y"] <= e["y"] + 52 and x["x"] < 750
                and x["y"] > 215]
        tits = [x for x in band if 115 <= x["x"] <= 750 and x["y"] <= e["y"] + 12]
        srcs = [x for x in band if x["x"] < 115]
        title = max(tits, key=lambda z: z["w"])["text"].strip() if tits else ""
        src = max(srcs, key=lambda z: z["w"])["text"].strip() if srcs else ""
        key = (e["text"].strip(), title[:36])
        if key not in seen:
            seen[key] = {"time": e["text"].strip(), "src": src, "title": title,
                         "ty": e["y"]}
            order.append(key)
            n += 1
    print("第%02d屏: 标签%d 新增%d %s" % (p, len(labels), n,
          [x["text"].strip() for x in labels]))
    if stop and n == 0:
        break
    R.scroll_at(rl + rw // 2, rt + rh // 2, -10, hwnd=rec["h"])
    time.sleep(1.0)

data = [seen[k] for k in order]
with open(os.path.join(OUT, "yday_links.json"), "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=1)
y = [d for d in data if "昨天" in d["time"]]
print("总 %d 条，其中「昨天」%d 条" % (len(data), len(y)))
for d in y:
    print("  %-8s | %-16s | %s" % (d["time"], d["src"][:16], d["title"][:50]))
print("done")
