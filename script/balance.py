# -*- coding: utf-8 -*-
"""渠道余额（阶段6.4/6.5）：查询余额、校准（生成校准记录）。"""
from datetime import datetime

from db import get_user_conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def list_balance(uid):
    """返回所有渠道余额列表。"""
    conn = get_user_conn(uid)
    try:
        rows = conn.execute(
            "SELECT id, name, balance FROM dim_channel ORDER BY sort_order, id").fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "name": r["name"], "balance": r["balance"]} for r in rows]


def calibrate(uid, channel_id, balance):
    """校准渠道余额：把目标余额写入 dim_channel.balance，
    并记录 before/after/delta 到 channel_calibrations。"""
    if not channel_id:
        return None, "缺少渠道 id"
    try:
        balance = round(float(balance), 2)
    except (TypeError, ValueError):
        return None, "余额格式不正确"

    conn = get_user_conn(uid)
    try:
        row = conn.execute(
            "SELECT id, name, balance FROM dim_channel WHERE id=?", (channel_id,)).fetchone()
        if not row:
            return None, "渠道不存在"
        before = row["balance"]
        delta = round(balance - before, 2)
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute("UPDATE dim_channel SET balance=? WHERE id=?", (balance, channel_id))
        cur = conn.execute(
            "INSERT INTO channel_calibrations"
            " (user_id, channel_id, before, after, delta, date, note, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (uid, channel_id, before, balance, delta, today, None, _now()))
        conn.commit()
        return {"id": cur.lastrowid, "channel_id": channel_id, "name": row["name"],
                "before": before, "after": balance, "delta": delta}, None
    finally:
        conn.close()