# -*- coding: utf-8 -*-
"""用暗像素列分布精确定位标题栏图标。用法: python _probe_icons.py"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C
import numpy as np

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
os.makedirs(OUT, exist_ok=True)

h = R.find_wechat_window()
C.open_group(h, "李老八", verbose=False)

was_min = R.quiet_show(h)
try:
    time.sleep(0.3)
    l, t, w, hh = C._safe_rect(h)
    # 先把可能开着的侧栏关掉：点聊天正文空白处
    R.click_at(l + int(w * 0.55), t + int(hh * 0.62), hwnd=h)
    time.sleep(0.8)

    img = R.capture_silent(h, settle=1.0)
    iw, ih = img.size
    a = np.asarray(img.convert("L")).astype(np.int16)

    # 标题栏条带
    y1, y2 = 48, 118
    strip = a[y1:y2, :]
    dark = (strip < 150).sum(axis=0)      # 每列暗像素数
    thresh = 2
    cols = dark > thresh

    # 聚簇
    clusters = []
    s = None
    for x in range(iw):
        if cols[x] and s is None:
            s = x
        elif not cols[x] and s is not None:
            if x - s >= 4:
                seg = dark[s:x]
                cx = s + int(np.argmax(seg))
                clusters.append((s, x, cx, int(seg.max())))
            s = None
    if s is not None:
        clusters.append((s, iw, s + int(np.argmax(dark[s:])), int(dark[s:].max())))

    print("标题栏条带 y=%d..%d  宽度=%d" % (y1, y2, iw))
    print("--- 暗像素簇 (start,end,峰值列,峰值高度) ---")
    for c in clusters:
        if c[3] >= 3:
            print("  x=%4d..%4d  峰=%4d  高=%d" % c)

    # 只保留右侧区域，放大导出
    crop = img.crop((int(iw * 0.78), y1 - 14, iw, y2 + 14))
    crop.resize((crop.size[0] * 4, crop.size[1] * 4)).save(
        os.path.join(OUT, "hdr_icons_x4.png"))
    print("已存 hdr_icons_x4.png  crop=", (int(iw * 0.78), y1 - 14, iw, y2 + 14))
finally:
    R.quiet_restore(h, was_min)
print("done")
