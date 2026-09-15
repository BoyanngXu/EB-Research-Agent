import json, re, zipfile, subprocess, os

BASE = os.environ.get("REPORT_DIR", r"C:\Users\<用户名>\Desktop\Report\_analysis")

def curl_json(url, timeout=20):
    try:
        out = subprocess.run(
            ["curl", "-s", "-A", "Mozilla/5.0", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=timeout+5)
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return json.loads(out.stdout)
    except Exception as e:
        return None

# 1) 东方财富全量 A股/港股 代码表（翻页）
map_name = {}
for pn in range(1, 52):
    url = (f"https://push2.eastmoney.com/api/qt/clist/get?pn={pn}&pz=100"
           f"&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:3,m:0+t:90&fields=f12,f14")
    d = curl_json(url)
    if not d:
        break
    diff = (d.get("data") or {}).get("diff") or {}
    if not diff:
        break
    for k, v in diff.items():
        code = v.get("f12"); name = v.get("f14")
        if code and name:
            map_name.setdefault(re.sub(r"[\s\-UW]", "", name).upper(), code)
    if len(diff) < 100:
        break
print("eastmoney map size:", len(map_name))

# 2) 649 去重标的
z = zipfile.ZipFile(os.path.join(BASE, "晨会分享分析总表.xlsx"))
xml = z.read("xl/worksheets/sheet2.xml").decode("utf-8")
rows = re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S)
def cv(r, col):
    m = re.search(r'<c r="%s\d+"[^>]*>(.*?)</c>' % col, r, re.S)
    if not m: return None
    c = m.group(1); it = re.search(r"<is><t[^>]*>(.*?)</t></is>", c, re.S)
    return it.group(1) if it else (re.search(r"<v>(.*?)</v>", c, re.S).group(1) if re.search(r"<v>(.*?)</v>", c, re.S) else None)
names = [cv(r, "B") for r in rows[1:]]; names = [x for x in names if x]; dist = set(names)
def norm(s): return re.sub(r"[\s\-UW]", "", s).upper()
resolved = {n: map_name.get(norm(n)) for n in dist}
ok = {n: c for n, c in resolved.items() if c}
print("去重标的:", len(dist), "| 解析到代码:", len(ok), "| 未解析:", len(dist) - len(ok))
unresolved = sorted(set(dist) - set(ok))
print("未解析样例:", unresolved[:60])
json.dump(ok, open(os.path.join(BASE, "resolve_map.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("saved resolve_map.json (%d)" % len(ok))
