# -*- coding: utf-8 -*-
"""微信群每日汇总（LLM 生成日报）。

读 wx_store 里已采集的群消息 -> 按群调用 LLM 生成结构化日报 -> 落 markdown + 写回 days 表。

用法：
    python wx_digest.py                          # 汇总今天全部群
    python wx_digest.py --day 2026-09-15         # 指定日期
    python wx_digest.py --group "投研"            # 只汇总群名含"投研"的
    python wx_digest.py --out C:/x/日报.md        # 指定输出文件
    python wx_digest.py --force                  # 已有摘要也重新生成
    python wx_digest.py --dry                    # 只打印将发送的 prompt，不调模型

前置：先用 wx_collect.py 采集（--once / --passive / --group）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wx_store as S          # noqa: E402

EB_ROOT = os.path.dirname(os.path.dirname(HERE))       # EB-Agent/
if EB_ROOT not in sys.path:
    sys.path.insert(0, EB_ROOT)

MAX_CHARS = 20000             # 单个群的转写文本上限（超出则截断并标注）

SYSTEM_PROMPT = """你是投研助理，负责把微信群里一天的聊天记录整理成一份**给投研人员看的日报**。

背景：这些群消息由「截图 + OCR」采集而来，**必然存在识别错误**（错别字、串行、数字错位、
表情/图片/文件内容缺失）。请据此调整：宁可保守，不要脑补。

输出要求（markdown，不要用代码块包裹整篇）：

## 今日要点
3~6 条，每条一句话，**句末用括号标注来源发送者**。只写真正有信息量的内容。

## 重要信息与数据
有具体数字/事实的条目：行情与价格、宏观数据、政策与监管、公司公告与事件、
行业景气与供需、研报观点（评级/目标价/盈利预测）。逐条列出，标注发送者。
没有则写「无」。

## 观点与分歧
群内出现的判断、预测、多空分歧。标注谁说了什么。没有则写「无」。

## 待跟进
需要我处理的：待回复的问题、约好的会议/路演、需要查证的信息、@我的消息。
没有则写「无」。

## 噪音过滤说明
一句话说明你剔除了哪些内容（寒暄、广告、求职模板、重复转发等）。

硬性规则：
- **只依据给定的聊天记录**，不要引入外部知识，不要编造数字或人名。
- 数字看不清或明显是 OCR 错误时，写「（数字疑为 OCR 错误）」而不是猜。
- 与投研无关的群（家人、球友、购物、招聘模板刷屏）就直说「本群今日无投研价值内容」，
  不要在要点里硬凑。
- 全中文，简洁，不用敬语套话。"""


def build_transcript(msgs):
    """把消息列表转成给模型的紧凑文本。"""
    lines = []
    for m in msgs:
        who = m.get("sender") or ("我" if m.get("side") == "right" else "?")
        ts = m.get("ts") or ""
        text = (m.get("text") or "").strip()
        if not text:
            continue
        lines.append("[%s] %s：%s" % (ts or "--:--", who, text))
    body = "\n".join(lines)
    if len(body) > MAX_CHARS:
        body = body[:MAX_CHARS] + "\n\n……（内容过长，已截断）"
    return body


def digest_group(grp, msgs, dry=False, max_tokens=1500):
    """对单个群生成日报。返回 (ok, text)。"""
    transcript = build_transcript(msgs)
    if not transcript.strip():
        return True, "（本群今日无可读文本消息）"

    user = ("群名：%s\n消息条数：%d\n\n=== 聊天记录开始 ===\n%s\n=== 聊天记录结束 ===\n\n"
            "请按系统提示的格式输出今日日报。" % (grp, len(msgs), transcript))

    if dry:
        return True, "[DRY RUN]\n\n--- SYSTEM ---\n%s\n\n--- USER ---\n%s" % (
            SYSTEM_PROMPT, user)

    from app.core import llm
    # 必须显式给 max_tokens：缺省时服务端按模型最大值预留额度，
    # 本机 API 的 TPM 配额较紧，会直接 429（实测 600 可通过、缺省即失败）。
    r = llm.chat(
        [{"role": "system", "content": SYSTEM_PROMPT},
         {"role": "user", "content": user}],
        override={"backend": "api"},          # 绕开桥接，直连云 API
        temperature=0.2,
        max_tokens=max_tokens,
    )
    if not r.get("ok"):
        return False, "模型调用失败：%s %s" % (r.get("kind"), r.get("message"))
    return True, (r.get("content") or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=time.strftime("%Y-%m-%d"), help="日期 YYYY-MM-DD")
    ap.add_argument("--group", help="只汇总群名含该关键字的群")
    ap.add_argument("--out", help="输出 markdown 文件")
    ap.add_argument("--force", action="store_true", help="已有摘要也重新生成")
    ap.add_argument("--dry", action="store_true", help="只打印 prompt，不调模型")
    ap.add_argument("--min-msgs", type=int, default=3,
                    help="少于此条数的群跳过（默认 3）")
    ap.add_argument("--max-tokens", type=int, default=1500,
                    help="模型输出上限。别设太大：本机 API 的 TPM 配额较紧，"
                         "缺省(不传)会直接 429（默认 1500）")
    args = ap.parse_args()

    day = args.day
    groups = S.groups_on(day)
    if args.group:
        groups = [g for g in groups if args.group in g]
    if not groups:
        print("没有找到 %s 的已采集消息（先用 wx_collect.py 采集）。" % day)
        return

    con = S.connect()
    cached = {}
    try:
        for d, g, dg in con.execute("SELECT day,grp,digest FROM days WHERE day=?", (day,)):
            cached[(d, g)] = dg
    finally:
        con.close()

    out_lines = ["# 微信群日报 · %s" % day, ""]
    for grp in groups:
        msgs = S.messages_on(day, grp)
        if len(msgs) < args.min_msgs:
            print("跳过「%s」（仅 %d 条，少于 %d）" % (grp, len(msgs), args.min_msgs))
            continue

        old = cached.get((day, grp))
        if old and not args.force and not args.dry:
            print("「%s」已有摘要，跳过（--force 可重算）" % grp)
            body = old
        else:
            print("生成「%s」…（%d 条消息）" % (grp, len(msgs)))
            ok, body = digest_group(grp, msgs, dry=args.dry,
                                    max_tokens=args.max_tokens)
            if not ok:
                print("  ✗ %s" % body)
                body = "> 生成失败：%s" % body
            elif not args.dry:
                S.set_digest(day, grp, body)

        out_lines += ["## %s" % grp, "", body, "", "---", ""]

    text = "\n".join(out_lines)
    out = args.out or os.path.join(HERE, "日报_%s.md" % day)
    if not args.dry:
        with io.open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("\n已写出 %s" % out)
    else:
        print(text[:3000])


if __name__ == "__main__":
    main()
