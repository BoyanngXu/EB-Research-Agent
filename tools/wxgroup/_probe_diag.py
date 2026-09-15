# -*- coding: utf-8 -*-
"""诊断：完整性级别 / 光标可见性 / 非客户区点击。"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R
import wx_collect as C

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"
u32 = R.user32
k32 = ctypes.windll.kernel32
adv = ctypes.windll.advapi32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenIntegrityLevel = 25
TokenElevation = 20


def pid_of(hwnd):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


def integrity(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "OpenProcess失败 err=%d" % ctypes.get_last_error()
    tok = wintypes.HANDLE()
    if not adv.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
        k32.CloseHandle(h)
        return "OpenProcessToken失败"
    out = []
    elev = wintypes.DWORD()
    ret = wintypes.DWORD()
    if adv.GetTokenInformation(tok, TokenElevation, ctypes.byref(elev),
                               ctypes.sizeof(elev), ctypes.byref(ret)):
        out.append("Elevated=%s" % bool(elev.value))
    size = wintypes.DWORD()
    adv.GetTokenInformation(tok, TokenIntegrityLevel, None, 0, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    adv.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    if adv.GetTokenInformation(tok, TokenIntegrityLevel, buf,
                               size.value, ctypes.byref(size)):
        tml = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
        cnt = adv.GetSidSubAuthorityCount(tml.Label.Sid)
        sub = adv.GetSidSubAuthority(tml.Label.Sid, cnt.contents.value - 1)
        out.append("IL=%d" % sub.contents.value)
    k32.CloseHandle(tok)
    k32.CloseHandle(h)
    return " ".join(out) or "未知"


h = R.find_wechat_window()
print("微信 pid =", pid_of(h), "| 完整性:", integrity(pid_of(h)))
print("本进程 pid =", k32.GetCurrentProcessId(), "| 完整性:", integrity(k32.GetCurrentProcessId()))

l, t, w, hh = C._safe_rect(h)
R.activate_window(h)
print("前台 =", R.foreground_title())

cx0, cy0 = R.cursor_pos()
try:
    # ---- 悬停测试：光标压到 efootball 行 vs 移开，比较该行像素 ----
    row = R.find_session(C.sessions_now(h), "efootball")
    print("efootball 行 =", row)
    if row:
        rx, ry = l + row["x"] + 40, t + row["y"] + row["h"] // 2
        box = (int(w * 0.02), row["y"] - 18, int(w * 0.34), row["y"] + 78)
        u32.SetCursorPos(cx0, cy0); time.sleep(0.8)
        a = R.capture_window(h, restore=False).crop(box)
        u32.SetCursorPos(rx, ry); time.sleep(0.9)
        b = R.capture_window(h, restore=False).crop(box)
        print("悬停导致该行像素变化 =", a.tobytes() != b.tobytes())

    # ---- 非客户区点击：标题栏"最小化"按钮 ----
    print("--- 点击窗口标题栏最小化按钮 (1277, 20) ---")
    u32.SetCursorPos(cx0, cy0); time.sleep(0.4)
    R.click_at(l + 1277, t + 20)
    time.sleep(1.2)
    print("   IsIconic =", bool(u32.IsIconic(h)))
    if u32.IsIconic(h):
        u32.ShowWindow(h, 9); time.sleep(0.6)
        print("   已还原 -> IsIconic =", bool(u32.IsIconic(h)))
finally:
    u32.SetCursorPos(cx0, cy0)
print("done")
