import json, re, zipfile, subprocess, sys, os
from concurrent.futures import ThreadPoolExecutor

BASE = os.environ.get("REPORT_DIR", r"C:\Users\<用户名>\Desktop\Report\_analysis")
codemap = json.load(open(os.path.join(BASE, "codemap_qt.json"), encoding="utf-8"))  # code -> name
# name -> code (normalized)
name2code = {}
for code, name in codemap.items():
    name2code.setdefault(re.sub(r"[\s\-UW]", "", name).upper(), code)

# 649 distinct 标的
z = zipfile.ZipFile(f"{BASE}/晨会分享分析总表.xlsx")
xml = z.read("xl/worksheets/sheet2.xml").decode("utf-8")
rows = re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S)
def cv(r, col):
    m = re.search(r'<c r="%s\d+"[^>]*>(.*?)</c>' % col, r, re.S)
    if not m: return None
    c = m.group(1); it = re.search(r"<is><t[^>]*>(.*?)</t></is>", c, re.S)
    return it.group(1) if it else (re.search(r"<v>(.*?)</v>", c, re.S).group(1) if re.search(r"<v>(.*?)</v>", c, re.S) else None)
names = [cv(r, "B") for r in rows[1:]]; names = [x for x in names if x]; dist = list(dict.fromkeys(names))
def norm(s): return re.sub(r"[\s\-UW]", "", s).upper()
resolved = [(n, name2code.get(norm(n))) for n in dist]
ok = [(n, c) for n, c in resolved if c]
print("去重标的:", len(dist), "| 解析到A股代码:", len(ok), "| 未解析:", len(dist) - len(ok), file=sys.stderr)
unresolved = sorted(set(dist) - {n for n, _ in ok})
print("未解析样例:", unresolved[:30], file=sys.stderr)

def fetch_kline(code):
    url = f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={code},day,2026-05-01,2026-09-08,320"
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "15", "-A", "Mozilla/5.0", url],
                           capture_output=True, timeout=25)
        d = json.loads(r.stdout.decode("utf-8", "ignore"))
        day = (d.get("data") or {}).get(code, {}).get("day") or []
        series = {row[0]: float(row[2]) for row in day if len(row) >= 3}
        return code, series
    except Exception as e:
        return code, {}

results = {}
with ThreadPoolExecutor(max_workers=16) as ex:
    for code, series in ex.map(fetch_kline, [c for _, c in ok]):
        if series:
            results[code] = series
print("kline 成功拉取:", len(results), "/ 解析出的", len(ok), "只", file=sys.stderr)
json.dump(results, open(f"{BASE}/_bt_quote_cache_full.json", "w", encoding="utf-8"))
# 统计每个的交易日数
lens = [len(v) for v in results.values()]
print("交易日数 min/median/max:", min(lens), sorted(lens)[len(lens)//2], max(lens), file=sys.stderr)
print("saved _bt_quote_cache_full.json with", len(results), "codes")
# 输出解析清单供核对
json.dump(ok, open(os.path.join(BASE, "resolved_ok.json"), "w", encoding="utf-8"), ensure_ascii=False)
