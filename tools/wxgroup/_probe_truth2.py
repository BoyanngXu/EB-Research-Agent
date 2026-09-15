# -*- coding: utf-8 -*-
"""用真实图像坐标重测点击。"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32

h = R.find_wechat_window()
R.INPUT_BACKEND = "sendinput"
print("前台激活 =", R.activate_window(h), "| 前台 =", R.foreground_title())
l, t, w, hh = C._safe_rect(h)
print("窗口 rect =", (l, t, w, hh), "| 图像尺寸 =", R.capture_window(h, restore=False).size)

cx0, cy0 = R.cursor_pos()
try:
    rows = C.sessions_now(h)
    print("--- 会话行（图像坐标） ---")
    for r in rows:
        sx = l + r["x"] + 40
        sy = t + r["y"] + r["h"] // 2
        print("   %-30s x=%4d y=%4d h=%3d  -> 屏幕(%4d,%4d)"
              % (r["name"][:30], r["x"], r["y"], r["h"], sx, sy))

    # --- 测1：左导航"通讯录"图标（真实图像坐标约 x=47,y=235） ---
    for tag, (ix, iy) in [("nav_contacts", (47, 235))]:
        img0 = R.capture_window(h, restore=False)
        R.click_at(l + ix, t + iy)
        time.sleep(1.3)
        img1 = R.capture_window(h, restore=False)
        img1.save(os.path.join(OUT, tag + "_after.png"))
        print("[%s] 点(%d,%d) 截图变化 = %s" % (tag, ix, iy, img0.tobytes() != img1.tobytes()))

    # 切回聊天
    R.click_at(l + 47, t + 174)
    time.sleep(1.0)

    # --- 测2：点 efootball 会话行 ---
    row = R.find_session(C.sessions_now(h), "efootball")
    if row:
        sx, sy = l + row["x"] + 40, t + row["y"] + row["h"] // 2
        before = C.chat_title(h)
        R.click_at(sx, sy)
        time.sleep(1.5)
        after = C.chat_title(h)
        print("[会话] 点(%d,%d) %r -> %r" % (sx, sy, before, after))
    else:
        print("[会话] 没找到 efootball 行")
finally:
    u32.SetCursorPos(cx0, cy0)
print("done")
