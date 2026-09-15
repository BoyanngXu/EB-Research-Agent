# -*- coding: utf-8 -*-
"""投递矩阵：消息后端(顶层/子窗口) x 前台/压底；外加键盘 Ctrl+F 测试。"""
import sys, os, time, ctypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
MK_LBUTTON = 0x0001
HWND_BOTTOM = 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
VK_CONTROL, VK_F, VK_ESCAPE = 0x11, 0x46, 0x1B


def lp_for(hwnd, sx, sy):
    pt = R._PT(sx, sy)
    u32.ScreenToClient(hwnd, ctypes.byref(pt))
    return ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)


def msg_click(h, sx, sy, to_child=True):
    tgt = R.deep_child(h, sx, sy) if to_child else h
    lp = lp_for(tgt, sx, sy)
    u32.SendMessageW(tgt, WM_LBUTTONDOWN, MK_LBUTTON, lp)
    time.sleep(0.08)
    u32.SendMessageW(tgt, WM_LBUTTONUP, 0, lp)


h = R.find_wechat_window()
l, t, w, hh = C._safe_rect(h)
print("hwnd =", h, "rect =", (l, t, w, hh))
cx0, cy0 = R.cursor_pos()


def row_pt(keyword):
    row = R.find_session(C.sessions_now(h), keyword)
    if not row:
        return None
    return l + row["x"] + 40, t + row["y"] + row["h"] // 2


def back_li():
    p = row_pt("李老八")
    if p:
        msg_click(h, p[0], p[1], True)
        time.sleep(1.3)


try:
    for state in ["foreground", "bottom"]:
        if state == "foreground":
            R.activate_window(h)
        else:
            u32.SetWindowPos(h, HWND_BOTTOM, 0, 0, 0, 0,
                             SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        time.sleep(0.8)
        print("=== 状态: %s | 前台 = %s ===" % (state, R.foreground_title()))
        for to_child in [True, False]:
            back_li()
            p = row_pt("efootball")
            if not p:
                print("   [child=%s] 无行" % to_child)
                continue
            before = C.chat_title(h)
            msg_click(h, p[0], p[1], to_child)
            time.sleep(1.5)
            after = C.chat_title(h)
            print("   [%-5s] %r -> %r  %s"
                  % ("child" if to_child else "top", before, after,
                     "OK" if "efootball" in (after or "") else "no"))

    # ---- 键盘测试：前台 + Ctrl+F ----
    print("=== 键盘 Ctrl+F（前台, SendInput） ===")
    R.activate_window(h)
    time.sleep(0.5)
    img0 = R.capture_window(h, restore=False)
    VK = {"ctrl": 0x11, "f": 0x46}
    for k in ["ctrl", "f"]:
        u32.keybd_event(VK[k], 0, 0, 0)
    time.sleep(0.1)
    for k in ["f", "ctrl"]:
        u32.keybd_event(VK[k], 0, 0x0002, 0)
    time.sleep(1.4)
    img1 = R.capture_window(h, restore=False)
    img1.save(os.path.join(OUT, "ctrl_f.png"))
    print("   截图变化 =", img0.tobytes() != img1.tobytes())
    items = R.ocr_items(img1)
    txt = " ".join(i["text"] for i in items)
    print("   含'查找' =", "查找" in txt, "| 含'搜索' =", "搜索" in txt)

    # ---- 键盘测试：消息后端 WM_KEYDOWN ----
    print("=== 键盘 Ctrl+F（消息后端 SendMessage） ===")
    tgt = R.deep_child(h, l + 700, t + 500)
    img2 = R.capture_window(h, restore=False)
    u32.SendMessageW(tgt, WM_KEYDOWN, 0x11, 0)
    u32.SendMessageW(tgt, WM_KEYDOWN, 0x46, 0)
    time.sleep(0.15)
    u32.SendMessageW(tgt, WM_KEYUP, 0x46, 0)
    u32.SendMessageW(tgt, WM_KEYUP, 0x11, 0)
    time.sleep(1.4)
    img3 = R.capture_window(h, restore=False)
    img3.save(os.path.join(OUT, "ctrl_f_msg.png"))
    print("   截图变化 =", img2.tobytes() != img3.tobytes())

    u32.keybd_event(VK_ESCAPE, 0, 0, 0)
    u32.keybd_event(VK_ESCAPE, 0, 0x0002, 0)
finally:
    u32.SetCursorPos(cx0, cy0)
print("done")
