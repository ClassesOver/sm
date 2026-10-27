"""冻结补证请求的最小 Python 兜底脚本基线。

该脚本只用于同输入性能对照，不代表生产 CodeMode 生成结果。
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def main() -> int:
    csv_path, request_path, output_path = map(Path, sys.argv[1:4])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    with csv_path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    current_periods = set(request["currentPeriods"])
    grouped: defaultdict[str, float] = defaultdict(float)
    for row in rows:
        if row.get(request["periodField"]) not in current_periods:
            continue
        dimension = row.get(request["dimensionField"])
        raw_value = row.get(request["measureField"])
        if dimension in (None, "") or raw_value in (None, ""):
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        grouped[str(dimension)] += value
    total = sum(grouped.values())
    ordered = sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
    result_rows = [
        [dimension, value, index, value / total if total else None]
        for index, (dimension, value) in enumerate(ordered, start=1)
    ]
    payload: dict[str, Any] = {
        "findings": [{
            "name": request["outputName"],
            "columns": [request["dimensionField"], "value", "rank", "share"],
            "rows": result_rows,
        }],
        "reconciliations": [{
            "name": request["outputName"] + "_total",
            "passed": abs(total - request["parentTotal"]) <= max(
                1e-9, 1e-12 * max(abs(total), abs(request["parentTotal"])),
            ),
            "left": total,
            "right": request["parentTotal"],
        }],
        "warnings": [],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
