# -*- coding: utf-8 -*-
"""三层分类管理：读取完整分类树、新增、删除、同级排序。

数据来源：当前用户业务库 `data/{uid}.db` 的 `dim_category` 表。
- 层级规则：无 parent_id 为一级场景；否则 level = parent_level + 1，最高 3 级。
- 删除校验：已被记录引用（used）或存在子分类时不可删除（前端红=可删，灰=不可删）。
"""
from db import get_user_conn


def get_categories(uid):
    """返回当前用户完整分类树（含 used 标记）。

    树结构：categories → children → children；used 表示该分类是否被任意记录直接引用。
    """
    conn = get_user_conn(uid)
    try:
        rows = conn.execute(
            "SELECT id, name, parent_id, level FROM dim_category ORDER BY sort_order, id").fetchall()
        used_ids = {
            r["category_id"]
            for r in conn.execute("SELECT category_id FROM records").fetchall()
        }
    finally:
        conn.close()
    nodes = {
        r["id"]: {
            "id": r["id"], "name": r["name"], "parent_id": r["parent_id"],
            "level": r["level"], "used": r["id"] in used_ids, "children": [],
        }
        for r in rows
    }
    roots = []
    for n in nodes.values():
        if n["parent_id"] is not None and n["parent_id"] in nodes:
            nodes[n["parent_id"]]["children"].append(n)
        else:
            roots.append(n)
    return roots


def add_category(uid, name, parent_id):
    """新增分类。无 parent_id → 一级场景；否则 level = parent_level + 1（不超过 3）。"""
    name = str(name or "").strip()
    if not name:
        return None, "分类名称不能为空"
    if len(name) > 30:
        return None, "分类名称过长（最多 30 字）"
    conn = get_user_conn(uid)
    try:
        if parent_id is None:
            level = 1
        else:
            parent = conn.execute(
                "SELECT level FROM dim_category WHERE id=?", (parent_id,)).fetchone()
            if not parent:
                return None, "父级分类不存在"
            if parent["level"] >= 3:
                return None, "分类层级不能超过 3 级"
            level = parent["level"] + 1
        cur = conn.execute(
            "INSERT INTO dim_category (name, parent_id, level, sort_order) VALUES (?,?,?,?)",
            (name, parent_id, level, 0))
        conn.commit()
        return {"id": cur.lastrowid, "name": name, "parent_id": parent_id, "level": level}, None
    finally:
        conn.close()


def delete_category(uid, category_id):
    """删除分类。已被记录引用或存在子分类时拒绝删除。"""
    conn = get_user_conn(uid)
    try:
        if not conn.execute("SELECT 1 FROM dim_category WHERE id=?", (category_id,)).fetchone():
            return None, "分类不存在"
        if conn.execute("SELECT 1 FROM dim_category WHERE parent_id=?", (category_id,)).fetchone():
            return None, "该分类存在子分类，请先删除子分类"
        if conn.execute("SELECT 1 FROM records WHERE category_id=?", (category_id,)).fetchone():
            return None, "该分类已被记录引用，不可删除"
        conn.execute("DELETE FROM dim_category WHERE id=?", (category_id,))
        conn.commit()
        return {"id": category_id}, None
    finally:
        conn.close()


def reorder_categories(uid, ids, parent_id=None):
    """按给定 id 顺序更新同级 sort_order（前端拖拽/排序后整组提交）。"""
    if not ids:
        return None, "缺少分类 id 列表"
    conn = get_user_conn(uid)
    try:
        # 校验每个 id 存在，且父级与给定 parent_id 一致（保护数据完整性）
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            "SELECT id, parent_id FROM dim_category WHERE id IN ({})".format(placeholders),
            tuple(ids)).fetchall()
        if len(rows) != len(set(ids)):
            return None, "存在不存在或重复的分类 id"
        if parent_id is not None:
            for r in rows:
                if (r["parent_id"] or 0) != parent_id:
                    return None, "分类父级不一致，无法排序"
        for pos, cid in enumerate(ids):
            conn.execute("UPDATE dim_category SET sort_order=? WHERE id=?", (pos + 1, cid))
        conn.commit()
        return len(ids), None
    finally:
        conn.close()