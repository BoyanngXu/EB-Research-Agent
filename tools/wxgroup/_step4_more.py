# -*- coding: utf-8 -*-
"""1) 图标精确 y 范围  2) 点 ... 后高频连续抓窗，捕捉瞬时菜单。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C
import numpy as np

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"


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
                out.append((hh, cls.value[:32], rc.left, rc.top,
                            rc.right - rc.left, rc.bottom - rc.top))
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


h = R.find_wechat_window()
pid = pid_of(h)
R.activate_window(h)
C.open_group(h, "李老八", verbose=False)
l, t, w, hh = C._safe_rect(h)
print("前台 =", R.foreground_title(), "rect =", (l, t, w, hh))

img = R.capture_window(h, restore=False)
a = np.asarray(img.convert("L")).astype(np.int16)

# --- 图标 y 范围 ---
for tag, x1, x2 in [("💬", 1161, 1187), ("∨", 1198, 1207),
                    ("📞", 1236, 1262), ("⋯", 1292, 1314)]:
    col = a[30:140, x1:x2]
    rows = (col < 200).sum(axis=1)
    ys = [y + 30 for y, v in enumerate(rows) if v >= 1]
    if ys:
        print("  %s x=%d..%d  y=%d..%d  (中心 y=%d)" % (
            tag, x1, x2, min(ys), max(ys), (min(ys) + max(ys)) // 2))
    else:
        print("  %s x=%d..%d  未检出" % (tag, x1, x2))

# --- 点 ⋯ 后高频抓窗 ---
print("=== 点 ⋯(1303, 80) 后连续抓窗 ===")
base = {x[0] for x in tops(pid)}
R.click_at(l + 1303, t + 80)
hits = {}
for i in range(20):
    time.sleep(0.1)
    cur = tops(pid)
    for x in cur:
        if x[0] not in base:
            hits[x[0]] = x
    if i == 3:
        R.capture_window(h, restore=False).save(os.path.join(OUT, "menu_after03.png"))
if hits:
    print("  捕获到新窗口:")
    for x in hits.values():
        print("    %s %s vis rect=(%d,%d,%d,%d)" % (x[0], x[1], x[2], x[3], x[4], x[5]))
        img2 = R.capture_window(x[0], restore=False, size=(x[4], x[5]))
        img2.save(os.path.join(OUT, "menu_popup.png"))
        for it in R.ocr_items(img2)[:25]:
            print("       %-26s x=%4d y=%3d" % (it["text"][:26], it["x"], it["y"]))
else:
    print("  2 秒内未出现任何新窗口")
R.capture_window(h, restore=False).save(os.path.join(OUT, "menu_after2s.png"))
print("done")
