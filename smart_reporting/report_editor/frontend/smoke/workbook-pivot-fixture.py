"""真实透视表烟测的来源生成、后端补丁及独立ZIP/openpyxl回读。"""
import base64
import json
import re
import sys
import zipfile
from io import BytesIO
from openpyxl import Workbook, load_workbook

payload = json.load(sys.stdin)
if payload["mode"] == "source":
    book = Workbook()
    sheet = book.active
    sheet.title = "数据"
    book.create_sheet("分析")
    for row in [("区域", "团队", "年份", "收入", "数量"), ("华东", "A", 2025, 10, 2), ("华东", "A", 2026, 20, 4), ("华东", "B", 2025, 30, 6), ("华西", "A", 2026, 40, 8)]:
        sheet.append(row)
    stream = BytesIO()
    book.save(stream)
    print(base64.b64encode(stream.getvalue()).decode())
elif payload["mode"] == "patch":
    from smart_reporting.report_editor.native_office import patch_office
    print(base64.b64encode(patch_office("xlsx", base64.b64decode(payload["bytes"]), payload["operations"])).decode())
else:
    data = base64.b64decode(payload["bytes"])
    book = load_workbook(BytesIO(data))
    sheet = book["分析"]
    package = zipfile.ZipFile(BytesIO(data))
    print(json.dumps({
        "pivots": [{"name": table.name, "cacheId": table.cacheId, "ref": table.location.ref,
                    "rows": [item.x for item in table.rowFields or []], "columns": [item.x for item in table.colFields or []],
                    "values": [{"field": item.fld, "aggregate": item.subtotal} for item in table.dataFields],
                    "recordCount": table.cache.recordCount, "source": table.cache.cacheSource.worksheetSource.ref} for table in sheet._pivots],
        "sourceBold": book["数据"]["A1"].font.bold,
        "cells": [[sheet.cell(row, column).value for column in range(2, 7)] for row in range(2, 10)],
        "source": [[book["数据"].cell(row, column).value for column in range(1, 6)] for row in range(1, 6)],
        "parts": {name: package.read(name).decode() for name in package.namelist() if re.match(r"xl/(pivotTables|pivotCache)/[^/]+\.xml$", name)},
    }))
