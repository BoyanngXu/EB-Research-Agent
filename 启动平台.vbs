' ============================================================
'  EB 投研 Agent 平台 - 双击启动器 (VBScript)
'  1) 启动前先杀掉占用 8765 的旧实例，确保双击等于真正的重启
'  2) 解释器优先级：项目自带 .venv -> Doubao 沙箱 -> 系统 python
'     - Doubao 路径用 %LOCALAPPDATA% 展开，不写死用户名
'     - 每个候选都做冒烟测试，失效的 .venv 会被自动跳过
' ============================================================
Option Explicit
Dim shell, fso, wd, venvPy, basesDir, pyexe, f, cand, killed, runCmd
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
wd = fso.GetParentFolderName(WScript.ScriptFullName)

' 1) 杀掉占用 8765 的旧实例
killed = KillPort(8765)

' 2) 定位解释器（逐级冒烟测试，坏了就往下走）
pyexe = ""

' 2a) 项目自带虚拟环境（换电脑重建后照样优先用）
venvPy = wd & "\.venv\Scripts\python.exe"
If fso.FileExists(venvPy) And PyOK(venvPy) Then pyexe = venvPy

' 2b) Doubao 沙箱（本机碰巧装了就白嫖，随版本轮换自动发现）
If pyexe = "" Then
    basesDir = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Doubao\User Data\sandbox_runtime\bases"
    If fso.FolderExists(basesDir) Then
        For Each f In fso.GetFolder(basesDir).SubFolders
            cand = f.Path & "\python\python.exe"
            If fso.FileExists(cand) And PyOK(cand) Then
                pyexe = cand
                Exit For
            End If
        Next
    End If
End If

' 2c) 兜底走 PATH
If pyexe = "" Then pyexe = "python"

' 3) 切到平台目录再启动服务
shell.CurrentDirectory = wd
If killed Then shell.Popup "已结束占用 8765 端口的旧实例，正在启动新版本。", 2, "EB-Agent", 64
'    用 --no-browser：浏览器统一由本脚本第 4 步打开，避免与 main.py 内置打开重复成两个窗口
runCmd = Chr(34) & pyexe & Chr(34) & " main.py --no-browser"
shell.Run runCmd, 1, False

' 4) 延迟后自动打开浏览器（只此一处，避免双开）
WScript.Sleep 2500
shell.Run "http://127.0.0.1:8765", 1, False

' ---- 冒烟测试：该解释器能否真的跑起来 ----
' 整份目录拷到新电脑后，.venv 里的基解释器路径会失效，
' 这里实测一次，跑不通就跳过，避免启动器选了个坏环境。
Function PyOK(p)
    Dim sh, rc
    Set sh = CreateObject("WScript.Shell")
    On Error Resume Next
    rc = sh.Run(Chr(34) & p & Chr(34) & " -c " & Chr(34) & "print(1)" & Chr(34), 0, True)
    If Err.Number <> 0 Then
        PyOK = False
    Else
        PyOK = (rc = 0)
    End If
    Err.Clear
End Function

' ---- 杀掉监听指定端口的进程 ----
Function KillPort(port)
    Dim sh, exec, line, parts, pid, k, target
    k = False
    target = ":" & CStr(port)
    Set sh = CreateObject("WScript.Shell")
    On Error Resume Next
    Set exec = sh.Exec("netstat -ano")
    If exec Is Nothing Then
        KillPort = False
        Exit Function
    End If
    Do While Not exec.StdOut.AtEndOfStream
        line = exec.StdOut.ReadLine
        If InStr(line, target) > 0 And InStr(line, "LISTENING") > 0 Then
            parts = Split(line)
            pid = parts(UBound(parts))
            If IsNumeric(pid) Then
                sh.Run "taskkill /PID " & pid & " /F", 0, True
                k = True
            End If
        End If
    Loop
    KillPort = k
End Function
