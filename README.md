# EB 投研 Agent 平台

把 **Data（成交估值数据）／ Anno（公告情报）／ Wechat（市场舆情）** 三件事
整合进一个浏览器界面，并内置一个**首页对话助手（Agentic RAG）**；"必须读懂才能做"的环节由
**魔搭 ModelScope（OpenAI 兼容接口）** 承担。

服务本体**零依赖**（纯 Python 标准库），不装任何第三方包也能起；但 Data/Anno/Wechat 的工具脚本
需要 `openpyxl / pdfplumber / playwright / python-docx` 等，由 `.venv` 提供。
> 本仓库**不含 `.venv`**（体积大，已 gitignore）：clone 后按「三、运行环境」一条命令建好即可。
> 若你是从同事那**整目录拷来**（含 `.venv`），则可直接双击启动，无需自建环境。

---

## 一、启动

**双击 `启动平台.vbs`** 即可（推荐，不受 `.bat` 的 IE 安全区域拦截）。
也可以用 `启动平台.bat`，两者挑解释器的顺序一致：

1. 项目自带的 `.venv\Scripts\python.exe` ← **首选**，并用 `python -c "print(1)"` 冒烟验证，坏了会跳过
2. Doubao 沙箱自带解释器（`%LOCALAPPDATA%\Doubao\...\bases\*\python\python.exe`，版本目录会轮换，遍历不写死）
3. PATH 里的 `python`

端口被占用时 `.bat` 会自动换 9000/9001。

命令行启动（任何情况都可用）：

```bash
cd C:\Users\<用户名>\Desktop\EB-Agent
python main.py                 # 启动并自动开浏览器
python main.py --port 9000     # 8765 被占用时换端口
python main.py --no-browser    # 不开浏览器
```

打开 `http://127.0.0.1:8765`。服务只监听本机，不对外。

> 若本机 `python` 不在 PATH，改用完整解释器路径，例如：
> `C:\Users\<用户名>\AppData\Local\Microsoft\WindowsApps\python3.exe main.py`
> 或用 `py -3 main.py`（装了 Python Launcher 时）。

---

## 二、三个项目在页面上怎么用

### 📊 数据 Data
1. **下载**：点「下载中证估值（xxxxx）」「下载深交所逐笔」。
   首次登录xxxxx要扫码，**别勾无头**；深交所免登录，可无头。
2. **重建**：选日期目录 → 「重建总表」。页面会先检查 4 份源文件齐不齐，缺哪份标红。
3. **查看**：点产出文件名直接预览表格（不用开 Excel）。

### 📋 公告 Anno —— 平台的 AI 核心
1. **转储**：「开始转储」把目录里所有 PDF 转成 txt，扫描件（无文字层）自动渲染成 PNG 图片，精读时由模型读图识别。
2. **AI 精读**：勾选要处理的文本 → 「开始精读」。LLM 逐份提炼 9 个字段
   （公告日期／上市公司／可交换债／证券代码／标的股票／股票代码／换股价格／公告性质／内容摘要），
   摘要按「事件/要点式」130~360 字撰写，主线为 EB 违约风险 + 财务状况分析。结果表格**可直接编辑**改错。
3. **生成**：「保存精读结果」→ 「生成整理表」。列宽对齐成品大表，可整行粘进
   《每日可交换债公告整理.xlsx》。

### 📰 舆情 Wechat
- 不填关键词 → 按当前时间自动研判（盘前／午盘／复盘）。
- 首次跑要扫码登录微信读书，之后自动复用登录态。
- 抓完点标题直接读正文。

### 🤖 首页对话助手（Agentic RAG）
- 首页直接问投研问题，助手从 **9 类内部源**检索作答：历史对话 / 公告 Anno / 成交估值 Data / 晨会观点 /
  回测 / 舆情文章 / 舆情记忆 / 任务日志 / 精读口径。
- **模型下拉 10 档**：按魔搭官方档位标注「主流 / 旗舰」（主流 1 魔粒/次、旗舰 2 魔粒/次），默认 `Qwen/Qwen3.5-35B-A3B`。
- **检索不足自动补料（A+B）**：生成前先判检索证据够不够（片段数 / 对比类是否有可支撑正文）；不足则**先补抓舆情再答**，
  不把匮乏答案当结果。补抓还没好时前端显示**进度卡**（不回显半成品），抓完后台**自动补答**并替换答案，无需刷新或重问。

---

## 三、运行环境

### 服务器本体
**零依赖**，任何 Python 3.8+ 都能跑（标准库 http.server + urllib）。

### 跑工具脚本的解释器
Data/Anno/Wechat 的脚本需要 `openpyxl / pdfplumber / playwright / python-docx` 等。
平台会**自动探测机器上依赖最全的那个 Python**（总览 · 设置 页可查看、可手动指定）。
启动器优先用项目自带的 `.venv`，它已经装好下面这些，开箱即用。

**重建 `.venv`**（拷到新电脑后若虚拟环境失效）：

```bash
cd C:\Users\<用户名>\Desktop\EB-Agent
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
# 可选：只有「自动下载数据源」才需要，约 700MB（chromium 内核）
.venv\Scripts\python.exe -m pip install -r requirements-extra.txt
.venv\Scripts\python.exe -m playwright install chromium
```

缺依赖时：进 **总览 · 设置 → 运行环境**，点对应项的「安装」按钮，日志实时滚动。

> 注意：chromium 内核装在 `%LOCALAPPDATA%\ms-playwright`，**不在项目目录里**，
> 且跟 playwright 版本绑定——换版本后要重新 `playwright install chromium`。

---

## 四、模型 API（魔搭 ModelScope）

在 **总览 · 设置** 页填 API Key（只存本机 `config.json`，不上传；仓库里只有 `config.example.json` 模板）。
也可以设环境变量 `MODELSCOPE_API_KEY`，两者都没配时 AI 精读会提示配置。

- 接口为 OpenAI 兼容格式：`https://api-inference.modelscope.cn/v1`，主模型默认 `Qwen/Qwen3.5-35B-A3B`
  （免费主流档），可用 `Qwen/Qwen3.5-27B` 等；失败会沿**兜底链**（`fallback_models` / `fallback_providers`）自动降级（可改）。
- 点「测试连接」验证。右上角小圆点常显状态：绿=可用，灰=未知，红=不可用。

**余额不足/无资源包**时，AI 精读会失败，但下载／重建／抓取不受影响——
页面会明确提示去充值，不会静默报错。

### 省 token：WorkBuddy 桥接后端

不想花模型 API token，可以把 LLM 后端切到 **「WorkBuddy 桥接」**（总览 · 设置 页 → 模型后端）。
此模式**完全不联网、不调用任何 API**：

1. 在公告页点「开始精读」后，平台把每份公告的 prompt（系统提示 + 正文）写成文件，
   落在 `runtime/bridge/inbox/<id>.prompt.md`。
2. 公告页的 **「WorkBuddy 桥接」面板**会列出待处理 prompt；点「复制 prompt」，
   把它交给 WorkBuddy（就是你现在对话的这个助手）运行。
3. 把 WorkBuddy 返回的 JSON 贴到对应「结果」框，点「提交」——任务自动续跑、写表。
   也可以直接把 `{"content": "<JSON 文本>"}` 存成 `runtime/bridge/outbox/<id>.json`。

- 优点：**零外部 token**，且精读质量等于 WorkBuddy 本身。
- 代价：每份公告需要一次人工「复制 → 运行 → 贴回」的搬运（适合量不大、又要省成本时）。
- 批量精读时，面板会逐个列出所有待处理 prompt，逐个提交即可。

---

## 五、目录结构

```
EB-Agent/
├── main.py                 启动入口（python main.py）
├── 启动平台.bat             Windows 双击启动（可能被 IE 区域拦截）
├── 启动平台.vbs             双击启动（推荐，不被 .bat 的区域限制拦截）
├── config.json             配置（含 API Key / 工作区路径，本地文件，gitignore）
├── requirements.txt        核心依赖清单
├── requirements-extra.txt  可选依赖（自动下载用：playwright / ddddocr）
├── .venv/                  虚拟环境（gitignore，需自建；启动器首选）
├── app/
│   ├── core/               内核：配置 / 环境自检 / 文件护栏 / 任务系统 / LLM 客户端
│   ├── projects/           三个项目的业务封装（anno / data / wechat）
│   ├── web/                HTTP 服务与 API 路由
│   └── worker/             解析子进程（用装了依赖的解释器跑）
├── tools/                  四个 skill（可直接拷给同事 standalone 使用）
│   ├── eb-anno-digest/  eb-data-download/  eb-data-rebuild/  wechat-gzh-crawler/
├── web/                    前端单页（index.html / app.js / styles.css）
└── runtime/                日志、临时文件、产出
```

---

## 六、常见问题

| 现象 | 原因与处理 |
|------|-----------|
| 端口被占用 | `python main.py --port 9000` |
| AI 精读报「余额不足」 | 魔搭账户需充值，或换一个有余量的 Key |
| 预览表格报「缺依赖」 | 总览 · 设置 → 运行环境 → 点「安装」 |
| 抓取公众号卡在登录 | 微信读书必须**有窗口**扫码，平台已默认全部有头模式、无无头选项；登录态存本地后自动复用 |
| xxxxx下载失败 | 验证码识别需要窗口兜底，首次别勾无头 |
| 想换数据目录 | 总览 · 设置 → 工作区路径，改完保存 |

---

## 七、设计取舍

- **为什么不用 Flask/FastAPI**：要"拷给同事就能跑"，不能要求对方先配环境装包。
- **为什么服务器自己调 LLM**：用标准库 `urllib`，服务器进程保持零依赖；
  只有依赖第三方库的解析活儿（读 xlsx/PDF）才丢给子进程。
- **长任务为什么不阻塞 HTTP**：一律"先返回 task_id，前端订阅 SSE 看日志"，
  任务可随时「停止」（Windows 下连子进程树一起结束，不留孤儿 playwright）。
