# -*- coding: utf-8 -*-
r"""易知（yizhi.poticat.com）中证可交换债券估值 —— 自动登录并下载

流程：打开登录页 → 自动填账号密码 → ddddocr 多模型投票识别验证码 →
      登录成功后导航到「中证可交换债券估值」→ 点查询 → 提取表格日期 →
      从页面 localStorage/cookie 取 Token → POST 下载 API 存为
      <日期目录>/中证可交换债券估值_YYYYMMDD.xlsx

用法：
    python AutoDownload_yz.py                     # 有窗口模式（推荐，验证码失败可手动补）
    python AutoDownload_yz.py --headless          # 无头模式（后台跑，识别不了验证码会跳过）
    python AutoDownload_yz.py --download-dir D:\Data
    python AutoDownload_yz.py --target-url <完整页面URL>   # 跳过菜单导航，直接操作该页

依赖：
    pip install playwright ddddocr pillow
    playwright install chromium

账号配置：复制同目录 config.example.ini 为 config.ini 并填写（勿提交给他人）。
"""
import argparse
import base64
import collections
import datetime
import io
import json as _json
import os
import sys
import traceback
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

C.check_deps(["playwright", "ddddocr", "PIL"])
C.install_no_input()

from PIL import Image, ImageEnhance  # noqa: E402
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout  # noqa: E402

LOGIN_URL = "https://yizhi.poticat.com/login"
DOWNLOAD_API = "https://yizhi.poticat.com/api/bond/download-csicbvaluation"
MAX_LOGIN_RETRY = 3
MAX_CAPTCHA_REFRESH = 6
CAPTCHA_LEN = 5
STATE_FILE = os.path.join(C.SKILL_DIR, "login_state.json")

_ocr_default = None
_ocr_beta = None


def _get_ocr():
    global _ocr_default, _ocr_beta
    if _ocr_default is None:
        import ddddocr
        _ocr_default = ddddocr.DdddOcr(show_ad=False)
        try:
            _ocr_beta = ddddocr.DdddOcr(show_ad=False, beta=True)
        except Exception:
            _ocr_beta = None
    return _ocr_default, _ocr_beta


def _build_variants(img_bytes):
    """对验证码生成多种预处理变体（原图/灰度/二值化/对比度增强 × 2x/3x 放大），提升 OCR 命中率。"""
    img = Image.open(io.BytesIO(img_bytes))
    w, h = img.size
    gray = img.convert("L")
    variants = []

    for scale in (1, 2, 3):
        im = img if scale == 1 else img.resize((w * scale, h * scale), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        variants.append(buf.getvalue())

    for scale in (2, 3):
        g = gray.resize((w * scale, h * scale), Image.LANCZOS)
        buf = io.BytesIO()
        g.save(buf, format="PNG")
        variants.append(buf.getvalue())

    for thresh in (100, 120, 128, 140, 150):
        bw = gray.point(lambda x, t=thresh: 255 if x > t else 0, mode="1")
        bw2 = bw.resize((w * 2, h * 2), Image.LANCZOS)
        buf = io.BytesIO()
        bw2.save(buf, format="PNG")
        variants.append(buf.getvalue())

    hc = ImageEnhance.Contrast(gray).enhance(2.0).resize((w * 2, h * 2), Image.LANCZOS)
    buf = io.BytesIO()
    hc.save(buf, format="PNG")
    variants.append(buf.getvalue())
    return variants


def recognize_captcha(page, headless):
    """多预处理变体 + 双模型投票；无共识则点击刷新重试。返回小写验证码或 None。"""
    ocr_default, ocr_beta = _get_ocr()
    for rnd in range(1, MAX_CAPTCHA_REFRESH + 1):
        cap = page.locator('img[src^="data:image"]').first
        if cap.count() == 0:
            cap = page.locator("img").nth(1)
        try:
            src = cap.get_attribute("src", timeout=5000)
        except PWTimeout:
            print("[OCR] 未找到验证码图片")
            return None
        if not src or not src.startswith("data:image"):
            print("[OCR] 验证码图片格式异常")
            return None

        img_bytes = base64.b64decode(src.partition(",")[2])
        candidates = []
        for v in _build_variants(img_bytes):
            for ocr in (ocr_default, ocr_beta):
                if ocr is None:
                    continue
                r = ocr.classification(v).strip()
                if len(r) == CAPTCHA_LEN and r.isalnum():
                    candidates.append(r.lower())

        if candidates:
            counter = collections.Counter(candidates)
            best, votes = counter.most_common(1)[0]
            print(f"[OCR] 第{rnd}轮 {dict(counter)} → 采用 {best!r} ({votes}/{len(candidates)})")
            if votes >= 2 or len(candidates) == 1:
                return best

        print(f"[OCR] 第{rnd}轮无共识，刷新验证码重试...")
        if rnd < MAX_CAPTCHA_REFRESH:
            cap.click()
            page.wait_for_timeout(1000)
    return None


def do_login(page, headless, email, password):
    page.get_by_placeholder("邮箱").fill(email)
    page.get_by_placeholder("密码").fill(password)

    text = recognize_captcha(page, headless)
    if not text:
        if headless:
            print("[OCR] 无头模式无法手动输入验证码，本次跳过（建议改用有窗口模式）")
            return False
        print("[OCR] 自动识别多次失败，请在浏览器里手动输入验证码后，回到本窗口按回车...")
        page.get_by_placeholder("验证码").click()
        C.pause("输入完成后按回车继续 > ")
    else:
        page.get_by_placeholder("验证码").fill(text)

    page.get_by_role("button", name="登录").click()
    page.wait_for_timeout(3000)

    if "login" not in page.url:
        return True

    try:
        body = page.locator("body").inner_text(timeout=2000)
        for kw in ("验证码错误", "验证码不正确", "验证码不能", "密码错误", "账号不存在", "登录失败"):
            if kw in body:
                for line in body.splitlines():
                    if kw in line:
                        print(f"[登录] 页面提示: {line.strip()}")
                        break
                break
    except Exception:
        pass
    return False


def api_download(token, enddate, download_dir):
    """POST 到下载接口，保存为 中证可交换债券估值_YYYYMMDD.xlsx，返回路径。"""
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://yizhi.poticat.com",
        "Referer": "https://yizhi.poticat.com/bond/csicbvaluation",
        "Token": token,
        "User-Agent": "AutoDownload/1.0",
    }
    body = {"filename": f"_{enddate.replace('-', '')}.xlsx", "enddate": enddate}
    req = urllib.request.Request(
        DOWNLOAD_API, data=_json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        if resp.getcode() != 200:
            raise RuntimeError(f"下载接口返回状态码 {resp.getcode()}")
        content = resp.read()

    path = C.unique_path(download_dir, f"中证可交换债券估值_{enddate.replace('-', '')}.xlsx")
    with open(path, "wb") as fh:
        fh.write(content)
    return path


def _find_token(page, context, fallback):
    # 1) 已知 token 名优先
    for key in ("Token", "token", "accessToken", "Authorization", "authToken", "tokenKey"):
        try:
            v = page.evaluate("() => window.localStorage.getItem('%s')" % key)
            if v:
                print("[Token] 从 localStorage 获取，key=%s" % key)
                return v
        except Exception:
            pass
    # 2) 放宽：遍历所有 localStorage，关键词命中优先，否则取最长类 token 串
    try:
        items = page.evaluate(
            "() => { const o={}; try{ for(let i=0;i<localStorage.length;i++){ const k=localStorage.key(i); o[k]=localStorage.getItem(k);} }catch(e){} return o; }"
        )
        cands = []
        for k, v in items.items():
            if not v:
                continue
            kl = k.lower()
            if any(t in kl for t in ("token", "auth", "jwt", "access")):
                cands.insert(0, (k, v))          # 关键字命中排最前
            elif len(v) >= 24:
                cands.append((k, v))
        cands.sort(key=lambda x: -len(x[1]))
        if cands:
            print("[Token] 从 localStorage 获取，key=%s" % cands[0][0])
            return cands[0][1]
    except Exception:
        pass
    # 3) cookie：已知名优先，未知名但值较长也试
    try:
        for c in context.cookies():
            n = (c.get("name") or "").lower()
            val = c.get("value") or ""
            if n in ("token", "auth", "authorization", "access_token") or len(val) >= 24:
                print("[Token] 从 cookie 获取，name=%s" % c.get("name"))
                return val
    except Exception:
        pass
    if fallback:
        print("[Token] 未能从页面提取，使用备用 token（config.ini 或内置兜底）")
        return fallback
    # 4) 诊断：把页面所有 localStorage key 与 cookie 名打出来，便于定位改版后的真实 key
    try:
        lk = page.evaluate("() => { const a=[]; try{ for(let i=0;i<localStorage.length;i++) a.push(localStorage.key(i)); }catch(e){} return a; }")
        ck = [c.get("name") for c in context.cookies()]
        print("[诊断] localStorage keys: %s" % lk)
        print("[诊断] cookie names: %s" % ck)
    except Exception:
        pass
    return None


MENU_TEXT = "中证可交换债券估值"
MENU_XPATH = "/html/body/div[1]/div/div/div[1]/aside/div/div[1]/div/div/ul/li/ul/li[1]"


def main():
    ap = argparse.ArgumentParser(description="易知：中证可交换债券估值 自动下载")
    ap.add_argument("--headless", action="store_true", help="无头模式（不弹窗）")
    ap.add_argument("--download-dir", default=os.getcwd(),
                    help="保存根目录（默认当前目录），实际保存到其下的 <表格日期>/ 子目录")
    ap.add_argument("--target-url", default=None, help="已知目标页完整 URL 时直接打开，跳过菜单导航")
    args = ap.parse_args()

    cfg = C.load_config("yizhi")
    email = cfg.get("email", "")
    password = cfg.get("password", "")
    # 兜底 Token：易知站点的会话 Token 长期有效，页面自动提取经常失败（站点改版），
    # 因此优先从 config.ini 的 [yizhi] 段读取 token。开源版本不再硬编码任何真实 Token，
    # 请自行在 config.ini 中填写（见 config.ini.example）。
    HARDCODED_FALLBACK_TOKEN = ""
    fallback_token = cfg.get("token", "") or HARDCODED_FALLBACK_TOKEN
    if not email or not password:
        print("[错误] config.ini 的 [yizhi] 段未填写 email / password")
        C.pause("\n按回车退出...")
        return 1

    with sync_playwright() as p:
        browser = C.launch_browser(p, args.headless)
        context = browser.new_context(accept_downloads=True, no_viewport=(not args.headless))
        page = context.new_page()

        print(f"[导航] 打开登录页 {LOGIN_URL}")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        if not args.headless:
            page.bring_to_front()
        page.wait_for_timeout(3000)

        ok = False
        for attempt in range(1, MAX_LOGIN_RETRY + 1):
            print(f"[登录] 第 {attempt}/{MAX_LOGIN_RETRY} 次尝试")
            try:
                if do_login(page, args.headless, email, password):
                    ok = True
                    break
            except Exception as e:
                print("[错误] 登录过程异常:", e)
            print("[信息] 未成功，刷新页面重试")
            try:
                page.reload()
            except Exception:
                pass
            page.wait_for_timeout(1000)

        if not ok:
            print("[错误] 自动登录多次失败，终止（检查 config.ini 账号密码，或改用有窗口模式手动输入验证码）")
            if not args.headless:
                C.pause("按回车关闭浏览器...")
            browser.close()
            return 1

        try:
            context.storage_state(path=STATE_FILE)
            print(f"[信息] 登录状态已保存 {STATE_FILE}")
        except Exception:
            print("[警告] 登录状态保存失败，继续执行")

        url = args.target_url or LOGIN_URL.replace("/login", "/")
        print(f"[导航] 打开目标页 {url}")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        if not args.target_url:
            try:
                print(f"[操作] 点击菜单「{MENU_TEXT}」")
                page.get_by_text(MENU_TEXT, exact=False).click(timeout=8000)
                page.wait_for_timeout(800)
            except Exception:
                print("[回退] 用 XPath 定位菜单")
                try:
                    page.wait_for_selector(f"xpath={MENU_XPATH}", timeout=10000)
                    loc = page.locator(f"xpath={MENU_XPATH}")
                    loc.scroll_into_view_if_needed()
                    try:
                        loc.click(timeout=8000)
                    except Exception:
                        page.eval_on_selector(f"xpath={MENU_XPATH}", "el => el.click()")
                    page.wait_for_timeout(800)
                except Exception as e:
                    print("[错误] 文本与 XPath 均无法点击菜单:", e)
                    if not args.headless:
                        C.pause("按回车关闭浏览器...")
                    browser.close()
                    return 1

        print("[操作] 点击「查询」")
        if not C.click_candidates(page, [
            ("role", "查询"),
            ("locator", 'button:has-text("查询")'),
            ("locator", '.el-button:has-text("查询")'),
            ("text", "查询"),
        ], timeout=10000):
            print("[错误] 未能点击「查询」")
            if not args.headless:
                C.pause("按回车关闭浏览器...")
            browser.close()
            return 1
        page.wait_for_timeout(1200)

        token = _find_token(page, context, fallback_token)
        if not token:
            print("[错误] 未能取得 Token，且 config.ini 未配置备用 token")
            if not args.headless:
                C.pause("按回车关闭浏览器...")
            browser.close()
            return 1

        try:
            table_date = C.extract_table_date(page)
        except Exception as e:
            print("[错误] 无法从表格提取日期:", e)
            if not args.headless:
                C.pause("检查后按回车退出...")
            browser.close()
            return 1
        enddate = f"{table_date[:4]}-{table_date[4:6]}-{table_date[6:]}"
        target_dir = os.path.join(args.download_dir, table_date)
        print(f"[信息] 表格日期 {table_date} → 保存到 {target_dir}")

        try:
            saved = api_download(token, enddate, target_dir)
            print(f"[完成] 已保存: {saved}")
        except Exception as e:
            print("[错误] API 下载失败:", e)
            if not args.headless:
                C.pause("按回车关闭浏览器...")
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
