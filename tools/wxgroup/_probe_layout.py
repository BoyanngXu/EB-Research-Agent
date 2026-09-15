# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
rec_hwnd = 2493358
rl, rt, rw, rh = R.window_rect(rec_hwnd)
img = R.capture_window(rec_hwnd, restore=False, size=(rw,rh))
img.save(r"C:/Users/<用户名>/AppData/Local/Temp/wxdbg/rec_layout.png")
items = R.ocr_items(img)
# 顶部 0..160 全部，按 y 再 x
print("=== 顶部 0..160 (x,y,text) ===")
for it in sorted([i for i in items if i["y"]<160], key=lambda z:(z["y"],z["x"])):
    print("  y=%-4d x=%-4d w=%-4d %s" % (it["y"], it["x"], it["w"], it["text"][:40]))
print("=== 全部块数:", len(items))
# 打印整列左侧 x<300 的（可能是筛选按钮/来源）
print("=== 左侧列 x<140 的块 ===")
for it in sorted([i for i in items if i["x"]<140], key=lambda z:(z["y"],z["x"])):
    print("  y=%-4d x=%-4d %s" % (it["y"], it["x"], it["text"][:30]))
