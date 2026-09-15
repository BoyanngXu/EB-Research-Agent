---
name: wechat-gzh-crawler
description: 自动抓取微信公众号的 A 股盘前/午盘/复盘文章并转成宋体 Word 文档。通过微信读书「搜一搜」取最新公众号文章（比搜狗微信搜索时效更新），按当前时间自动研判关键词，抓最热前 N 篇。当用户说"抓今天的 A 股复盘""下载公众号午评""爬一下 A 股文章"时使用。
agent_created: true
---

# 微信公众号 A 股文章爬虫

## 用法

```bash
pip install -r requirements.txt
playwright install chromium

python scripts/wechat_gzh_crawler_weread.py                  # 自动研判关键词，抓 10 篇
python scripts/wechat_gzh_crawler_weread.py -n 20             # 抓 20 篇
python scripts/wechat_gzh_crawler_weread.py -k "A股午盘"      # 手动指定关键词
python scripts/wechat_gzh_crawler_weread.py -o D:\out         # 指定输出目录
```

Windows 双击 `运行爬虫.bat`，macOS/Linux 执行 `运行爬虫.command`。

**运行会弹浏览器要求扫码登录微信读书**（登录态存到 `login_state.json`，之后自动复用）。
扫码登录不可避，因此平台始终以**有头模式（headed）**运行，从不传 `--headless`
（无头模式在需要登录时会直接失败，因为没法扫码）。首次使用请在有图形界面的环境运行，
用微信扫一次码；之后同一份登录态可复用。

## 关键词自动研判

按运行时间选词，这是为了避免抓到隔夜的旧文章：

| 时间 | 关键词 | 说明 |
|------|--------|------|
| 11:30 前 | `A股盘前` | 盘前 + 早盘合并 |
| 11:30–15:00 | `A股午盘` | 午盘 + 午后合并 |
| 15:00 后 | `今日A股复盘` | 收盘后 |
| 周末 | `A股复盘` | 非交易日 |

## 输出

每篇一个独立 `.docx`，文件名 `序号_公众号名_文章标题.docx`。
文档格式：标题居中宋体 18 号，来源/发布时间居中 10 号，正文宋体 12 号、首行缩进 24 磅。

## 关键实现点

1. **直链提取靠劫持 `window.open`**：搜索结果列表项点击后会 `window.open` 跳文章，
   直接读 DOM 拿不到 href。做法是在 `page.evaluate` 里临时替换 `window.open`
   捕获 URL，点完立即还原。这是整个爬虫最脆弱也最核心的一步。
2. **中文字体必须设 `eastAsia`**：只设 `run.font.name = "宋体"` 不够，中文会掉回默认字体，
   必须同时写 `rPr.rFonts` 的 `w:eastAsia`。
3. **正文段落去重**：公众号正文 DOM 嵌套严重，用「跳过含子段落标签的元素」+
   去重保序来避免重复文本。
4. **优先系统 Chrome/Edge**：微信系页面对 Playwright 内置 Chromium 的指纹更敏感，
   用系统浏览器成功率更高。

## 排错

- **搜到 0 篇 / 直链全空** → 微信读书搜索页改版，需更新 `search_and_extract()`
  里的 CSS 选择器（`.search_list_item`、`.article__title-text`、`.source__title`）。
- **「未找到正文区域」** → 触发了微信的环境异常校验。等一会儿再跑，或减少并发篇数。
- **登录态失效** → 删掉 `login_state.json` 重新扫码。
- **中文乱码（mac/Linux 终端）** → 脚本已强制 `stdout` 为 UTF-8，仍异常时检查终端 locale。
