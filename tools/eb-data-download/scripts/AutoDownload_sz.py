# -*- coding: utf-8 -*-
r"""深交所 现券交易信息（逐笔）—— 自动下载

流程：打开 bond.szse.cn 逐笔页面 → 用站点专用 JS 把「证券类别」设为
      「非公开发行可交换公司债券」→ 点查询 → 提取表格日期 → 触发导出 →
      捕获浏览器下载，保存为 <日期目录>/现券交易信息（逐笔）.xlsx

用法：
    python AutoDownload_sz.py                  # 有窗口模式（推荐）
    python AutoDownload_sz.py --headless       # 无头模式
    python AutoDownload_sz.py --download-dir D:\Data
    python AutoDownload_sz.py --url <页面URL>  # 页面改版时指定新地址

依赖：
    pip install playwright
    playwright install chromium

注意：导出前端触发、无登录要求，比xxxxx站点稳定；导出按钮文本改版时
      调整下方 EXPORT_CANDIDATES 即可。
"""
import argparse
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

C.check_deps(["playwright"])
C.install_no_input()

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout  # noqa: E402

DEFAULT_URL = "https://bond.szse.cn/marketdata/statistics/detail/bond/pbp/index.html"
TARGET_CATEGORY = "非公开发行可交换公司债券"

EXPORT_CANDIDATES = [
    ("text", "导出"),
    ("text", "导出Excel"),
    ("text", "导出全部"),
    ("text", "下载"),
    ("text", "下载数据"),
    ("locator", 'button:has-text("导出")'),
    ("locator", '.el-button:has-text("导出")'),
    ("locator", 'button:has-text("导出Excel")'),
]


def select_category(page):
    """深交所下拉是多选树（c-combotree），需要 JS：展开父节点 → 取消「全部」→ 勾选目标项。"""
    print(f"[操作] 用站点专用 JS 选择证券类别：{TARGET_CATEGORY}")
    try:
        page.evaluate("() => { document.querySelector('a.c-combotree-btn')?.click(); }")
        page.wait_for_timeout(500)

        page.evaluate("""() => {
            document.querySelectorAll('li[data-id]').forEach(li => {
                const nv = li.querySelector('.nodeValue');
                if (nv && ['债券', 'ABS'].includes(nv.textContent.trim())) {
                    const sw = li.querySelector('.switch');
                    if (sw && sw.className.includes('plus')) sw.click();
                }
            });
        }""")
        page.wait_for_timeout(500)

        page.evaluate("""() => {
            document.querySelectorAll('li[data-id]').forEach(li => {
                const nv = li.querySelector('.nodeValue');
                if (nv && nv.textContent.trim() === '全部') {
                    const cb = li.querySelector('[class*="check"]');
                    if (cb && cb.className.includes('glyphicon-check')) cb.click();
                }
            });
        }""")
        page.wait_for_timeout(300)

        page.evaluate("""(target) => {
            document.querySelectorAll('li[data-id]').forEach(li => {
                const nv = li.querySelector('.nodeValue');
                if (nv && nv.textContent.trim() === target) {
                    const cb = li.querySelector('[class*="check"]');
                    if (cb && cb.className.includes('glyphicon-unchecked')) cb.click();
                }
            });
        }""", TARGET_CATEGORY)
        page.wait_for_timeout(300)
        print("[信息] 类别选择完成")
    except Exception as e:
        print("[警告] 类别选择步骤异常，回退到通用策略（可能导出全部债券）:", e)


def main():
    ap = argparse.ArgumentParser(description="深交所：现券交易信息（逐笔）自动下载")
    ap.add_argument("--headless", action="store_true", help="无头模式")
    ap.add_argument("--download-dir", default=os.getcwd(),
                    help="保存根目录（默认当前目录），实际保存到其下的 <表格日期>/ 子目录")
    ap.add_argument("--url", default=DEFAULT_URL, help="目标页面 URL")
    ap.add_argument("--no-category", action="store_true", help="跳过证券类别筛选（导出全量）")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = C.launch_browser(p, args.headless)
        context = browser.new_context(accept_downloads=True, no_viewport=(not args.headless))
        page = context.new_page()

        print(f"[导航] 打开 {args.url}")
        page.goto(args.url, wait_until="domcontentloaded")
        if not args.headless:
            page.bring_to_front()
        page.wait_for_timeout(3000)

        C.click_candidates(page, [
            ("text", "现券交易信息（逐笔）"),
            ("text", "现券交易信息(逐笔)"),
            ("locator", 'a:has-text("现券交易信息（逐笔）")'),
            ("locator", 'a:has-text("现券交易信息(逐笔)")'),
        ], timeout=8000)
        page.wait_for_timeout(800)

        if not args.no_category:
            select_category(page)

        print("[操作] 点击「查询」")
        if not C.click_candidates(page, [
            ("role", "查询"),
            ("locator", 'button:has-text("查询")'),
            ("text", "查询"),
        ], timeout=10000):
            print("[警告] 未能点击「查询」，仍继续尝试导出")
        else:
            page.wait_for_timeout(1000)

        try:
            table_date = C.extract_table_date(page)
        except Exception as e:
            print("[错误] 无法从表格提取日期，停止下载:", e)
            if not args.headless:
                C.pause("检查后按回车退出...")
            browser.close()
            return 1
        target_dir = os.path.join(args.download_dir, table_date)
        print(f"[信息] 表格日期 {table_date} → 保存到 {target_dir}")

        saved = None
        for kind, sel in EXPORT_CANDIDATES:
            try:
                print(f"[尝试] 触发导出 ({kind}) {sel}")
                with page.expect_download(timeout=20000) as dl:
                    if not C.click_candidates(page, [(kind, sel)], timeout=8000):
                        raise RuntimeError("click failed")
                download = dl.value
                path = C.unique_path(target_dir, "现券交易信息（逐笔）.xlsx")
                try:
                    download.save_as(path)
                except Exception:
                    suggested = getattr(download, "suggested_filename", None) or "export.xlsx"
                    if not suggested.lower().endswith(".xlsx"):
                        suggested += ".xlsx"
                    path = C.unique_path(target_dir, suggested)
                    download.save_as(path)
                print(f"[完成] 已保存: {path}")
                saved = path
                break
            except PWTimeout:
                print("[超时] 等待下载超时，换下一个候选")
                continue
            except Exception as e:
                print("[信息] 该候选未触发下载:", e)
                continue

        if not saved:
            print("[错误] 未能触发下载。建议有窗口模式运行以查看页面；"
                  "若导出按钮改名，请修改脚本顶部 EXPORT_CANDIDATES。")
            if not args.headless:
                C.pause("检查后按回车退出...")
            browser.close()
            return 1

        if not args.headless:
            C.pause("\n下载完成，按回车关闭浏览器...")
        browser.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        C.pause("\n程序异常退出，按回车关闭窗口...")
        sys.exit(1)
