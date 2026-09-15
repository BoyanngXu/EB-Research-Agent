# -*- coding: utf-8 -*-
"""微信 4.0 群消息采集编排。

两种模式：
  被动模式（默认，零交互、零打扰）：
      每隔 N 秒截取微信窗口 -> OCR -> 落库。
      PrintWindow 可在窗口最小化/被遮挡时取到内容，因此不抢焦点、不点击。
      覆盖范围 = 你在微信里实际打开看过的群。

  主动模式（--group / --all，会驱动客户端：点击+滚动，但只读不发送）：
      自动在会话列表里找到目标群 -> 点击打开 -> 滚轮上翻 -> 逐屏截图 -> 合并去重。

用法：
    python wx_collect.py --list                      # 看当前会话列表（群名）
    python wx_collect.py --passive --interval 60     # 被动采集，每 60 秒一次
    python wx_collect.py --once                      # 只采一次当前打开的聊天
    python wx_collect.py --group "XX投研群" --pages 6 # 主动：打开该群并翻 6 屏
    python wx_collect.py --all --pages 6             # 主动：配置里的所有群
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_read as R          # noqa: E402
import wx_store as S         # noqa: E402

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "groups.json")


def load_groups():
    """目标群配置：[{"name": "群名关键字", "alias": "简称"}]"""
    if not os.path.isfile(CONFIG):
        return []
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("groups") or []
    except Exception:
        return []


# ------------------------------------------------------------------ 基础操作
def snapshot(hwnd):
    """截当前窗口并解析出 {group, messages} + 原始 OCR 块。

    用 capture_silent：窗口最小化时会非激活还原一下再截，不抢焦点。
    """
    img = R.capture_silent(hwnd)
    items = R.ocr_items(img)
    parsed = R.parse_chat(items, *img.size)
    parsed["_items"] = items
    parsed["_size"] = img.size
    return parsed


def sessions_now(hwnd):
    img = R.capture_silent(hwnd)
    items = R.ocr_items(img)
    return R.list_sessions(items, *img.size)


def chat_title(hwnd):
    """只读"聊天区标题栏"的群名。

    这是判断"当前打开了哪个会话"的**唯一可靠依据**。
    空字符串 = 没有打开任何会话（微信显示空状态占位图）。
    """
    img = R.capture_silent(hwnd)
    items = R.ocr_items(img)
    p = R.panes(*img.size)
    hd = [it for it in items if R.in_rect(it, p["header"])]
    if not hd:
        return ""
    return R._clean_group(sorted(hd, key=lambda z: z["x"])[0]["text"])


def _safe_rect(hwnd):
    """窗口屏幕矩形；最小化时回落到"还原态"矩形，避免坐标算到屏幕外。"""
    l, t, w, h = R.window_rect(hwnd)
    if w <= 0 or h <= 0 or l <= -10000 or t <= -10000:
        return R.restored_rect(hwnd)
    return l, t, w, h


def find_session_deep(hwnd, keyword, max_pages=8, verbose=False):
    """在当前会话列表里找群；找不到就滚动列表继续找。

    为什么需要：会话列表通常有折叠区，目标群可能不在首屏可见范围内。
    返回 (row, 滚动次数)；未找到返回 (None, max_pages)。
    """
    l, t, w, h = _safe_rect(hwnd)
    sx, sy = l + 230, t + int(h * 0.5)
    for i in range(max_pages):
        row = R.find_session(sessions_now(hwnd), keyword)
        if row:
            return row, i
        R.scroll_at(sx, sy, -5, hwnd=hwnd)   # 列表向下滚，露出更靠后的会话
        time.sleep(0.7)
    return None, max_pages


def open_group(hwnd, keyword, retries=3, verbose=False):
    """在会话列表里点击打开指定群。返回是否成功。

    实测踩过的坑（2026-09-15）：
      1. **点击"已经打开的"会话会把它关掉**（微信 4.0 的切换行为）。
         所以必须先看标题栏，已在目标群就不要再点。
      2. 成功判定**只能看标题栏**。早期版本拿关键字去匹配整屏 OCR 文字，
         而会话列表里永远有这个名字，导致永远误报成功。
      3. 目标群可能在会话列表折叠区外，必须能滚动列表去找。
      4. 点击/滚动默认走**消息后端**（不占鼠标、不抢前台）。
         窗口必须非最小化 —— quiet_show 会临时非激活还原并压到最底层。
      5. 例外：点"公众号""服务号"这类会弹出独立窗口的会话，微信自己会抢前台。
    """
    was_min = R.quiet_show(hwnd)
    try:
        for attempt in range(retries):
            title = chat_title(hwnd)
            if verbose:
                print("   [尝试 %d] 当前标题 = %r" % (attempt + 1, title))
            if keyword and keyword in title:
                return True                       # 已在该群，再点会关掉

            row, scrolled = find_session_deep(hwnd, keyword, verbose=verbose)
            if row is None:
                if verbose:
                    print("   [尝试 %d] 列表里找不到「%s」" % (attempt + 1, keyword))
                time.sleep(0.8)
                continue

            l, t, w, h = _safe_rect(hwnd)         # 点击前重新取，避免窗口被移动/还原
            sx = l + row["x"] + 40
            sy = t + row["y"] + row["h"] // 2
            if verbose:
                print("   [尝试 %d] 命中行 %r(y=%d)，点击屏幕坐标 (%d, %d)，滚动 %d 次"
                      % (attempt + 1, row["name"][:24], row["y"], sx, sy, scrolled))
            R.click_at(sx, sy, hwnd=hwnd)
            time.sleep(1.3)
            if scrolled:
                R.scroll_at(l + 230, t + int(h * 0.5), scrolled * 5 + 10, hwnd=hwnd)
                time.sleep(0.6)
            got = chat_title(hwnd)
            if verbose:
                print("   [尝试 %d] 点击后标题 = %r" % (attempt + 1, got))
            if keyword and keyword in got:
                return True
        return False
    finally:
        R.quiet_restore(hwnd, was_min)


def _chat_scroll_point(hwnd):
    """聊天区滚动锚点。

    ⚠ 窗口最小化时 GetWindowRect 返回 (-32000,-32000,237,39)，直接拿它算锚点
    会把滚轮事件发到屏幕外 —— 表现为"截图正常、标题正常，就是滚不动"，极难排查。
    所以最小化时改用 GetWindowPlacement 的还原位置。
    """
    l, t, w, h = _safe_rect(hwnd)
    if w <= 0 or h <= 0 or l <= -10000 or t <= -10000:
        l, t, w, h = R.restored_rect(hwnd)
    return (l + int(w * (R.SESSION_W + (1 - R.SESSION_W) / 2)),
            t + int(h * 0.5))


def scroll_and_capture(hwnd, pages=6, notches=10, settle=1.0, verbose=False):
    """在聊天区向上滚动，逐屏取"行"，用重叠区拼接成完整对话。

    为什么在"行"层面拼接而不是逐条消息去重：
        相邻两屏有重叠，OCR 对同一行在不同屏可能给出略有差异的文字，
        逐条精确去重会失效（同一消息重复出现），且跨屏的长消息会被截断。
        先拼行、再切消息，两个问题一起解决。

    **对用户无感**：滚动走消息后端（不占鼠标、不抢前台），窗口由 quiet_show
    临时非激活还原并压到最底层；窗口本来就是最小化的话，做完再放回去。

    settle 不能太小：微信历史是懒加载的，翻上去后要等它渲染完再截，
    否则连续几屏截到同一画面、看起来像"滚不动"（实测 0.75s 会卡，1.0s 稳）。

    卡住重试：检测到本屏没新增就加大滚动量并延长等待，最多连续重试 5 次。
    """
    was_min = R.quiet_show(hwnd)
    group, rows = "", []
    stall = 0
    try:
        for i in range(pages):
            img = R.capture_silent(hwnd)
            items = R.ocr_items(img)
            p = R.panes(*img.size)
            if not group:
                hd = [it for it in items if R.in_rect(it, p["header"])]
                if hd:
                    group = R._clean_group(sorted(hd, key=lambda z: z["x"])[0]["text"])
            new_rows = R.chat_rows(items, *img.size)
            before = len(rows)
            rows = R.stitch_rows(rows, new_rows)
            gained = len(rows) - before
            if verbose:
                print("   第 %d 屏: OCR %d 块 / 行 %d -> 累计 %d（新增 %d）%s"
                      % (i + 1, len(items), len(new_rows), len(rows), gained,
                         "  [等待重载]" if stall else ""))
            if i >= pages - 1:
                break
            if gained <= 0:
                stall += 1
                if stall > 5:
                    if verbose:
                        print("   ! 连续 5 屏无新增，停止滚动（可能已到顶或微信未加载更多）")
                    break
            else:
                stall = 0
            step = notches * (3 if stall else 1)
            wait = settle * (3.0 if stall else 1.0)
            cx, cy = _chat_scroll_point(hwnd)
            R.scroll_at(cx, cy, step, hwnd=hwnd)
            time.sleep(wait)
    finally:
        R.quiet_restore(hwnd, was_min)
    l, t, w, h = R.window_rect(hwnd)
    return {"group": group, "rows": rows, "w": w, "h": h}


def scan_all_sessions(hwnd, max_pages=12, verbose=False):
    """滚动遍历整个会话列表，返回全部会话行（按名称去重）。

    会话列表通常有折叠区，首屏看不全。扫完后自动滚回顶部。
    全程走消息后端 + quiet_show，不占鼠标、不抢前台。
    """
    was_min = R.quiet_show(hwnd)
    l, t, w, h = _safe_rect(hwnd)
    sx, sy = l + 230, t + int(h * 0.5)
    seen, out = set(), []
    for i in range(max_pages):
        rows = sessions_now(hwnd)
        added = 0
        for r in rows:
            k = R._nkey(r["name"])
            if k and k not in seen:
                seen.add(k)
                out.append(r)
                added += 1
        if verbose:
            print("   第 %d 屏: 可见 %d 行, 新增 %d, 累计 %d"
                  % (i + 1, len(rows), added, len(out)))
        if added == 0 and i > 0:
            break                       # 已到底
        R.scroll_at(sx, sy, -5, hwnd=hwnd)
        time.sleep(0.7)
    R.scroll_at(sx, sy, max_pages * 5 + 20, hwnd=hwnd)      # 滚回顶部
    time.sleep(0.6)
    R.quiet_restore(hwnd, was_min)
    return out


def collect_group(hwnd, keyword, pages=6, verbose=False):
    if not open_group(hwnd, keyword):
        return {"ok": False, "error": "未能在会话列表里打开「%s」" % keyword}
    res = scroll_and_capture(hwnd, pages=pages, verbose=verbose)
    # 把聊天滚回底部，避免把用户的微信留在翻历史的中间位置
    cx, cy = _chat_scroll_point(hwnd)
    R.scroll_at(cx, cy, -300, hwnd=hwnd)
    time.sleep(0.5)
    day = time.strftime("%Y-%m-%d")
    parsed = R.rows_to_messages(res["rows"], res["w"], res["h"],
                                group=res["group"] or keyword)
    msgs = [dict(m, group=parsed["group"] or keyword, day=day)
            for m in parsed["messages"]]
    added = S.save_messages(msgs)
    return {"ok": True, "group": parsed["group"] or keyword,
            "rows": len(res["rows"]), "parsed": len(msgs), "added": added}


# ------------------------------------------------------------------ 采集入口
def collect_once(verbose=True):
    hwnd = R.find_wechat_window()
    if not hwnd:
        return {"ok": False, "error": "未找到微信主窗口"}
    snap = snapshot(hwnd)
    if not snap.get("group"):
        if verbose:
            print("当前没有打开任何会话（微信空状态），跳过")
        return {"ok": True, "group": "", "parsed": 0, "added": 0}
    msgs = [dict(m, group=snap["group"], day=time.strftime("%Y-%m-%d"))
            for m in snap["messages"]]
    added = S.save_messages(msgs)
    if verbose:
        print("会话: %s | 解析 %d 条 | 新增 %d 条"
              % (snap["group"], len(msgs), added))
    return {"ok": True, "group": snap["group"], "parsed": len(msgs), "added": added}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="打印当前会话列表")
    ap.add_argument("--once", action="store_true", help="采集当前打开的聊天一次")
    ap.add_argument("--passive", action="store_true", help="被动循环采集")
    ap.add_argument("--interval", type=int, default=60, help="被动模式间隔秒")
    ap.add_argument("--group", help="主动模式：群名关键字")
    ap.add_argument("--all", action="store_true", help="主动模式：配置里的所有群")
    ap.add_argument("--pages", type=int, default=6, help="主动模式每群翻屏数")
    ap.add_argument("--stats", action="store_true", help="打印库统计")
    ap.add_argument("--scan", action="store_true", help="扫描整个会话列表（含折叠区）")
    ap.add_argument("--intrusive", action="store_true",
                    help="改用 SendInput 后端（会移动真实鼠标、抢前台）。"
                         "默认是消息后端：不占鼠标、不抢前台、窗口压在最底层")
    args = ap.parse_args()

    if args.intrusive:
        R.INPUT_BACKEND = "sendinput"

    if args.stats:
        print(json.dumps(S.stats(), ensure_ascii=False, indent=2))
        return

    hwnd = R.find_wechat_window()
    if not hwnd:
        print("ERR: 未找到微信主窗口（微信 4.0 是否已登录？）")
        sys.exit(1)

    if args.scan:
        rows = scan_all_sessions(hwnd, verbose=True)
        print("\n共 %d 个会话：" % len(rows))
        for r in rows:
            print("  %s" % r["text"][:70])
        return

    if args.list:
        for r in sessions_now(hwnd):
            print("  y=%-5d %s" % (r["y"], r["text"][:70]))
        return

    if args.once:
        print(json.dumps(collect_once(), ensure_ascii=False))
        return

    if args.group or args.all:
        time.sleep(0.3)
        targets = [args.group] if args.group else [g["name"] for g in load_groups()]
        if not targets:
            print("ERR: 没有目标群（--group 指定，或在 groups.json 里配置）")
            sys.exit(1)
        for kw in targets:
            r = collect_group(hwnd, kw, pages=args.pages, verbose=True)
            print(json.dumps(r, ensure_ascii=False))
        return

    if args.passive:
        print("被动采集启动，每 %d 秒一次（Ctrl+C 停止）" % args.interval)
        while True:
            try:
                r = collect_once()
                print("[%s] %s" % (time.strftime("%H:%M:%S"), json.dumps(r, ensure_ascii=False)))
            except KeyboardInterrupt:
                print("已停止")
                return
            except Exception as e:
                print("[%s] 采集异常: %s" % (time.strftime("%H:%M:%S"), e))
            time.sleep(args.interval)

    ap.print_help()


if __name__ == "__main__":
    main()
