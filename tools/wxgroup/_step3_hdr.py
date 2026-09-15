# -*- coding: utf-8 -*-
"""逐个点标题栏 4 个图标，看各自触发什么。必须在沙箱外运行。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

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
            if u32.IsWindowVisible(hh) and (rc.right - rc.left) > 30:
                out.append((hh, cls.value[:30], rc.left, rc.top,
                            rc.right - rc.left, rc.bottom - rc.top))
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


h = R.find_wechat_window()
pid = pid_of(h)
R.activate_window(h)
C.open_group(h, "李老八", verbose=False)
l, t, w, hh = C._safe_rect(h)
print("前台 =", R.foreground_title(), "| rect =", (l, t, w, hh))
print("可见顶层窗口 =", tops(pid))

for name, ix in [("💬聊天信息", 1174), ("∨箭头", 1202), ("📞通话", 1249), ("⋯更多", 1303)]:
    for iy in [80]:
        a = R.capture_window(h, restore=False)
        nb = {x[0] for x in tops(pid)}
        R.click_at(l + ix, t + iy)
        time.sleep(1.6)
        b = R.capture_window(h, restore=False)
        b.save(os.path.join(OUT, "hdr_%d_%d.png" % (ix, iy)))
        na = tops(pid)
        neww = [x for x in na if x[0] not in nb]
        txt = " ".join(it["text"] for it in R.ocr_items(b))
        print("[%s] 点(%d,%d) 主窗变化=%s 新增窗口=%d %s"
              % (name, ix, iy, a.tobytes() != b.tobytes(), len(neww), neww))
        print("     含群公告=%s 含查找=%s 含搜索=%s" % (
            "群公告" in txt, "查找" in txt, "搜索" in txt))
        for x in neww:
            img = R.capture_window(x[0], restore=False, size=(x[4], x[5]))
            img.save(os.path.join(OUT, "hdr_win_%d.png" % ix))
            its = R.ocr_items(img)
            print("     弹窗 %s (%s) %dx%d OCR=%d" % (x[0], x[1], x[4], x[5], len(its)))
            for it in its[:20]:
                print("        %-26s x=%4d y=%3d" % (it["text"][:26], it["x"], it["y"]))
        # 关掉可能打开的侧栏/菜单
        u32.keybd_event(0x1B, 0, 0, 0); u32.keybd_event(0x1B, 0, 2, 0)
        time.sleep(0.6)
print("done")
