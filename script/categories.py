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
    # used 上溯：任一子项被引用则该节点视为「不可删」
    def _propagate(n):
        n["used"] = n["used"] or any(_propagate(c) for c in n["children"])
        return n["used"]
    for r in roots:
        _propagate(r)
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
    """删除分类。

    - 一级场景：若其名下所有子项都未被记录引用，则级联删除该一级分类及其全部子项；
      若任一子项被引用则拒绝。一级本身不直接存记录（记录只指向叶子子项）。
    - 非一级：沿用旧规则——被引用或存在子分类时拒绝。
    """
    conn = get_user_conn(uid)
    try:
        cat = conn.execute(
            "SELECT id, parent_id, level FROM dim_category WHERE id=?", (category_id,)).fetchone()
        if not cat:
            return None, "分类不存在"
        if (cat["parent_id"] or 0) == 0 and cat["level"] == 1:
            child_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM dim_category WHERE parent_id=?", (category_id,)).fetchall()]
            if child_ids:
                mark = ",".join("?" * len(child_ids))
                used = conn.execute(
                    "SELECT 1 FROM records WHERE category_id IN ({}) LIMIT 1".format(mark),
                    tuple(child_ids)).fetchone()
                if used:
                    return None, "该场景下存在已被记账引用的子项，不可删除"
                conn.execute("DELETE FROM dim_category WHERE id IN ({})".format(mark),
                             tuple(child_ids))
            conn.execute("DELETE FROM dim_category WHERE id=?", (category_id,))
            conn.commit()
            return {"id": category_id, "deleted_subitems": len(child_ids)}, None
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