# -*- coding: utf-8 -*-
"""记账核心（阶段 4）：消费场景字典、渠道字典+新建渠道、新增一笔并联动渠道余额。

数据均为当前用户业务库（data/{uid}.db）内读写，鉴权在 server.py 完成。
"""
import uuid
from datetime import datetime

from db import get_user_conn


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def list_motives(uid):
    """消费场景列表（三个种子：独自/社交/为他人）。"""
    conn = get_user_conn(uid)
    try:
        rows = conn.execute("SELECT id, name FROM dim_motive ORDER BY sort_order, id").fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]
    finally:
        conn.close()


def channels_info(uid):
    """渠道列表 + 最近一次记账所用渠道 id（供前端「记住上一次渠道」默认选中）。"""
    conn = get_user_conn(uid)
    try:
        rows = conn.execute(
            "SELECT id, name, balance FROM dim_channel ORDER BY sort_order, id").fetchall()
        channels = [{"id": r["id"], "name": r["name"], "balance": r["balance"]} for r in rows]
        last = conn.execute(
            "SELECT channel_id FROM records WHERE channel_id IS NOT NULL "
            "ORDER BY created_at DESC, date DESC LIMIT 1").fetchone()
        last_id = last["channel_id"] if last else None
        return {"channels": channels, "last_used_channel_id": last_id}
    finally:
        conn.close()


def add_channel(uid, name):
    """新增渠道（初始余额 0），记账页「＋ 新建渠道」。"""
    name = (name or "").strip()
    if not name:
        return None, "请输入渠道名称"
    conn = get_user_conn(uid)
    try:
        exists = conn.execute("SELECT 1 FROM dim_channel WHERE name=?", (name,)).fetchone()
        if exists:
            return None, "该渠道已存在"
        cur = conn.execute(
            "INSERT INTO dim_channel (name, sort_order, balance) VALUES (?,50,0)", (name,))
        conn.commit()
        return {"id": cur.lastrowid, "name": name, "balance": 0}, None
    finally:
        conn.close()


def add_record(uid, data):
    """新增一笔并联动更新渠道余额（balance += amount，支出负即减、收入正即加）。

    records.category_id 指向二级子项（叶子，记账页两级模型）。
    """
    amount = data.get("amount")
    if amount is None or not isinstance(amount, (int, float)):
        return None, "请输入有效金额"
    amount = float(amount)
    if amount == 0:
        return None, "金额不能为 0"
    date = (data.get("date") or "").strip()
    if not date:
        return None, "请选择日期"
    category_id = _to_int(data.get("category_id"))
    motive_id = _to_int(data.get("motive_id"))
    channel_id = _to_int(data.get("channel_id"))
    t = (data.get("time") or "").strip() or None
    note = (data.get("note") or "").strip()

    conn = get_user_conn(uid)
    try:
        # 校验分类必须是叶子：二级且无子，或三级
        cat = conn.execute(
            "SELECT id, level FROM dim_category WHERE id=?", (category_id,)).fetchone()
        if not cat:
            return None, "分类不存在"
        if cat["level"] == 2:
            if conn.execute("SELECT 1 FROM dim_category WHERE parent_id=?",
                            (category_id,)).fetchone():
                return None, "该二级分类下还有子分类，请选择最细一级"
        elif cat["level"] != 3:
            return None, "请选择叶子子分类"
        if motive_id is not None and not conn.execute(
                "SELECT 1 FROM dim_motive WHERE id=?", (motive_id,)).fetchone():
            return None, "消费场景无效"
        if channel_id is not None and not conn.execute(
                "SELECT 1 FROM dim_channel WHERE id=?", (channel_id,)).fetchone():
            return None, "渠道无效"

        rid = uuid.uuid4().hex
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO records (uuid,user_id,date,time,amount,category_id,motive_id,channel_id,note,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, uid, date, t, amount, category_id, motive_id, channel_id, note, now))
        if channel_id is not None:
            conn.execute("UPDATE dim_channel SET balance = balance + ? WHERE id=?",
                         (amount, channel_id))
        conn.commit()
        return {"uuid": rid}, None
    finally:
        conn.close()


def update_record(uid, record_id, data):
    """按 uuid 更新一条记录（日期/时间/金额/分类/消费场景/渠道/备注）。

    金额或渠道变化时联动调整渠道余额（旧的减回、新的加上），与 add_record 的
    balance += amount 规则保持一致。
    """
    amount = data.get("amount")
    if amount is None or not isinstance(amount, (int, float)):
        return None, "请输入有效金额"
    amount = float(amount)
    if amount == 0:
        return None, "金额不能为 0"
    date = (data.get("date") or "").strip()
    if not date:
        return None, "请选择日期"
    category_id = _to_int(data.get("category_id"))
    motive_id = _to_int(data.get("motive_id"))
    channel_id = _to_int(data.get("channel_id"))
    t = (data.get("time") or "").strip() or None
    note = (data.get("note") or "").strip()

    conn = get_user_conn(uid)
    try:
        old = conn.execute(
            "SELECT amount, channel_id FROM records WHERE uuid=? AND user_id=?",
            (record_id, uid)).fetchone()
        if not old:
            return None, "记录不存在"
        old_amount = old["amount"]
        old_channel = old["channel_id"]

        # 分类校验（同 add_record）：必须是叶子
        cat = conn.execute(
            "SELECT id, level FROM dim_category WHERE id=?", (category_id,)).fetchone()
        if not cat:
            return None, "分类不存在"
        if cat["level"] == 2:
            if conn.execute("SELECT 1 FROM dim_category WHERE parent_id=?",
                            (category_id,)).fetchone():
                return None, "该二级分类下还有子分类，请选择最细一级"
        elif cat["level"] != 3:
            return None, "请选择叶子子分类"
        if motive_id is not None and not conn.execute(
                "SELECT 1 FROM dim_motive WHERE id=?", (motive_id,)).fetchone():
            return None, "消费场景无效"
        if channel_id is not None and not conn.execute(
                "SELECT 1 FROM dim_channel WHERE id=?", (channel_id,)).fetchone():
            return None, "渠道无效"

        # 渠道余额联动：旧渠道减回旧金额，新渠道加上新金额（同渠道则等价净差）
        if old_channel is not None:
            conn.execute("UPDATE dim_channel SET balance = balance - ? WHERE id=?",
                         (old_amount, old_channel))
        if channel_id is not None:
            conn.execute("UPDATE dim_channel SET balance = balance + ? WHERE id=?",
                         (amount, channel_id))
        conn.execute(
            "UPDATE records SET date=?, time=?, amount=?, category_id=?, motive_id=?, "
            "channel_id=?, note=? WHERE uuid=? AND user_id=?",
            (date, t, amount, category_id, motive_id, channel_id, note, record_id, uid))
        conn.commit()
        return {"uuid": record_id}, None
    finally:
        conn.close()