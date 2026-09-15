# -*- coding: utf-8 -*-
"""沙箱外验证：真实鼠标点击能否生效。
1) 点窗口标题栏"最小化"按钮（非客户区，OS 处理）
2) 点会话行切换聊天（Qt 内容区）
"""
import sys, os, time, ctypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

u32 = R.user32
h = R.find_wechat_window()
l, t, w, hh = C._safe_rect(h)
print("hwnd =", h, "rect =", (l, t, w, hh))
print("屏幕 =", u32.GetSystemMetrics(0), "x", u32.GetSystemMetrics(1))

cx0, cy0 = R.cursor_pos()
print("原光标 =", (cx0, cy0))
try:
    # ---- 1) 非客户区：最小化按钮 ----
    u32.ShowWindow(h, 9)
    time.sleep(0.5)
    btn = (l + w - 88, t + 20)
    print("[1] 点标题栏最小化按钮 屏幕(%d,%d)" % btn)
    u32.SetCursorPos(btn[0], btn[1])
    time.sleep(0.4)
    print("    光标实际 =", R.cursor_pos())
    u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(0.12)
    u32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(1.2)
    print("    IsIconic =", bool(u32.IsIconic(h)))
    if u32.IsIconic(h):
        u32.ShowWindow(h, 9); time.sleep(0.8)

    # ---- 2) 内容区：切会话 ----
    R.activate_window(h)
    print("[2] 前台 =", R.foreground_title())
    row = R.find_session(C.sessions_now(h), "efootball")
    if row:
        pt = (l + row["x"] + 40, t + row["y"] + row["h"] // 2)
        before = C.chat_title(h)
        u32.SetCursorPos(pt[0], pt[1]); time.sleep(0.5)
        u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(0.15)
        u32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(1.6)
        print("    点 %s : %r -> %r" % (pt, before, C.chat_title(h)))
    # 切回
    row = R.find_session(C.sessions_now(h), "李老八")
    if row:
        u32.SetCursorPos(l + row["x"] + 40, t + row["y"] + row["h"] // 2)
        time.sleep(0.4)
        u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(0.15)
        u32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(1.2)
        print("    复位标题 =", repr(C.chat_title(h)))
finally:
    u32.SetCursorPos(cx0, cy0)
print("done")
