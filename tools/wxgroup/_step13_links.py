# -*- coding: utf-8 -*-
"""在聊天记录窗口点「链接」筛选器，看是否与日期叠加。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def wtitle(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def find_rec(pid):
    res = []

    def cb(hh, _):
        if pid_of(hh) == pid and u32.IsWindowVisible(hh) and "聊天记录" in wtitle(hh):
            rc = wintypes.RECT()
            u32.GetWindowRect(hh, ctypes.byref(rc))
            res.append({"h": hh, "rect": (rc.left, rc.top,
                                          rc.right - rc.left, rc.bottom - rc.top)})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return res


def click_screen(sx, sy, hold=0.12):
    u32.SetCursorPos(sx, sy); time.sleep(0.3)
    u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(hold)
    u32.mouse_event(0x0004, 0, 0, 0, 0)


h = R.find_wechat_window()
pid = pid_of(h)
recs = find_rec(pid)
if not recs:
    sys.exit("没有聊天记录窗口")
rec = recs[0]
rl, rt, rw, rh = rec["rect"]
print("记录窗 =", rec["h"], rec["rect"])

R.activate_window(rec["h"])
time.sleep(0.5)
img = R.capture_window(rec["h"], restore=False, size=(rw, rh))
img.save(os.path.join(OUT, "rec_before_link.png"))
items = R.ocr_items(img)

for label in ["链接", "图片与视频"]:
    hit = [it for it in items if it["text"].strip() == label]
    if not hit:
        print("找不到「%s」" % label)
        continue
    it = hit[0]
    sx, sy = rl + it["x"] + it["w"] // 2, rt + it["y"] + it["h"] // 2
    print("点「%s」-> 屏幕(%d,%d)" % (label, sx, sy))
    click_screen(sx, sy)
    time.sleep(1.8)
    img2 = R.capture_window(rec["h"], restore=False, size=(rw, rh))
    img2.save(os.path.join(OUT, "rec_after_%s.png" % label))
    its2 = R.ocr_items(img2)
    print("--- 点「%s」后 OCR (%d 块) ---" % (label, len(its2)))
    for x in its2[:40]:
        print("   %-34s x=%4d y=%3d" % (x["text"][:34], x["x"], x["y"]))
    # 把筛选器行单独打印，看日期 chip 还在不在
    chips = [x["text"] for x in its2 if 80 < x["y"] < 200]
    print("   筛选器行:", chips)
    break
print("done")
