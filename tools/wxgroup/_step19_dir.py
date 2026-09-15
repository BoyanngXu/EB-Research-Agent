# -*- coding: utf-8 -*-
"""确认 9/14 视图的滚动方向，并存前几屏。"""
import sys, os, time, re, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg\yday2"
os.makedirs(OUT, exist_ok=True)
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"

CLK = re.compile(r"(?:\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日|昨天|前天|星期[一二三四五六日天])?\s*\d{1,2}:\d{2}$")


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
rec = None


def cb(hh, _):
    global rec
    if pid_of(hh) == pid and u32.IsWindowVisible(hh) and "聊天记录" in wtitle(hh):
        rc = wintypes.RECT()
        u32.GetWindowRect(hh, ctypes.byref(rc))
        rec = {"h": hh, "rect": (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)}
    return True


u32.EnumWindows(WNDENUMPROC(cb), 0)
if not rec:
    sys.exit("没有聊天记录窗口")
rl, rt, rw, rh = rec["rect"]
print("记录窗 =", rec["h"], rec["rect"])
R.activate_window(rec["h"]); time.sleep(0.5)

for i in range(4):
    img = R.capture_window(rec["h"], restore=False, size=(rw, rh))
    img.save(os.path.join(OUT, "d%02d.png" % i))
    items = R.ocr_items(img)
    stamps = [x["text"].strip() for x in items if CLK.search(x["text"].strip())]
    hdr = [x["text"].strip() for x in items if "月" in x["text"] and "日" in x["text"]]
    print("屏%d: 日期头=%s | 时间戳=%s" % (i, hdr, stamps))
    R.scroll_at(rl + rw // 2, rt + rh // 2, -10, hwnd=rec["h"])
    time.sleep(1.0)
print("done")
