# -*- coding: utf-8 -*-
"""用日期筛选锁定 9/14，然后逐屏截图存档（供后续解析）。"""
import sys, os, time, json, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
SHOT = os.path.join(OUT, "yday")
os.makedirs(SHOT, exist_ok=True)
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"

MAXPAGE = int(sys.argv[1]) if len(sys.argv) > 1 else 25
NOTCH = int(sys.argv[2]) if len(sys.argv) > 2 else 10


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
            w_, h_ = rc.right - rc.left, rc.bottom - rc.top
            if w_ >= minw and h_ >= minw:
                out.append({"h": hh, "title": wtitle(hh),
                            "rect": (rc.left, rc.top, w_, h_)})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def click_screen(sx, sy, hold=0.12):
    u32.SetCursorPos(sx, sy); time.sleep(0.3)
    u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(hold)
    u32.mouse_event(0x0004, 0, 0, 0, 0)


def click_text(win, label, nth=0):
    l, t, w, h = win["rect"]
    img = R.capture_window(win["h"], restore=False, size=(w, h))
    its = [it for it in R.ocr_items(img) if it["text"].strip() == label]
    if len(its) <= nth:
        return False
    it = its[nth]
    click_screen(l + it["x"] + it["w"] // 2, t + it["y"] + it["h"] // 2)
    return True


DAY = int(sys.argv[3]) if len(sys.argv) > 3 else 14

h = R.find_wechat_window()
pid = pid_of(h)
rec = [w for w in wins(pid) if "聊天记录" in w["title"]]
if not rec:
    sys.exit("没有聊天记录窗口")
rec = rec[0]
rl, rt, rw, rh = rec["rect"]
print("记录窗 =", rec["h"], rec["rect"])
R.activate_window(rec["h"]); time.sleep(0.5)

# 1) 点「日期」
if not click_text(rec, "日期"):
    sys.exit("点不到日期")
time.sleep(1.5)
picker = [w for w in wins(pid, 200) if 400 < w["rect"][2] < 600 and 500 < w["rect"][3] < 750]
if not picker:
    sys.exit("日期选择器没出现")
picker = picker[0]
print("选择器 =", picker["h"], picker["rect"])
R.activate_window(picker["h"]); time.sleep(0.4)

# 2) 选日
if not click_text(picker, str(DAY)):
    sys.exit("选择器里没有 %d" % DAY)
time.sleep(0.7)
if not click_text(picker, "确定"):
    sys.exit("点不到确定")
time.sleep(1.8)

# 3) 回到记录窗，从头逐屏截
R.activate_window(rec["h"]); time.sleep(0.5)
R.scroll_at(rl + rw // 2, rt + rh // 2, 300, hwnd=rec["h"])
time.sleep(1.2)

meta = []
for p in range(MAXPAGE):
    img = R.capture_window(rec["h"], restore=False, size=(rw, rh))
    fn = os.path.join(SHOT, "p%02d.png" % p)
    img.save(fn)
    items = R.ocr_items(img)
    txt = " | ".join(it["text"].strip() for it in items[:6])
    meta.append({"page": p, "file": fn, "head": txt,
                 "n": len(items)})
    print("第%02d屏: %d 块 | %s" % (p, len(items), txt[:110]))
    R.scroll_at(rl + rw // 2, rt + rh // 2, -NOTCH, hwnd=rec["h"])
    time.sleep(1.0)

with open(os.path.join(SHOT, "meta.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=1)
print("done ->", SHOT)
