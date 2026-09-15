# -*- coding: utf-8 -*-
"""逐条取链接 URL：右键 -> 用默认浏览器打开 -> Ctrl+L/Ctrl+C -> 读剪贴板。
用法: python _step21_url.py <最多条目数>"""
import sys, os, time, json, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
k32 = ctypes.windll.kernel32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
R.INPUT_BACKEND = "sendinput"
KEYUP = 0x0002
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 3


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
            if rc.right - rc.left >= minw and rc.bottom - rc.top >= minw:
                out.append({"h": hh, "title": wtitle(hh),
                            "rect": (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def read_clip():
    CF_UNICODETEXT = 13
    if not u32.OpenClipboard(None):
        return ""
    try:
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = k32.GlobalLock(h)
        try:
            return ctypes.c_wchar_p(p).value or ""
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def set_clip(t):
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    data = ctypes.create_unicode_buffer(t)
    size = ctypes.sizeof(data)
    h = k32.GlobalAlloc(GMEM_MOVEABLE, size)
    p = k32.GlobalLock(h)
    ctypes.memmove(p, data, size)
    k32.GlobalUnlock(h)
    if not u32.OpenClipboard(None):
        return False
    u32.EmptyClipboard()
    u32.SetClipboardData(CF_UNICODETEXT, h)
    u32.CloseClipboard()
    return True


def click_screen(sx, sy, right=False, hold=0.12):
    u32.SetCursorPos(sx, sy); time.sleep(0.3)
    dn, up = (0x0008, 0x0010) if right else (0x0002, 0x0004)
    u32.mouse_event(dn, 0, 0, 0, 0); time.sleep(hold)
    u32.mouse_event(up, 0, 0, 0, 0)


def hotkey(vk):
    u32.keybd_event(0x11, 0, 0, 0); time.sleep(0.05)
    u32.keybd_event(vk, 0, 0, 0); time.sleep(0.06)
    u32.keybd_event(vk, 0, KEYUP, 0); time.sleep(0.05)
    u32.keybd_event(0x11, 0, KEYUP, 0)


h = R.find_wechat_window()
pid = pid_of(h)
rec = [w for w in wins(pid) if "聊天记录" in w["title"]]
if not rec:
    sys.exit("没有聊天记录窗口")
rec = rec[0]
rl, rt, rw, rh = rec["rect"]
print("记录窗 =", rec["h"], rec["rect"])
R.activate_window(rec["h"]); time.sleep(0.5)


def ocr_rec():
    return R.ocr_items(R.capture_window(rec["h"], restore=False, size=(rw, rh)))


# 解析当前屏的条目：title(x~124) / time(x~775) / source(x~122, y+37)
def parse(items):
    ents = []
    for it in items:
        t = it["text"].strip()
        if it["y"] < 215:
            continue
        if 760 <= it["x"] <= 830 and ("昨天" in t or "前天" in t or ":" in t or "日" in t):
            ents.append({"ty": it["y"], "time": t, "title": "", "src": ""})
    for e in ents:
        band = [x for x in items if e["ty"] - 22 <= x["y"] <= e["ty"] + 50 and x["x"] < 760]
        tits = [x for x in band if 118 <= x["x"] <= 760 and x["y"] < e["ty"] + 12]
        srcs = [x for x in band if x["x"] < 118]
        if tits:
            e["title"] = max(tits, key=lambda z: z["w"])["text"].strip()
        if srcs:
            e["src"] = max(srcs, key=lambda z: z["w"])["text"].strip()
        e["tx"] = 124 + 120
    return ents


results = []
done = 0
for page in range(6):
    items = ocr_rec()
    ents = [e for e in parse(items) if "昨天" in e["time"]]
    print("第%d屏: 昨日条目 %d" % (page, len(ents)))
    for e in ents:
        if done >= LIMIT:
            break
        sx, sy = rl + e["tx"], rt + e["ty"] + 8
        print("  [%d] %s | %s" % (done + 1, e["src"][:14], e["title"][:44]))
        # 右键
        click_screen(sx, sy, right=True)
        time.sleep(1.3)
        menu = [w for w in wins(pid, 100) if w["h"] != rec["h"] and w["h"] != h
                and w["rect"][2] < 600]
        url = ""
        opened = False
        for m in menu:
            mitems = R.ocr_items(R.capture_window(m["h"], restore=False,
                                                  size=(m["rect"][2], m["rect"][3])))
            tgt = [x for x in mitems if "默认浏览器" in x["text"] or "浏览器打开" in x["text"]]
            if tgt:
                x = tgt[0]
                print("    菜单=%s -> 点「%s」" % (m["h"], x["text"].strip()))
                click_screen(m["rect"][0] + x["x"] + x["w"] // 2,
                             m["rect"][1] + x["y"] + x["h"] // 2)
                opened = True
                break
            else:
                print("    菜单 OCR:", [x["text"].strip() for x in mitems][:10])
        if not opened:
            u32.keybd_event(0x1B, 0, 0, 0); u32.keybd_event(0x1B, 0, KEYUP, 0)
            time.sleep(0.5)
            done += 1
            results.append({**e, "url": "", "err": "no-menu"})
            continue

        time.sleep(3.5)
        fg = R.foreground_title()
        print("    打开后前台 =", fg)
        set_clip("__NONE__")
        time.sleep(0.2)
        hotkey(0x4C)          # Ctrl+L
        time.sleep(0.4)
        hotkey(0x43)          # Ctrl+C
        time.sleep(0.6)
        url = read_clip()
        print("    URL =", url[:120])
        hotkey(0x57)          # Ctrl+W 关标签
        time.sleep(0.8)
        R.activate_window(rec["h"]); time.sleep(0.5)
        results.append({**e, "url": url})
        done += 1

    if done >= LIMIT:
        break
    R.scroll_at(rl + rw // 2, rt + rh // 2, -10, hwnd=rec["h"])
    time.sleep(1.0)

with open(os.path.join(OUT, "urls.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
print("共取 %d 条 -> urls.json" % len(results))
for r in results:
    print("  %-14s | %-40s | %s" % (r["src"][:14], r["title"][:40], r.get("url", "")[:90]))
print("done")
