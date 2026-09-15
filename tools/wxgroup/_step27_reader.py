# -*- coding: utf-8 -*-
"""定位微信内置阅读器顶栏的「⋯」按钮，点开看有没有复制链接。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import numpy as np
from PIL import Image

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP = 0x0001 | 0x0002 | 0x0010


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


# 找阅读器：Chrome_WidgetWin_* 且完全在屏幕内、标题含「微信」
SW, SH = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)


def on_screen(w):
    l, t, ww, hh = w["rect"]
    return l >= -5 and t >= -5 and l + ww <= SW + 5 and t + hh <= SH + 5


cands = [w for w in allwin(200) if "Chrome_WidgetWin" in w["cls"] and on_screen(w)]
print("候选:", [(w["h"], w["cls"], w["title"][:12], w["rect"]) for w in cands])
if not cands:
    sys.exit("没有找到阅读器窗口")
pref = [w for w in cands if "微信" in w["title"]]
rd = max(pref or cands, key=lambda w: w["rect"][2] * w["rect"][3])
rl, rt, rw, rh = rd["rect"]
print("阅读器 =", rd["h"], rd["cls"], repr(rd["title"]), rd["rect"])
u32.SetWindowPos(rd["h"], HWND_TOPMOST, 0, 0, 0, 0, SWP)
time.sleep(0.4)
R.activate_window(rd["h"]); time.sleep(0.5)
print("前台 =", R.foreground_title())

img = R.capture_window(rd["h"], restore=False, size=(rw, rh))
img.save(os.path.join(OUT, "reader_full.png"))
a = np.asarray(img.convert("L")).astype(np.int16)
strip = a[0:60, :]
for th in (150, 190):
    dark = (strip < th).sum(axis=0)
    cl, s = [], None
    for x in range(rw):
        if dark[x] >= 2 and s is None:
            s = x
        elif dark[x] < 2 and s is not None:
            if x - s >= 3:
                cl.append((s, x, s + int(np.argmax(dark[s:x])), int(dark[s:x].max())))
            s = None
    print("阈值<%d 顶栏簇:" % th)
    for c in cl:
        print("   x=%4d..%4d 峰=%4d 高=%d" % c)

crop = img.crop((int(rw * 0.6), 0, rw, 60))
crop.resize((crop.size[0] * 4, 240), Image.NEAREST).save(os.path.join(OUT, "reader_top.png"))
print("已存 reader_top.png (x 起点=%d)" % int(rw * 0.6))
u32.SetWindowPos(rd["h"], HWND_NOTOPMOST, 0, 0, 0, 0, SWP)
print("done")
