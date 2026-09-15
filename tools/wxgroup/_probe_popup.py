# -*- coding: utf-8 -*-
"""点 ... 后枚举微信进程的顶层弹窗并逐个截图。用法: python _probe_popup.py [x] [y]"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
os.makedirs(OUT, exist_ok=True)

cx = int(sys.argv[1]) if len(sys.argv) > 1 else 1300
cy = int(sys.argv[2]) if len(sys.argv) > 2 else 80

VK_ESCAPE = 0x1B
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
u32 = R.user32

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def top_windows(pid):
    out = []

    def cb(h, _):
        if pid_of(h) == pid:
            n = u32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, buf, n + 1)
            cls = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(h, cls, 256)
            rc = wintypes.RECT()
            u32.GetWindowRect(h, ctypes.byref(rc))
            out.append({
                "hwnd": h, "cls": cls.value, "title": buf.value,
                "rect": (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top),
                "vis": bool(u32.IsWindowVisible(h)),
            })
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def esc(hwnd):
    u32.SendMessageW(hwnd, WM_KEYDOWN, VK_ESCAPE, 0)
    u32.SendMessageW(hwnd, WM_KEYUP, VK_ESCAPE, 0)


h = R.find_wechat_window()
pid = pid_of(h)
print("hwnd =", h, "| pid =", pid)
C.open_group(h, "李老八", verbose=False)

was_min = R.quiet_show(h)
try:
    time.sleep(0.3)
    l, t, w, hh = C._safe_rect(h)
    esc(h); time.sleep(0.4); esc(h); time.sleep(0.4)

    before = {x["hwnd"] for x in top_windows(pid)}
    print("--- 点击前窗口数 =", len(before))
    for x in top_windows(pid):
        if x["vis"]:
            print("   %-10s %-34s %s" % (x["hwnd"], x["cls"][:34], x["rect"]))

    print("点击窗口内 (%d,%d) -> 屏幕 (%d,%d)" % (cx, cy, l + cx, t + cy))
    R.click_at(l + cx, t + cy, hwnd=h)
    time.sleep(1.8)

    after = top_windows(pid)
    new = [x for x in after if x["hwnd"] not in before]
    print("--- 点击后窗口数 =", len(after), "| 新增 =", len(new))
    for x in after:
        mark = "NEW " if x["hwnd"] not in before else "    "
        print("  %s%-10s %-34s vis=%-5s %s" % (
            mark, x["hwnd"], x["cls"][:34], x["vis"], x["rect"]))

    for i, x in enumerate(new):
        if x["rect"][2] < 20 or x["rect"][3] < 20:
            continue
        img = R.capture_window(x["hwnd"], restore=False, size=(x["rect"][2], x["rect"][3]))
        fn = os.path.join(OUT, "popup_%d_%s.png" % (i, x["hwnd"]))
        img.save(fn)
        items = R.ocr_items(img)
        print("--- 弹窗 %s (%s) OCR %d 块 -> %s" % (x["hwnd"], x["cls"][:30], len(items), fn))
        for it in items[:30]:
            print("     %-26s x=%4d y=%3d" % (it["text"][:26], it["x"], it["y"]))
finally:
    R.quiet_restore(h, was_min)
print("done")
