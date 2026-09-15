# -*- coding: utf-8 -*-
r"""可交换债数据.xlsx 重建脚本（通用版 / 可移植）

用途：根据某日目录下的 4 个源文件，自动重建「可交换债数据.xlsx」总表。

    上证固收成交明细.xlsx  —— 上证成交（手工从固收平台导出）
    可交债.xlsx            —— 标的清单（手工从 Wind 导出）
    现券交易信息（逐笔）.xlsx —— 深交所逐笔（AutoDownload_sz.py 自动下载）
    中证可交换债券估值.xlsx  —— 中证估值（AutoDownload_xx.py 自动下载）

用法：
    python 可交换债数据.py 20260817              # 相对日期目录，相对 --base 解析
    python 可交换债数据.py D:\Data\20260817      # 完整路径
    python 可交换债数据.py                       # 交互输入，直接回车取最新日期
    python 可交换债数据.py 20260817 --base D:\Data
    python 可交换债数据.py 20260817 --no-template # 强制用纯数值模板（不依赖任何既有 xlsx）

输出：日期目录下生成 可交换债数据.xlsx。已有旧版会先存档到 .analysis/。

------------------------------------------------------------------
设计要点（都是从真实事故里总结的，改动前请先读懂）
------------------------------------------------------------------
1. 行结构动态生成：按 可交债.xlsx 的标的顺序逐只展开，"有成交的每笔一行，
   无成交的单行列出"，不依赖固定行位 —— 成交笔数多少都不会错位或丢行。
2. 所有名称/利率/估值按证券代码前 6 位 VLOOKUP，不依赖源文件行号对齐。
3. 表外成交自动剔除：只保留出现在 可交债.xlsx 表内的标的成交
   （否则可转债如「申能转债」会混进来）。
4. B 列证券代码：裸 6 位数（无市场后缀）补 ".SZ"，已有 .SH/.SZ 后缀保留原样
   （先 TRIM 去尾随空格再判位数）。
5. 源文件名自动规范化（目标已存在则跳过不覆盖）：
       上证固收成交明细*.xlsx     -> 上证固收成交明细.xlsx
       中证可交换债券估值_*.xlsx  -> 中证可交换债券估值.xlsx
       现券交易信息（逐笔）*.xlsx -> 现券交易信息（逐笔）.xlsx
6. 写入与公式一致的缓存值并设 fullCalcOnLoad：打开即显示正确、重算也正确。
7. F/G/H 三列（成交金额、成交量、均价）为 0 或空时整格留空，不写公式不写缓存值。
8. 模板缺失兜底：找不到任何带外部链接的模板时，自动生成纯数值模板，
   保证全新环境也能跑通（只是没有公式联动）。

依赖：openpyxl
"""
import argparse
import datetime
import glob
import io
import os
import re
import shutil
import sys
import zipfile

try:
    import openpyxl
    from openpyxl.styles import Font, Alignment
    from openpyxl.utils import get_column_letter, column_index_from_string
except ImportError:
    print("=" * 58)
    print("缺少依赖库 openpyxl，请先执行：")
    print()
    print("    pip install openpyxl")
    print()
    print("也可以直接双击上级目录的「安装依赖.bat」一键完成。")
    print("=" * 58)
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\n按回车退出...")
    except Exception:
        pass
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
TEMPLATE_DIR = os.path.join(SKILL_DIR, "模板")

SOURCES = ["上证固收成交明细.xlsx", "可交债.xlsx", "现券交易信息（逐笔）.xlsx", "中证可交换债券估值.xlsx"]
OUT_NAME = "可交换债数据.xlsx"
HEADERS = ["日期", "证券代码", "证券名称", "正股代码", "正股简称",
           "成交金额（万元）", "成交量(张)", "成交均价（净价）",
           "票面利率(当期参考%)", "补偿利率（%）", "转股价格(元)", "正股收盘价(元)",
           "中证含权估值(元)", "期权价值(元)", "中证不含权估值(元)"]
NCOL = len(HEADERS)


# ---------------------------------------------------------------- 基础工具

def fmt_date(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    if v is None:
        return ""
    return str(v).strip()


def parse_amount(v):
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return 0.0


def norm_b(v):
    """B 列代码：裸 6 位补 .SZ，已有后缀保留。"""
    s = str(v).strip() if v is not None else ""
    return s + ".SZ" if len(s) == 6 else s


def is_code(v):
    return bool(re.match(r"^\d{6}", str(v).strip() if v is not None else ""))


def normalize_source_names(day_dir):
    rules = [
        ("上证固收成交明细*.xlsx", "上证固收成交明细.xlsx"),
        ("中证可交换债券估值_*.xlsx", "中证可交换债券估值.xlsx"),
        ("现券交易信息（逐笔）*.xlsx", "现券交易信息（逐笔）.xlsx"),
    ]
    for pattern, target_name in rules:
        target = os.path.join(day_dir, target_name)
        for fpath in glob.glob(os.path.join(day_dir, pattern)):
            if os.path.basename(fpath) == target_name:
                continue
            if os.path.exists(target):
                print(f"[跳过] 目标已存在，不覆盖：{os.path.basename(fpath)}")
                continue
            os.rename(fpath, target)
            print(f"[重命名] {os.path.basename(fpath)} -> {target_name}")


def load_day(day_dir):
    paths = {n: os.path.join(day_dir, n) for n in SOURCES}
    missing = [n for n, p in paths.items() if not os.path.exists(p)]
    if missing:
        sys.exit(f"[错误] {day_dir} 缺少源文件：{missing}")
    return tuple(
        openpyxl.load_workbook(paths[n], data_only=True).worksheets[0] for n in SOURCES
    )


# ---------------------------------------------------------------- 行计划

def build_plan(sse, kjz, xq):
    """返回 [("bond", kjz_row) | ("sse", sse_row) | ("xq", xq_row)]
    规则：只保留出现在 可交债.xlsx 表内的标的成交，表外成交一律剔除。"""
    sse_trades = [r for r in range(2, sse.max_row + 1) if is_code(sse.cell(row=r, column=4).value)]
    xq_trades = [r for r in range(2, xq.max_row + 1) if is_code(xq.cell(row=r, column=2).value)]
    kjz_bonds = [r for r in range(2, kjz.max_row + 1) if is_code(kjz.cell(row=r, column=1).value)]

    code_sse = lambda r: str(sse.cell(row=r, column=4).value).strip()[:6]
    code_xq = lambda r: str(xq.cell(row=r, column=2).value).strip()[:6]
    code_kjz = lambda r: str(kjz.cell(row=r, column=1).value).strip()[:6]

    kjz_codes = {code_kjz(k) for k in kjz_bonds}
    sse_trades = [r for r in sse_trades if code_sse(r) in kjz_codes]
    xq_trades = [r for r in xq_trades if code_xq(r) in kjz_codes]

    plan = []
    for k in kjz_bonds:
        c6 = code_kjz(k)
        t_sse = [r for r in sse_trades if code_sse(r) == c6]
        t_xq = [r for r in xq_trades if code_xq(r) == c6]
        if t_sse or t_xq:
            plan.extend(("sse", r) for r in t_sse)
            plan.extend(("xq", r) for r in t_xq)
        else:
            plan.append(("bond", k))
    return plan


def _lookup(ws, col=1):
    return {str(ws.cell(row=r, column=col).value).strip()[:6]: r
            for r in range(2, ws.max_row + 1) if is_code(ws.cell(row=r, column=col).value)}


def bond_info(kjz, code6):
    """(证券名称, 正股代码, 正股简称, 票面, 补偿, 转股价, 正股收盘) 或 None"""
    r = _lookup(kjz).get(code6)
    if not r:
        return None

    def g(col, zero=False):
        v = kjz.cell(row=r, column=col).value
        if v is None:
            return 0.0 if zero else ""
        s = str(v).strip()
        if s.startswith("#"):   # #NAME? / #N/A 等公式错误按空处理
            return "" if not zero else 0.0
        return v
    return g(2), g(3), g(4), g(5, True), g(6, True), g(7, True), g(8, True)


def gz_info(gz, code6):
    r = _lookup(gz).get(code6)
    if not r:
        return "", "", ""
    out = []
    for col in (5, 6, 7):
        v = gz.cell(row=r, column=col).value
        if v is None:
            out.append(0.0)
        else:
            s = str(v).strip()
            out.append("" if s.startswith("#") else v)
    return out


def build_rows(sse, kjz, xq, gz):
    plan = build_plan(sse, kjz, xq)
    date_str = fmt_date(sse.cell(row=3, column=2).value)
    if not date_str:
        for r in range(2, sse.max_row + 1):
            if is_code(sse.cell(row=r, column=4).value):
                date_str = fmt_date(sse.cell(row=r, column=2).value)
                break

    hval = lambda f, g: "" if g == 0 else round(f * 10000.0 / g, 4)

    rows = []
    for typ, src in plan:
        v = {}
        if typ == "bond":
            code6 = str(kjz.cell(row=src, column=1).value).strip()[:6]
            f = (sum(parse_amount(xq.cell(row=r, column=7).value) for r in range(2, xq.max_row + 1)
                     if is_code(xq.cell(row=r, column=2).value)
                     and str(xq.cell(row=r, column=2).value).strip()[:6] == code6)
                 + sum(parse_amount(sse.cell(row=r, column=13).value) for r in range(2, sse.max_row + 1)
                       if is_code(sse.cell(row=r, column=4).value)
                       and str(sse.cell(row=r, column=4).value).strip()[:6] == code6))
            g = (sum(parse_amount(xq.cell(row=r, column=6).value) * 100 for r in range(2, xq.max_row + 1)
                     if is_code(xq.cell(row=r, column=2).value)
                     and str(xq.cell(row=r, column=2).value).strip()[:6] == code6)
                 + sum(parse_amount(sse.cell(row=r, column=12).value) * 100 for r in range(2, sse.max_row + 1)
                       if is_code(sse.cell(row=r, column=4).value)
                       and str(sse.cell(row=r, column=4).value).strip()[:6] == code6))
            v[1], v[2] = date_str, norm_b(kjz.cell(row=src, column=1).value)
        elif typ == "sse":
            code6 = str(sse.cell(row=src, column=4).value).strip()[:6]
            f = parse_amount(sse.cell(row=src, column=13).value)
            g = parse_amount(sse.cell(row=src, column=12).value) * 100
            v[1], v[2] = fmt_date(sse.cell(row=src, column=2).value), norm_b(sse.cell(row=src, column=4).value)
        else:
            code6 = str(xq.cell(row=src, column=2).value).strip()[:6]
            f = parse_amount(xq.cell(row=src, column=7).value)
            g = parse_amount(xq.cell(row=src, column=6).value) * 100
            v[1], v[2] = fmt_date(xq.cell(row=src, column=1).value), norm_b(xq.cell(row=src, column=2).value)

        bi = bond_info(kjz, code6)
        v[3], v[4], v[5] = (bi[0], bi[1], bi[2]) if bi else ("", "", "")
        v[6], v[7], v[8] = round(f, 6), round(g, 6), hval(f, g)
        v[9], v[10], v[11], v[12] = (bi[3], bi[4], bi[5], bi[6]) if bi else ("", "", "", "")
        v[13], v[14], v[15] = gz_info(gz, code6)
        rows.append(((typ, src), v))
    return rows, date_str


# ---------------------------------------------------------------- 公式

def f_vlookup(r, col, table=2, wildcard=True):
    """外部链接索引：1=上证 2=可交债 3=现券 4=中证估值"""
    if wildcard:
        return f'IFERROR(VLOOKUP(LEFT($B{r},6)&"*",[{table}]可交债!$A:$H,{col},FALSE),"")'
    return f'IFERROR(VLOOKUP(LEFT($B{r},6),[{table}]中证可交换债券估值!$A:$H,{col},FALSE),"")'


def f_h(r):
    return f'IF(G{r}=0,"",ROUND(F{r}*10000/G{r},4))'


def f_bond_aggr(r):
    F = (f'SUMPRODUCT((LEFT(TRIM(\'[3]现券交易信息（逐笔）\'!$B$2:$B$500),6)=LEFT($B{r},6))'
         f'*(IFERROR(--SUBSTITUTE(\'[3]现券交易信息（逐笔）\'!$G$2:$G$500,",",""),0)))'
         f'+SUMIF([1]sheet1!$D$2:$D$500,LEFT($B{r},6)&"*",[1]sheet1!$M$2:$M$500)')
    G = (f'SUMPRODUCT((LEFT(TRIM(\'[3]现券交易信息（逐笔）\'!$B$2:$B$500),6)=LEFT($B{r},6))'
         f'*(IFERROR(--SUBSTITUTE(\'[3]现券交易信息（逐笔）\'!$F$2:$F$500,",",""),0)*100))'
         f'+SUMIF([1]sheet1!$D$2:$D$500,LEFT($B{r},6)&"*",[1]sheet1!$L$2:$L$500)*100')
    return F, G


def f_b_code(ref):
    return f'IF(LEN(TRIM({ref}))=6,TRIM({ref})&".SZ",TRIM({ref}))'


def build_formula(spec, row):
    typ, src = spec
    f = {}
    for c in range(1, NCOL + 1):
        if typ == "bond":
            if c == 1:
                f[c] = 'TEXT([1]sheet1!$B$3,"yyyy-mm-dd")'
            elif c == 2:
                f[c] = f_b_code(f'[2]可交债!A{src}')
            elif c in (3, 4, 5):
                f[c] = f_vlookup(row, c - 1)
            elif c == 6:
                f[c] = f_bond_aggr(row)[0]
            elif c == 7:
                f[c] = f_bond_aggr(row)[1]
            elif c == 8:
                f[c] = f_h(row)
            elif c in (9, 10, 11, 12):
                f[c] = f_vlookup(row, c - 4)
            else:
                f[c] = f_vlookup(row, c - 8, table=4, wildcard=False)
        elif typ == "sse":
            if c == 1:
                f[c] = f'TEXT([1]sheet1!B{src},"yyyy-mm-dd")'
            elif c == 2:
                f[c] = f_b_code(f'[1]sheet1!D{src}')
            elif c in (3, 4, 5):
                f[c] = f_vlookup(row, c - 1)
            elif c == 6:
                f[c] = f'[1]sheet1!M{src}'
            elif c == 7:
                f[c] = f'[1]sheet1!L{src}*100'
            elif c == 8:
                f[c] = f_h(row)
            elif c in (9, 10, 11, 12):
                f[c] = f_vlookup(row, c - 4)
            else:
                f[c] = f_vlookup(row, c - 8, table=4, wildcard=False)
        else:
            if c == 1:
                f[c] = f'\'[3]现券交易信息（逐笔）\'!A{src}'
            elif c == 2:
                f[c] = f_b_code(f'\'[3]现券交易信息（逐笔）\'!B{src}')
            elif c in (3, 4, 5):
                f[c] = f_vlookup(row, c - 1)
            elif c == 6:
                f[c] = f'VALUE(SUBSTITUTE(\'[3]现券交易信息（逐笔）\'!G{src},",",""))'
            elif c == 7:
                f[c] = f'VALUE(SUBSTITUTE(\'[3]现券交易信息（逐笔）\'!F{src},",",""))*100'
            elif c == 8:
                f[c] = f_h(row)
            elif c in (9, 10, 11, 12):
                f[c] = f_vlookup(row, c - 4)
            else:
                f[c] = f_vlookup(row, c - 8, table=4, wildcard=False)
    return f


# ---------------------------------------------------------------- 模板

def find_template(day_dir, extra_dirs):
    """按优先级找最近修改的 可交换债数据.xlsx：本 skill 的 模板/ 优先，其次 --base 下的日期目录。"""
    cands = []
    tpl = os.path.join(TEMPLATE_DIR, OUT_NAME)
    if os.path.exists(tpl):
        cands.append(tpl)
    for d in extra_dirs:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            p = os.path.join(d, name, OUT_NAME)
            if os.path.exists(p) and os.path.abspath(os.path.join(d, name)) != os.path.abspath(day_dir):
                cands.append(p)
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)


def style_plain(ws, nrow):
    """纯数值模板的极简排版：宋体 11 号、居中、冻结首行。"""
    font = Font(name="宋体", size=11)
    align = Alignment(horizontal="center", vertical="center")
    for c in range(1, NCOL + 1):
        cell = ws.cell(row=1, column=c)
        cell.value = HEADERS[c - 1]
        cell.font = font
        cell.alignment = align
    for r in range(1, nrow + 1):
        for c in range(1, NCOL + 1):
            ws.cell(row=r, column=c).font = font
            ws.cell(row=r, column=c).alignment = align
    for c, w in enumerate([12, 14, 16, 12, 12, 16, 14, 16, 18, 14, 14, 14, 16, 14, 18], start=1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A2"


# ---------------------------------------------------------------- 缓存值注入

def fmt_num(v):
    if isinstance(v, int):
        return str(v)
    s = format(float(v), ".15f").rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


def xml_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def inject_cached(zin, zout, values):
    """把公式的结果值写进 sheet1.xml 的 <v> 节点，保证未刷新链接时也能直接显示。"""
    with zipfile.ZipFile(zin) as zi, zipfile.ZipFile(zout, "w", zipfile.ZIP_DEFLATED) as zo:
        for item in zi.infolist():
            data = zi.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                xml = data.decode("utf-8")

                def repl(m):
                    attrs, body = m.group(1), m.group(2)
                    if "<f" not in body:
                        return m.group(0)
                    ref = re.search(r'r="([A-Z]+)(\d+)"', attrs)
                    if not ref:
                        return m.group(0)
                    v = values.get((int(ref.group(2)), column_index_from_string(ref.group(1))))
                    body = re.sub(r"<v\s*/>|<v>.*?</v>", "", body, flags=re.S)
                    fm = re.search(r"<f\b.*?(?:</f>|/>)", body, re.S)
                    idx = fm.end()
                    if v is None or v == "":
                        na = attrs if 't="' in attrs else attrs.rstrip() + ' t="str"'
                        return f"<c{na}>{body[:idx]}<v></v>{body[idx:]}</c>"
                    if isinstance(v, str):
                        na = attrs if 't="' in attrs else attrs.rstrip() + ' t="str"'
                        return f"<c{na}>{body[:idx]}<v>{xml_escape(v)}</v>{body[idx:]}</c>"
                    if isinstance(v, (int, float)):
                        return f"<c{attrs}>{body[:idx]}<v>{fmt_num(v)}</v>{body[idx:]}</c>"
                    return m.group(0)

                data = re.sub(r"<c\b([^>]*)>(.*?)</c>", repl, xml, flags=re.S).encode("utf-8")
            zo.writestr(item, data)


# ---------------------------------------------------------------- 主流程

def rebuild(day_dir, base_dirs, use_template=True):
    day_dir = os.path.abspath(day_dir)
    if not os.path.isdir(day_dir):
        sys.exit(f"[错误] 目录不存在：{day_dir}")

    normalize_source_names(day_dir)
    sse, kjz, xq, gz = load_day(day_dir)
    rows, date_str = build_rows(sse, kjz, xq, gz)
    print(f"[信息] 日期 {date_str}　数据行 {len(rows)}")

    out = os.path.join(day_dir, OUT_NAME)
    archive_dir = os.path.join(SKILL_DIR, ".analysis")
    os.makedirs(archive_dir, exist_ok=True)

    base = None
    if os.path.exists(out):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        arc = os.path.join(archive_dir, f"{date_str}_可交换债数据_旧版_{ts}.xlsx")
        shutil.copy2(out, arc)
        print(f"[存档] 旧版 -> {arc}")
        base = out
    elif use_template:
        base = find_template(day_dir, base_dirs)

    values = {}
    if base:
        print(f"[模板] 使用 {base}")
        wb = openpyxl.load_workbook(base, data_only=False)
        ws = wb.worksheets[0]
        for r in range(1, max(2 + len(rows), ws.max_row) + 1):
            for c in range(1, NCOL + 1):
                if ws.cell(row=r, column=c).value is not None:
                    ws.cell(row=r, column=c).value = None
        for c, h in enumerate(HEADERS, start=1):
            ws.cell(row=1, column=c).value = h
        for i, (spec, vals) in enumerate(rows):
            r = 2 + i
            fml = build_formula(spec, r)
            for c in range(1, NCOL + 1):
                v = vals.get(c, "")
                # F/G/H 为 0 或空时整格留空
                if c in (6, 7, 8) and (v == 0 or v == "" or v is None):
                    ws.cell(row=r, column=c).value = None
                    continue
                ws.cell(row=r, column=c).value = "=" + fml[c]
                values[(r, c)] = v
        wb.calculation.fullCalcOnLoad = True
        tmp = os.path.join(archive_dir, f"_rebuild_{os.path.basename(day_dir)}.xlsx")
        wb.save(tmp)
        inject_cached(tmp, out, values)
        os.remove(tmp)
    else:
        print("[模板] 未找到任何模板，自动生成纯数值模板（无外部链接公式）")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        for i, (spec, vals) in enumerate(rows):
            for c in range(1, NCOL + 1):
                v = vals.get(c, "")
                if c in (6, 7, 8) and (v == 0 or v == "" or v is None):
                    continue
                ws.cell(row=2 + i, column=c).value = v
        style_plain(ws, 1 + len(rows))
        wb.save(out)

    print(f"[完成] 已重建 -> {out}")


def main():
    ap = argparse.ArgumentParser(description="重建可交换债数据.xlsx（可移植版）")
    ap.add_argument("day", nargs="?", default=None, help="日期目录名（如 20260817）或完整路径；不传则交互输入")
    ap.add_argument("--base", default=SKILL_DIR, help="日期目录所在的根目录，默认本 skill 目录")
    ap.add_argument("--no-template", action="store_true", help="不使用既有模板，直接生成纯数值表")
    a = ap.parse_args()

    base = os.path.abspath(a.base)
    base_dirs = [base, SKILL_DIR]
    day = a.day

    if not day:
        dirs = [n for n in os.listdir(base) if re.fullmatch(r"\d{8}", n) and os.path.isdir(os.path.join(base, n))]
        latest = max(dirs) if dirs else ""
        day = input(f"请输入日期，直接回车自动选择最新日期 {latest}：").strip()
        if not day:
            if not latest:
                sys.exit(f"[错误] {base} 下未找到 yyyymmdd 格式的日期文件夹")
            day = latest
            print(f"[信息] 自动选择最新日期目录：{day}")
    elif not re.fullmatch(r"\d{8}", day):
        pass  # 当作完整路径处理
    else:
        day = os.path.join(base, day)

    rebuild(day, base_dirs, use_template=not a.no_template)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
