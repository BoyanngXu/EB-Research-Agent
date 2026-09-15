# -*- coding: utf-8 -*-
"""点击时序/API 变体：找出微信能接受的点击方式。"""
import sys, os, time, ctypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

u32 = R.user32
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000


def norm(x, y):
    sw, sh = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
    return int(x * 65535 / max(1, sw - 1)), int(y * 65535 / max(1, sh - 1))


def click_slow(sx, sy, t_move=0.35, t_down=0.18):
    nx, ny = norm(sx, sy)
    R._send_mouse(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
    time.sleep(t_move)
    R._send_mouse(nx, ny, 0, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE)
    time.sleep(t_down)
    R._send_mouse(nx, ny, 0, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE)


def click_setpos(sx, sy, t_move=0.35, t_down=0.18):
    u32.SetCursorPos(sx, sy)
    time.sleep(t_move)
    u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(t_down)
    u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


h = R.find_wechat_window()
R.INPUT_BACKEND = "sendinput"
R.activate_window(h)
l, t, w, hh = C._safe_rect(h)
print("前台 =", R.foreground_title())

cx0, cy0 = R.cursor_pos()


def go_back_li():
    row = R.find_session(C.sessions_now(h), "李老八")
    if row:
        click_slow(l + row["x"] + 40, t + row["y"] + row["h"] // 2)
        time.sleep(1.4)


try:
    variants = [
        ("sendinput 0.35/0.18", lambda sx, sy: click_slow(sx, sy)),
        ("sendinput 0.60/0.30", lambda sx, sy: click_slow(sx, sy, 0.60, 0.30)),
        ("SetCursorPos+down/up", lambda sx, sy: click_setpos(sx, sy)),
        ("SetCursorPos 0.6/0.3", lambda sx, sy: click_setpos(sx, sy, 0.6, 0.3)),
    ]
    for name, fn in variants:
        go_back_li()
        before = C.chat_title(h)
        row = R.find_session(C.sessions_now(h), "efootball")
        if not row:
            print("[%s] 无行" % name)
            continue
        sx, sy = l + row["x"] + 40, t + row["y"] + row["h"] // 2
        fn(sx, sy)
        time.sleep(1.6)
        after = C.chat_title(h)
        print("[%-22s] %r -> %r  %s" % (name, before, after,
                                        "OK" if "efootball" in (after or "") else "no"))
finally:
    go_back_li()
    u32.SetCursorPos(cx0, cy0)
print("done")
