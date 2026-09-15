# -*- coding: utf-8 -*-
"""精确定位标题栏右侧图标：暗像素列分布（低阈值）。"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C
import numpy as np

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
h = R.find_wechat_window()
R.activate_window(h)
l, t, w, hh = C._safe_rect(h)
print("rect =", (l, t, w, hh))

img = R.capture_window(h, restore=False)
iw, ih = img.size
print("image =", (iw, ih))
a = np.asarray(img.convert("L")).astype(np.int16)

# 标题栏条带：群名文字 y=72..100，图标与之同排
for y1, y2 in [(50, 118), (60, 110)]:
    strip = a[y1:y2, :]
    print("=== 条带 y=%d..%d ===" % (y1, y2))
    for th in (150, 180, 205):
        dark = (strip < th).sum(axis=0)
        clusters = []
        s = None
        for x in range(1050, iw):
            if dark[x] >= 2 and s is None:
                s = x
            elif dark[x] < 2 and s is not None:
                if x - s >= 3:
                    seg = dark[s:x]
                    clusters.append((s, x, s + int(np.argmax(seg)), int(seg.max())))
                s = None
        print("  阈值<%d : %s" % (th, ["%d..%d(峰%d,高%d)" % c for c in clusters]))

# 导出一张带刻度的大图：每 20px 画一条竖线
crop = img.crop((1100, 40, iw, 130)).convert("RGB")
arr = np.asarray(crop).copy()
for x in range(1100, iw):
    if x % 20 == 0:
        arr[:, x - 1100] = [255, 0, 0]
from PIL import Image
Image.fromarray(arr).resize(((iw - 1100) * 4, 90 * 4), Image.NEAREST).save(
    os.path.join(OUT, "hdr_ruler.png"))
print("已存 hdr_ruler.png（x=1100..%d，每20px红线，起点 x=1100）" % iw)
print("done")
