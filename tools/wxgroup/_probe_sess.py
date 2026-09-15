# -*- coding: utf-8 -*-
"""只测会话行点击，前后各存一张图。"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32

h = R.find_wechat_window()
R.INPUT_BACKEND = "sendinput"
R.activate_window(h)
l, t, w, hh = C._safe_rect(h)
print("前台 =", R.foreground_title(), "| rect =", (l, t, w, hh))

cx0, cy0 = R.cursor_pos()
try:
    row = R.find_session(C.sessions_now(h), "efootball")
    print("命中行 =", row)
    if row:
        sx, sy = l + row["x"] + 40, t + row["y"] + row["h"] // 2
        img0 = R.capture_window(h, restore=False)
        img0.save(os.path.join(OUT, "sess_before.png"))
        R.click_at(sx, sy)
        time.sleep(0.35)
        img_mid = R.capture_window(h, restore=False)
        img_mid.save(os.path.join(OUT, "sess_mid.png"))
        time.sleep(1.6)
        img1 = R.capture_window(h, restore=False)
        img1.save(os.path.join(OUT, "sess_after.png"))
        print("点 (%d,%d)" % (sx, sy))
        print("  0.35s 变化 =", img0.tobytes() != img_mid.tobytes())
        print("  2.0s  变化 =", img0.tobytes() != img1.tobytes())
        print("  标题 =", repr(C.chat_title(h)))
finally:
    u32.SetCursorPos(cx0, cy0)
print("done")
