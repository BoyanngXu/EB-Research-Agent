# -*- coding: utf-8 -*-
"""前台可控性验证：激活后立刻点 💬 / ⋯，并逐步校验前台是否仍是微信。"""
import sys, os, time, ctypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C
from PIL import ImageGrab

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
R.INPUT_BACKEND = "sendinput"


def click(ix, iy, l, t, hold=0.12):
    u32.SetCursorPos(l + ix, t + iy)
    time.sleep(0.3)
    u32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(hold)
    u32.mouse_event(0x0004, 0, 0, 0, 0)


def esc():
    u32.keybd_event(0x1B, 0, 0, 0); u32.keybd_event(0x1B, 0, 2, 0)


h = R.find_wechat_window()
print("激活 =", R.activate_window(h), "| 前台 =", R.foreground_title())
l, t, w, hh = C._safe_rect(h)
print("rect =", (l, t, w, hh), "| 前台 =", R.foreground_title())


def probe(tag, ix, iy):
    print("--- %s 点(%d,%d) ---" % (tag, ix, iy))
    a = R.capture_window(h, restore=False)
    print("   点击前前台 =", R.foreground_title())
    click(ix, iy, l, t)
    time.sleep(0.9)
    print("   点击后前台 =", R.foreground_title())
    b = R.capture_window(h, restore=False)
    b.save(os.path.join(OUT, "fg_%s.png" % tag))
    txt = " ".join(it["text"] for it in R.ocr_items(b))
    print("   窗口变化=%s | 群公告=%s | 查找=%s | 免打扰=%s | 置顶=%s"
          % (a.tobytes() != b.tobytes(), "群公告" in txt, "查找" in txt,
             "免打扰" in txt, "置顶" in txt))
    esc(); time.sleep(0.6)
    return b


# 保证窗口在前面
R.activate_window(h)
probe("info1174", 1174, 84)
R.activate_window(h)
probe("more1303", 1303, 84)
R.activate_window(h)
probe("more1303_90", 1303, 90)
print("done")
