# -*- coding: utf-8 -*-
"""点阅读器的 ⋯ 菜单，找「复制链接」。"""
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
SW, SH = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)


def wtitle(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def cls_of(hwnd):
    b = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(hwnd, b, 256)
    return b.value


def allwin(minw=60):
    out = []

    def cb(hh, _):
        if u32.IsWindowVisible(hh):
            rc = wintypes.RECT()
            u32.GetWindowRect(hh, ctypes.byref(rc))
            if rc.right - rc.left >= minw and rc.bottom - rc.top >= minw:
                out.append({"h": hh, "cls": cls_of(hh), "title": wtitle(hh),
                            "rect": (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def click_screen(sx, sy, hold=0.12):
    u32.SetCursorPos(sx, sy); time.sleep(0.3)
    u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(hold)
    u32.mouse_event(0x0004, 0, 0, 0, 0)


def on_screen(w):
    l, t, ww, hh = w["rect"]
    return l >= -5 and t >= -5 and l + ww <= SW + 5 and t + hh <= SH + 5


cands = [w for w in allwin(200) if "Chrome_WidgetWin" in w["cls"] and on_screen(w)]
pref = [w for w in cands if "微信" in w["title"]]
if not (pref or cands):
    sys.exit("没有阅读器窗口")
rd = max(pref or cands, key=lambda w: w["rect"][2] * w["rect"][3])
rl, rt, rw, rh = rd["rect"]
print("阅读器 =", rd["h"], rd["cls"], repr(rd["title"]), rd["rect"])

u32.SetWindowPos(rd["h"], HWND_TOPMOST, 0, 0, 0, 0, SWP)
time.sleep(0.4)
R.activate_window(rd["h"]); time.sleep(0.5)
print("前台 =", R.foreground_title())

base = {w["h"] for w in allwin(20)}
sx, sy = rl + 1198, rt + 26
print("点 ⋯ -> 屏幕(%d,%d)" % (sx, sy))
click_screen(sx, sy)
time.sleep(1.5)

for w in allwin(20):
    if w["h"] in base:
        continue
    print("  NEW %s %r rect=%s" % (w["cls"][:28], w["title"][:40], w["rect"]))
    if w["rect"][2] > 80:
        img = R.capture_window(w["h"], restore=False, size=(w["rect"][2], w["rect"][3]))
        img.save(os.path.join(OUT, "rdmenu_%s.png" % w["h"]))
        for it in R.ocr_items(img)[:20]:
            print("     %-26s x=%4d..%4d y=%3d..%3d" % (
                it["text"][:26], it["x"], it["x"] + it["w"], it["y"], it["y"] + it["h"]))

R.capture_window(rd["h"], restore=False, size=(rw, rh)).save(os.path.join(OUT, "rd_after_menu.png"))
u32.SetWindowPos(rd["h"], HWND_NOTOPMOST, 0, 0, 0, 0, SWP)
print("done")
