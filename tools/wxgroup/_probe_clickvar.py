# -*- coding: utf-8 -*-
"""点击投递方式变体矩阵：找出哪种能真正生效。"""
import sys, os, time, ctypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

u32 = R.user32
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
MK_LBUTTON = 0x0001


def lp_for(hwnd, sx, sy):
    pt = R._PT(sx, sy)
    u32.ScreenToClient(hwnd, ctypes.byref(pt))
    return ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)


def click_variant(h, sx, sy, mode):
    top = h
    child = R.deep_child(h, sx, sy)
    lp_top = lp_for(top, sx, sy)
    lp_ch = lp_for(child, sx, sy)
    if mode == "top":
        u32.SendMessageW(top, WM_LBUTTONDOWN, MK_LBUTTON, lp_top)
        time.sleep(0.06)
        u32.SendMessageW(top, WM_LBUTTONUP, 0, lp_top)
    elif mode == "child":
        u32.SendMessageW(child, WM_LBUTTONDOWN, MK_LBUTTON, lp_ch)
        time.sleep(0.06)
        u32.SendMessageW(child, WM_LBUTTONUP, 0, lp_ch)
    elif mode == "child_move":
        u32.SendMessageW(child, WM_MOUSEMOVE, 0, lp_ch)
        time.sleep(0.05)
        u32.SendMessageW(child, WM_LBUTTONDOWN, MK_LBUTTON, lp_ch)
        time.sleep(0.06)
        u32.SendMessageW(child, WM_LBUTTONUP, 0, lp_ch)
    elif mode == "top_move":
        u32.SendMessageW(top, WM_MOUSEMOVE, 0, lp_top)
        time.sleep(0.05)
        u32.SendMessageW(top, WM_LBUTTONDOWN, MK_LBUTTON, lp_top)
        time.sleep(0.06)
        u32.SendMessageW(top, WM_LBUTTONUP, 0, lp_top)
    elif mode == "post_child":
        u32.PostMessageW(child, WM_LBUTTONDOWN, MK_LBUTTON, lp_ch)
        time.sleep(0.06)
        u32.PostMessageW(child, WM_LBUTTONUP, 0, lp_ch)


h = R.find_wechat_window()
print("hwnd =", h, "| 标题 =", repr(C.chat_title(h)))

was_min = bool(u32.IsIconic(h))
try:
    u32.ShowWindow(h, 4); time.sleep(0.9)   # SW_SHOWNOACTIVATE
    print("前台 =", R.foreground_title())

    for mode in ["top", "child", "child_move", "top_move", "post_child"]:
        # 确保回到李老八
        row0 = R.find_session(C.sessions_now(h), "李老八")
        if row0:
            l, t, w, hh = C._safe_rect(h)
            R.click_at(l + row0["x"] + 40, t + row0["y"] + row0["h"] // 2, hwnd=h)
            time.sleep(1.1)
        before = C.chat_title(h)

        row = R.find_session(C.sessions_now(h), "efootball")
        if not row:
            print("[%s] 找不到 efootball 行" % mode)
            continue
        l, t, w, hh = C._safe_rect(h)
        sx = l + row["x"] + 40
        sy = t + row["y"] + row["h"] // 2
        click_variant(h, sx, sy, mode)
        time.sleep(1.5)
        after = C.chat_title(h)
        print("[%-10s] before=%-26r after=%-26r %s"
              % (mode, before, after, "OK" if "efootball" in (after or "") else "no"))
finally:
    u32.ShowWindow(h, 6)
print("done")
