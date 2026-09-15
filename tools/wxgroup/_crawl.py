# -*- coding: utf-8 -*-
"""长距离爬取：向上翻屏抓群历史，边跑边落盘。

用法: python _crawl.py <pages> [out.json]
"""
import ctypes
import json
import sys
import time

sys.path.insert(0, r"C:\Users\<用户名>\Desktop\EB-Agent\tools\wxgroup")
import wx_read as R
import wx_collect as C

PAGES = int(sys.argv[1]) if len(sys.argv) > 1 else 60
OUT = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\<用户名>\Desktop\EB-Agent\tools\wxgroup\_crawl.json"

u = ctypes.windll.user32
hwnd = R.find_wechat_window()
print("IsIconic =", bool(u.IsIconic(hwnd)), "| rect =", R.window_rect(hwnd), flush=True)
print("前台 =", R.foreground_title(), flush=True)
print("后端 =", R.INPUT_BACKEND, flush=True)

t0 = time.time()
ok = C.open_group(hwnd, "李老八", verbose=True)
print("open_group =", ok, "| 标题 =", repr(C.chat_title(hwnd)), flush=True)

if not ok:
    sys.exit("未能打开目标群")

was_min = R.quiet_show(hwnd)
group, rows = "", []
stall = 0
try:
    for i in range(PAGES):
        img = R.capture_silent(hwnd)
        items = R.ocr_items(img)
        p = R.panes(*img.size)
        if not group:
            hd = [it for it in items if R.in_rect(it, p["header"])]
            if hd:
                group = R._clean_group(sorted(hd, key=lambda z: z["x"])[0]["text"])
        new_rows = R.chat_rows(items, *img.size)
        before = len(rows)
        rows = R.stitch_rows(rows, new_rows)
        gained = len(rows) - before
        if gained <= 0:
            stall += 1
        else:
            stall = 0
        if i % 5 == 0 or stall:
            print("  第 %3d 屏: 行 %2d -> 累计 %4d (新增 %3d) %.0fs%s"
                  % (i + 1, len(new_rows), len(rows), gained, time.time() - t0,
                     "  [等待重载]" if stall else ""), flush=True)
        if i % 20 == 0:
            with open(OUT, "w", encoding="utf-8") as fh:
                json.dump({"group": group, "size": [img.size[0], img.size[1]],
                           "pages_done": i + 1, "rows": rows}, fh, ensure_ascii=False)
        if stall > 5:
            print("  ! 连续 5 屏无新增，停止", flush=True)
            break
        step = 10 * (3 if stall else 1)
        wait = 1.0 * (3.0 if stall else 1.0)
        cx, cy = C._chat_scroll_point(hwnd)
        R.scroll_at(cx, cy, step, hwnd=hwnd)
        time.sleep(wait)
finally:
    # 滚回底部
    cx, cy = C._chat_scroll_point(hwnd)
    R.scroll_at(cx, cy, -600, hwnd=hwnd)
    time.sleep(0.6)
    R.quiet_restore(hwnd, was_min)

w, h = 1365, 1031
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump({"group": group, "size": [w, h], "pages_done": PAGES, "rows": rows},
              fh, ensure_ascii=False)
print("累计行数 = %d（%.0fs）已写出 %s" % (len(rows), time.time() - t0, OUT), flush=True)

print("\n时间分隔（行序，从旧到新）:", flush=True)
for i, r in enumerate(rows):
    if R.RE_TIME.match(r["text"]):
        print("   #%-5d %s" % (i, r["text"]), flush=True)
print("IsIconic =", bool(u.IsIconic(hwnd)), "| 前台 =", R.foreground_title(), flush=True)
