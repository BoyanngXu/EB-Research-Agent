# -*- coding: utf-8 -*-
"""验证 deep_child 修复后点击是否生效。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
os.makedirs(OUT, exist_ok=True)
u32 = R.user32
VK_ESCAPE = 0x1B
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def top_windows(pid):
    out = []

    def cb(h, _):
        if pid_of(h) == pid:
            cls = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(h, cls, 256)
            rc = wintypes.RECT()
            u32.GetWindowRect(h, ctypes.byref(rc))
            out.append({"hwnd": h, "cls": cls.value,
                        "rect": (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top),
                        "vis": bool(u32.IsWindowVisible(h))})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def esc(hwnd):
    u32.SendMessageW(hwnd, WM_KEYDOWN, VK_ESCAPE, 0)
    u32.SendMessageW(hwnd, WM_KEYUP, VK_ESCAPE, 0)


def txt_of(img):
    return " ".join(it["text"] for it in R.ocr_items(img))


h = R.find_wechat_window()
pid = pid_of(h)
C.open_group(h, "李老八", verbose=False)
print("子窗口 =", R.deep_child(h, 1000, 500))

was_min = R.quiet_show(h)
try:
    time.sleep(0.3)
    l, t, w, hh = C._safe_rect(h)
    for _ in range(2):
        esc(h); time.sleep(0.4)

    # ---- A: 完整点击 💬 (1174,80) ----
    print("=== A: 点击 💬 (1174,80) ===")
    tgt, lp = R.click_at(l + 1174, t + 80, hwnd=h)
    print("  目标窗口 =", tgt, " lp =", hex(lp))
    time.sleep(1.4)
    ta = txt_of(R.capture_silent(h, settle=0.9))
    print("  侧栏打开 =", ("群公告" in ta) or ("搜索群成员" in ta))

    for _ in range(2):
        esc(h); time.sleep(0.4)

    # ---- B: 只按下不抬起 ⋯ (1300,80) ----
    print("=== B: 按下不抬起 ⋯ (1300,80) ===")
    before = {x["hwnd"] for x in top_windows(pid)}
    tgt, lp = R.click_at(l + 1300, t + 80, hwnd=h, release=False)
    time.sleep(1.6)
    after = top_windows(pid)
    new = [x for x in after if x["hwnd"] not in before]
    print("  新增窗口 =", len(new))
    for x in new:
        print("   NEW %-10s %-32s vis=%-5s %s" % (
            x["hwnd"], x["cls"][:32], x["vis"], x["rect"]))
    u32.SendMessageW(tgt, 0x0202, 0, lp)
    time.sleep(0.4)

    for i, x in enumerate(new):
        if x["rect"][2] < 20 or x["rect"][3] < 20:
            continue
        img = R.capture_window(x["hwnd"], restore=False, size=(x["rect"][2], x["rect"][3]))
        fn = os.path.join(OUT, "popC_%d.png" % i)
        img.save(fn)
        items = R.ocr_items(img)
        print("  弹窗 %s OCR=%d -> %s" % (x["hwnd"], len(items), fn))
        for it in items[:25]:
            print("      %-26s x=%4d y=%3d" % (it["text"][:26], it["x"], it["y"]))
finally:
    R.quiet_restore(h, was_min)
print("done")
