# -*- coding: utf-8 -*-
import sys, os, ctypes, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
u32 = R.user32
from ctypes import wintypes
def pid_of(hwnd):
    p = wintypes.DWORD(); u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p)); return p.value

rec_hwnd = 2493358
rl, rt, rw, rh = R.window_rect(rec_hwnd)
print("记录窗 rect:", (rl,rt,rw,rh))
img = R.capture_window(rec_hwnd, restore=False, size=(rw,rh))
img.save(r"C:/Users/<用户名>/AppData/Local/Temp/wxdbg/rec_now.png")
items = R.ocr_items(img)
print("OCR 块数:", len(items))
# 打印顶部区域(筛选chip)信息 + 时间标签分布
print("--- 顶部/筛选区 (y<120) ---")
for it in items:
    if it["y"] < 130:
        print("  y=%-4d x=%-4d %s" % (it["y"], it["x"], it["text"][:40]))
print("--- 时间标签(760<=x<=845, y>200) ---")
ts = [it for it in items if 755<=it["x"]<=850 and it["y"]>200]
for it in ts[:60]:
    print("  y=%-4d %s" % (it["y"], it["text"][:30]))
print("时间标签总数:", len(ts))
