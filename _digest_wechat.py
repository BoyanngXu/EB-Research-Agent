# -*- coding: utf-8 -*-
"""EB-Agent 公众号「记忆压缩」：把 _prev 归档旧文按时段提炼成精华 txt。

产出到 Wechat/_digest/，每个时段一份综合要点，供以后检索调用。不删原文（删除由调用方另做）。
"""
import os, sys, glob, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.core import datareader, llm, config

# 路径从脚本位置推导：本文件位于 EB-Agent/ 下，工作区根是其上一级
_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.environ.get("EB_WORKSPACE_ROOT") or os.path.dirname(_HERE)
_WECHAT = os.path.join(_WS, "Wechat")
DIGEST_DIR = os.path.join(_WECHAT, "_digest")

# _prev 下按批次分子目录，自动取最新的一批（不再写死某个批次号）
_PREV_ROOT = os.path.join(_WECHAT, "_prev")
PREV_DIR = ""
if os.path.isdir(_PREV_ROOT):
    _subs = sorted(d for d in os.listdir(_PREV_ROOT)
                   if os.path.isdir(os.path.join(_PREV_ROOT, d)))
    PREV_DIR = os.path.join(_PREV_ROOT, _subs[-1]) if _subs else _PREV_ROOT

# 时段 → (日期标签, 文件名过滤正则)
PERIODS = [
    ("2026-09-01", "盘前", ["盘前", "9月1日", "9.1", "9_1", "09-01"]),
    ("2026-09-03", "午盘", ["午盘", "午评", "午报", "9.3", "9月3", "09_03"]),
]

OVERRIDE = {"backend": "api", "model": "deepseek-v4-flash", "temperature": 0.2, "timeout": 120}

SUMMARY_SYSTEM = """你是一位资深的 A 股盘面情报分析师，负责把同一时段的多篇公众号财经文章压缩成一份精炼、可长期复用的「市场记忆」。

输出为纯文本，结构如下（每节都用中文，紧贴原文数据，绝不编造数字）：
【时段】YYYY-MM-DD 盘前/午盘
【市场情绪】1-2 句概括
【指数与关键数据】列出指数点位、涨跌幅、成交额等确凿数字；原文没有就不写
【主线 / 热点板块】分点
【关键事件 / 信息点】分点，含具体数字、日期、公司名
【风险与分歧】若有，写市场担心的点 / 多空分歧
【来源】共 N 篇（附上主要公众号名称，不超过 6 个）

硬性要求：
1. 只提炼原文里出现的信息，原文没有的字段写「原文未提及」，不要脑补。
2. 篇幅控制在 300~500 字，是「压缩记忆」不是全文抄录。
3. 中文输出，不要 markdown 代码块、不要解释。"""


def period_files(period_keywords):
    out = []
    for p in sorted(glob.glob(os.path.join(PREV_DIR, "*.docx"))):
        fn = os.path.basename(p)
        if any(k in fn for k in period_keywords):
            out.append(p)
    return out


def collect_text(files, budget_chars=9000):
    """读取若干 docx，截取每篇前若干字，拼成喂给模型的材料。"""
    blocks, sources = [], []
    per = max(1500, budget_chars // max(1, len(files)))
    for p in files:
        try:
            d = datareader.read_docx(p, max_chars=per)
            paras = d.get("paragraphs") or []
            if not paras:
                continue
            title = (d.get("title") or os.path.basename(p)).strip()
            body = " ".join(paras)
            blocks.append("【%s】\n%s" % (title, body))
            sources.append(title.split("_")[0] if "_" in title else title[:20])
        except Exception as e:
            print("  ! skip %s: %s" % (os.path.basename(p), e))
    return "\n\n".join(blocks), sources


def main():
    os.makedirs(DIGEST_DIR, exist_ok=True)
    for label, kind, keywords in PERIODS:
        files = period_files(keywords)
        if not files:
            print("[%s] 无匹配文件，跳过" % label)
            continue
        print("[%s %s] 匹配 %d 篇" % (label, kind, len(files)))
        material, sources = collect_text(files)
        user = ("以下是 %s 公众号文章正文（已拼接），请压缩成一份市场记忆：\n\n%s"
                % (label, material[:20000]))
        print("  调用 LLM 提炼…")
        try:
            resp = llm.chat(
                [{"role": "system", "content": SUMMARY_SYSTEM},
                 {"role": "user", "content": user}],
                override=OVERRIDE)
        except Exception as e:
            print("  LLM 调用失败: %s" % e)
            continue
        if not resp.get("ok"):
            print("  LLM 返回异常: %s" % resp.get("error"))
            continue
        summary = (resp.get("content") or "").strip()
        # 加文件头
        src_names = list(dict.fromkeys(sources))[:6]
        header = ("# %s %s公众号舆情 · 记忆压缩\n"
                  "生成时间: %s\n"
                  "来源: %d 篇（%s）\n\n" %
                  (label, kind, time.strftime("%Y-%m-%d %H:%M:%S"),
                   len(sources), " / ".join(src_names)))
        out_path = os.path.join(DIGEST_DIR, "%s-%s舆情精华.txt" % (label, kind))
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(header + summary)
        print("  ✓ 已写入 %s (%d 字)" % (out_path, len(summary)))


if __name__ == "__main__":
    main()
