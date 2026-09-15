# -*- coding: utf-8 -*-
"""点 ⋯ / ∨ 后用全屏截图看菜单（菜单若是独立窗口，全屏能抓到）。"""
import sys, os, time, ctypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C
from PIL import ImageGrab

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
R.INPUT_BACKEND = "sendinput"
KEYUP = 0x0002


def esc():
    u32.keybd_event(0x1B, 0, 0, 0); u32.keybd_event(0x1B, 0, KEYUP, 0)


h = R.find_wechat_window()
R.activate_window(h)
C.open_group(h, "李老八", verbose=False)
l, t, w, hh = C._safe_rect(h)
print("前台 =", R.foreground_title(), "rect =", (l, t, w, hh))

for tag, (ix, iy) in [("more_1303_84", (1303, 84)),
                      ("chev_1202_84", (1202, 84)),
                      ("info_1174_84", (1174, 84))]:
    R.capture_window(h, restore=False).save(os.path.join(OUT, "%s_before.png" % tag))
    sx, sy = l + ix, t + iy
    u32.SetCursorPos(sx, sy)
    time.sleep(0.35)
    u32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.12)
    u32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(1.0)
    g = ImageGrab.grab()
    g.save(os.path.join(OUT, "%s_screen.png" % tag))
    # 只保留微信窗口附近区域，便于查看
    box = (max(0, l - 60), max(0, t - 20), min(g.size[0], l + w + 60), min(g.size[1], t + 500))
    g.crop(box).save(os.path.join(OUT, "%s_crop.png" % tag))
    print("[%s] 屏幕 %s -> 存 %s_crop.png" % (tag, g.size, tag))
    esc()
    time.sleep(0.7)
print("done")
