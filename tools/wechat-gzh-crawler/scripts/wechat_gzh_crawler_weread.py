# -*- coding: utf-8 -*-
r"""微信公众号文章爬虫（微信读书搜索版）→ Word（宋体）

自动模式：
  - 关键词根据系统时间自动研判（盘前/午盘/复盘）
  - 下载搜索结果中最热的 N 篇
  - 每篇生成独立宋体 Word 文档

通过微信读书「搜一搜」获取最新公众号文章，比搜狗微信搜索时效更新。

依赖：
    pip install playwright beautifulsoup4 python-docx lxml requests
    playwright install chromium

用法：
    python wechat_gzh_crawler_weread.py                     # 自动研判关键词，抓 10 篇
    python wechat_gzh_crawler_weread.py -n 20               # 抓 20 篇
    python wechat_gzh_crawler_weread.py -k "A股午盘"        # 手动指定关键词
    python wechat_gzh_crawler_weread.py -o D:\out           # 指定输出目录
    python wechat_gzh_crawler_weread.py --headless          # 无头（不推荐：需登录时会因无法扫码而失败）

首次运行会弹出浏览器要求**扫码登录微信读书**，登录态保存在本 skill 根目录的
login_state.json，之后自动复用，不必每次扫码。

注意：搜索结果依赖微信读书的 `search.weixin.qq.com` 接口，页面结构改版时
需同步调整 search_and_extract() 里的 CSS 选择器。
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
STATE_FILE = os.path.join(SKILL_DIR, "login_state.json")

DEPS = {"playwright": "playwright", "bs4": "beautifulsoup4",
        "docx": "python-docx", "lxml": "lxml", "requests": "requests"}

_missing = []
for _mod, _pkg in DEPS.items():
    try:
        __import__(_mod)
    except ImportError:
        _missing.append(_pkg)
if _missing:
    print("=" * 58)
    print("缺少依赖库，请先执行：")
    print(f"    pip install {' '.join(_missing)}")
    print("    playwright install chromium")
    print()
    print("也可以直接双击上级目录的「安装依赖.bat」一键完成。")
    print("=" * 58)
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\n按回车退出...")
    except Exception:
        pass
    sys.exit(1)

import requests                                     # noqa: E402
from bs4 import BeautifulSoup                       # noqa: E402
from docx import Document                           # noqa: E402
from docx.shared import Pt                          # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH       # noqa: E402
from docx.oxml.ns import qn                         # noqa: E402
from playwright.sync_api import sync_playwright     # noqa: E402

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/122.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

WEREAD_HOME = "https://weread.qq.com/"
SEARCH_URL = ("https://search.weixin.qq.com/cgi-bin/newsearchweb/userclientjump"
              "?path=page/search/weread&query={query}&platform=pc")


# ---------------------------------------------------------------- 工具

def set_song(run, size=None):
    """设置宋体（含中文东亚字体，缺了 eastAsia 中文会掉回默认字体）。"""
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    if size:
        run.font.size = Pt(size)


def sanitize_filename(name):
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", "", name)
    return name[:50]


def auto_keyword():
    """按当前时间研判 A 股关键词：盘前 / 午盘 / 收盘复盘 / 周末。"""
    now = datetime.now()
    t = now.hour * 60 + now.minute
    if now.weekday() >= 5:
        kw, period = "A股复盘", "周末/非交易日"
    elif t < 11 * 60 + 30:
        kw, period = "A股盘前", "盘前（11:30 前，含早盘）"
    elif t < 15 * 60:
        kw, period = "A股午盘", "午盘（11:30-15:00，含午后）"
    else:
        kw, period = "今日A股复盘", "收盘后（15:00 后）"
    print(f"[自动研判] {now:%Y-%m-%d %H:%M} {period}")
    print(f"[自动研判] 搜索关键词：「{kw}」")
    return kw


# ---------------------------------------------------------------- 登录

def ensure_login(page, headless, timeout=180):
    """已登录直接返回；否则唤起扫码，等待最多 timeout 秒。"""
    if os.path.exists(STATE_FILE):
        try:
            ctx = page.context
            for c in json.load(open(STATE_FILE, encoding="utf-8")).get("cookies", []):
                ctx.add_cookies([c])
            page.goto(WEREAD_HOME, wait_until="domcontentloaded")
            time.sleep(3)
            if "我的书架" in page.inner_text("body") or "继续阅读" in page.inner_text("body"):
                print("[登录] 复用已保存的登录态")
                return True
        except Exception:
            pass

    page.goto(WEREAD_HOME, wait_until="domcontentloaded")
    time.sleep(5)

    if headless:
        print("[错误] 无头模式无法扫码登录。请先用有窗口模式登录一次，"
              "登录态会保存到 login_state.json。")
        return False

    print("[登录] 未检测到登录，唤起二维码...")
    page.evaluate("document.querySelectorAll('a').forEach(a => {"
                  "if (a.textContent.includes('登录')) a.click(); })")
    time.sleep(3)
    page.evaluate("var m=document.querySelector('.mask,.dialog_mask,.wr_overlay');if(m)m.click();")
    time.sleep(2)
    page.evaluate("document.querySelectorAll('a').forEach(a => {"
                  "if (a.textContent.includes('登录')) a.click(); })")
    time.sleep(5)

    print("\n" + "=" * 55)
    print("  请用微信扫描浏览器中的二维码登录")
    print(f"  登录成功后自动继续（最多等待 {timeout} 秒）")
    print("=" * 55 + "\n")

    waited = 0
    while waited < timeout:
        time.sleep(3)
        waited += 3
        try:
            txt = page.inner_text("body")
            if "我的书架" in txt or "继续阅读" in txt:
                print(f"[登录] 成功！（等待 {waited} 秒）")
                page.context.storage_state(path=STATE_FILE)
                print(f"[登录] 登录态已保存到 {STATE_FILE}")
                return True
        except Exception:
            pass
    raise RuntimeError(f"登录超时（{timeout} 秒未扫码），请重新运行。")


# ---------------------------------------------------------------- 搜索

def search_and_extract(page, keyword, count, max_scroll=3):
    """搜索并取最热前 count 篇，返回 [{title, desc, source, date, url}]。"""
    print(f"[搜索] 关键词「{keyword}」，取最热前 {count} 篇")
    page.goto(SEARCH_URL.format(query=urllib.parse.quote(keyword)),
              wait_until="domcontentloaded")
    time.sleep(6)

    print("[搜索] 加载结果...")
    for r in range(1, max_scroll + 1):
        for _ in range(2):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);"
                          "window.dispatchEvent(new Event('scroll'));")
            time.sleep(1)
        time.sleep(1.5)
        c = page.evaluate("document.querySelectorAll('.search_list_item').length")
        print(f"  第{r}轮: {c}篇")
        if c >= count * 3:
            break

    print("[搜索] 提取元数据...")
    arts_json = page.evaluate("""
        (() => {
            const arts = [];
            document.querySelectorAll('.search_list_item').forEach((item, i) => {
                const t = item.querySelector('.article__title-text');
                const d = item.querySelector('.article__desc');
                const s = item.querySelector('.source__title');
                const dt = item.querySelector('.source__text.date');
                arts.push({
                    idx: i,
                    title: (t?.textContent || '').trim(),
                    desc: (d?.textContent || '').trim().substring(0,200),
                    source: (s?.textContent || '').trim(),
                    date: (dt?.textContent || '').trim(),
                });
            });
            return JSON.stringify(arts);
        })()
    """)
    arts = json.loads(arts_json)
    print(f"  共搜到 {len(arts)} 篇，取前 {min(count, len(arts))} 篇")
    target = arts[:count]

    # 直链提取：劫持 window.open 捕获点击后跳转的 URL
    print("[搜索] 提取文章直链...")
    indices = [a["idx"] for a in target]
    urls_json = page.evaluate(f"""
        (async function() {{
            var sleep = ms => new Promise(r => setTimeout(r, ms));
            var items = document.querySelectorAll('.search_list_item');
            var results = [];
            var orig = window.open;
            var indices = {json.dumps(indices)};
            for (var k = 0; k < indices.length; k++) {{
                var i = indices[k];
                if (i >= items.length) {{ results.push({{idx:i,url:''}}); continue; }}
                var captured = '';
                window.open = function(u) {{ captured = u; return null; }};
                items[i].scrollIntoView({{block:'center', behavior:'instant'}});
                items[i].click();
                await sleep(100);
                window.open = orig;
                results.push({{idx:i, url:captured}});
            }}
            window.open = orig;
            return JSON.stringify(results);
        }})()
    """)
    url_map = {x["idx"]: x["url"] for x in json.loads(urls_json)}
    for a in target:
        a["url"] = url_map.get(a["idx"], "")

    print(f"[搜索] 直链提取完成：{sum(1 for a in target if a['url'])}/{len(target)} 篇成功")
    return target


# ---------------------------------------------------------------- 正文抓取

def fetch_article(url):
    """返回 (title, author, publish_time, [paragraphs])。"""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")

    title_tag = (soup.select_one("#activity-name") or soup.select_one(".rich_media_title")
                 or soup.select_one("h1"))
    title = title_tag.get_text(strip=True) if title_tag else "未知标题"

    author_tag = soup.select_one("#js_name") or soup.select_one(".profile_nickname")
    author = author_tag.get_text(strip=True) if author_tag else ""

    pub_tag = soup.select_one("#publish_time")
    publish_time = pub_tag.get_text(strip=True) if pub_tag else ""

    content = soup.select_one("#js_content") or soup.select_one(".rich_media_content")
    if not content:
        raise RuntimeError("未找到正文区域（可能触发了微信的环境异常校验）")

    paragraphs = []
    for el in content.find_all(["p", "section", "h1", "h2", "h3", "h4", "li"]):
        if el.find(["p", "section", "h1", "h2", "h3", "h4", "li"]):
            continue
        text = el.get_text(strip=True)
        if text and len(text) > 1:
            paragraphs.append(text)
    if not paragraphs:
        paragraphs = [ln.strip() for ln in content.get_text("\n", strip=True).split("\n") if ln.strip()]

    seen, clean = set(), []
    for p in paragraphs:
        if p not in seen:
            seen.add(p)
            clean.append(p)
    return title, author, publish_time, clean


def save_word(title, author, publish_time, paragraphs, filename, url=""):
    doc = Document()
    h = doc.add_heading(level=0)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_song(h.add_run(title), size=18)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    parts = []
    if author:
        parts.append(f"来源：{author}")
    if publish_time:
        parts.append(f"发布时间：{publish_time}")
    if parts:
        set_song(meta.add_run("    ".join(parts)), size=10)
    # 原文链接（Word 会把 http 文本识别为可点击链接）
    if url:
        link_p = doc.add_paragraph()
        link_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_song(link_p.add_run("原文链接：" + url), size=9)

    doc.add_paragraph("")
    for p in paragraphs:
        para = doc.add_paragraph()
        para.paragraph_format.first_line_indent = Pt(24)
        set_song(para.add_run(p), size=12)
    doc.save(filename)


def _write_meta(docx_path, title, author, publish_time, url, source):
    """写侧车 json，持久化原文链接等元数据（供平台检索/前端展示引用）。"""
    mp = docx_path + ".meta.json"
    try:
        with open(mp, "w", encoding="utf-8") as mf:
            json.dump({"title": title, "author": author,
                       "publish_time": publish_time, "url": url or "",
                       "source": source or ""}, mf, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="微信公众号 A 股复盘文章爬虫（微信读书搜索版）")
    ap.add_argument("-n", "--count", type=int, default=10, help="抓取篇数，默认 10")
    ap.add_argument("-k", "--keyword", default=None, help="手动指定关键词，默认按时间自动研判")
    ap.add_argument("-o", "--out", default=os.getcwd(), help="输出目录，默认当前目录")
    ap.add_argument("--headless", action="store_true", help="无头模式（不推荐：需扫码登录时会直接失败）")
    ap.add_argument("--scroll", type=int, default=3, help="滚动轮数，默认 3")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    keyword = args.keyword or auto_keyword()

    print("=" * 60)
    print("  微信公众号文章爬虫（微信读书搜索版）")
    print(f"  关键词「{keyword}」· 最热前 {args.count} 篇 · 每篇独立宋体 Word")
    print(f"  输出目录：{args.out}")
    print("=" * 60)

    with sync_playwright() as p:
        browser = None
        if not args.headless:
            for channel in ("chrome", "msedge"):
                try:
                    browser = p.chromium.launch(channel=channel, headless=False,
                                                args=["--start-maximized"])
                    break
                except Exception:
                    continue
        if browser is None:
            browser = p.chromium.launch(headless=args.headless)

        context = browser.new_context(viewport={"width": 1280, "height": 900},
                                      user_agent=HEADERS["User-Agent"])
        page = context.new_page()

        try:
            if not ensure_login(page, args.headless):
                browser.close()
                return 1
            articles = search_and_extract(page, keyword, args.count, args.scroll)
        finally:
            browser.close()

    total = len(articles)
    print(f"\n[下载] 开始批量爬取 {total} 篇...\n")
    ok = 0
    for i, art in enumerate(articles, start=1):
        if not art.get("url"):
            print(f"[{i}/{total}] 跳过（无直链）：{art['title'][:40]}")
            continue
        try:
            print(f"[{i}/{total}] {art['title'][:50]}")
            print(f"         来源：{art['source']} | {art['date']}")
            title, author, pub_time, paras = fetch_article(art["url"])
            fname = f"{i:02d}_{sanitize_filename(art['source'] or author)}_{sanitize_filename(title)}.docx"
            path = os.path.join(args.out, fname)
            save_word(title, author, pub_time or art["date"], paras, path, url=art["url"])
            _write_meta(path, title, author, pub_time or art["date"],
                        art["url"], art["source"])
            print(f"         ✓ {fname}（{len(paras)}段，约{sum(len(p) for p in paras)}字）")
            ok += 1
        except Exception as e:
            print(f"         ✗ 失败：{e}")
        time.sleep(1)

    print("\n" + "=" * 55)
    print(f"  全部完成！成功 {ok}/{total} 篇")
    print(f"  关键词：「{keyword}」　输出：{args.out}")
    print("=" * 55)
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[中断] 用户取消")
        sys.exit(130)
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            if sys.stdin and sys.stdin.isatty():
                input("\n按回车键退出...")
        except Exception:
            pass
        sys.exit(1)
