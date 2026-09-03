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


def write_xlsx(headers, rows, sheet_name="records"):
    """把表头 + 数据写成 .xlsx 字节。rows 为等长 list（与 headers 对齐）。"""
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
    sheet = ('<worksheet xmlns="{0}"><sheetData>{1}</sheetData></worksheet>'
             .format(_NS, "".join(lines)))

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="{ct}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    ).format(ct=_CT)

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="{rs}">'
        '<Relationship Id="rId1" Type="{od}/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    ).format(rs=_RS, od=_OD)

    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="{ns}" xmlns:r="{od}">'
        '<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    ).format(ns=_NS, od=_OD, name=_xml_escape(sheet_name))

    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="{rs}">'
        '<Relationship Id="rId1" Type="{od}/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="{od}/styles" Target="styles.xml"/>'
        '</Relationships>'
    ).format(rs=_RS, od=_OD)

    styles = (
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

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/styles.xml", styles)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def _col_to_idx(col):
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def read_xlsx(data):
    """从 .xlsx 字节读数据。返回 (headers, rows)。

    headers: 首行表头（去空白）列表
    rows:    其余行，list[dict]，dict 以表头为键（数值已转文本）
    """
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(_TAG + "si"):
                shared.append("".join(t.text or "" for t in si.iter(_TAG + "t")))
        sheet_path = "xl/worksheets/sheet1.xml"
        if sheet_path not in names:
            return [], []
        root = ET.fromstring(z.read(sheet_path))

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


# ---- 当前用户记录的导出 / 导入 ----
COLUMNS = ["日期", "时间", "金额", "分类", "消费场景", "渠道", "备注"]


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
    """导出当前用户全部记录为 .xlsx 字节。

    保存记账时输入的全部字段：日期/时间/金额/分类(全路径)/消费场景/渠道/备注。
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
    finally:
        conn.close()
    data = []
    for x in rows_db:
        data.append([x["date"], x["time"] or "", x["amount"],
                     path_of(x["category_id"]), x["motive"] or "",
                     x["channel"] or "", x["note"] or ""])
    return write_xlsx(COLUMNS, data, "记账记录")


def import_records(uid, raw):
    """从 .xlsx 字节导入记录到当前用户。返回 {added, skipped, errors}。

    按列名匹配「日期/时间/金额/分类/消费场景/渠道/备注」；
    分类按叶子名称解析（同名歧义时只解析到唯一叶子，否则跳过）；
    消费场景按名称解析，缺省按收入/支出给默认/不填；渠道按名称，不存在则自动新建。
    以「日期+金额+分类+场景+渠道+备注」去重（幂等）。
    """
    headers, rows = read_xlsx(raw)
    if not headers or not rows:
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
    for row in rows:
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
        # 分类（叶子）：优先按全路径，其次按唯一叶子名
        cname = resolve_field(row, "分类")
        cat_id = None
        if cname:
            if cname in leaf_by_path:
                cat_id = leaf_by_path[cname]
            else:
                ids = leaf_by_name.get(cname, [])
                if len(ids) == 1:
                    cat_id = ids[0]
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
    return {"added": added, "skipped": skipped,
            "errors": ("；".join(dict.fromkeys(skip_reasons))[:200]
                       if skip_reasons else "")}