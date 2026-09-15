# -*- coding: utf-8 -*-
"""抓取日期选择器窗口并 OCR。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def wtitle(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


h = R.find_wechat_window()
pid = pid_of(h)
print("微信 pid =", pid, "主窗 =", h)
found = []
def cb(hh, _):
    if pid_of(hh) == pid and u32.IsWindowVisible(hh):
        rc = wintypes.RECT()
        u32.GetWindowRect(hh, ctypes.byref(rc))
        w_, h_ = rc.right - rc.left, rc.bottom - rc.top
        if w_ > 100 and h_ > 100:
            found.append((hh, wtitle(hh), rc.left, rc.top, w_, h_))
    return True


u32.EnumWindows(WNDENUMPROC(cb), 0)
for f in found:
    print("  %-10s %-38r rect=(%d,%d,%d,%d)" % (f[0], f[1][:38], f[2], f[3], f[4], f[5]))

# 日期选择器：尺寸约 492x612 的那个
pick = [f for f in found if 400 < f[4] < 600 and 500 < f[5] < 750]
if not pick:
    print("没找到疑似日期选择器")
    sys.exit(0)
p = pick[0]
print("选择器 =", p)
img = R.capture_window(p[0], restore=False, size=(p[4], p[5]))
img.save(os.path.join(OUT, "picker.png"))
print("已存 picker.png", img.size)
print("--- OCR ---")
for it in R.ocr_items(img):
    print("   %-24s x=%4d..%4d y=%3d..%3d" % (
        it["text"][:24], it["x"], it["x"] + it["w"], it["y"], it["y"] + it["h"]))
print("done")
