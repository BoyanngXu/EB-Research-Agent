# -*- coding: utf-8 -*-
"""把微信临时置顶(TOPMOST)以排除其他窗口干扰，再干净测 💬 / ⋯。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def tops(pid):
    out = []

    def cb(hh, _):
        if pid_of(hh) == pid:
            cls = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(hh, cls, 256)
            rc = wintypes.RECT()
            u32.GetWindowRect(hh, ctypes.byref(rc))
            if u32.IsWindowVisible(hh):
                out.append((hh, cls.value[:30], rc.left, rc.top,
                            rc.right - rc.left, rc.bottom - rc.top))
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def esc():
    u32.keybd_event(0x1B, 0, 0, 0); u32.keybd_event(0x1B, 0, 2, 0)


h = R.find_wechat_window()
pid = pid_of(h)
u32.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
time.sleep(0.4)
R.activate_window(h)
l, t, w, hh = C._safe_rect(h)
print("rect =", (l, t, w, hh), "| 前台 =", R.foreground_title())


def probe(tag, ix, iy):
    esc(); time.sleep(0.5)
    a = R.capture_window(h, restore=False)
    na = {x[0] for x in tops(pid)}
    u32.SetCursorPos(l + ix, t + iy); time.sleep(0.35)
    u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(0.12)
    u32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(1.4)
    b = R.capture_window(h, restore=False)
    b.save(os.path.join(OUT, "tm_%s.png" % tag))
    txt = " ".join(it["text"] for it in R.ocr_items(b))
    nb = tops(pid)
    new = [x for x in nb if x[0] not in na]
    print("[%s] 点(%d,%d) 前台=%s 主窗变化=%s 新窗口=%d"
          % (tag, ix, iy, R.foreground_title(), a.tobytes() != b.tobytes(), len(new)))
    print("     群公告=%s 查找=%s 免打扰=%s 置顶=%s 备注=%s"
          % ("群公告" in txt, "查找" in txt, "免打扰" in txt, "置顶" in txt, "备注" in txt))
    for x in new:
        print("     NEW %s %s rect=%s" % (x[0], x[1], x[2:]))
        im = R.capture_window(x[0], restore=False, size=(x[4], x[5]))
        im.save(os.path.join(OUT, "tm_win_%s.png" % tag))
        for it in R.ocr_items(im)[:20]:
            print("        %-24s x=%4d y=%3d" % (it["text"][:24], it["x"], it["y"]))


for tag, ix, iy in [("info_1175", 1175, 84), ("more_1303", 1303, 84)]:
    probe(tag, ix, iy)

u32.SetWindowPos(h, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
print("done")
