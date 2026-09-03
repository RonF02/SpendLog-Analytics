# -*- coding: utf-8 -*-
"""多维聚合报表（阶段5）。

GET /api/report/aggregate?month=YYYY-MM&category_id=&motive=&channel=
                          &is_weekend=&period=&month_part=

核心约定（见重构方案）：
- 消费类统计（scene_breakdown / scenario_breakdown / spending_dist）只对支出 amount<0；
- total 的 balance 用全部金额；channel_breakdown 用全部金额（暂定）；
- 时间特征在查询层派生：is_weekend(周六/周日)、period(按小时分凌晨/上午/下午/晚上)、
  month_part(按日分月初/月中/月末)，各筛选可任意组合。
"""
from datetime import datetime

from db import get_user_conn


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _period(hour):
    if hour is None:
        return None
    if hour < 6:
        return "凌晨"
    if hour < 12:
        return "上午"
    if hour < 18:
        return "下午"
    return "晚上"


def _month_part(day):
    if day <= 10:
        return "月初"
    if day <= 20:
        return "月中"
    return "月末"


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def aggregate(uid, params):
    """返回 (data, err)。data 含 total/scene_breakdown/scenario_breakdown/
    channel_breakdown/spending_dist/records/path。"""
    month = (params.get("month") or "").strip()
    if not month:
        return None, "缺少 month 参数"
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        return None, "month 格式应为 YYYY-MM"

    conn = get_user_conn(uid)
    try:
        # 分类父子关系（用于下钻与筛选）
        cat_parent, cat_name, cat_level = {}, {}, {}
        for c in conn.execute("SELECT id, name, parent_id, level FROM dim_category").fetchall():
            cat_parent[c["id"]] = c["parent_id"]
            cat_name[c["id"]] = c["name"]
            cat_level[c["id"]] = c["level"]
        rows = conn.execute(
            """SELECT r.uuid, r.date, r.time, r.amount, r.note,
                      r.category_id, r.motive_id, r.channel_id,
                      m.name AS mname, ch.name AS chname
               FROM records r
               LEFT JOIN dim_motive m ON m.id=r.motive_id
               LEFT JOIN dim_channel ch ON ch.id=r.channel_id
               WHERE r.date LIKE ?""", (month + "-%",)).fetchall()
    finally:
        conn.close()

    # 预解析为可筛选的记录对象
    recs = []
    for r in rows:
        d = r["date"]
        t = r["time"] or ""
        hour = int(t[:2]) if len(t) >= 2 and t[:2].isdigit() else None
        kwargs = {}
        try:
            wd = datetime.strptime(d, "%Y-%m-%d").weekday()
            kwargs["is_weekend"] = (wd >= 5)
            kwargs["month_part"] = _month_part(int(d[8:10]))
        except (ValueError, IndexError):
            kwargs["is_weekend"] = None
            kwargs["month_part"] = None
        recs.append(dict(
            uuid=r["uuid"], date=d, time=t, amount=r["amount"], note=r["note"],
            category_id=r["category_id"], motive_id=r["motive_id"], channel_id=r["channel_id"],
            category=cat_name.get(r["category_id"]), motive=r["mname"], channel=r["chname"],
            period=_period(hour), **kwargs))

    # ---- 筛选条件 ----
    cat_id = _int(params.get("category_id"))
    motive = _int(params.get("motive"))
    channel = (params.get("channel") or "").strip()
    iw = (params.get("is_weekend") or "").strip().lower()
    period_f = (params.get("period") or "").strip()
    mp_f = (params.get("month_part") or "").strip()

    # 目标筛选分类的子树 id 集合（含自身）
    sub_ids = None
    if cat_id is not None:
        sub_ids = set()
        stack = [cat_id]
        while stack:
            n = stack.pop()
            if n in sub_ids:
                continue
            sub_ids.add(n)
            stack.extend(cid for cid, p in cat_parent.items() if p == n)

    def _match(rc):
        if sub_ids is not None and rc["category_id"] not in sub_ids:
            return False
        if motive is not None and rc["motive_id"] != motive:
            return False
        if channel and rc["channel"] != channel:
            return False
        if iw in ("true", "false") and rc["is_weekend"] is not None \
                and str(rc["is_weekend"]).lower() != iw:
            return False
        if period_f and rc["period"] != period_f:
            return False
        if mp_f and rc["month_part"] != mp_f:
            return False
        return True

    recs = [x for x in recs if _match(x)]

    # ---- 一级(drill 根，None 表示虚拟根) 的直属子节点分组 ----
    def children_of(root):
        return [cid for cid, p in cat_parent.items() if p == root]

    cur_root = None if cat_id is None else cat_id
    group_nodes = children_of(cur_root)
    if not group_nodes:
        group_nodes = [cat_id] if cat_id is not None else []

    def top_child(rc):
        """返回 rc.category 在 cur_root 下的直属子节点 id（ancestor-or-self 向上收敛到 cur_root 的下一级）。"""
        node = rc["category_id"]
        while node is not None and node in cat_parent and cat_parent.get(node) is not None \
                and cat_parent[node] != cur_root:
            node = cat_parent[node]
        # 若 node 恰为 cur_root（记录直接挂在 drill 根上），归到自身一个组
        return node

    # ---- total（全部金额）----
    income = sum(x["amount"] for x in recs if x["amount"] is not None and x["amount"] > 0)
    expense = sum(-x["amount"] for x in recs if x["amount"] is not None and x["amount"] < 0)
    balance = sum(x["amount"] or 0 for x in recs)

    # 支出记录集合
    exp = [x for x in recs if x["amount"] is not None and x["amount"] < 0]

    # ---- scene_breakdown（支出，按 cur_root 的直属子节分组）----
    sb_map = {}
    for x in exp:
        g = top_child(x)
        if g is None:
            continue
        e = sb_map.setdefault(g, {"category_id": g, "name": cat_name.get(g) or "未分类", "total": 0.0})
        e["total"] += -x["amount"]
    scene_breakdown = sorted(sb_map.values(), key=lambda z: -z["total"])

    # ---- scenario_breakdown（支出，按消费场景）----
    sc_map = {}
    for x in exp:
        e = sc_map.setdefault(x["motive"] or "未分类",
                              {"name": x["motive"] or "未分类", "total": 0.0})
        e["total"] += -x["amount"]
    scenario_breakdown = sorted(sc_map.values(), key=lambda z: -z["total"])

    # ---- channel_breakdown（全部金额，按渠道）----
    ch_map = {}
    for x in recs:
        e = ch_map.setdefault(x["channel"] or "未分类",
                              {"channel": x["channel"] or "未分类", "total": 0.0})
        e["total"] += (x["amount"] or 0)
    channel_breakdown = sorted(ch_map.values(), key=lambda z: -z["total"])

    # ---- spending_dist（支出，按一级/叶子分类 + 记录数/中位数/平均）----
    def dist_key(x):
        # 未传 category_id → 按一级场景；传了 → 按叶子分类（记录本身）
        if cur_root is None:
            return top_child(x)
        return x["category_id"]

    sd_map = {}
    for x in exp:
        k = dist_key(x)
        e = sd_map.setdefault(k, {"category_id": k, "name": cat_name.get(k) or "未分类",
                                  "total": 0.0, "count": 0, "amts": []})
        a = -x["amount"]
        e["total"] += a
        e["count"] += 1
        e["amts"].append(a)
    spending_dist = []
    for e in sd_map.values():
        amts = sorted(e["amts"])
        n = len(amts)
        median = amts[n // 2] if n else 0.0
        if n % 2 == 0 and n > 0:
            median = (amts[n // 2 - 1] + amts[n // 2]) / 2
        spending_dist.append({"category_id": e["category_id"], "name": e["name"],
                              "total": round(e["total"], 2), "count": e["count"],
                              "median": round(median, 2),
                              "avg": round(e["total"] / n, 2) if n else 0.0})
    spending_dist.sort(key=lambda z: -z["total"])

    # ---- records（明细，日期/时间降序，数量上限避免过大）----
    records = [{"uuid": x["uuid"], "date": x["date"], "time": x["time"], "amount": x["amount"],
                "category": x["category"], "motive": x["motive"], "channel": x["channel"],
                "note": x["note"]}
               for x in recs]
    records.sort(key=lambda z: (z["date"], z["time"] or ""), reverse=True)

    # ---- 面包屑（从 drill 根到叶）----
    path = []
    node = cat_id
    while node is not None:
        path.insert(0, {"category_id": node, "name": cat_name.get(node)})
        node = cat_parent.get(node)

    data = {
        "total": {"income": round(income, 2), "expense": round(expense, 2),
                  "balance": round(balance, 2)},
        "scene_breakdown": scene_breakdown,
        "scenario_breakdown": scenario_breakdown,
        "channel_breakdown": channel_breakdown,
        "spending_dist": spending_dist,
        "records": records,
        "path": path,
    }
    return data, None