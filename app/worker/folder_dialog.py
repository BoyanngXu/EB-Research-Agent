# -*- coding: utf-8 -*-
"""弹出 Windows 文件夹选择对话框，优先用「现代」资源管理器风格弹窗。

实现：ctypes 直接调用 COM 的 IFileOpenDialog（FOS_PICKFOLDERS），
即 Windows 10/11「选择文件夹」那个带左侧导航栏 / 地址栏 / 网络位置的弹窗。
若该 COM 类不可用（极罕见），回退到旧版 SHBrowseForFolder 树形弹窗。

本脚本由 files.select_dir 单独 spawn 起来跑（子进程有自己的 STA 主线程 +
消息泵，且继承用户的桌面会话，能稳定弹出原生选择框）；选中路径以 UTF-8
字节写到 stdout，父进程读回填补输入框。不依赖 tkinter（ctypes 为标准库自带）。

调试：加 --diag 可只检测环境（不弹任何窗），打印各步 HRESULT 与结论。
"""
import argparse
import ctypes
import sys
from ctypes import (Structure, POINTER, byref, c_void_p, c_ubyte, c_ushort,
                    c_ulong, c_long, c_wchar_p, WINFUNCTYPE, wintypes)

# ---- 微软定义的 GUID（来自 shobjidl.h） ----
CLSID_FileOpenDialog = "{DC1C5A9C-E88A-4EDE-A5A1-60F82A20AEF7}"
IID_IFileOpenDialog  = "{D57C7288-D4AD-4768-BE02-9D969532D960}"
IID_IShellItem       = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"

COINIT_APARTMENTTHREADED = 0x2
CLSCTX_INPROC_SERVER     = 0x1
FOS_PICKFOLDERS          = 0x20
FOS_FORCEFILESYSTEM      = 0x40
SIGDN_FILESYSPATH        = 0x80058000
S_OK, S_FALSE            = 0, 1

# 用户点「取消」时 Show 返回的 HRESULT：HRESULT_FROM_WIN32(ERROR_CANCELLED)
HRESULT_CANCELLED = 0x800704C7


class GUID(Structure):
    _fields_ = [
        ("Data1", c_ulong),
        ("Data2", c_ushort),
        ("Data3", c_ushort),
        ("Data4", c_ubyte * 8),
    ]


def _guid(s):
    s = s.strip("{}")
    a, b, c, d, e = s.split("-")
    g = GUID()
    g.Data1 = int(a, 16)
    g.Data2 = int(b, 16)
    g.Data3 = int(c, 16)
    data4 = bytes.fromhex(d + e)
    for i in range(8):
        g.Data4[i] = data4[i]
    return g


def _method(p, index, argtypes, restype=c_long):
    """取接口 p 的 vtable[index] 函数，返回 (this, *args)->结果 的可调用对象。"""
    lpVtbl = ctypes.cast(p, POINTER(c_void_p))[0]
    func_addr = ctypes.cast(lpVtbl, POINTER(c_void_p * 32))[0][index]
    F = WINFUNCTYPE(restype, c_void_p, *argtypes)
    return F(func_addr)


def _hr(v):
    """把 ctypes 返回的有符号 HRESULT 规整成无符号，便于阅读。"""
    try:
        return v & 0xFFFFFFFF
    except Exception:
        return v


def _declare(ole32, shell32):
    """显式声明函数签名。

    64 位下必须声明，否则 ctypes 默认把返回值当 32 位 c_int、
    指针/参数按默认规则转换，容易截断或静默失败。
    """
    ole32.CoInitializeEx.argtypes = [c_void_p, c_ulong]
    ole32.CoInitializeEx.restype = c_long
    ole32.CoCreateInstance.argtypes = [POINTER(GUID), c_void_p, c_ulong,
                                       POINTER(GUID), POINTER(c_void_p)]
    ole32.CoCreateInstance.restype = c_long
    ole32.CoTaskMemFree.argtypes = [c_void_p]
    shell32.SHCreateItemFromParsingName.argtypes = [c_wchar_p, c_void_p,
                                                    POINTER(GUID), POINTER(c_void_p)]
    shell32.SHCreateItemFromParsingName.restype = c_long


def diag(msg):
    """诊断信息统一写 stderr，父进程可捕获并落盘。"""
    try:
        sys.stderr.write(u"[folder_dialog] %s\n" % msg)
    except Exception:
        pass


def modern_browse(initial, title):
    """现代 IFileOpenDialog 文件夹选择框。

    返回 (path, status)；status ∈ {"ok", "cancel", "fail"}。
    "cancel" 表示用户主动取消，调用方**不应**再回退旧版弹窗。

    调用方需已 CoInitializeEx(STA)。vtable 槽位严格按 shobjidl.h：
    IUnknown(0/1/2) + IModalWindow.Show(3) + IFileDialog 从 4 起，
    故 SetOptions=9 / SetFolder=12 / SetTitle=16 / GetResult=19。
    """
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    _declare(ole32, shell32)

    pFileOpen = c_void_p()
    clsid = _guid(CLSID_FileOpenDialog)
    iid = _guid(IID_IFileOpenDialog)
    hr = ole32.CoCreateInstance(byref(clsid), None, CLSCTX_INPROC_SERVER,
                                byref(iid), byref(pFileOpen))
    if hr != S_OK or not pFileOpen.value:
        diag("CoCreateInstance(IFileOpenDialog) 失败 hr=0x%08X" % _hr(hr))
        return None, "fail"
    try:
        Release    = _method(pFileOpen.value, 2, [], c_ulong)
        Show       = _method(pFileOpen.value, 3, [c_void_p])
        SetFolder  = _method(pFileOpen.value, 12, [c_void_p])
        SetTitle   = _method(pFileOpen.value, 16, [c_wchar_p])
        GetResult  = _method(pFileOpen.value, 19, [POINTER(c_void_p)])
        SetOptions = _method(pFileOpen.value, 9, [c_ulong])

        hr = SetOptions(pFileOpen.value, FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM)
        diag("SetOptions hr=0x%08X" % _hr(hr))
        SetTitle(pFileOpen.value, title)

        # 初始目录：用 SHCreateItemFromParsingName 拿 IShellItem，再 SetFolder
        if initial:
            iid_psi = _guid(IID_IShellItem)
            psi = c_void_p()
            hr = shell32.SHCreateItemFromParsingName(initial, None,
                                                     byref(iid_psi), byref(psi))
            diag("SHCreateItemFromParsingName(%s) hr=0x%08X" % (initial, _hr(hr)))
            if hr == S_OK and psi.value:
                SetFolder(pFileOpen.value, psi.value)
                _method(psi.value, 2, [], c_ulong)(psi.value)  # 释放临时 IShellItem

        # 弹窗（阻塞；用户选完或取消后返回）
        hr = Show(pFileOpen.value, None)
        diag("Show hr=0x%08X" % _hr(hr))
        if _hr(hr) == HRESULT_CANCELLED:
            return None, "cancel"
        if hr != S_OK:
            return None, "fail"

        psi = c_void_p()
        hr = GetResult(pFileOpen.value, byref(psi))
        if hr != S_OK or not psi.value:
            diag("GetResult 失败 hr=0x%08X" % _hr(hr))
            return None, "fail"

        pname = c_wchar_p()
        try:
            # IShellItem vtable：Release=2, GetDisplayName=5
            GetDisplayName = _method(psi.value, 5, [c_ulong, POINTER(c_wchar_p)])
            hr = GetDisplayName(psi.value, SIGDN_FILESYSPATH, byref(pname))
            if hr == S_OK and pname.value:
                return pname.value, "ok"
            diag("GetDisplayName 失败 hr=0x%08X" % _hr(hr))
        finally:
            _method(psi.value, 2, [], c_ulong)(psi.value)
            if pname.value:
                ole32.CoTaskMemFree(pname)
    finally:
        try:
            Release(pFileOpen.value)
        except Exception:
            pass
    return None, "fail"


def legacy_browse(initial, title):
    """回退方案：旧版 SHBrowseForFolder 树形对话框（兼容性兜底）。"""
    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32
    ole32 = ctypes.windll.ole32

    BIF_RETURNONLYFSDIRS = 0x1
    BIF_NEWDIALOGSTYLE = 0x40
    BIF_EDITBOX = 0x10
    BFFM_INITIALIZED = 1
    BFFM_SETSELECTIONW = 0x473

    class BI(Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", c_void_p),
            ("pszDisplayName", c_wchar_p),
            ("lpszTitle", c_wchar_p),
            ("ulFlags", c_ulong),
            ("lpfn", c_void_p),
            ("lParam", c_void_p),
            ("iImage", c_long),
        ]

    shell32.SHBrowseForFolderW.argtypes = [POINTER(BI)]
    shell32.SHBrowseForFolderW.restype = c_void_p   # 64 位关键：否则 PIDL 被截断为 0
    shell32.SHGetPathFromIDListW.argtypes = [c_void_p, c_wchar_p]
    shell32.SHGetPathFromIDListW.restype = c_int
    user32.SendMessageW.argtypes = [wintypes.HWND, c_ulong, c_ulong, c_void_p]
    user32.SendMessageW.restype = c_int
    ole32.CoTaskMemFree.argtypes = [c_void_p]

    disp = ctypes.create_unicode_buffer(1024)
    pbuf = ctypes.create_unicode_buffer(1024)

    def cb(hwnd, msg, lp, dt):
        if msg == BFFM_INITIALIZED and initial:
            user32.SendMessageW(hwnd, BFFM_SETSELECTIONW, 1,
                                ctypes.cast(c_wchar_p(initial), c_void_p))
        return 0

    BCB = WINFUNCTYPE(c_int, wintypes.HWND, c_ulong, c_void_p, c_void_p)
    bi = BI()
    bi.pszDisplayName = disp
    bi.lpszTitle = title
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE | BIF_EDITBOX
    bi.lpfn = ctypes.cast(BCB(cb), c_void_p)
    pidl = shell32.SHBrowseForFolderW(byref(bi))
    path = ""
    if pidl:
        try:
            if shell32.SHGetPathFromIDListW(pidl, pbuf):
                path = pbuf.value
        finally:
            ole32.CoTaskMemFree(pidl)
    return path or None


def run_diag(initial):
    """只检测环境，不弹任何窗口。返回诊断行列表。"""
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    _declare(ole32, shell32)
    lines = []
    try:
        lines.append("python: %s" % sys.executable)
        lines.append("指针位数: %d 位" % (ctypes.sizeof(c_void_p) * 8))

        hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        lines.append("CoInitializeEx(STA) hr=0x%08X" % _hr(hr))
        if hr not in (S_OK, S_FALSE):
            lines.append("结论: COM 初始化失败 -> 无法弹出现代对话框")
            return lines

        p = c_void_p()
        clsid = _guid(CLSID_FileOpenDialog)
        iid = _guid(IID_IFileOpenDialog)
        hr = ole32.CoCreateInstance(byref(clsid), None, CLSCTX_INPROC_SERVER,
                                    byref(iid), byref(p))
        lines.append("CoCreateInstance(IFileOpenDialog) hr=0x%08X p=%s"
                     % (_hr(hr), p.value))
        if hr != S_OK or not p.value:
            if _hr(hr) == 0x80040154:
                lines.append("结论: 0x80040154 REGDB_E_CLASSNOTREG —— 该类未注册，"
                             "会回退旧版对话框")
            else:
                lines.append("结论: IFileOpenDialog 创建失败 -> 会回退旧版对话框")
            return lines

        # 已能创建：再验证 vtable 槽位是否正确（不 Show）
        try:
            so = _method(p.value, 9, [c_ulong])
            lines.append("SetOptions(槽9) hr=0x%08X"
                         % _hr(so(p.value, FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM)))
            st = _method(p.value, 16, [c_wchar_p])
            lines.append("SetTitle(槽16) hr=0x%08X" % _hr(st(p.value, u"诊断")))
            gr = _method(p.value, 19, [POINTER(c_void_p)])
            lines.append("GetResult(槽19) 已解析(未调用)")
            del gr
        except Exception as e:
            lines.append("vtable 调用异常: %r" % (e,))

        if initial:
            psi = c_void_p()
            iid_psi = _guid(IID_IShellItem)
            hr = shell32.SHCreateItemFromParsingName(initial, None,
                                                     byref(iid_psi), byref(psi))
            lines.append("SHCreateItemFromParsingName hr=0x%08X" % _hr(hr))
            if hr == S_OK and psi.value:
                lines.append("初始目录可解析: OK")
        lines.append("结论: 现代对话框(IFileOpenDialog) 可用")
        lines.append("注意: 本次为 --diag 检测，未弹出任何窗口")
        return lines
    finally:
        try:
            ole32.CoUninitialize()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--initial", default="")
    ap.add_argument("--title", default="选择目录")
    ap.add_argument("--diag", action="store_true",
                    help="只检测环境并打印诊断，不弹出任何窗口")
    args = ap.parse_args()

    if args.diag:
        for line in run_diag(args.initial):
            sys.stdout.write(line + "\n")
        sys.stdout.flush()
        return

    ole32 = ctypes.windll.ole32
    _declare(ole32, ctypes.windll.shell32)
    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    if hr not in (S_OK, S_FALSE):
        diag("CoInitializeEx 失败 hr=0x%08X" % _hr(hr))
        return

    try:
        path, status = modern_browse(args.initial, args.title)
        diag("modern status=%s" % status)
        if not path and status == "fail":
            # 仅「现代弹窗创建/获取结果失败」才兜底；用户点取消不二次弹窗
            diag("回退旧版 SHBrowseForFolder")
            path = legacy_browse(args.initial, args.title)
        if path:
            # 以 UTF-8 字节写出，避免管道默认编码（中文 Windows 为 cp936）
            # 把中文路径名截断/乱码；父进程按 utf-8 解码。
            sys.stdout.buffer.write(path.encode("utf-8"))
            sys.stdout.buffer.flush()
    finally:
        ole32.CoUninitialize()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        diag("未捕获异常: %r" % (e,))
