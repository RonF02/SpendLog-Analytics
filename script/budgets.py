# -*- coding: utf-8 -*-
"""预算模块（阶段6.1/6.2）：预算查询与设置（覆盖更新）。"""
from datetime import datetime

from db import get_user_conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def list_budgets(uid, month):
    """返回某月各一级场景的预算。month: YYYY-MM。若未设置，返回空列表。"""
    conn = get_user_conn(uid)
    try:
        rows = conn.execute(
            """SELECT b.id, b.category_id, b.month, b.amount, c.name AS category
               FROM budgets b
               LEFT JOIN dim_category c ON c.id=b.category_id
               WHERE b.month=? AND b.category_id IN (
                   SELECT id FROM dim_category WHERE level=1)
               ORDER BY c.sort_order, c.id""", (month,)).fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "category_id": r["category_id"], "month": r["month"],
             "amount": r["amount"], "category": r["category"]} for r in rows]


def set_budget(uid, category_id, month, amount):
    """设置/覆盖某月某一级场景预算。category_id 必须是一级场景。"""
    if not category_id:
        return None, "缺少分类 id"
    try:
        month = str(month)
        datetime.strptime(month, "%Y-%m")
    except (TypeError, ValueError):
        return None, "month 格式应为 YYYY-MM"
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return None, "金额格式不正确"
    if amount < 0:
        return None, "预算不能为负"

    conn = get_user_conn(uid)
    try:
        lvl = conn.execute("SELECT level FROM dim_category WHERE id=?", (category_id,)).fetchone()
        if not lvl:
            return None, "分类不存在"
        if lvl["level"] != 1:
            return None, "预算仅支持按一级场景设置"
        now = _now()
        exist = conn.execute(
            "SELECT id FROM budgets WHERE category_id=? AND month=?", (category_id, month)).fetchone()
        if exist:
            conn.execute(
                "UPDATE budgets SET amount=?, updated_at=? WHERE id=?", (amount, now, exist["id"]))
            bid = exist["id"]
        else:
            cur = conn.execute(
                "INSERT INTO budgets (user_id, category_id, month, amount, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?)",
                (uid, category_id, month, amount, now, now))
            bid = cur.lastrowid
        conn.commit()
        return {"id": bid, "category_id": category_id, "month": month, "amount": amount}, None
    finally:
        conn.close()