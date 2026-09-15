# -*- coding: utf-8 -*-
"""切到链接筛选，逐屏 dump 详细结构（含坐标），用于修正解析器。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg\lk"
os.makedirs(OUT, exist_ok=True)
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"
PAGES = int(sys.argv[1]) if len(sys.argv) > 1 else 6


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def wtitle(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def click_screen(sx, sy, hold=0.12):
    u32.SetCursorPos(sx, sy); time.sleep(0.3)
    u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(hold)
    u32.mouse_event(0x0004, 0, 0, 0, 0)


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
rl, rt, rw, rh = rec["rect"]
print("记录窗 =", rec["h"], rec["rect"])
R.activate_window(rec["h"]); time.sleep(0.5)


def items_now():
    return R.ocr_items(R.capture_window(rec["h"], restore=False, size=(rw, rh)))


# 清 chip
for x in items_now():
    if 140 <= x["y"] <= 210 and ("×" in x["text"] or "x" in x["text"] or "X" in x["text"]):
        print("清 chip:", repr(x["text"]))
        click_screen(rl + x["x"] + x["w"] - 10, rt + x["y"] + x["h"] // 2)
        time.sleep(1.2)
        break

# 点链接
for x in items_now():
    if 140 <= x["y"] <= 210 and x["text"].strip() == "链接":
        print("点链接")
        click_screen(rl + x["x"] + x["w"] // 2, rt + x["y"] + x["h"] // 2)
        time.sleep(1.8)
        break

R.scroll_at(rl + rw // 2, rt + rh // 2, 300, hwnd=rec["h"])
time.sleep(1.2)

for p in range(PAGES):
    img = R.capture_window(rec["h"], restore=False, size=(rw, rh))
    img.save(os.path.join(OUT, "l%02d.png" % p))
    print("=== 第%d屏 ===" % p)
    for it in R.ocr_items(img):
        if it["y"] < 210:
            continue
        print("   %-40s x=%4d..%4d y=%4d..%4d" % (
            it["text"][:40], it["x"], it["x"] + it["w"], it["y"], it["y"] + it["h"]))
    R.scroll_at(rl + rw // 2, rt + rh // 2, -10, hwnd=rec["h"])
    time.sleep(1.0)
print("done")
