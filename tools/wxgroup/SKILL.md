---
name: wechat-group-digest
description: 非侵入式只读采集微信群消息（微信 4.0 电脑版，截图 + OCR），落 SQLite 后可按日汇总。当用户说"采集微信群消息""把今天的群消息抓下来""跑一下微信群日报""看看某个群今天聊了什么""扫一下我的会话列表"时使用。全程只读：不注入微信进程、不抓协议、不解密数据库、不发送任何消息。
agent_created: true
---

# 微信群消息只读采集（微信 4.0 电脑版）

## 红线（任何改动都不得违反）

只读。**不注入微信进程、不抓私有协议、不读/不解密本地数据库、不发送任何消息。**
实现方式是 `PrintWindow` 截取窗口像素 → OCR 识别 → 结构化。
从微信视角看，它只是"屏幕被截了一张图"，不产生任何发往服务器的请求。

**禁止使用**：WeChatFerry / wcferry / wechaty pad / Xposed / Hook 注入 / 群发 /
自动回复 / 加好友。这些是明确的封号路径，与本方案无关。

## 为什么是"截图 + OCR"（2026-09-15 实测，微信 4.0）

| 路径 | 结论 |
|------|------|
| Windows 通知库 `wpndatabase.db` | ❌ 微信 4.0 不写 toast，通知库里没有微信（197 个 handler 无微信） |
| UI Automation | ❌ 微信 4.0 是 Qt 自绘，UIA 树只有 1 个不透明面板 `MMUIRenderSubWindowHW`，零控件 |
| 本地数据库 | ❌ 加密，且相关工具已被腾讯 DMCA 追责（红线） |
| adb `dumpsys notification` | ❌ Android 6.0 起屏蔽正文 |
| **PrintWindow + RapidOCR** | ✅ 唯一可行的非侵入只读通道 |

## 文件

| 文件 | 职责 |
|------|------|
| `wx_read.py` | 采集引擎：窗口定位、截图、OCR、版面切分、消息解析、跨屏拼接、输入模拟 |
| `wx_collect.py` | 采集编排：被动/主动两种模式，会话查找，落库 |
| `wx_store.py` | SQLite 存储（`wxgroup.db`），指纹去重 |
| `wx_digest.py` | 汇总层：读库 → 按群调 LLM 生成投研日报 → markdown + 写回 days 表 |
| `groups.json` | 目标群配置（`--all` 模式用） |

## 用法

```bash
PY=EB-Agent/.venv/Scripts/python.exe      # 必须用项目 .venv（依赖见下）

# —— 采集 ——
$PY wx_collect.py --scan                    # 扫描整个会话列表（含折叠区），挑群用
$PY wx_collect.py --list                    # 只看当前可见的会话列表
$PY wx_collect.py --once                    # 采一次当前打开的聊天并落库（零交互）
$PY wx_collect.py --passive --interval 60   # 被动循环采集（零交互、不抢焦点）
$PY wx_collect.py --group "群名关键字" --pages 6   # 主动：找群→打开→翻 6 屏→落库
$PY wx_collect.py --all --pages 6           # 主动：groups.json 里的所有群
$PY wx_collect.py --stats                   # 库统计
$PY wx_collect.py --intrusive --group "XX"  # 改用 SendInput（会占鼠标，仅调试用）

# —— 汇总 ——
$PY wx_digest.py                            # 汇总今天全部群 → 日报_YYYY-MM-DD.md
$PY wx_digest.py --day 2026-09-15 --force   # 指定日期重算
$PY wx_digest.py --group "投研"              # 只汇总群名含关键字的
$PY wx_digest.py --dry                      # 只打印将发送的 prompt，不调模型
$PY wx_digest.py --min-msgs 20              # 消息太少的群跳过

# —— 调试 ——
$PY wx_read.py --probe                      # 打印带坐标的 OCR 原始结果（调参用）
$PY wx_read.py --dump C:/path/out.json      # 全量 dump（截图信息+OCR+行+解析），校准用
```

### 两种模式的区别

- **被动模式**（`--once` / `--passive`）：零交互。只截当前打开的那个会话。
  窗口最小化时会用 `SW_SHOWNOACTIVATE` 非激活还原一下再截、截完放回，
  **不抢前台焦点**。覆盖范围 = 你在微信里实际打开看过的群。
- **主动模式**（`--group` / `--all`）：会驱动客户端（点击 + 滚动），但**只读不发送**。
  默认走消息后端，**不占鼠标、不抢前台、窗口压在最底层**，用户可以照常干活。
  ⚠️ 副作用：点击会话会把该群**标记为已读**（微信自身行为，无法避免）。

## 对用户是否无感？（2026-09-15 实测）

| 操作 | 占鼠标？ | 抢前台？ | 遮挡窗口？ |
|------|---------|---------|-----------|
| 截图（PrintWindow） | 否 | 否 | 否 |
| 滚动（`WM_MOUSEWHEEL` 消息） | **否** | **否** | 否 |
| 点击（`WM_LBUTTONDOWN` 消息） | **否** | **否** | 否 |
| ~~SendInput 后端（旧实现）~~ | 是 | 是 | 是 |

实测：微信被最小化时跑完整采集，前台始终是别的程序（WorkBuddy / Edge），
鼠标坐标全程不变，跑完窗口自动放回最小化。

**唯一例外**：点"公众号""服务号"这类会弹出独立窗口的会话时，
微信自己会把新窗口拉到前台（这是微信行为，不是我们注入的）。

## 依赖

必须用 `EB-Agent/.venv/Scripts/python.exe`（沙箱 Python 缺依赖）：
`Pillow`、`numpy`、`rapidocr_onnxruntime`。
RapidOCR 是离线中英文 OCR，约 1.4 秒/屏。

## 实测踩过的坑（改代码前务必看）

1. **DPI 感知必须显式设置**。进程不设 DPI 感知时 `GetSystemMetrics` 返回 1280×720
   而真实屏幕 1920×1080，`GetWindowRect` 是逻辑坐标 —— 点击会全部打偏 1.5 倍，
   实际点到别的程序上。`wx_read.py` 在模块导入时调用
   `SetProcessDpiAwareness(2)` / `SetProcessDPIAware()`。**不要删。**

2. **最小化的窗口截出来是空白图**。`GetWindowRect` 对最小化窗口返回
   `(-32000,-32000,237,39)` 特征值，直接截图得到 237×39 废图（OCR 0 块）。
   即使用 `GetWindowPlacement` 拿到正确尺寸，PrintWindow 渲染最小化窗口仍是空白。
   **必须先用 `SW_SHOWNOACTIVATE` 还原**（不抢焦点），截完再 `SW_MINIMIZE` 放回。
   见 `wx_read.capture_silent()`。

3. **点击"已经打开的"会话会把它关掉**（微信 4.0 的切换行为）。
   `open_group` 必须先读标题栏，已在目标群就不要再点，否则聊天面板会被关成空状态。

4. **判断"打开了哪个群"只能看标题栏**。早期版本拿关键字匹配整屏 OCR 文字，
   而会话列表里永远有这个名字 → 永远误报成功（实测 5 屏全空却返回 True）。
   见 `wx_collect.chat_title()`。

5. **滚轮事件必须拆成多次**。把 `notches*120` 塞进单个 `mouseData`，
   Qt 的微信只按"一格"处理 —— `notches=60` 实际只滚 1 格。
   必须循环发 `abs(notches)` 个独立的 `MOUSEEVENTF_WHEEL` 事件。

6. **多屏拼接要在"行"层面做，不能逐条消息去重**。相邻两屏有重叠，
   OCR 对同一行在不同屏可能给出略有差异的文字，逐条精确去重会失效（内容重复出现），
   且跨屏的长消息会被截断。正确做法：先按行拼接（`stitch_rows`，精确归一化匹配 +
    `difflib` 模糊兜底），再切消息。

7. **发送者名比正文更靠左**。群聊里名字渲染在气泡上方、与气泡左边缘对齐，
   而气泡内正文有内边距 —— 实测名字 `x1=565`、正文 `x1=583`，差约 18px。
   所以"比正文列更靠左、且足够短"的行就是发送者名。
   正文列只统计**左侧行**（70 分位），否则自己发的右对齐消息会把列算偏。

8. **时间分隔有多种形态**：`10:30` / `昨天09:38` / `星期五12:59` / `9月15日 上午10:30`。
   正则只匹配裸"昨天"会漏掉绝大多数。

9. **`import fitz` 的弃用告警**由 C 层直写 stderr，`warnings` 过滤器压不住
   —— 用新模块名 `import pymupdf`。

10. **Git Bash 的 `/c/...` 路径不能传给 Windows Python**（会变成 `C:\c\...`）。
    命令行传路径一律用 `C:/...` 形式。

11. **调 LLM 必须显式传 `max_tokens`**（`wx_digest.py` 默认 1500）。
    本机 SenseNova API 的 **TPM 配额较紧**：不传 `max_tokens` 时服务端按模型最大值预留额度，
    哪怕 prompt 只有 1668 字符也会直接 `HTTP 429 (inference exceeds tpm/rpm limit)`。
    实测 `max_tokens=600` 可通过、缺省即失败。注意 `deepseek-v4-flash` 是**带思维链的模型**，
    一次 262 tokens 的输出里 194 是 reasoning —— 预算别卡太死，否则 `content` 会是空串。

12. **输入注入必须用"消息后端"，不要用 SendInput**。
    `SendMessageW(hwnd, WM_MOUSEWHEEL, ...)`（lParam 传**屏幕坐标**）和
    `SendMessageW(hwnd, WM_LBUTTONDOWN/UP, ...)`（lParam 传**客户区坐标**，
    先 `ScreenToClient`）能直接驱动微信 4.0（Qt），
    **不移动鼠标、不要求窗口在前台**。SendInput 会移动真实鼠标并要求窗口在前台，
    等于把用户电脑占住 —— 已降级为 `--intrusive` 调试选项。
    唯一要求：窗口**不能最小化**（最小化时消息滚轮不生效）。

13. **窗口最小化时滚轮坐标会算到屏幕外**。`GetWindowRect` 对最小化窗口返回
    `(-32000,-32000,237,39)`，拿它算滚动/点击锚点，滚轮就发到屏幕外了 ——
    表现为"**截图正常、标题正常，就是滚不动**"，极难排查。
    最小化时改用 `GetWindowPlacement` 的 `rcNormalPosition`（`wx_read.restored_rect`），
    并且用 `quiet_show()` 临时非激活还原 + `SetWindowPos(HWND_BOTTOM)` 压到最底层。

14. **跨屏拼接的重叠方向：向上翻时是"新屏尾部 == 累积头部"**。
    聊天向上翻看更早的消息，新一屏的**底部**与已累积内容的**顶部**重叠，
    拼接应为 `新屏去掉尾部重叠 + 累积内容`。
    若按网页向下滚动的语义写成 `累积 + 新屏[k:]`，则每次整段追加、完全不重叠，
    同一批消息被重复采集（实测 117 行里 6 行整段重复）。

15. **`settle` 不能小于 1.0 秒**。微信历史是**懒加载**的，翻上去后要等它渲染完再截，
    否则连续几屏截到同一画面、看起来像"滚不动"（实测 0.75s 会卡住，1.0s 稳）。
    另外 `notches` 建议 10：视口约 676px、每格约 50px，10 格 = 500px，
    留 176px 重叠（约 6 行）够拼接；太大就重叠不足，太小则效率低。

16. **判定"是否拿到前台焦点"要看 `GetForegroundWindow()`，不能只看
    `SetForegroundWindow` 是否抛异常**。Windows 会静默拒绝非前台进程的前台请求，
    此时 SendInput 点击会落到覆盖在微信之上的窗口上，而 PrintWindow 读标题一切正常。

## 汇总层（wx_digest.py）

读 `wxgroup.db` 里当天消息 → 按群拼转写文本 → 调 `app/core/llm.py`（`override={"backend":"api"}`
绕开 WorkBuddy 桥接，直连云 API）→ 生成 markdown 日报，同时写回 `days` 表的 `digest` 列做缓存。

日报结构固定五节：**今日要点 / 重要信息与数据 / 观点与分歧 / 待跟进 / 噪音过滤说明**。
系统提示里明确要求：只依据给定记录、不编造数字人名、OCR 可疑处标注而非猜测、
无投研价值的群直接说"本群今日无投研价值内容"而不硬凑。

已有摘要默认跳过，`--force` 重算。

## 版面参数（窗口 1365×1031 / 150% 缩放标定）

```
SESSION_W = 0.34    # 最左竖排导航栏 + 会话列表   x 0..465
HEADER_H  = 0.11    # 聊天区标题栏（群名）        y 0..113
INPUT_H   = 0.235   # 底部输入区（输入框+工具条）  y 789..1031
```

窗口尺寸变化时这些**比例**仍然适用。若用户改了微信字号或缩放，
用 `wx_read.py --probe` 重新核对一次。

## 已知局限

- 图片 / 表情 / 语音 / 文件 / 小程序卡片只 OCR 得到零星文字，内容会缺失或错乱。
- 长消息被气泡截断、分页处可能粘连；OCR 会有错别字（尤其生僻字、emoji）。
- 发送者名在滚动中被截断时，该条消息的 sender 会沿用上一位发送者。
- 主动模式会把群标记为已读。

## 后续

- 把"采集 + 汇总"串成定时任务（EB-Agent 平台任务，或 Windows 计划任务）。
- EB-Agent 前端加「微信群日报」页面，直接读 `wxgroup.db` + `days.digest`。
- 投递渠道未定：网页 / 企业微信群机器人 webhook（**不往个人微信回写**，保持只读）。
