# -*- coding: utf-8 -*-
"""在日期选择器里选 9/14 -> 确定 -> 看聊天记录窗口是否跳到昨日。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"

DAY = int(sys.argv[1]) if len(sys.argv) > 1 else 14


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def wtitle(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def visible_wins(pid):
    out = []

    def cb(hh, _):
        if pid_of(hh) == pid and u32.IsWindowVisible(hh):
            rc = wintypes.RECT()
            u32.GetWindowRect(hh, ctypes.byref(rc))
            w_, h_ = rc.right - rc.left, rc.bottom - rc.top
            if w_ > 100 and h_ > 100:
                out.append({"h": hh, "title": wtitle(hh),
                            "rect": (rc.left, rc.top, w_, h_)})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def click_screen(sx, sy, hold=0.12):
    u32.SetCursorPos(sx, sy); time.sleep(0.3)
    u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(hold)
    u32.mouse_event(0x0004, 0, 0, 0, 0)


h = R.find_wechat_window()
pid = pid_of(h)
wins = visible_wins(pid)
for w in wins:
    print("  %-10s %-38r rect=%s" % (w["h"], w["title"][:38], w["rect"]))

picker = [w for w in wins if 400 < w["rect"][2] < 600 and 500 < w["rect"][3] < 750]
rec = [w for w in wins if "聊天记录" in w["title"]]
if not picker:
    sys.exit("没有日期选择器窗口（先跑 _step10_date.py）")
if not rec:
    sys.exit("没有聊天记录窗口")
picker, rec = picker[0], rec[0]
print("选择器 =", picker["h"], picker["rect"], "| 记录窗 =", rec["h"], rec["rect"])

R.activate_window(picker["h"])
time.sleep(0.4)

pl, pt, pw, ph = picker["rect"]
img = R.capture_window(picker["h"], restore=False, size=(pw, ph))
items = R.ocr_items(img)
print("--- 选择器 OCR ---")
for it in items:
    print("   %-20s x=%4d..%4d y=%3d..%3d" % (
        it["text"][:20], it["x"], it["x"] + it["w"], it["y"], it["y"] + it["h"]))

# 点目标日
day = [it for it in items if it["text"].strip() == str(DAY)]
if not day:
    sys.exit("选择器里没有 %d" % DAY)
d = day[0]
dx, dy = pl + d["x"] + d["w"] // 2, pt + d["y"] + d["h"] // 2
print("点 %d -> 屏幕(%d,%d)" % (DAY, dx, dy))
click_screen(dx, dy)
time.sleep(0.7)
R.capture_window(picker["h"], restore=False, size=(pw, ph)).save(
    os.path.join(OUT, "picker_after_day.png"))

# 点确定
img2 = R.capture_window(picker["h"], restore=False, size=(pw, ph))
its2 = R.ocr_items(img2)
ok = [it for it in its2 if it["text"].strip() == "确定"]
if not ok:
    sys.exit("没找到确定")
o = ok[0]
ox, oy = pl + o["x"] + o["w"] // 2, pt + o["y"] + o["h"] // 2
print("点确定 -> 屏幕(%d,%d)" % (ox, oy))
click_screen(ox, oy)
time.sleep(1.8)

# 记录窗结果
print("--- 记录窗 OCR ---")
img3 = R.capture_window(rec["h"], restore=False, size=(rec["rect"][2], rec["rect"][3]))
img3.save(os.path.join(OUT, "rec_yesterday.png"))
for it in R.ocr_items(img3)[:45]:
    print("   %-32s x=%4d y=%3d" % (it["text"][:32], it["x"], it["y"]))
print("done")
