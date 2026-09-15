# -*- coding: utf-8 -*-
"""带校验的日期选择：打开选择器 -> 打印状态 -> 点14 -> 再打印 -> 确定 -> 验证。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"
DAY = int(sys.argv[1]) if len(sys.argv) > 1 else 14


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def wtitle(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def wins(pid, minw=80):
    out = []

    def cb(hh, _):
        if pid_of(hh) == pid and u32.IsWindowVisible(hh):
            rc = wintypes.RECT()
            u32.GetWindowRect(hh, ctypes.byref(rc))
            w_, h_ = rc.right - rc.left, rc.bottom - rc.top
            if w_ >= minw and h_ >= minw:
                out.append({"h": hh, "title": wtitle(hh),
                            "rect": (rc.left, rc.top, w_, h_)})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def click_screen(sx, sy, hold=0.12):
    u32.SetCursorPos(sx, sy); time.sleep(0.3)
    u32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(hold)
    u32.mouse_event(0x0004, 0, 0, 0, 0)


h = R.find_wechat_window()
pid = pid_of(h)
rec = [w for w in wins(pid) if "聊天记录" in w["title"]]
if not rec:
    sys.exit("没有聊天记录窗口")
rec = rec[0]
R.activate_window(rec["h"]); time.sleep(0.5)

# 打开选择器：先清掉已生效的筛选 chip（形如「品 日期 ×」），再点「日期」
rl, rt, rw, rh = rec["rect"]


def rec_items():
    return R.ocr_items(R.capture_window(rec["h"], restore=False, size=(rw, rh)))


def filter_row(items):
    return [x for x in items if 140 <= x["y"] <= 210]


items = rec_items()
chips = [x for x in filter_row(items)
         if ("日期" in x["text"] or "链接" in x["text"] or "文件" in x["text"])
         and ("×" in x["text"] or "x" in x["text"] or "X" in x["text"])]
if chips:
    c = chips[0]
    print("清除 chip:", repr(c["text"]))
    click_screen(rl + c["x"] + c["w"] - 10, rt + c["y"] + c["h"] // 2)
    time.sleep(1.2)
    items = rec_items()

day_btns = [x for x in filter_row(items) if x["text"].strip() == "日期"]
if not day_btns:
    day_btns = [x for x in filter_row(items) if "日期" in x["text"]]
if not day_btns:
    print("筛选行:", [x["text"] for x in filter_row(items)])
    sys.exit("找不到日期按钮")
it = day_btns[0]
print("点日期按钮:", repr(it["text"]))
click_screen(rl + it["x"] + it["w"] // 2, rt + it["y"] + it["h"] // 2)
time.sleep(1.5)

pick = [w for w in wins(pid, 200) if 400 < w["rect"][2] < 600 and 500 < w["rect"][3] < 750]
if not pick:
    sys.exit("选择器没出现")
pick = pick[0]
print("选择器 =", pick["h"], pick["rect"])
R.activate_window(pick["h"]); time.sleep(0.5)
pl, pt, pw, ph = pick["rect"]


def picker_shot(tag):
    im = R.capture_window(pick["h"], restore=False, size=(pw, ph))
    im.save(os.path.join(OUT, "pk_%s.png" % tag))
    items = R.ocr_items(im)
    print("  [%s] %s" % (tag, [x["text"].strip() for x in items]))
    return items


items = picker_shot("open")
day = [x for x in items if x["text"].strip() == str(DAY)]
if not day:
    sys.exit("选择器里没有 %d" % DAY)
d = day[0]
dx, dy = pl + d["x"] + d["w"] // 2, pt + d["y"] + d["h"] // 2
print("点 %d -> 屏幕(%d,%d)" % (DAY, dx, dy))
click_screen(dx, dy)
time.sleep(0.8)
items2 = picker_shot("day")

ok = [x for x in items2 if x["text"].strip() == "确定"]
if not ok:
    sys.exit("没有确定")
o = ok[0]
click_screen(pl + o["x"] + o["w"] // 2, pt + o["y"] + o["h"] // 2)
time.sleep(2.0)

print("--- 记录窗结果 ---")
im3 = R.capture_window(rec["h"], restore=False, size=(rw, rh))
im3.save(os.path.join(OUT, "rec_verify.png"))
for x in R.ocr_items(im3)[:12]:
    print("   %-34s x=%4d y=%3d" % (x["text"][:34], x["x"], x["y"]))
print("done")
