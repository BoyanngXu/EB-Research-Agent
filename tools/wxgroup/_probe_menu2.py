# -*- coding: utf-8 -*-
"""探测 ... 菜单（v2：先关侧栏）。用法: python _probe_menu2.py [x] [y]"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
os.makedirs(OUT, exist_ok=True)

cx = int(sys.argv[1]) if len(sys.argv) > 1 else 1300
cy = int(sys.argv[2]) if len(sys.argv) > 2 else 80

VK_ESCAPE = 0x1B
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101


def esc(hwnd):
    R.user32.SendMessageW(hwnd, WM_KEYDOWN, VK_ESCAPE, 0)
    R.user32.SendMessageW(hwnd, WM_KEYUP, VK_ESCAPE, 0)


def panel_open(img):
    """侧栏（聊天信息）是否开着。"""
    items = R.ocr_items(img)
    txt = " ".join(it["text"] for it in items)
    return ("群公告" in txt) or ("搜索群成员" in txt)


h = R.find_wechat_window()
C.open_group(h, "李老八", verbose=False)
print("标题 =", repr(C.chat_title(h)))

was_min = R.quiet_show(h)
try:
    time.sleep(0.3)
    l, t, w, hh = C._safe_rect(h)
    print("safe_rect =", (l, t, w, hh))

    # 关侧栏
    for _ in range(2):
        esc(h)
        time.sleep(0.5)
    img0 = R.capture_silent(h, settle=0.9)
    print("关侧栏后 panel_open =", panel_open(img0))

    print("点击窗口内 (%d, %d) -> 屏幕 (%d, %d)" % (cx, cy, l + cx, t + cy))
    R.click_at(l + cx, t + cy, hwnd=h)
    time.sleep(1.6)

    img = R.capture_silent(h, settle=1.0)
    iw, ih = img.size
    img.save(os.path.join(OUT, "menu_v2.png"))
    crop = img.crop((int(iw * 0.42), 0, iw, int(ih * 0.75)))
    crop.resize((crop.size[0] * 2, crop.size[1] * 2)).save(
        os.path.join(OUT, "menu_v2_x2.png"))

    items = R.ocr_items(img)
    mid = [it for it in items if it["x"] > iw * 0.42 and it["y"] > ih * 0.04]
    print("--- 区域 OCR (%d 块) ---" % len(mid))
    for it in mid[:45]:
        print("  %-24s x=%4d..%4d y=%3d..%3d" % (
            it["text"][:24], it["x"], it["x"] + it["w"], it["y"], it["y"] + it["h"]))
finally:
    R.quiet_restore(h, was_min)
print("done")
