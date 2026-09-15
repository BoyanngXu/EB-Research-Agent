# -*- coding: utf-8 -*-
import json, zipfile, re, subprocess, os, bisect, openpyxl
from collections import defaultdict

BASE = os.environ.get("REPORT_DIR", r"C:\Users\<用户名>\Desktop\Report\_analysis")
OUT = os.path.join(BASE, "F观点命中回测_板块.html")
XLSX = os.path.join(BASE, "晨会分享分析总表.xlsx")

# 1) 行情
quotes = json.load(open(os.path.join(BASE, "_bt_quote_cache_full.json"), encoding="utf-8"))
# 指数/ETF
idx = {}
for code in ["sh000300", "sh512480", "sh515700", "sh512660"]:
    try:
        d = json.load(open(os.path.join(BASE, f"idx_{code}.json"), encoding="utf-8"))
        day = (d.get("data") or {}).get(code, {}).get("day") or []
        idx[code] = {r[0]: float(r[2]) for r in day if len(r) >= 3}
    except Exception as e:
        print("idx fail", code, e)
allq = dict(quotes); allq.update(idx)

# 2) 代码->名称
codemap = json.load(open(os.path.join(BASE, "codemap_qt.json"), encoding="utf-8"))
name_of = lambda c: codemap.get(c, c)
# 标的名->代码 (fetch_klines 阶段解析好的 452 条)
resolve = {n: c for n, c in json.load(open(os.path.join(BASE, "resolved_ok.json"), encoding="utf-8"))}

# 评级 -> 方向分组 & 日期归一化（A列 YYYYMMDD -> YYYY-MM-DD）
BULL = {'强推', '推荐', '关注'}      # 看多类(红/黄)
BEAR = {'负面', '提示风险', '谨慎'}  # 看空类(绿)
NEU  = {'中性', '仅提及'}            # 中性类(黄/蓝)
def norm_date(a):
    if not a: return None
    a = str(a).strip()
    if re.fullmatch(r'\d{8}', a): return f"{a[0:4]}-{a[4:6]}-{a[6:8]}"
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', a): return a
    return None

# 3) Excel: 板块(C) -> 标的(B) + 方向(D) + 日期(A)  (用 openpyxl 读, 兼容 inlineStr/sharedStrings)
_wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
_ws = _wb['标的明细']
_h = [c.value for c in _ws[1]]
_an = _h.index('日期') + 1
_bn = _h.index('标的') + 1
_cn = _h.index('细分板块') + 1
_dn = _h.index('方向') + 1
sec_stocks = {}   # 板块 -> list of (code, [(name, rate, pdate), ...])
sec_mentions = {} # 板块 -> 提及标的数(去重名)
sec_raw = defaultdict(list)
for _row in _ws.iter_rows(min_row=2, values_only=True):
    sec = _row[_cn-1]; name = _row[_bn-1]; rate = _row[_dn-1]; pdate = norm_date(_row[_an-1])
    if not sec or not name: continue
    sec_mentions.setdefault(sec, set()).add(name)
    code = resolve.get(name)
    if code and code in quotes:
        sec_raw[(sec, code)].append((name_of(code), rate, pdate))
# 同一只票在同一板块的多次预测合并为一组
for (sec, code), lst in sec_raw.items():
    sec_stocks.setdefault(sec, []).append((code, lst))
_wb.close()

# 4) 公共日期轴 (窗口 5/13 ~ 9/12)
alld = set()
for s in allq.values():
    alld |= set(s.keys())
dates = sorted(d for d in alld if "2026-05-13" <= d <= "2026-09-12")
B0 = dates[0]
print("公共日期轴:", len(dates), "条, base=", B0)

# 预测日(YYYY-MM-DD) -> 在 dates 数组中的下标(就近对齐到交易日)
dates_i = [int(d.replace('-', '')) for d in dates]
def date_to_idx(dt):
    if not dt: return 0
    di = int(dt.replace('-', ''))
    i = bisect.bisect_left(dates_i, di)
    if i >= len(dates_i): return len(dates_i) - 1
    if i == 0: return 0
    if dates_i[i] == di: return i
    return i - 1 if (di - dates_i[i - 1]) <= (dates_i[i] - di) else i

def rebase(series, base=B0):
    b = series.get(base)
    if b in (None, 0):
        for d in dates:
            if d in series: b = series[d]; base = d; break
    if b in (None, 0):
        return [None] * len(dates)
    return [round(series[d] / b * 100, 2) if d in series else None for d in dates]

def ret_of(arr):
    vals = [v for v in arr if v is not None]
    if len(vals) < 2: return 0.0
    return round((vals[-1] / vals[0] - 1) * 100, 1)

hs300 = rebase(idx.get("sh000300", {}))

# 5) 板块指数 (等权) + 个股  (遍历全部板块, 含无行情的)
sectors = []
empty_secs = []
for sec in sorted(sec_mentions.keys()):
    members = sec_stocks.get(sec, [])
    if not members:
        empty_secs.append(sec)
        sectors.append({"name": sec, "members": 0,
                        "mentions": len(sec_mentions.get(sec, [])),
                        "ret": None, "series": [None] * len(dates),
                        "stocks": [], "empty": True,
                        "dir_counts": {}, "bull": 0, "bear": 0, "neu": 0,
                        "hit_n": 0, "hit_d": 0})
        continue
    # 个股 rebased (同一只票的多条预测合并为一张卡)
    stock_objs = []
    for code, lst in members:
        rb = rebase(quotes[code])
        full_ret = ret_of(rb)
        preds = []
        for (nm, rate, pdate) in lst:
            idx = date_to_idx(pdate)
            v0 = rb[idx] if (0 <= idx < len(rb) and rb[idx] is not None) else None
            vals = [v for v in rb if v is not None]
            v1 = vals[-1] if vals else None
            pret = round(v1 / v0 * 100 - 100, 1) if (v0 not in (None, 0) and v1 is not None) else None
            if rate in BULL: hit = (pret > 0) if pret is not None else None
            elif rate in BEAR: hit = (pret < 0) if pret is not None else None
            else: hit = None
            preds.append({"rate": rate, "pdate": pdate, "m_idx": idx, "pret": pret, "hit": hit})
        preds.sort(key=lambda p: (p["pdate"] or ""))
        hn = sum(1 for p in preds if p["hit"] is True)
        hd = sum(1 for p in preds if p["hit"] is not None)
        stock_objs.append({"code": code, "name": lst[-1][0], "series": rb, "ret": full_ret,
                           "preds": preds, "n_preds": len(preds),
                           "rate": preds[-1]["rate"], "m_idx": preds[-1]["m_idx"],
                           "hit_n": hn, "hit_d": hd})
    # 板块等权指数
    sec_series = []
    for i, d in enumerate(dates):
        vals = [so["series"][i] for so in stock_objs if so["series"][i] is not None]
        sec_series.append(round(sum(vals) / len(vals), 2) if vals else None)
    dir_counts = {}
    for so in stock_objs:
        for p in so["preds"]:
            dir_counts[p["rate"]] = dir_counts.get(p["rate"], 0) + 1
    bull = sum(dir_counts.get(r, 0) for r in BULL)
    bear = sum(dir_counts.get(r, 0) for r in BEAR)
    neu  = sum(dir_counts.get(r, 0) for r in NEU)
    hit_d = sum(so["hit_d"] for so in stock_objs)
    hit_n = sum(so["hit_n"] for so in stock_objs)
    sectors.append({
        "name": sec,
        "members": len(stock_objs),
        "mentions": len(sec_mentions.get(sec, [])),
        "ret": ret_of(sec_series),
        "series": sec_series,
        "stocks": stock_objs,
        "empty": False,
        "dir_counts": dir_counts, "bull": bull, "bear": bear, "neu": neu,
        "hit_n": hit_n, "hit_d": hit_d,
    })
sectors.sort(key=lambda s: -(s["ret"] if s["ret"] is not None else -999))
NTOTAL = len(sectors); NHAS = len([s for s in sectors if not s["empty"]])
tot_bull = sum(s.get("bull", 0) for s in sectors)
tot_bear = sum(s.get("bear", 0) for s in sectors)
tot_neu  = sum(s.get("neu", 0) for s in sectors)
print("总板块:", NTOTAL, "| 有行情:", NHAS, "| 无行情:", len(empty_secs))
print("方向: 看多类", tot_bull, "| 看空类", tot_bear, "| 中性类", tot_neu)

# ---------- 5b) 主题归类 (移植 inject_theme.py) ----------
THEMES = [
    ("机器人", ["机器人", "具身智能", "Tier1"]),
    ("卫星与商业航天", ["卫星", "航天", "星载", "太阳翼", "商业航天", "TR组件", "激光通信", "激光/星载"]),
    ("算力与AI硬件", ["算力", "AI服务器", "服务器", "液冷", "散热", "散热驱动", "华为算力",
                    "国产算力", "算力租赁", "算力硬件", "互联网Capex", "算力与AI硬件",
                    "AI电源", "800V", "SST", "UPS", "HVDC", "Capex"]),
    ("电力与电源", ["电力电源", "变压器", "电力设备", "燃机", "SOFC", "发动机"]),
    ("半导体设备与制造", ["半导体设备", "半导体零部件", "光刻", "硅片", "晶圆", "代工", "封测",
                       "载板", "EDA", "新凯来", "洁净室", "玻璃基", "半导体材料",
                       "半导体设备材料", "设备", "半导体"]),
    ("芯片设计", ["芯片", "GPU", "CPU", "存储", "磷化铟", "碳化硅", "AI芯片", "卫星芯片",
                "交换芯片", "光芯片", "模拟芯片", "芯片与互联"]),
    ("通信与光模块", ["光连接", "CPO", "MPO", "光通信", "光纤", "光模块", "交换机", "运营商", "连接器", "通信"]),
    ("消费电子", ["消费电子", "ODM", "光学"]),
    ("新能源", ["光伏", "TOPCon", "储能", "固态电池", "新能源与材料", "太空光伏"]),
    ("医药", ["创新药", "AI制药", "消费医药"]),
    ("消费", ["消费", "养殖", "生猪"]),
    ("AI应用与软件", ["AI应用", "AI软件", "SaaS", "办公AI", "大模型", "AI营销", "AI短剧",
                   "AI4S", "AI办公", "AI", "数据工具", "数据治理"]),
    ("传媒与互联网", ["游戏", "影视", "互联网", "网安"]),
    ("电子元件", ["MLCC", "电容", "被动元件", "MIM"]),
    ("材料与化工", ["材料", "氟化工", "PTFE原料", "铜", "CCL", "PCB", "电子布", "3D打印"]),
    ("综合", ["综合"]),
]
def theme_of(name):
    for t, kws in THEMES:
        for k in kws:
            if k in name:
                return t
    return "综合"
for _s in sectors:
    _s['theme'] = theme_of(_s['name'])

# ---------- 5c) 原话注入 (移植 patch_board_quote.py: 标的明细 G列) ----------
try:
    _wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    _ws = _wb['标的明细']
    _h = [c.value for c in _ws[1]]
    _dn = _h.index('日期') + 1; _nn = _h.index('标的') + 1; _qn = _h.index('观点原话') + 1
    quote_map = {}
    for _row in _ws.iter_rows(min_row=2, values_only=True):
        _nm = _row[_nn-1]; _dt = _row[_dn-1]; _q = _row[_qn-1]
        if _nm and _q:
            quote_map.setdefault(_nm, []).append((str(_dt), _q))
    _wb.close()
    print("标的明细 原话 lookup:", sum(len(v) for v in quote_map.values()), "条")
except Exception as e:
    print("warn 标的明细读取失败:", e); quote_map = {}

for _s in sectors:
    for _st in _s.get('stocks', []):
        _qby = {}
        for _dt, _q in quote_map.get(_st['name'], []):
            _key = _dt.replace('-', '') if _dt else _dt
            _qby.setdefault(_key, _q)
        _quotes = []; _seen = set()
        for _p in _st.get('preds', []):
            _m = _p.get('m_idx')
            if not (isinstance(_m, int) and 0 <= _m < len(dates)):
                continue
            _d8 = dates[_m].replace('-', '')
            _q = _qby.get(_d8)
            if _q and _d8 not in _seen:
                _seen.add(_d8); _quotes.append({'qdate': dates[_m], 'quote': _q})
        if not _quotes and quote_map.get(_st['name']):
            _dt, _q = quote_map[_st['name']][0]; _sdt = str(_dt)
            _dd = _sdt if len(_sdt) != 8 else f"{_sdt[:4]}-{_sdt[4:6]}-{_sdt[6:]}"
            _quotes.append({'qdate': _dd, 'quote': _q})
        _quotes.sort(key=lambda x: x['qdate'])
        _st['quotes'] = _quotes

payload = {"base": B0, "dates": dates, "hs300": hs300, "sectors": sectors,
           "empty": empty_secs, "tot_bull": tot_bull, "tot_bear": tot_bear,
           "tot_neu": tot_neu}
raw = json.dumps(payload, ensure_ascii=False)

# 6) 以当前 HTML 为底模, 仅替换 const DATA = {...} 数据 blob (保留主题/原话/命中率增强)
cur = open(OUT, encoding='utf-8').read()
mi = cur.index("const DATA = ")
start = cur.index("{", mi)
_obj, end = json.JSONDecoder().raw_decode(cur[start:])
out = cur[:start] + raw + cur[start+end:]
open(OUT, "w", encoding='utf-8').write(out)
print("written:", OUT, "| %.1f KB" % (os.path.getsize(OUT)/1024))
print("sectors with data:", NHAS, "| total member stocks:", sum(s["members"] for s in sectors))
