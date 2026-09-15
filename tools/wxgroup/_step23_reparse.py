# -*- coding: utf-8 -*-
"""离线重解析已保存的链接视图截图，修正来源字段。"""
import sys, os, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R

OUT = r"C:\Users\<用户名>\AppData\Local\Temp\wxdbg"

rows = []
for fn in sorted(glob.glob(os.path.join(OUT, "lk_col_*.png"))):
    img = R.Image.open(fn) if hasattr(R, "Image") else None
    from PIL import Image
    img = Image.open(fn)
    items = R.ocr_items(img)
    labels = [x for x in items if 750 <= x["x"] <= 845 and x["y"] > 215
              and ("昨天" in x["text"] or "前天" in x["text"] or ":" in x["text"])]
    for e in labels:
        ty = e["y"]
        tits = [x for x in items if 115 <= x["x"] <= 750 and ty - 26 <= x["y"] <= ty + 10]
        srcs = [x for x in items if 115 <= x["x"] <= 460 and ty + 14 <= x["y"] <= ty + 54]
        title = max(tits, key=lambda z: z["w"])["text"].strip() if tits else ""
        src = max(srcs, key=lambda z: z["w"])["text"].strip() if srcs else ""
        rows.append({"file": os.path.basename(fn), "time": e["text"].strip(),
                     "src": src, "title": title})

# 去重（同一屏滚动重叠）
seen, uniq = set(), []
for r in rows:
    k = (r["title"][:34], r["src"][:10])
    if r["title"] and k not in seen:
        seen.add(k)
        uniq.append(r)

yd = [r for r in uniq if "昨天" in r["time"]]
print("总 %d / 昨日 %d" % (len(uniq), len(yd)))
print("=" * 100)
for i, r in enumerate(yd, 1):
    print("%2d. [%s] %s" % (i, r["src"] or "-", r["title"]))
with open(os.path.join(OUT, "yday_links2.json"), "w", encoding="utf-8") as f:
    json.dump(yd, f, ensure_ascii=False, indent=1)
print("saved yday_links2.json")
