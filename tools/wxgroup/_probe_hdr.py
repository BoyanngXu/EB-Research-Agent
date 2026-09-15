# -*- coding: utf-8 -*-
"""探测聊天标题栏右侧图标精确坐标。用法: python _probe_hdr.py"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
os.makedirs(OUT, exist_ok=True)

h = R.find_wechat_window()
print("hwnd =", h)
if not h:
    sys.exit("no wechat window")

l, t, w, hh = R.window_rect(h)
print("window_rect(原始) =", (l, t, w, hh))
print("restored_rect    =", R.restored_rect(h))
print("IsIconic         =", bool(R.user32.IsIconic(h)))

was_min = R.quiet_show(h)
try:
    time.sleep(0.5)
    img = R.capture_silent(h, settle=1.0)
    iw, ih = img.size
    print("image size =", (iw, ih))
    if w > 0 and hh > 0:
        print("scale x = %.4f  scale y = %.4f" % (iw / float(w), ih / float(hh)))

    # 裁标题栏右侧区域（图像坐标）
    box = (int(iw * 0.80), int(ih * 0.045), iw, int(ih * 0.115))
    crop = img.crop(box)
    print("crop box =", box, "-> size", crop.size)
    crop.resize((crop.size[0] * 3, crop.size[1] * 3)).save(
        os.path.join(OUT, "hdr_right_x3.png"))
    img.save(os.path.join(OUT, "hdr_full.png"))

    items = R.ocr_items(img)
    top = [it for it in items if it["y2"] < ih * 0.15]
    print("--- 标题栏 OCR ---")
    for it in sorted(top, key=lambda a: a["x1"]):
        print("  %-24s x=%4d..%4d y=%3d..%3d" % (
            it["text"][:24], it["x1"], it["x2"], it["y1"], it["y2"]))
finally:
    R.quiet_restore(h, was_min)
print("done")
