# -*- coding: utf-8 -*-
"""沙箱外重测：Ctrl+F 聊天内搜索 / 左上搜索框 / 右键菜单。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"
KEYUP = 0x0002


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


def key(vk, up=False):
    u32.keybd_event(vk, 0, KEYUP if up else 0, 0)


def watch(h, pid, tag, secs=2.0):
    base = {x[0] for x in tops(pid)}
    hit = {}
    t0 = time.time()
    while time.time() - t0 < secs:
        time.sleep(0.1)
        for x in tops(pid):
            if x[0] not in base:
                hit[x[0]] = x
    if hit:
        for x in hit.values():
            print("   [%s] 新窗口 %s %s rect=(%d,%d,%d,%d)"
                  % (tag, x[0], x[1], x[2], x[3], x[4], x[5]))
            im = R.capture_window(x[0], restore=False, size=(x[4], x[5]))
            im.save(os.path.join(OUT, "win_%s_%s.png" % (tag, x[0])))
            for it in R.ocr_items(im)[:22]:
                print("       %-26s x=%4d y=%3d" % (it["text"][:26], it["x"], it["y"]))
    return hit


h = R.find_wechat_window()
pid = pid_of(h)
R.activate_window(h)
C.open_group(h, "李老八", verbose=False)
l, t, w, hh = C._safe_rect(h)
print("前台 =", R.foreground_title(), "rect =", (l, t, w, hh))

# ---------- 1) Ctrl+F ----------
print("=== 1) Ctrl+F（沙箱外） ===")
img0 = R.capture_window(h, restore=False)
key(0x11); time.sleep(0.06); key(0x46); time.sleep(0.08)
key(0x46, True); key(0x11, True)
time.sleep(1.2)
img1 = R.capture_window(h, restore=False)
img1.save(os.path.join(OUT, "ctrl_f_out.png"))
print("   主窗变化 =", img0.tobytes() != img1.tobytes())
watch(h, pid, "ctrlF", 0.5)
key(0x1B); key(0x1B, True); time.sleep(0.5)

# ---------- 2) 左上搜索框 ----------
print("=== 2) 点左上搜索框 (200, 75) ===")
img0 = R.capture_window(h, restore=False)
R.click_at(l + 200, t + 75)
time.sleep(1.3)
img1 = R.capture_window(h, restore=False)
img1.save(os.path.join(OUT, "searchbox_out.png"))
print("   主窗变化 =", img0.tobytes() != img1.tobytes())
watch(h, pid, "searchbox", 0.5)
key(0x1B); key(0x1B, True); time.sleep(0.5)

# ---------- 3) 右键聊天区消息 ----------
print("=== 3) 右键聊天区 (700, 400) ===")
img0 = R.capture_window(h, restore=False)
sx, sy = l + 700, t + 400
u32.SetCursorPos(sx, sy); time.sleep(0.3)
u32.mouse_event(0x0008, 0, 0, 0, 0); time.sleep(0.1)
u32.mouse_event(0x0010, 0, 0, 0, 0)
time.sleep(1.2)
img1 = R.capture_window(h, restore=False)
img1.save(os.path.join(OUT, "rclick_out.png"))
print("   主窗变化 =", img0.tobytes() != img1.tobytes())
watch(h, pid, "rclick", 0.5)
key(0x1B); key(0x1B, True)
print("done")
