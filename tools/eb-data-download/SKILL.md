---
name: eb-data-download
description: 自动下载可交换债每日数据源。覆盖两个站点——易知（yizhi.poticat.com）的「中证可交换债券估值」，以及深交所（bond.szse.cn）的「现券交易信息（逐笔）」。自动处理登录验证码、菜单导航、表格日期识别，按日期建子目录归档。当用户说"下载可交换债数据""拉取今天的估值/逐笔成交""跑一下数据源下载"时使用。
agent_created: true
---

# 可交换债数据源自动下载

把每天手工点网页下载数据的动作自动化。产出两个 xlsx，落到 `<保存根目录>/<YYYYMMDD>/` 下，
文件名与后续「合并重建」环节要求的源文件名严格一致。

## 产出文件

| 脚本 | 产出 | 落到 |
|------|------|------|
| `scripts/AutoDownload_yz.py` | `中证可交换债券估值_YYYYMMDD.xlsx` | `<dir>/<日期>/` |
| `scripts/AutoDownload_sz.py` | `现券交易信息（逐笔）.xlsx` | `<dir>/<日期>/` |

日期不是今天，而是**从页面表格里抓出来的数据日期** —— 避免早上下 yesterday 数据却存成今天的目录。

## 前置条件

```bash
pip install -r requirements.txt
playwright install chromium
```

易知站点还需要 `config.ini`（从 `config.example.ini` 复制并填账号密码）。深交所页面无需登录。

## 用法

```bash
# 易知：中证可交换债券估值（需登录 + 验证码识别）
python scripts/AutoDownload_yz.py --download-dir D:\Data

# 深交所：现券交易信息（逐笔）（免登录，自动筛选「非公开发行可交换公司债券」）
python scripts/AutoDownload_sz.py --download-dir D:\Data
```

常用参数：
- `--headless` 无头后台运行。易知站点验证码识别失败时无头模式无法手动兜底，**首次运行建议有窗口**。
- `--download-dir` 保存根目录，脚本会自动在其下建日期子目录。
- `--target-url` / `--url` 页面改版时直接指定新地址，跳过菜单导航。

Windows 用户双击 `运行_易知估值.bat` / `运行_深交所逐笔.bat` 即可，会交互式询问模式和目录。

## 关键实现点

**验证码识别**（易知）不是单次 OCR 就提交，而是：对同一张验证码生成 10 种预处理变体
（原图 / 灰度 / 5 档阈值二值化 / 对比度增强，各配 2x、3x 放大），每种变体跑 ddddocr 的
default 和 beta 两个模型，全部结果投票，**至少 2 票一致才采纳**，否则点击图片刷新重试，
最多 6 轮。这是把识别成功率从"时灵时不灵"拉到稳定可用的关键。

**Token 获取**优先从页面 `localStorage` 依次试 `Token`/`token`/`accessToken`/`Authorization`
等 key，再退到 cookie，最后才用 `config.ini` 里的备用 token（会过期，留空更安全）。

**深交所类别筛选**用的是站点专用 JS：那个下拉是 `c-combotree` 多选树，常规点击打不开，
需要依次执行"点触发器 → 展开【债券】【ABS】父节点 → 取消【全部】勾选 → 勾选
【非公开发行可交换公司债券】"四步 `page.evaluate`。

## 排错

- **登录反复失败** → 改用有窗口模式，脚本会在自动识别失败后暂停等你手动输入验证码。
- **点不到菜单/按钮** → 站点改版。有窗口模式下观察页面，把新选择器补进
  `MENU_XPATH`（易知）或 `EXPORT_CANDIDATES`（深交所）。
- **playwright 报缺浏览器** → 执行 `playwright install chromium`。
- **导出了全量债券而非只有可交换债** → 类别筛选 JS 失效了，加 `--no-category` 确认，
  然后改 `select_category()` 适配新的下拉结构。

## 下一步

下载完的 `中证可交换债券估值_YYYYMMDD.xlsx` 和 `现券交易信息（逐笔）.xlsx` 放进日期目录后，
配合 `上证固收成交明细.xlsx`、`可交债.xlsx`（这两个目前仍需手工从 Wind/上证固收导出），
交给 **eb-data-rebuild** skill 合并重建总表。
