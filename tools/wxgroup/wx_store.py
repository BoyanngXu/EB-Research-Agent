# -*- coding: utf-8 -*-
"""微信群消息本地存储（SQLite）。

表结构：
    messages(id, grp, day, ts, sender, text, side, fp, created)
        fp = 指纹(group|sender|text) 用于去重（截图重叠/重复采集）
    days(day, grp, updated, digest)  —— 每日汇总缓存
所有数据只落本机，不上传。
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wxgroup.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grp TEXT NOT NULL,
    day TEXT NOT NULL,
    ts TEXT,
    sender TEXT,
    text TEXT NOT NULL,
    side TEXT,
    fp TEXT NOT NULL,
    created TEXT NOT NULL,
    UNIQUE(grp, day, fp)
);
CREATE INDEX IF NOT EXISTS idx_msg_day_grp ON messages(day, grp);
CREATE TABLE IF NOT EXISTS days(
    day TEXT NOT NULL,
    grp TEXT NOT NULL,
    updated TEXT,
    digest TEXT,
    PRIMARY KEY(day, grp)
);
"""


def connect(db=None):
    con = sqlite3.connect(db or DEFAULT_DB)
    con.executescript(SCHEMA)
    return con


def _fp(grp, sender, text):
    raw = "%s|%s|%s" % (grp, sender or "", (text or "").strip())
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def save_messages(msgs, db=None):
    """msgs: [{group, day, time, sender, text, side}]。返回新增条数。"""
    con = connect(db)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    added = 0
    try:
        for m in msgs:
            grp = (m.get("group") or "").strip()
            text = (m.get("text") or "").strip()
            if not grp or not text:
                continue
            cur = con.execute(
                "INSERT OR IGNORE INTO messages(grp,day,ts,sender,text,side,fp,created)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (grp, m.get("day") or time.strftime("%Y-%m-%d"), m.get("time") or "",
                 m.get("sender") or "", text, m.get("side") or "",
                 _fp(grp, m.get("sender"), text), now))
            added += cur.rowcount
        con.commit()
    finally:
        con.close()
    return added


def groups_on(day, db=None):
    con = connect(db)
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT grp FROM messages WHERE day=? ORDER BY grp", (day,))]
    finally:
        con.close()


def messages_on(day, grp=None, db=None):
    con = connect(db)
    con.row_factory = sqlite3.Row
    try:
        if grp:
            rows = con.execute(
                "SELECT * FROM messages WHERE day=? AND grp=? ORDER BY id", (day, grp))
        else:
            rows = con.execute(
                "SELECT * FROM messages WHERE day=? ORDER BY grp, id", (day,))
        return [dict(r) for r in rows]
    finally:
        con.close()


def set_digest(day, grp, text, db=None):
    con = connect(db)
    try:
        con.execute("INSERT OR REPLACE INTO days(day,grp,updated,digest) VALUES(?,?,?,?)",
                    (day, grp, time.strftime("%Y-%m-%d %H:%M:%S"), text))
        con.commit()
    finally:
        con.close()


def stats(db=None):
    con = connect(db)
    try:
        n = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        days = [r[0] for r in con.execute(
            "SELECT DISTINCT day FROM messages ORDER BY day DESC LIMIT 10")]
        return {"total": n, "recent_days": days}
    finally:
        con.close()


if __name__ == "__main__":
    print(stats())
