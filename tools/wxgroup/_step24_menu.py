# -*- coding: utf-8 -*-
"""逐条右键，dump 菜单项，判断哪些支持「用默认浏览器打开」。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 8
KEYUP = 0x0002


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


def rclick(sx, sy):
    u32.SetCursorPos(sx, sy); time.sleep(0.3)
    u32.mouse_event(0x0008, 0, 0, 0, 0); time.sleep(0.12)
    u32.mouse_event(0x0010, 0, 0, 0, 0)


def esc():
    u32.keybd_event(0x1B, 0, 0, 0); u32.keybd_event(0x1B, 0, KEYUP, 0)


h = R.find_wechat_window()
pid = pid_of(h)
rec = [x for x in wins(pid) if "聊天记录" in x["title"]]
if not rec:
    sys.exit("没有聊天记录窗口")
rec = rec[0]
rl, rt, rw, rh = rec["rect"]
R.activate_window(rec["h"]); time.sleep(0.5)
R.scroll_at(rl + rw // 2, rt + rh // 2, 300, hwnd=rec["h"])
time.sleep(1.2)

base = {x["h"] for x in wins(pid, 20)}
items = R.ocr_items(R.capture_window(rec["h"], restore=False, size=(rw, rh)))
labels = [x for x in items if 750 <= x["x"] <= 845 and x["y"] > 215
          and ("昨天" in x["text"] or ":" in x["text"])]
print("本屏条目 %d" % len(labels))
for i, e in enumerate(labels[:N]):
    band = [x for x in items if 115 <= x["x"] <= 750 and e["y"] - 26 <= x["y"] <= e["y"] + 10]
    title = max(band, key=lambda z: z["w"])["text"].strip() if band else "?"
    sx, sy = rl + 300, rt + e["y"] - 6
    rclick(sx, sy)
    time.sleep(1.2)
    menu = [w for w in wins(pid, 20) if w["h"] not in base and w["rect"][2] < 600]
    txts = []
    for m in menu:
        its = R.ocr_items(R.capture_window(m["h"], restore=False,
                                           size=(m["rect"][2], m["rect"][3])))
        txts = [x["text"].strip() for x in its]
    print("%2d. %-42s -> %s" % (i + 1, title[:42], txts))
    esc(); time.sleep(0.6)
print("done")
