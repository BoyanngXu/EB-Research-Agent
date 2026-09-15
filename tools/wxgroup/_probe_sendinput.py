# -*- coding: utf-8 -*-
"""降级方案验证：真实鼠标 + 前台激活 能否点击。"""
import sys, os, time, ctypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

u32 = R.user32
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002


def force_foreground(hwnd):
    """先把微信弄到前台。返回 (成功, 用了哪招)。"""
    if R.activate_window(hwnd):
        return True, "activate_window"
    # 兜底：模拟一次 ALT 轻按，解锁 SetForegroundWindow
    try:
        u32.keybd_event(VK_MENU, 0, 0, 0)
        time.sleep(0.05)
        u32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.1)
        u32.ShowWindow(hwnd, 9)
        u32.SetForegroundWindow(hwnd)
        time.sleep(0.4)
    except Exception as e:
        print("   ALT 兜底异常:", e)
    return (u32.GetForegroundWindow() == hwnd), "alt-hack"


def click_session(h, keyword):
    row = R.find_session(C.sessions_now(h), keyword)
    if not row:
        return "NO-ROW", None
    l, t, w, hh = C._safe_rect(h)
    sx = l + row["x"] + 40
    sy = t + row["y"] + row["h"] // 2
    R.click_at(sx, sy)          # hwnd=None -> SendInput 真实鼠标
    time.sleep(1.4)
    return C.chat_title(h), (sx, sy)


h = R.find_wechat_window()
R.INPUT_BACKEND = "sendinput"
print("hwnd =", h, "| 后端 = sendinput | 标题 =", repr(C.chat_title(h)))

cx0, cy0 = R.cursor_pos()
print("原鼠标位置 =", (cx0, cy0))
try:
    ok, how = force_foreground(h)
    print("前台激活 =", ok, "| 方式 =", how, "| 当前前台 =", R.foreground_title())
    if not ok:
        print("!! 没能拿到前台，点击会落到别的窗口上")

    got, pt = click_session(h, "efootball")
    print("点击 efootball %s -> 标题 = %r" % (pt, got))
    time.sleep(0.4)
    got2, pt2 = click_session(h, "李老八")
    print("点击 李老八   %s -> 标题 = %r" % (pt2, got2))
finally:
    R.user32.SetCursorPos(cx0, cy0)
    print("鼠标已复位")
print("done")
