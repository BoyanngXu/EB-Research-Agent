# -*- coding: utf-8 -*-
"""在聊天记录窗口里右键一条链接，看弹出菜单有没有「复制链接」。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def wtitle(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def wins(pid, minw=50):
    out = []

    def cb(hh, _):
        if pid_of(hh) == pid and u32.IsWindowVisible(hh):
            rc = wintypes.RECT()
            u32.GetWindowRect(hh, ctypes.byref(rc))
            w_, h_ = rc.right - rc.left, rc.bottom - rc.top
            if w_ >= minw and h_ >= minw:
                out.append({"h": hh, "title": wtitle(hh), "cls":
                            (lambda b: (u32.GetClassNameW(hh, b, 256), b.value)[1])(
                                ctypes.create_unicode_buffer(256)),
                            "rect": (rc.left, rc.top, w_, h_)})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


h = R.find_wechat_window()
pid = pid_of(h)
recs = [w for w in wins(pid) if "聊天记录" in w["title"]]
if not recs:
    sys.exit("没有聊天记录窗口")
rec = recs[0]
rl, rt, rw, rh = rec["rect"]
print("记录窗 =", rec["h"], rec["rect"])

R.activate_window(rec["h"])
time.sleep(0.5)
base = {w["h"] for w in wins(pid, 20)}

# 右键一条链接条目
sx, sy = rl + 300, rt + 260
print("右键 (%d,%d)" % (sx, sy))
u32.SetCursorPos(sx, sy); time.sleep(0.35)
u32.mouse_event(0x0008, 0, 0, 0, 0); time.sleep(0.12)
u32.mouse_event(0x0010, 0, 0, 0, 0)
time.sleep(1.4)

new = [w for w in wins(pid, 20) if w["h"] not in base]
print("新增窗口 =", len(new))
for w in new:
    print("  %s %s %r rect=%s" % (w["h"], w["cls"][:28], w["title"][:30], w["rect"]))
    img = R.capture_window(w["h"], restore=False, size=(w["rect"][2], w["rect"][3]))
    img.save(os.path.join(OUT, "rclick_menu_%s.png" % w["h"]))
    for it in R.ocr_items(img)[:25]:
        print("     %-24s x=%4d..%4d y=%3d..%3d" % (
            it["text"][:24], it["x"], it["x"] + it["w"], it["y"], it["y"] + it["h"]))

R.capture_window(rec["h"], restore=False, size=(rw, rh)).save(
    os.path.join(OUT, "rec_after_rclick.png"))
u32.keybd_event(0x1B, 0, 0, 0); u32.keybd_event(0x1B, 0, 2, 0)
print("done")
