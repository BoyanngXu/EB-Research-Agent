# -*- coding: utf-8 -*-
"""打开聊天记录窗口 -> 点「日期」筛选器 -> 看日期选择器长什么样。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP = 0x0001 | 0x0002 | 0x0010


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def tops(pid):
    out = []

    def cb(hh, _):
        if pid_of(hh) == pid:
            cls = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(hh, cls, 256)
            rc = wintypes.RECT()
            u32.GetWindowRect(hh, ctypes.byref(rc))
            if u32.IsWindowVisible(hh):
                out.append({"h": hh, "cls": cls.value,
                            "rect": (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def win_text(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def esc():
    u32.keybd_event(0x1B, 0, 0, 0); u32.keybd_event(0x1B, 0, 2, 0)


def click_screen(sx, sy, hold=0.12):
    u32.SetCursorPos(sx, sy); time.sleep(0.3)
    u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(hold)
    u32.mouse_event(0x0004, 0, 0, 0, 0)


h = R.find_wechat_window()
pid = pid_of(h)
u32.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP)
R.activate_window(h)
l, t, w, hh = C._safe_rect(h)
print("主窗 rect =", (l, t, w, hh), "| 前台 =", R.foreground_title())

def find_rec(pid):
    for x in tops(pid):
        if "聊天记录" in win_text(x["h"]):
            return x
    return None


# ---- 打开/定位聊天记录窗口 ----
esc(); time.sleep(0.4)
rec = find_rec(pid)
if rec is None:
    click_screen(l + 1303, t + 84)
    time.sleep(1.8)
    rec = find_rec(pid)
if rec is None:
    for x in tops(pid):
        print("  可见窗口 %s cls=%s rect=%s title=%r"
              % (x["h"], x["cls"], x["rect"], win_text(x["h"])))
    sys.exit("没找到聊天记录窗口")
print("聊天记录窗口 =", rec, "| title =", repr(win_text(rec["h"])))

rl, rt, rw, rh = rec["rect"]
img = R.capture_window(rec["h"], restore=False, size=(rw, rh))
img.save(os.path.join(OUT, "rec_win.png"))
items = R.ocr_items(img)
print("--- 聊天记录窗口 OCR ---")
for it in items[:30]:
    print("   %-28s x=%4d..%4d y=%3d..%3d" % (
        it["text"][:28], it["x"], it["x"] + it["w"], it["y"], it["y"] + it["h"]))

# ---- 点「日期」 ----
tgt = [it for it in items if it["text"].strip() == "日期"]
if not tgt:
    sys.exit("没找到「日期」按钮")
d = tgt[0]
sx = rl + d["x"] + d["w"] // 2
sy = rt + d["y"] + d["h"] // 2
print("点「日期」窗口内(%d,%d) -> 屏幕(%d,%d)" % (d["x"], d["y"], sx, sy))
click_screen(sx, sy)
time.sleep(1.5)

img2 = R.capture_window(rec["h"], restore=False, size=(rw, rh))
img2.save(os.path.join(OUT, "rec_date.png"))
items2 = R.ocr_items(img2)
print("--- 点日期后 OCR (%d 块) ---" % len(items2))
for it in items2[:45]:
    print("   %-28s x=%4d..%4d y=%3d..%3d" % (
        it["text"][:28], it["x"], it["x"] + it["w"], it["y"], it["y"] + it["h"]))

u32.SetWindowPos(h, HWND_NOTOPMOST, 0, 0, 0, 0, SWP)
print("done")
