# -*- coding: utf-8 -*-
"""探测微信4.0 聊天标题栏 ... 菜单。用法: python _probe_menu.py [点x] [点y]"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
os.makedirs(OUT, exist_ok=True)

cx = int(sys.argv[1]) if len(sys.argv) > 1 else 1299
cy = int(sys.argv[2]) if len(sys.argv) > 2 else 82

h = R.find_wechat_window()
print("hwnd =", h)

# 先打开群（内部自带 quiet_show / quiet_restore）
ok = C.open_group(h, "李老八", verbose=True)
print("open_group =", ok, "| 标题 =", repr(C.chat_title(h)))

was_min = R.quiet_show(h)
try:
    time.sleep(0.4)
    l, t, w, hh = C._safe_rect(h)
    print("safe_rect =", (l, t, w, hh), "| IsIconic =", bool(R.user32.IsIconic(h)))
    print("点击窗口内 (%d, %d) -> 屏幕 (%d, %d)" % (cx, cy, l + cx, t + cy))
    R.click_at(l + cx, t + cy, hwnd=h)
    time.sleep(1.6)
    img = R.capture_silent(h, settle=1.0)
    iw, ih = img.size
    print("截图 =", (iw, ih))
    img.save(os.path.join(OUT, "menu_try.png"))

    # 右侧 45% 区域放大，便于看菜单
    crop = img.crop((int(iw * 0.50), 0, iw, int(ih * 0.85)))
    crop.resize((crop.size[0] * 2, crop.size[1] * 2)).save(
        os.path.join(OUT, "menu_try_right_x2.png"))

    items = R.ocr_items(img)
    right = [it for it in items if it["x"] > iw * 0.5 and it["y"] > ih * 0.05]
    print("--- 右侧 OCR (%d 块) ---" % len(right))
    for it in right[:40]:
        print("  %-22s x=%4d..%4d y=%3d..%3d" % (
            it["text"][:22], it["x"], it["x"] + it["w"], it["y"], it["y"] + it["h"]))
finally:
    R.quiet_restore(h, was_min)
print("done")
