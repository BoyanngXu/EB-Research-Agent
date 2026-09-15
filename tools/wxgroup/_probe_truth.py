# -*- coding: utf-8 -*-
"""点击地面真相：点左导航图标 + 截图对比，确认鼠标点击到底有没有生效。"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
os.makedirs(OUT, exist_ok=True)
u32 = R.user32

h = R.find_wechat_window()
R.INPUT_BACKEND = "sendinput"
print("hwnd =", h)
print("前台激活 =", R.activate_window(h), "| 前台 =", R.foreground_title())

l, t, w, hh = C._safe_rect(h)
print("窗口 rect =", (l, t, w, hh))

cx0, cy0 = R.cursor_pos()
try:
    # 目标1：左侧竖排导航的"通讯录"图标（窗口内约 x=37, y=186）
    for tag, (ix, iy) in [("nav_contacts", (37, 186)), ("nav_chat", (37, 138))]:
        img0 = R.capture_window(h, restore=False)
        img0.save(os.path.join(OUT, tag + "_before.png"))

        sx, sy = l + ix, t + iy
        print("[%s] 点击屏幕 (%d, %d) ..." % (tag, sx, sy))
        R.click_at(sx, sy)
        time.sleep(1.3)
        print("   点击后真实光标 =", R.cursor_pos(), "(目标 %d, %d)" % (sx, sy))

        img1 = R.capture_window(h, restore=False)
        img1.save(os.path.join(OUT, tag + "_after.png"))
        a, b = img0.tobytes(), img1.tobytes()
        print("   截图是否变化 =", a != b)
finally:
    u32.SetCursorPos(cx0, cy0)
print("done")
