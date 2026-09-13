# -*- coding: utf-8 -*-
"""Excel(.xlsx) 导入导出——纯标准库实现（零第三方依赖）。

- write_xlsx / read_xlsx：极简单工作表 .xlsx 读写（inlineStr 内联字符串 + 数值单元格；
  兼容 sharedStrings），保持后端「零第三方依赖」约束。
- export_records / import_records：以「当前用户的记账记录」为对象，导出/导入 xlsx，
  导出列与导入列一一对应，可完整回读还原。
"""
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

from db import get_user_conn
from records import add_record, add_channel
from categories import add_category

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_RS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OD = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_TAG = "{%s}" % _NS


def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _col_letter(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


root_rels = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="{rs}">'
    '<Relationship Id="rId1" Type="{od}/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>'
).format(rs=_RS, od=_OD)

styles_xml = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="{ns}">'
    '<fonts count="2">'
    '<font><sz val="11"/><color theme="1"/><name val="宋体"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><color theme="1"/><name val="宋体"/><family val="2"/></font>'
    '</fonts>'
    '<fills count="2">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '</fills>'
    '<borders count="1"><border>'
    '<left style="none"/><right style="none"/><top style="none"/><bottom style="none"/><diagonal/>'
    '</border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>'
).format(ns=_NS)


def _sheet_xml(headers, rows, sheet_name):
    """单个 worksheet 的 XML。与旧 write_xlsx 相同格式。"""
    lines = []
    for rnum, row in enumerate([headers] + rows, start=1):
        cells = []
        for i, val in enumerate(row, start=1):
            ref = _col_letter(i) + str(rnum)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                cells.append('<c r="{}"><v>{}</v></c>'.format(ref, val))
            else:
                cells.append('<c r="{0}" t="inlineStr"><is><t xml:space="preserve">{1}</t></is></c>'
                             .format(ref, _xml_escape(val)))
        lines.append('<row r="{}">{}</row>'.format(rnum, "".join(cells)))
    return ('<worksheet xmlns="{0}"><sheetData>{1}</sheetData></worksheet>'
            .format(_NS, "".join(lines)))


def write_xlsx_sheets(sheets):
    """把多张工作表写成 .xlsx 字节。

    sheets: list of (name, headers, rows)。
    """
    sheets_xml = [(name, _sheet_xml(h, r, name)) for name, h, r in sheets]
    n = len(sheets_xml)

    sheet_overrides = "".join(
        '<Override PartName="/xl/worksheets/sheet{}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        .format(i) for i in range(1, n + 1))
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="{ct}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + sheet_overrides +
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    ).format(ct=_CT)

    work_sheets = "".join(
        '<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'.format(name=_xml_escape(name), i=i)
        for i, (name, _) in enumerate(sheets_xml, start=1))
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="{ns}" xmlns:r="{od}"><sheets>{sheets}</sheets></workbook>'
    ).format(ns=_NS, od=_OD, sheets=work_sheets)

    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="{rs}">'
    ).format(rs=_RS)
    for i in range(1, n + 1):
        wb_rels += '<Relationship Id="rId{}" Type="{od}/worksheet" Target="worksheets/sheet{}.xml"/>'.format(i, i, od=_OD)
    wb_rels += '<Relationship Id="rId{}" Type="{od}/styles" Target="styles.xml"/>'.format(n + 1, od=_OD)
    wb_rels += '</Relationships>'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/styles.xml", styles_xml)
        for i, (_, xml) in enumerate(sheets_xml, start=1):
            z.writestr("xl/worksheets/sheet{}.xml".format(i), xml)
    return buf.getvalue()


def write_xlsx(headers, rows, sheet_name="records"):
    """写单张工作表（兼容单 sheet 使用方）。"""
    return write_xlsx_sheets([(sheet_name, headers, rows)])


def _col_to_idx(col):
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def _parse_worksheet(root, shared):
    """把单个 worksheet XML 解析为 (headers, rows)。"""
    grid = []
    for row_el in root.iter(_TAG + "row"):
        cells = {}
        for c in row_el.iter(_TAG + "c"):
            ref = c.get("r") or ""
            t = c.get("t")
            if t == "inlineStr":
                el = c.find(_TAG + "is")
                val = ("".join(x.text or "" for x in el.iter(_TAG + "t"))
                       if el is not None else "")
            elif t == "s":
                v = c.find(_TAG + "v")
                idx = int(v.text) if v is not None and v.text else 0
                val = shared[idx] if idx < len(shared) else ""
            else:
                v = c.find(_TAG + "v")
                val = v.text if v is not None and v.text is not None else ""
            col = "".join(ch for ch in ref if ch.isalpha()) or _col_letter(len(cells) + 1)
            cells[col] = val
        grid.append(cells)

    if not grid:
        return [], []

    header_cells = sorted(grid[0].items(), key=lambda kv: _col_to_idx(kv[0]))
    headers = [(v or "").strip() for _, v in header_cells]
    col_to_header = {c: (v or "").strip() for c, v in header_cells}
    rows = []
    for cells in grid[1:]:
        d = {}
        for c, v in cells.items():
            h = col_to_header.get(c)
            if h:
                d[h] = v
        rows.append(d)
    return headers, rows


def read_xlsx_sheets(data):
    """读取 .xlsx 全部工作表。返回 {sheet_name: (headers, rows)}。"""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(_TAG + "si"):
                shared.append("".join(t.text or "" for t in si.iter(_TAG + "t")))
        wb_root = ET.fromstring(z.read("xl/workbook.xml"))
        # sheet 名 -> r:id
        rid_of = {}
        for sh in wb_root.iter(_TAG + "sheet"):
            rid = sh.get("{%s}id" % _OD) or sh.get("id")
            if rid:
                rid_of[sh.get("name")] = rid
        # r:id -> 目标文件
        target_of = {}
        if "xl/_rels/workbook.xml.rels" in names:
            rels_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            for rel in rels_root:
                rid, tgt = rel.get("Id"), rel.get("Target")
                if rid and tgt:
                    target_of[rid] = tgt
        sheets = {}
        for name, rid in rid_of.items():
            tgt = target_of.get(rid)
            if not tgt:
                continue
            path = tgt if tgt.startswith("xl/") else "xl/" + tgt
            if path not in names:
                continue
            root = ET.fromstring(z.read(path))
            sheets[name] = _parse_worksheet(root, shared)
    return sheets


def read_xlsx(data):
    """读取 .xlsx 第一张工作表。返回 (headers, rows)。"""
    sheets = read_xlsx_sheets(data)
    if not sheets:
        return [], []
    headers, rows = next(iter(sheets.values()))
    return headers, rows


# ---- 当前用户记录的导出 / 导入 ----
COLUMNS = ["日期", "时间", "金额", "分类", "消费场景", "渠道", "备注"]
ACCOUNTS_COLUMNS = ["账户名称", "余额"]


def _category_paths(conn):
    """返回 cid -> 全路径「一级/子项[/商家]」的闭包，解决子项重名无法还原的问题。"""
    cats = {c["id"]: (c["name"] or "", c["parent_id"]) for c in
            conn.execute("SELECT id, name, parent_id FROM dim_category").fetchall()}

    def path_of(cid):
        parts, cur, seen = [], cid, set()
        while cur and cur not in seen:
            seen.add(cur)
            nm, pid = cats.get(cur, ("", None))
            parts.append(nm)
            cur = pid
        return "/".join(reversed(parts))

    return path_of


def export_records(uid):
    """导出当前用户全部记录与账户余额为 .xlsx 字节。

    两张工作表：
      「记账记录」：保存记账时输入的全部字段（日期/时间/金额/分类全路径/消费场景/渠道/备注）；
      「账户」：账户名称 + 当前余额（导入时可自动补建并回写余额）。
    """
    conn = get_user_conn(uid)
    path_of = _category_paths(conn)
    try:
        rows_db = conn.execute(
            """SELECT r.date, r.time, r.amount, r.category_id,
                      m.name AS motive, ch.name AS channel, r.note
               FROM records r
               LEFT JOIN dim_motive m ON m.id=r.motive_id
               LEFT JOIN dim_channel ch ON ch.id=r.channel_id
               ORDER BY r.date, r.time""").fetchall()
        accts = conn.execute(
            "SELECT name, balance FROM dim_channel ORDER BY id").fetchall()
    finally:
        conn.close()
    data = []
    for x in rows_db:
        data.append([x["date"], x["time"] or "", x["amount"],
                     path_of(x["category_id"]), x["motive"] or "",
                     x["channel"] or "", x["note"] or ""])
    account_rows = [[a["name"], a["balance"]] for a in accts]
    return write_xlsx_sheets([
        ("记账记录", COLUMNS, data),
        ("账户", ACCOUNTS_COLUMNS, account_rows),
    ])


def _child_id(uid, name, parent_id):
    """按名称在其父级下查分类 id，找不到返回 None。"""
    conn = get_user_conn(uid)
    try:
        if parent_id is None:
            row = conn.execute(
                "SELECT id FROM dim_category WHERE name=? AND parent_id IS NULL",
                (name,)).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM dim_category WHERE name=? AND parent_id=?",
                (name, parent_id)).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def _resolve_or_create(uid, cname, leaf_by_path, leaf_by_name):
    """按 Excel 的分类名解析叶子 id；找不到则自适应补建整套分类。

    支持「一级/子项[/商家]」全路径，逐层匹配/补建到叶子；
    单个子项名若在现存分类中唯一则复用，否则补建到「其他」一级下
    （保证是可记账的二级叶子，不会建出无法记账的一级）。
    """
    if not cname:
        return None
    if cname in leaf_by_path:
        return leaf_by_path[cname]
    ids = leaf_by_name.get(cname, [])
    if len(ids) == 1:
        return ids[0]
    parts = [p for p in (s.strip() for s in str(cname).split("/")) if p]
    if not parts:
        return None
    if len(parts) == 1:
        parent_id = _child_id(uid, "其他", None)
        if parent_id is None:
            created, err = add_category(uid, "其他", None)
            if err or not created:
                return None
            parent_id = created["id"]
        parts = ["其他", parts[0]]
    parent_id, node_id, ok = None, None, True
    for part in parts:
        node_id = _child_id(uid, part, parent_id)
        if node_id is None:
            created, err = add_category(uid, part, parent_id)
            if err or not created:
                ok = False
                break
            node_id = created["id"]
        parent_id = node_id
    return node_id if ok else None


def import_records(uid, raw):
    """从 .xlsx 字节导入记录与账户余额到当前用户。返回 {added, skipped, errors}。

    「记账记录」按列名匹配「日期/时间/金额/分类/消费场景/渠道/备注」；
    分类按叶子名称解析（全路径 → 唯一叶子名），找不到时自适应补建缺失分类；
    消费场景按名称解析，缺省按收入/支出给默认/不填；渠道按名称，不存在则自动新建。
    以「日期+金额+分类+场景+渠道+备注」去重（幂等）。
    「账户」逐一回写余额：账户缺失则自动新建，Excel 中的余额直接覆盖。
    """
    sheets = read_xlsx_sheets(raw)
    rec_rows = None
    acct_rows = None
    for name, (h, r) in sheets.items():
        if not r:
            continue
        if rec_rows is None and h and "日期" in h:
            rec_rows = r
        if "余额" in h and "账户名称" in h:
            acct_rows = r
    if not rec_rows:
        return {"added": 0, "skipped": 0, "errors": "文件为空或无数据"}

    conn = get_user_conn(uid)
    try:
        path_of = _category_paths(conn)
        # 全路径查表 + 叶子名回退（兼容旧导出格式、兼容重名需唯一）
        leaf_by_path, leaf_by_name = {}, {}
        for c in conn.execute(
                "SELECT id, name, parent_id, level FROM dim_category").fetchall():
            has_child = conn.execute(
                "SELECT 1 FROM dim_category WHERE parent_id=?", (c["id"],)).fetchone()
            if c["level"] >= 2 and not has_child:
                leaf_by_path[path_of(c["id"])] = c["id"]
                leaf_by_name.setdefault(c["name"], []).append(c["id"])
        motive_map = {r["name"]: r["id"]
                      for r in conn.execute("SELECT id, name FROM dim_motive").fetchall()}
        channel_map = {r["name"]: {"id": r["id"], "balance": r["balance"]}
                       for r in conn.execute(
                           "SELECT id, name, balance FROM dim_channel").fetchall()}
        default_motive = None
        for nm, i in motive_map.items():
            if nm == "独自消费":
                default_motive = i
                break
    finally:
        conn.close()

    def resolve_field(row, *keys):
        for k in keys:
            if row.get(k) not in (None, ""):
                return str(row.get(k)).strip()
        return ""

    added = skipped = 0
    skip_reasons = []
    for row in rec_rows:
        try:
            amount = float(resolve_field(row, "金额"))
        except (TypeError, ValueError):
            skipped += 1
            skip_reasons.append("金额无法解析")
            continue
        if amount == 0:
            skipped += 1
            continue
        date = resolve_field(row, "日期")
        if not date:
            skipped += 1
            continue
        # 分类（叶子）：全路径 → 唯一叶子名 → 自适应补建缺失分类
        cname = resolve_field(row, "分类")
        cat_id = _resolve_or_create(uid, cname, leaf_by_path, leaf_by_name)
        if cat_id is None:
            skipped += 1
            skip_reasons.append("分类「%s」无法定位叶子" % cname)
            continue
        # 渠道（不存在则新建）
        chname = resolve_field(row, "渠道")
        ch_id = channel_map.get(chname, {}).get("id")
        if not ch_id:
            created, err = add_channel(uid, chname or "未命名渠道")
            if err:
                skipped += 1
                skip_reasons.append(err)
                continue
            ch_id = created["id"]
            channel_map[chname] = {"id": ch_id}
        # 消费场景
        mname = resolve_field(row, "消费场景")
        motive_id = motive_map.get(mname, default_motive if amount < 0 else None)
        note = resolve_field(row, "备注")
        time_v = resolve_field(row, "时间")

        # 去重（幂等）：日期+金额+分类+场景+渠道+备注
        conn = get_user_conn(uid)
        try:
            dup = conn.execute(
                """SELECT 1 FROM records WHERE date=? AND amount=? AND category_id=?
                   AND COALESCE(motive_id,0)=COALESCE(?,0) AND channel_id=? AND COALESCE(note,'')=?""",
                (date, amount, cat_id, motive_id, ch_id, note or "")).fetchone()
        finally:
            conn.close()
        if dup:
            skipped += 1
            continue
        _, err = add_record(uid, {
            "date": date, "time": time_v or None, "amount": amount,
            "category_id": cat_id, "motive_id": motive_id,
            "channel_id": ch_id, "note": note or None,
        })
        if err:
            skipped += 1
            skip_reasons.append(err)
            continue
        added += 1

    # 回写账户余额：缺失自动新建，余额直接覆盖
    if acct_rows:
        acct_conn = get_user_conn(uid)
        try:
            cid_by_name = {r["name"]: r["id"]
                           for r in acct_conn.execute(
                               "SELECT id, name FROM dim_channel").fetchall()}
            for row in acct_rows:
                if row.get("账户名称") in (None, ""):
                    continue
                name = str(row["账户名称"]).strip()
                try:
                    balance = float(row.get("余额"))
                except (TypeError, ValueError):
                    continue
                ch_id = cid_by_name.get(name)
                if not ch_id:
                    created, err = add_channel(uid, name or "未命名账户")
                    if err or not created:
                        continue
                    ch_id = created["id"]
                    cid_by_name[name] = ch_id
                    ch_conn = get_user_conn(uid)
                    try:
                        ch_conn.execute(
                            "UPDATE dim_channel SET balance=? WHERE id=?", (balance, ch_id))
                        ch_conn.commit()
                    finally:
                        ch_conn.close()
                    continue
                acct_conn.execute(
                    "UPDATE dim_channel SET balance=? WHERE id=?", (balance, ch_id))
            acct_conn.commit()
        finally:
            acct_conn.close()

    return {"added": added, "skipped": skipped,
            "errors": ("；".join(dict.fromkeys(skip_reasons))[:200]
                       if skip_reasons else "")}