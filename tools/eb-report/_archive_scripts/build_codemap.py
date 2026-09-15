import subprocess, re, json, sys, os

ROOT = os.environ.get("REPORT_DIR", r"C:\Users\<用户名>\Desktop\Report\_analysis")

def qt_query(codes):
    # codes: list of 'sh688981' etc. returns raw stdout bytes
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "15", "-A", "Mozilla/5.0", url],
                           capture_output=True, timeout=25)
        return r.stdout
    except Exception as e:
        return b""

def parse(raw):
    # returns dict code->name (decoded gbk)
    out = {}
    for part in raw.decode("gbk", "ignore").split(";"):
        m = re.match(r'^v_(\w+)="(.*)"$', part.strip())
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key == "pv_none_match":
            continue
        f = val.split("~")
        if len(f) > 1 and f[1]:
            out[key] = f[1]
    return out

# 候选代码范围（沪A/科创板/深A/创业板）
codes = []
for x in range(600000, 606000): codes.append("sh%d" % x)
for x in range(688000, 689000): codes.append("sh%d" % x)
for x in range(1, 3000):        codes.append("sz%06d" % x)
for x in range(300000, 303000): codes.append("sz%d" % x)
print("candidate codes:", len(codes), file=sys.stderr)

codemap = {}
batch = 90
for i in range(0, len(codes), batch):
    chunk = codes[i:i+batch]
    raw = qt_query(chunk)
    if raw:
        codemap.update(parse(raw))
    if (i // batch) % 20 == 0:
        print("progress %d/%d got %d" % (i, len(codes), len(codemap)), file=sys.stderr)

print("total valid codes:", len(codemap), file=sys.stderr)
json.dump(codemap, open(os.path.join(ROOT, "codemap_qt.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("saved codemap_qt.json")
