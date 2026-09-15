# -*- coding: utf-8 -*-
"""打印微信主窗口的子窗口树，并定位点 (x,y) 落在哪个子窗口。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def cls_name(h):
    b = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(h, b, 256)
    return b.value


def rect_of(h):
    rc = wintypes.RECT()
    u32.GetWindowRect(h, ctypes.byref(rc))
    return (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)


def walk(h, depth=0, maxd=4):
    lines = []
    child = u32.GetWindow(h, 5)  # GW_CHILD
    while child:
        r = rect_of(child)
        lines.append("  " * depth + "%-30s hwnd=%-10s vis=%-5s rect=%s" % (
            cls_name(child)[:30], child, bool(u32.IsWindowVisible(child)), r))
        if depth < maxd:
            lines += walk(child, depth + 1, maxd)
        child = u32.GetWindow(child, 2)  # GW_HWNDNEXT
    return lines


h = R.find_wechat_window()
print("主窗口 =", h, cls_name(h), rect_of(h))

was_min = R.quiet_show(h)
try:
    time.sleep(0.4)
    l, t, w, hh = C._safe_rect(h)
    print("--- 子窗口树 ---")
    for ln in walk(h):
        print(ln)

    # 逐点探测：从顶层往下走 ChildWindowFromPointEx
    CWP_ALL = 0x0000
    for (cx, cy) in [(1174, 80), (1300, 80), (700, 400)]:
        cur = h
        pt = wintypes.POINT(l + cx, t + cy)
        chain = []
        for _ in range(6):
            u32.ScreenToClient(cur, ctypes.byref(pt))
            c = u32.ChildWindowFromPointEx(cur, pt, CWP_ALL)
            if not c or c == cur:
                break
            chain.append("%s(%s)" % (cls_name(c)[:24], c))
            cur = c
        print("点 (%d,%d) 命中链: %s" % (cx, cy, " -> ".join(chain) or "(仅顶层)"))
        print("    最终窗口 = %s %s" % (cur, cls_name(cur)))
finally:
    R.quiet_restore(h, was_min)
print("done")
