# -*- coding: utf-8 -*-
"""滚动「链接」列表，收集时间标签，直到越过昨天。"""
import sys, os, time, re, json, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"

PAGES = int(sys.argv[1]) if len(sys.argv) > 1 else 6
NOTCH = int(sys.argv[2]) if len(sys.argv) > 2 else 8


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
print("前台 =", R.foreground_title())

TIME_RE = re.compile(r"^(?:\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日|昨天|前天|星期[一二三四五六日天])"
                     r"(?:\s*\d{1,2}:\d{2})?$|^\d{1,2}:\d{2}$")

allrows = {}
for page in range(PAGES):
    img = R.capture_window(rec["h"], restore=False, size=(rw, rh))
    if page == 0:
        img.save(os.path.join(OUT, "link_p0.png"))
    items = R.ocr_items(img)
    times = [it["text"].strip() for it in items if TIME_RE.match(it["text"].strip())]
    dates = [t for t in times if "月" in t or "年" in t]
    print("第%2d屏: 时间标签 %d 个 | 日期标签: %s" % (page, len(times), dates))
    for it in items:
        t = it["text"].strip()
        if TIME_RE.match(t) or ("月" in t and "日" in t):
            allrows.setdefault(t, 0)
            allrows[t] += 1

    # 向下滚
    R.scroll_at(rl + rw // 2, rt + rh // 2, -NOTCH, hwnd=rec["h"])
    time.sleep(1.0)

print("--- 出现过的日期/时间标签 ---")
for k in sorted(allrows):
    print("   ", k)
print("done")
