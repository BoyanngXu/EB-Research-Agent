# -*- coding: utf-8 -*-
"""微信群消息只读采集器（微信 4.0 电脑版 · 截图 + OCR）

设计红线（务必遵守）：
    只读。不注入微信进程、不抓私有协议、不读本地数据库、不发送任何消息。
    实现方式：PrintWindow 截取微信窗口像素 -> OCR 识别文字 -> 结构化。
    从微信视角看，它只是"屏幕被截了一张图"，不产生任何发往服务器的请求。

为什么是截图 OCR（2026-09-15 实测结论，微信 4.0）：
    - Windows 通知库：微信 4.0 不写 toast，通知库里没有微信（197 个 handler 无微信）。
    - UI Automation：微信 4.0 是 Qt 自绘，UIA 树只有一个不透明面板
      （MMUIRenderSubWindowHW），读不到任何控件。
    - 本地数据库：加密，且相关工具已被腾讯 DMCA 追责（红线）。
    - 结论：截图 + OCR 是微信 4.0 电脑版唯一可行的非侵入只读通道。

用法：
    python wx_read.py --probe            # 打印当前微信窗口 + OCR 结果（含坐标，用于调参）
    python wx_read.py --json             # 输出结构化 JSON
    python wx_read.py --save out.png     # 同时保存截图便于核对
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
import time
from ctypes import wintypes

# ------------------------------------------------------------------ 窗口定位
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def _set_dpi_aware():
    """必须！否则在 150% 缩放屏上 GetWindowRect 返回逻辑坐标，
    与屏幕实拍/输入坐标差 1.5 倍，点击会全部打偏。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


_set_dpi_aware()

WECHAT_TITLES = ("微信", "Weixin", "WeChat")
WECHAT_CLASS_HINT = "QWindowIcon"      # 微信 4.0 = Qt51514QWindowIcon


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT),
                ("showCmd", wintypes.UINT), ("ptMinPosition", POINT),
                ("ptMaxPosition", POINT), ("rcNormalPosition", RECT)]


def find_wechat_window():
    """返回微信主窗口 hwnd（找不到返回 None）。

    注意：微信 4.0 有多个同类的 Qt 窗口（主窗口标题「微信」，
    小弹窗标题「Weixin」）。必须优先取标题恰为「微信」的，否则会抓到小弹窗。
    """
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        cbuf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cbuf, 256)
        cls, title = cbuf.value, buf.value
        if WECHAT_CLASS_HINT in cls and title in WECHAT_TITLES:
            r = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            area = (r.right - r.left) * (r.bottom - r.top)
            found.append((area, hwnd, title, bool(user32.IsWindowVisible(hwnd))))
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        return None
    # 1) 标题恰为「微信」的优先；2) 面积最大；3) 可见优先
    main = [f for f in found if f[2] == "微信"]
    pool = main or found
    pool.sort(key=lambda f: (f[0], f[3]), reverse=True)
    return pool[0][1]


def window_rect(hwnd):
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def window_size(hwnd):
    """返回窗口内容尺寸。

    【关键】窗口最小化时 GetWindowRect 返回 (-32000,-32000,237,39) 这种特征值，
    直接用它截图会得到一张 237x39 的废图（OCR 全空）。此时改用
    GetWindowPlacement 的 rcNormalPosition —— 最小化窗口也能拿到还原后的真实尺寸，
    而 PrintWindow 本来就会按"还原态"渲染，所以尺寸对得上。
    """
    _, _, w, h = window_rect(hwnd)
    if w > 0 and h > 0 and not user32.IsIconic(hwnd):
        return w, h
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    if user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
        rc = wp.rcNormalPosition
        nw, nh = rc.right - rc.left, rc.bottom - rc.top
        if nw > 0 and nh > 0:
            return nw, nh
    return w, h


def restored_rect(hwnd):
    """窗口"还原态"的屏幕矩形 —— 最小化时也能拿到正确的位置和尺寸。

    最小化窗口的 GetWindowRect 是 (-32000,-32000,237,39) 这种特征值，
    拿它算点击/滚动坐标会全部落到屏幕外。GetWindowPlacement 的
    rcNormalPosition 不受最小化影响。
    """
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    if user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
        rc = wp.rcNormalPosition
        w, h = rc.right - rc.left, rc.bottom - rc.top
        if w > 0 and h > 0:
            return rc.left, rc.top, w, h
    return window_rect(hwnd)


def capture_window(hwnd, restore=True, size=None):
    """用 PrintWindow 截取窗口像素（可在窗口被遮挡/最小化时工作）。返回 PIL.Image。

    restore=True 会 SW_RESTORE 抢焦点（仅主动导航时需要）；
    被动采集必须 restore=False，此时靠 window_size() 拿正确尺寸。
    """
    from PIL import Image

    if restore:
        user32.ShowWindow(hwnd, 9)    # SW_RESTORE，确保窗口已渲染
        time.sleep(0.35)

    w, h = size or window_size(hwnd)
    if w <= 0 or h <= 0:
        raise RuntimeError("窗口尺寸异常: %dx%d" % (w, h))

    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    try:
        user32.PrintWindow(hwnd, mdc, 0x2)     # PW_RENDERFULLCONTENT
        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h             # top-down
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, hdc)


def capture_window_wh(hwnd, w, h):
    """按指定尺寸截图（用于最小化窗口：尺寸由 window_size 推算）。"""
    return capture_window(hwnd, restore=False, size=(w, h))


SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_SHOWNOACTIVATE = 4
WPF_RESTORETOMAXIMIZED = 0x0002


def capture_silent(hwnd, settle=0.9):
    """被动采集专用截图：不抢焦点、不改变窗口最终状态。

    为什么需要它（2026-09-15 实测）：
        最小化的窗口用 PrintWindow 截出来是**空白图**（OCR 0 块），
        所以"最小化也能被动采"这个假设不成立，必须先还原。
        但用 SW_SHOWNOACTIVATE 还原**不会抢走前台焦点**（实测前台窗口不变），
        截完再按原状态（最小化 / 最大化后最小化）放回去，用户无感。
    """
    was_min = bool(user32.IsIconic(hwnd))
    to_max = False
    if was_min:
        wp = WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(WINDOWPLACEMENT)
        if user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
            to_max = bool(wp.flags & WPF_RESTORETOMAXIMIZED)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        time.sleep(settle)
    try:
        return capture_window(hwnd, restore=False)
    finally:
        if was_min:
            if to_max:
                user32.ShowWindow(hwnd, SW_MAXIMIZE)
                time.sleep(0.25)
            user32.ShowWindow(hwnd, SW_MINIMIZE)


# ------------------------------------------------------------------ OCR
_ENGINE = None


def ocr_engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def ocr_items(img):
    """OCR -> [{'text','x','y','w','h','score'}]，按 y 再 x 排序。"""
    import numpy as np
    arr = np.asarray(img)
    res, _ = ocr_engine()(arr)
    items = []
    for box, text, score in (res or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append({"text": str(text), "x": int(min(xs)), "y": int(min(ys)),
                      "w": int(max(xs) - min(xs)), "h": int(max(ys) - min(ys)),
                      "score": round(float(score), 3)})
    items.sort(key=lambda it: (it["y"], it["x"]))
    return items


# ------------------------------------------------------------------ 输入模拟（仅导航用）
# 用途：打开群聊、滚动查看历史。**不发送任何消息**。
# 这是本方案唯一"驱动客户端"的部分；不想驱动就别调用它
# （wx_collect.py 的被动模式全程不碰这些函数）。
#
# 两种后端（2026-09-15 实测）：
#   "message"  直接给窗口发 WM_MOUSEWHEEL / WM_LBUTTONDOWN 消息。
#              **不移动鼠标、不抢前台、不遮挡用户窗口** —— 微信在后台被压着也能驱动。
#              唯一要求：窗口不能是最小化（最小化时不生效）。
#              实测微信 4.0（Qt）完全支持。
#   "sendinput" 传统 SendInput。会移动真实鼠标，且要求窗口在前台/在光标下，
#              等于把用户电脑占住 —— 只作为兜底。
INPUT_BACKEND = "message"

WM_MOUSEWHEEL = 0x020A
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
HWND_BOTTOM = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


class _PT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
INPUT_MOUSE = 0


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("mi", MOUSEINPUT)]


def cursor_pos():
    p = _PT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def foreground_title():
    h = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, b, n + 1)
    return b.value or "(无标题)"


def quiet_show(hwnd):
    """让窗口"可见但不激活"，并压到最底层，使驱动操作对用户完全无感。

    为什么需要：消息方式的滚轮/点击要求窗口**非最小化**（实测最小化时不生效），
    但用户窗口不应该被抢焦点、也不该挡住用户的东西。
    SW_SHOWNOACTIVATE 显示窗口但不激活；SetWindowPos(HWND_BOTTOM) 压到所有窗口之下。

    返回 was_minimized —— 调用方做完活后用 `ShowWindow(hwnd, SW_MINIMIZE)` 放回去。
    """
    was_min = bool(user32.IsIconic(hwnd))
    if was_min:
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        time.sleep(0.8)
    user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    time.sleep(0.3)
    return was_min


def quiet_restore(hwnd, was_minimized):
    """按 quiet_show 的结果把窗口放回最小化。"""
    if was_minimized:
        user32.ShowWindow(hwnd, SW_MINIMIZE)


def activate_window(hwnd, tries=3):
    """把微信窗口带到前台，并**确认真的拿到了前台焦点**。返回是否成功。

    只有 SendInput 后端才需要它。消息后端不需要窗口在前台。
    为什么不能只调 SetForegroundWindow：Windows 会拒绝非前台进程的前台请求
    （静默失败），此时 SendInput 的点击会落到覆盖在微信之上的窗口上，
    表现为"点了没反应"，而 PrintWindow 读标题却一切正常 —— 极难排查。
    这里逐次校验 GetForegroundWindow，失败则用 AttachThreadInput 兜底。
    """
    for _ in range(tries):
        user32.ShowWindow(hwnd, 9)                      # SW_RESTORE
        try:
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        time.sleep(0.25)
        if user32.GetForegroundWindow() == hwnd:
            return True
        try:
            fg = user32.GetForegroundWindow()
            tid_fg = user32.GetWindowThreadProcessId(fg, None)
            tid_me = ctypes.windll.kernel32.GetCurrentThreadId()
            user32.AttachThreadInput(tid_me, tid_fg, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(tid_me, tid_fg, False)
        except Exception:
            pass
        time.sleep(0.3)
        if user32.GetForegroundWindow() == hwnd:
            return True
    return user32.GetForegroundWindow() == hwnd


def _send_mouse(nx, ny, data, flags):
    mi = MOUSEINPUT(nx, ny, data, flags, 0, None)
    user32.SendInput(1, ctypes.byref(INPUT(INPUT_MOUSE, mi)), ctypes.sizeof(INPUT))


def _norm(x, y):
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    return int(x * 65535 / max(1, sw - 1)), int(y * 65535 / max(1, sh - 1))


try:
    user32.ChildWindowFromPointEx.argtypes = [wintypes.HWND, _PT, wintypes.UINT]
    user32.ChildWindowFromPointEx.restype = wintypes.HWND
except Exception:
    pass


def deep_child(hwnd, sx, sy):
    """返回屏幕点 (sx, sy) 下**最深**的子窗口。

    【为什么必须有它（2026-09-15 实测）】
    微信 4.0 主窗口（Qt51514QWindowIcon）下只有**一个**子窗口
    `MMUIRenderSubWindowHW`，它覆盖整个客户区。鼠标**按键**消息必须发给它：
    发给顶层窗口时点击**完全无响应**（点群名旁的 💬/⋯ 毫无反应）。
    而滚轮 WM_MOUSEWHEEL 发给顶层能被 Qt 转发，所以滚动一直正常 ——
    这也是为什么"能滚不能点"这个坑很难一眼看出。
    """
    cur = hwnd
    for _ in range(6):
        pt = _PT(sx, sy)
        if not user32.ScreenToClient(cur, ctypes.byref(pt)):
            break
        c = user32.ChildWindowFromPointEx(cur, pt, 0)
        if not c or c == cur:
            break
        cur = c
    return cur


def click_at(sx, sy, hwnd=None, backend=None, release=True, hold=0.05):
    """在屏幕绝对坐标单击左键。

    默认走消息后端（不移动鼠标、不抢前台）。hwnd 为 None 时退回 SendInput。

    release=False 只发按下不发抬起（用于探测 Qt 弹出菜单：Qt 菜单在
    LBUTTONDOWN 时打开并 grab 鼠标，紧跟的 LBUTTONUP 会立刻把菜单关掉）。
    """
    if (backend or INPUT_BACKEND) == "message" and hwnd:
        tgt = deep_child(hwnd, sx, sy)
        pt = _PT(sx, sy)
        user32.ScreenToClient(tgt, ctypes.byref(pt))
        lp = ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)
        user32.SendMessageW(tgt, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        if not release:
            return tgt, lp
        time.sleep(hold)
        user32.SendMessageW(tgt, WM_LBUTTONUP, 0, lp)
        return tgt, lp
    nx, ny = _norm(sx, sy)
    _send_mouse(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
    time.sleep(0.03)
    _send_mouse(nx, ny, 0, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE)
    time.sleep(0.03)
    _send_mouse(nx, ny, 0, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE)


def scroll_at(sx, sy, notches, step_delay=0.02, hwnd=None, backend=None):
    """在指定屏幕坐标滚动滚轮。notches>0 向上（看更早的消息）。

    默认走消息后端：`SendMessageW(hwnd, WM_MOUSEWHEEL, ...)`，
    lParam 传**屏幕坐标**，微信自己判断滚哪个子控件。
    不移动鼠标、不要求窗口在前台（实测窗口在后台被压着也能滚）。

    【关键】必须拆成 notches 个独立滚轮事件。
    实测：把 notches*120 塞进单个事件的 mouseData，Qt 的微信只按"一格"处理，
    所以 notches=60 实际只滚 1 格 —— 会导致翻屏采集几乎全是重复内容。
    """
    if not notches:
        return
    if (backend or INPUT_BACKEND) == "message" and hwnd:
        delta = 120 if notches > 0 else -120
        wparam = (delta & 0xFFFF) << 16
        lparam = ((sy & 0xFFFF) << 16) | (sx & 0xFFFF)
        for _ in range(abs(notches)):
            user32.SendMessageW(hwnd, WM_MOUSEWHEEL, wparam, lparam)
            time.sleep(step_delay)
        time.sleep(0.05)
        return
    nx, ny = _norm(sx, sy)
    _send_mouse(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
    time.sleep(0.05)
    flag = 1 if notches > 0 else -1
    delta = int(120 * flag) & 0xFFFFFFFF
    for _ in range(abs(notches)):
        _send_mouse(nx, ny, delta, MOUSEEVENTF_WHEEL)
        time.sleep(step_delay)
    time.sleep(0.05)


# ------------------------------------------------------------------ 版面切分
# 微信 4.0 主窗口比例（2026-09-15 实测标定，窗口 1365x1031 / 150% 缩放）
#   最左竖排导航栏 + 会话列表  →  x 0..465   （会话预览文字最右到 x=445）
#   聊天区标题栏（群名）        →  y 0..113   （群名文字 y=72..100）
#   聊天正文                   →  y 113..789
#   底部输入区（输入框+工具条） →  y 789..1031（"发送"按钮 y=958）
SESSION_W = 0.34          # 左侧会话列表（含最左导航栏）宽度占比
HEADER_H = 0.11           # 聊天区顶部标题栏高度占比
INPUT_H = 0.235           # 底部输入区（输入框+工具条）高度占比


def panes(w, h):
    sx = int(w * SESSION_W)
    hy = int(h * HEADER_H)
    iy = int(h * (1 - INPUT_H))
    return {
        "session": (0, 0, sx, h),
        "chat": (sx, 0, w, h),
        "header": (sx, 0, w, hy),
        "chat_body": (sx, hy, w, iy),
        "input": (sx, iy, w, h),
    }


def in_rect(it, rect):
    x1, y1, x2, y2 = rect
    cx, cy = it["x"] + it["w"] / 2, it["y"] + it["h"] / 2
    return x1 <= cx <= x2 and y1 <= cy <= y2


# ------------------------------------------------------------------ 消息解析
# 时间分隔：可能是"10:30" / "昨天09:38" / "星期五12:59" / "9月15日 上午10:30"
_CLOCK = r"(?:上午|下午|凌晨|晚上|中午)?\s*\d{1,2}:\d{2}"
RE_TIME = re.compile(
    r"^(?:"
    r"\d{4}年\d{1,2}月\d{1,2}日(?:\s*" + _CLOCK + r")?"
    r"|\d{1,2}月\d{1,2}日(?:\s*" + _CLOCK + r")?"
    r"|(?:星期[一二三四五六日天]|昨天|前天|今天)(?:\s*" + _CLOCK + r")?"
    r"|" + _CLOCK +
    r")$")

# 系统提示 / 浮动胶囊，不是用户消息
RE_SYS = re.compile(r"^(\d+\s*条新消息|以下为新消息|查看更多消息|消息已发出|"
                    r"对方正在输入|该内容不支持查看|\d+人正在|以上是打招呼的内容|"
                    r"该类型消息暂不支持|引用|已撤回.*)$")

# 发送者名相对正文列的左偏（实测 565 vs 583，约 18px）
NAME_DX = 12
NAME_MAX_LEN = 24


def _clean_group(t):
    """清掉群名尾部 OCR 误识别的图标字符（常被识别成 Q）。"""
    t = re.sub(r"\s+", " ", (t or "").strip())
    t = re.sub(r"[Qq\s]+$", "", t)
    return t[:60]


def _rows_of(items, y_gap=8):
    """把 OCR 块按 y 邻近度聚成"行"（同一行的多个块拼起来）。"""
    sel = sorted(items, key=lambda z: (z["y"], z["x"]))
    rows = []
    for it in sel:
        if rows and abs(it["y"] - rows[-1]["y"]) <= y_gap:
            rows[-1]["items"].append(it)
        else:
            rows.append({"y": it["y"], "items": [it]})
    for r in rows:
        r["items"].sort(key=lambda z: z["x"])
        r["text"] = " ".join(i["text"] for i in r["items"]).strip()
        r["x1"] = min(i["x"] for i in r["items"])
        r["x2"] = max(i["x"] + i["w"] for i in r["items"])
        r["h"] = max(i["h"] for i in r["items"])
    return [r for r in rows if r["text"]]


def _median(vals):
    if not vals:
        return 0
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _quantile(vals, q):
    if not vals:
        return 0
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def chat_rows(items, w, h):
    """聊天区 OCR -> 行列表（已剔除系统提示与浮动胶囊）。"""
    p = panes(w, h)
    body = [it for it in items if in_rect(it, p["chat_body"])]
    body = [it for it in body if not RE_SYS.match(it["text"].strip())]
    return _rows_of(body)


def rows_to_messages(rows, w, h, group="", line_gap=None):
    """行列表 -> 消息列表。

    切分规则：时间分隔行重置上下文；"发送者名"行强制开新消息；
    其余按行距切分（超过 ~1.9 倍中位行距视为新消息）。

    发送者名怎么认（2026-09-15 实测）：
        群聊里名字渲染在气泡**上方、与气泡左边缘对齐**，而气泡内正文有内边距
        —— 实测名字 x1=565、正文 x1=583，差约 18px。
        所以"比正文列更靠左、且足够短"的行就是发送者名。
        正文列只统计**左侧行**，否则自己发的右对齐消息会把列算偏。
    """
    p = panes(w, h)
    bx1, _, bx2, _ = p["chat_body"]
    bw = max(1, bx2 - bx1)
    if not rows:
        return {"group": group, "messages": []}

    left_rows = [r for r in rows if (r["x2"] - bx1) / bw <= 0.90]
    col = _quantile([r["x1"] for r in (left_rows or rows)], 0.7)
    name_x = max(col - NAME_DX, bx1 + 20)

    pitch = line_gap or max(20.0, _median(
        [rows[i]["y"] - rows[i - 1]["y"] for i in range(1, len(rows))]) or 29.0)
    split_gap = pitch * 1.9

    messages = []
    cur_time = ""
    last_sender = ""
    cur = None
    prev_y = None
    for r in rows:
        t = r["text"]
        if RE_TIME.match(t):
            cur_time = t
            cur = None
            prev_y = r["y"]
            continue

        # 发送者名：比正文列更靠左、且足够短
        if r["x1"] <= name_x and len(t) <= NAME_MAX_LEN:
            last_sender = t
            cur = None                       # 换人 -> 强制开新消息
            prev_y = r["y"]
            continue

        rel_r = (r["x2"] - bx1) / bw
        # 自己的消息：右对齐（气泡右边界贴近聊天区右侧）
        side = "right" if rel_r > 0.90 else "left"

        new_msg = (cur is None or cur["side"] != side
                   or (prev_y is not None and r["y"] - prev_y > split_gap))
        if new_msg:
            cur = {"time": cur_time,
                   "sender": ("我" if side == "right" else last_sender),
                   "text": t, "side": side}
            messages.append(cur)
        else:
            cur["text"] = (cur["text"] + " " + t).strip()
        prev_y = r["y"]

    for m in messages:
        m["text"] = re.sub(r"\s+", " ", m["text"]).strip()
    return {"group": group, "messages": [m for m in messages if m["text"]]}


def parse_chat(items, w, h, line_gap=None):
    """把聊天区 OCR 结果解析成 {group, messages:[{time,sender,text,side}]}。"""
    p = panes(w, h)
    head = [it for it in items if in_rect(it, p["header"])]
    group = ""
    if head:
        group = _clean_group(sorted(head, key=lambda z: z["x"])[0]["text"])
    return rows_to_messages(chat_rows(items, w, h), w, h, group=group,
                            line_gap=line_gap)


# ------------------------------------------------------------------ 滚动拼接
def _nkey(t):
    """归一化文本，用于跨屏比对（去掉空白与标点，OCR 抖动更宽容）。"""
    return re.sub(r"[\s\W_]+", "", t or "")


def stitch_rows(acc, new, fuzzy=0.82):
    """把新一屏的行拼接到累积行上（**聊天向上翻**的场景）。

    ⚠ 方向很关键（2026-09-15 实测踩过）：
        向上翻看更早的消息时，新一屏显示的是**更早**的内容，
        它的**底部**与已累积内容的**顶部**重叠。
        所以：重叠 = 新屏尾部 k 行 == 累积头部 k 行，
        拼接 = 新屏去掉尾部重叠 + 累积内容。

        早先按"网页向下滚动"的语义写成（累积尾部 == 新屏头部、acc+new[k:]），
        结果每次都是整段追加、完全不重叠，同一批消息被重复采集
        （实测 117 行里 6 行整段重复）。
    """
    if not acc:
        return list(new)
    if not new:
        return acc
    na = [_nkey(r["text"]) for r in acc]
    nn = [_nkey(r["text"]) for r in new]
    top = min(len(acc), len(new))
    # 1) 精确归一化匹配：新屏尾部 k 行 == 累积头部 k 行
    for k in range(top, 0, -1):
        if nn[-k:] == na[:k]:
            return new[:len(new) - k] + acc
    # 2) 模糊兜底（OCR 抖动导致个别字不同）
    import difflib
    best_k, best_r = 0, 0.0
    for k in range(1, top + 1):
        a = "".join(nn[-k:])          # 新屏尾部
        b = "".join(na[:k])           # 累积头部
        if not a or not b:
            continue
        r = difflib.SequenceMatcher(None, a, b).ratio()
        if r > best_r:
            best_k, best_r = k, r
    if best_r >= fuzzy:
        return new[:len(new) - best_k] + acc
    # 3) 完全找不到重叠（滚动跨过了一屏）：保守前置，宁可重复也不丢
    return new + acc


# ------------------------------------------------------------------ 会话列表
def group_rows(items, rect, y_gap=16):
    """把 OCR 块按 y 邻近度聚成"行"，行内按 x 排序。"""
    out = []
    for r in _rows_of([it for it in items if in_rect(it, rect)], y_gap=y_gap):
        out.append({
            "name": r["items"][0]["text"] if r["items"] else "",
            "text": r["text"],
            "x": r["x1"], "y": r["y"], "h": r["h"],
        })
    return out


def list_sessions(items, w, h):
    """OCR 会话列表 -> [{name,text,x,y,h}]。"""
    p = panes(w, h)
    return group_rows(items, p["session"])


def find_session(rows, keyword):
    """在会话行里按关键字找，返回最靠上的一行。

    优先匹配"群名"列（避免关键字只出现在消息预览里，点到别的会话）。
    """
    if not keyword:
        return None
    hits = [r for r in rows if keyword in r["name"]]
    if not hits:
        hits = [r for r in rows if keyword in r["text"]]
    if not hits:
        return None
    hits.sort(key=lambda r: r["y"])
    return hits[0]


# ------------------------------------------------------------------ 对外接口
def collect_once(save_png=None, probe=False):
    hwnd = find_wechat_window()
    if not hwnd:
        return {"ok": False, "error": "未找到微信主窗口（微信 4.0 是否已启动？）"}
    img = capture_window(hwnd)
    if save_png:
        os.makedirs(os.path.dirname(os.path.abspath(save_png)), exist_ok=True)
        img.save(save_png)
    items = ocr_items(img)
    if probe:
        return {"ok": True, "size": img.size, "items": items}
    w, h = img.size
    parsed = parse_chat(items, w, h)
    parsed.update({"ok": True, "size": img.size, "item_count": len(items)})
    return parsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="打印带坐标的 OCR 原始结果")
    ap.add_argument("--json", action="store_true", help="输出结构化 JSON")
    ap.add_argument("--save", metavar="PNG", help="保存截图")
    ap.add_argument("--dump", metavar="FILE", help="把截图+OCR+解析结果全量写出，用于校准")
    args = ap.parse_args()

    r = collect_once(save_png=args.save, probe=args.probe)
    if not r.get("ok"):
        print("ERR:", r.get("error"))
        sys.exit(1)

    if args.dump:
        hwnd = find_wechat_window()
        img = capture_silent(hwnd)
        items = ocr_items(img)
        w, h = img.size
        p = panes(w, h)
        rows = _rows_of([it for it in items
                         if in_rect(it, p["chat_body"])
                         and not RE_SYS.match(it["text"].strip())])
        payload = {
            "size": [w, h], "panes": {k: list(v) for k, v in p.items()},
            "items": items,
            "rows": [{"y": x["y"], "x1": x["x1"], "x2": x["x2"],
                      "h": x["h"], "text": x["text"]} for x in rows],
            "parsed": parse_chat(items, w, h),
            "sessions": list_sessions(items, w, h),
        }
        with open(args.dump, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        print("已写出 %s（OCR %d 块，正文 %d 行，消息 %d 条）"
              % (args.dump, len(items), len(rows), len(payload["parsed"]["messages"])))
        return

    if args.probe:
        print("窗口尺寸: %dx%d，OCR 块数: %d" % (r["size"][0], r["size"][1], len(r["items"])))
        for it in r["items"]:
            print("  y=%-5d x=%-5d w=%-4d %s" % (it["y"], it["x"], it["w"], it["text"][:70]))
        return

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return

    print("群/会话: %s" % (r.get("group") or "(未识别)"))
    print("消息数: %d" % len(r["messages"]))
    for m in r["messages"]:
        who = m["sender"] or ("我" if m["side"] == "right" else "?")
        print("  [%s] %s: %s" % (m["time"] or "--:--", who, m["text"][:80]))


if __name__ == "__main__":
    main()
