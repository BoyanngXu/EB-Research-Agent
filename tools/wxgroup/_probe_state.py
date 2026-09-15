# -*- coding: utf-8 -*-
"""点击对窗口状态的敏感性：A 非激活显示 / B 压到底 / C 真激活，分别测能否切群。"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

u32 = R.user32
SW_SHOWNOACTIVATE, SW_SHOW, SW_MINIMIZE = 4, 5, 6
HWND_BOTTOM = 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010


def click_session(h, keyword):
    row = R.find_session(C.sessions_now(h), keyword)
    if not row:
        return "NO-ROW", None
    l, t, w, hh = C._safe_rect(h)
    sx = l + row["x"] + 40
    sy = t + row["y"] + row["h"] // 2
    R.click_at(sx, sy, hwnd=h)
    time.sleep(1.4)
    return C.chat_title(h), (sx, sy)


h = R.find_wechat_window()
print("hwnd =", h, "| 起始标题 =", repr(C.chat_title(h)))
was_min = bool(u32.IsIconic(h))
print("初始 IsIconic =", was_min)


def report(tag, got, pt):
    ok = bool(got) and "efootball" in got
    print("  [%s] 点击%s -> 标题 = %r  => %s" % (tag, pt, got, "成功" if ok else "失败"))
    return ok


try:
    # ---------- A: 非激活显示，不压底 ----------
    print("=== A: SW_SHOWNOACTIVATE（不压底） ===")
    u32.ShowWindow(h, SW_SHOWNOACTIVATE)
    time.sleep(0.9)
    print("  前台 =", R.foreground_title())
    got, pt = click_session(h, "efootball")
    report("A", got, pt)

    # 回李老八
    u32.ShowWindow(h, SW_SHOWNOACTIVATE); time.sleep(0.4)
    row = R.find_session(C.sessions_now(h), "李老八")
    if row:
        l, t, w, hh = C._safe_rect(h)
        R.click_at(l + row["x"] + 40, t + row["y"] + row["h"] // 2, hwnd=h)
        time.sleep(1.3)
    print("  复位标题 =", repr(C.chat_title(h)))

    # ---------- B: 非激活显示 + 压到底 ----------
    print("=== B: SW_SHOWNOACTIVATE + HWND_BOTTOM ===")
    u32.SetWindowPos(h, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
    time.sleep(0.7)
    print("  前台 =", R.foreground_title())
    got, pt = click_session(h, "efootball")
    report("B", got, pt)

    # ---------- C: 真激活 ----------
    print("=== C: ShowWindow(SW_SHOW) + SetForegroundWindow ===")
    u32.ShowWindow(h, SW_SHOW)
    u32.SetForegroundWindow(h)
    time.sleep(0.9)
    print("  前台 =", R.foreground_title())
    got, pt = click_session(h, "efootball")
    report("C", got, pt)
finally:
    # 收尾：切回李老八 + 最小化
    try:
        u32.ShowWindow(h, SW_SHOWNOACTIVATE); time.sleep(0.4)
        row = R.find_session(C.sessions_now(h), "李老八")
        if row:
            l, t, w, hh = C._safe_rect(h)
            R.click_at(l + row["x"] + 40, t + row["y"] + row["h"] // 2, hwnd=h)
            time.sleep(1.2)
        print("收尾标题 =", repr(C.chat_title(h)))
    except Exception as e:
        print("收尾异常", e)
    u32.ShowWindow(h, SW_MINIMIZE)
print("done")
