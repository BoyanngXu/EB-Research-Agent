# -*- coding: utf-8 -*-
"""聊天记录窗口 -> 点「日期」。正确做法：激活搜索窗口本身再点其内部。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"


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


def wtitle(hwnd):
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


def find_rec(pid):
    for x in tops(pid):
        if "聊天记录" in wtitle(x["h"]):
            return x
    return None


def shot(w, tag):
    l, t, ww, hh = w["rect"]
    img = R.capture_window(w["h"], restore=False, size=(ww, hh))
    img.save(os.path.join(OUT, tag + ".png"))
    return img


def dump(img, limit=40):
    items = R.ocr_items(img)
    for it in items[:limit]:
        print("   %-30s x=%4d..%4d y=%3d..%3d" % (
            it["text"][:30], it["x"], it["x"] + it["w"], it["y"], it["y"] + it["h"]))
    return items


h = R.find_wechat_window()
pid = pid_of(h)
R.activate_window(h)
l, t, w, hh = C._safe_rect(h)
print("主窗 rect =", (l, t, w, hh), "| 前台 =", R.foreground_title())

esc(); time.sleep(0.4)
rec = find_rec(pid)
if rec is None:
    click_screen(l + 1303, t + 84)
    time.sleep(1.8)
    rec = find_rec(pid)
if rec is None:
    sys.exit("没找到聊天记录窗口")
print("搜索窗口 =", rec["h"], "| rect =", rec["rect"], "| title =", repr(wtitle(rec["h"])))

# 激活搜索窗口本身
R.activate_window(rec["h"])
time.sleep(0.5)
print("激活后前台 =", R.foreground_title())

img = shot(rec, "rec_before")
items = dump(img, 20)
rl, rt, rw, rh = rec["rect"]

tgt = [it for it in items if it["text"].strip() == "日期"]
if not tgt:
    sys.exit("没找到「日期」")
d = tgt[0]
sx, sy = rl + d["x"] + d["w"] // 2, rt + d["y"] + d["h"] // 2
print("点「日期」-> 屏幕(%d,%d)" % (sx, sy))
click_screen(sx, sy)
time.sleep(1.6)
print("点击后前台 =", R.foreground_title())

img2 = shot(rec, "rec_after_date")
print("--- 点日期后 ---")
dump(img2, 45)

# 顺便看看有没有新窗口（日期选择器可能是独立窗口）
for x in tops(pid):
    if x["h"] != h and x["h"] != rec["h"]:
        print("  其他窗口 %s rect=%s title=%r" % (x["h"], x["rect"], wtitle(x["h"])))
print("done")
