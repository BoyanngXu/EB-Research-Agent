# -*- coding: utf-8 -*-
import sys, os, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

def pid_of(hwnd):
    p = wintypes.DWORD(); u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p)); return p.value
def wtitle(hwnd):
    n = u32.GetWindowTextLengthW(hwnd); b = ctypes.create_unicode_buffer(n+1)
    u32.GetWindowTextW(hwnd, b, n+1); return b.value
def cls_of(hwnd):
    b = ctypes.create_unicode_buffer(256); u32.GetClassNameW(hwnd, b, 256); return b.value

h = R.find_wechat_window()
print("微信主窗口:", h)
if h:
    print("  主窗口标题:", wtitle(h), "cls:", cls_of(h))
    print("  主窗口rect:", R.window_rect(h))
    pid = pid_of(h)
    print("  微信PID:", pid)
    recs = []
    chromes = []
    def cb(hw, _):
        if pid_of(hw) == pid and u32.IsWindowVisible(hw):
            rc = wintypes.RECT(); u32.GetWindowRect(hw, ctypes.byref(rc))
            t = wtitle(hw); c = cls_of(hw)
            if "聊天记录" in t: recs.append((hw, t, (rc.left,rc.top,rc.right-rc.left,rc.bottom-rc.top)))
            if "Chrome_WidgetWin" in c: chromes.append((hw, t, (rc.left,rc.top,rc.right-rc.left,rc.bottom-rc.top)))
        return True
    u32.EnumWindows(WNDENUMPROC(cb), 0)
    print("聊天记录窗口:", len(recs))
    for r in recs: print("  ", r)
    print("Chrome窗口:", len(chromes))
    for r in chromes: print("  ", r)
