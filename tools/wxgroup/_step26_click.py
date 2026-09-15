# -*- coding: utf-8 -*-
"""把「聊天记录」窗口临时置顶，再点开一条公众号文章，看打开的是什么窗口。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP = 0x0001 | 0x0002 | 0x0010
TARGET = sys.argv[1] if len(sys.argv) > 1 else "企业年金"


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def wtitle(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def allwin(minw=60):
    out = []

    def cb(hh, _):
        if u32.IsWindowVisible(hh):
            rc = wintypes.RECT()
            u32.GetWindowRect(hh, ctypes.byref(rc))
            if rc.right - rc.left >= minw and rc.bottom - rc.top >= minw:
                b = ctypes.create_unicode_buffer(256)
                u32.GetClassNameW(hh, b, 256)
                out.append({"h": hh, "pid": pid_of(hh), "cls": b.value,
                            "title": wtitle(hh),
                            "rect": (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def click_screen(sx, sy, hold=0.12):
    u32.SetCursorPos(sx, sy); time.sleep(0.3)
    u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(hold)
    u32.mouse_event(0x0004, 0, 0, 0, 0)


h = R.find_wechat_window()
pid = pid_of(h)
rec = [x for x in allwin() if "聊天记录" in x["title"]]
if not rec:
    sys.exit("没有聊天记录窗口")
rec = rec[0]
rl, rt, rw, rh = rec["rect"]
print("记录窗 =", rec["h"], rec["rect"])

u32.SetWindowPos(rec["h"], HWND_TOPMOST, 0, 0, 0, 0, SWP)
time.sleep(0.4)
R.activate_window(rec["h"]); time.sleep(0.5)
print("前台 =", R.foreground_title())

items = R.ocr_items(R.capture_window(rec["h"], restore=False, size=(rw, rh)))
hit = [x for x in items if TARGET in x["text"]]
if not hit:
    R.scroll_at(rl + rw // 2, rt + rh // 2, 300, hwnd=rec["h"])
    time.sleep(1.2)
    items = R.ocr_items(R.capture_window(rec["h"], restore=False, size=(rw, rh)))
    hit = [x for x in items if TARGET in x["text"]]
if not hit:
    print("本屏条目:", [x["text"][:26] for x in items if 750 <= x["x"] <= 845 and x["y"] > 215])
    sys.exit("找不到目标")
t0 = hit[0]
base = {x["h"] for x in allwin(20)}
print("点击 %r" % t0["text"][:40])
click_screen(rl + t0["x"] + 60, rt + t0["y"] + 8)
time.sleep(3.5)
print("前台 =", R.foreground_title())
for w in allwin(20):
    if w["h"] in base:
        continue
    print("  NEW pid=%d %s %r rect=%s" % (w["pid"], w["cls"][:28], w["title"][:44], w["rect"]))
    if w["rect"][2] > 250:
        img = R.capture_window(w["h"], restore=False, size=(w["rect"][2], w["rect"][3]))
        img.save(os.path.join(OUT, "art2_%s.png" % w["h"]))
        print("    saved art2_%s.png" % w["h"])
        for it in R.ocr_items(img)[:16]:
            print("      %-36s x=%4d y=%3d" % (it["text"][:36], it["x"], it["y"]))
u32.SetWindowPos(rec["h"], HWND_NOTOPMOST, 0, 0, 0, 0, SWP)
print("done")
