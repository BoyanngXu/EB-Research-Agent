# -*- coding: utf-8 -*-
"""步骤1：打开 ... 菜单，枚举弹窗并截图识别。
必须在沙箱外运行（真实鼠标）。用法: python _step1_menu.py [x] [y]"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
os.makedirs(OUT, exist_ok=True)
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

R.INPUT_BACKEND = "sendinput"          # 真实鼠标

cx = int(sys.argv[1]) if len(sys.argv) > 1 else 1300
cy = int(sys.argv[2]) if len(sys.argv) > 2 else 80


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def top_windows(pid):
    out = []

    def cb(hh, _):
        if pid_of(hh) == pid:
            cls = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(hh, cls, 256)
            rc = wintypes.RECT()
            u32.GetWindowRect(hh, ctypes.byref(rc))
            out.append({"hwnd": hh, "cls": cls.value,
                        "rect": (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top),
                        "vis": bool(u32.IsWindowVisible(hh))})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


h = R.find_wechat_window()
pid = pid_of(h)
print("hwnd =", h, "| pid =", pid)
print("激活 =", R.activate_window(h), "| 前台 =", R.foreground_title())
print("打开群 =", C.open_group(h, "李老八", verbose=True))

l, t, w, hh = C._safe_rect(h)
print("rect =", (l, t, w, hh))

before = {x["hwnd"] for x in top_windows(pid)}
print("点击窗口内 (%d,%d) -> 屏幕(%d,%d)" % (cx, cy, l + cx, t + cy))
R.click_at(l + cx, t + cy)          # hwnd=None -> SendInput
time.sleep(1.8)

after = top_windows(pid)
new = [x for x in after if x["hwnd"] not in before]
print("新增窗口 =", len(new))
for x in after:
    if x["vis"] or x["hwnd"] in before:
        pass
    if x["hwnd"] in before:
        continue
    print("   NEW %-10s %-34s vis=%-5s %s" % (x["hwnd"], x["cls"][:34], x["vis"], x["rect"]))

for i, x in enumerate(new):
    if x["rect"][2] < 20 or x["rect"][3] < 20:
        continue
    img = R.capture_window(x["hwnd"], restore=False, size=(x["rect"][2], x["rect"][3]))
    fn = os.path.join(OUT, "menu_step1_%d.png" % i)
    img.save(fn)
    items = R.ocr_items(img)
    print("--- 弹窗 %s (%s) OCR %d 块 -> %s" % (x["hwnd"], x["cls"][:30], len(items), fn))
    for it in items[:30]:
        print("     %-28s x=%4d y=%3d" % (it["text"][:28], it["x"], it["y"]))

# 主窗口也存一张
R.capture_window(h, restore=False).save(os.path.join(OUT, "menu_step1_main.png"))
print("done")
