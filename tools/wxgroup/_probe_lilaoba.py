# -*- coding: utf-8 -*-
"""抓取"李老八"群的历史消息（向上翻屏），dump 出行结构供分析。"""
import ctypes
import json
import sys
import time

sys.path.insert(0, r"C:\Users\<用户名>\Desktop\EB-Agent\tools\wxgroup")
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\Desktop\EB-Agent\tools\wxgroup\_probe_lilaoba.json"
PAGES = int(sys.argv[1]) if len(sys.argv) > 1 else 20

u = ctypes.windll.user32
hwnd = R.find_wechat_window()
print("微信窗口:", hwnd, "IsIconic =", bool(u.IsIconic(hwnd)))
R.activate_window(hwnd)
time.sleep(0.8)

print("初始标题 =", repr(C.chat_title(hwnd)))
t0 = time.time()
ok = C.open_group(hwnd, "李老八", verbose=True)
print("open_group =", ok, "| 标题 =", repr(C.chat_title(hwnd)), "(%.1fs)" % (time.time() - t0))
if not ok:
    sys.exit("未能打开目标群")

R.activate_window(hwnd)
time.sleep(0.4)
res = C.scroll_and_capture(hwnd, pages=PAGES, notches=8, settle=0.85, verbose=True)
print("累计行数 =", len(res["rows"]), "(%.1fs)" % (time.time() - t0))

# 落盘
payload = {"group": res["group"], "size": [res["w"], res["h"]], "rows": res["rows"]}
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=1)
print("已写出", OUT)

# 时间分隔一览（判断是否翻到昨日）
print("\n时间分隔行:")
for r in res["rows"]:
    if R.RE_TIME.match(r["text"]):
        print("   y=%-5d %s" % (r["y"], r["text"]))

# 滚回底部
l, t, w, h = R.window_rect(hwnd)
R.scroll_at(l + int(w * (R.SESSION_W + (1 - R.SESSION_W) / 2)), t + int(h * 0.5), -120)
time.sleep(0.8)
print("\n已滚回底部 (%.1fs)" % (time.time() - t0))
