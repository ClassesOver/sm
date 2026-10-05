"""B0 追溯合成 fixtures 与独立标准答案（计划第 9 节）。

输入 CSV 全部可手算；expected/*.json 是人工手算常量（答案来源），
answers.py 用标准库 csv + 纯 Python 独立重算（与被测 polars 实现不同路径），
两者在 test_lineage_fixtures.py 中互证自洽。答案不从被测实现反向生成。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent
CSV_DIR = FIXTURES_DIR / "csv"
EXPECTED_DIR = FIXTURES_DIR / "expected"


def csv_path(name: str) -> Path:
    return CSV_DIR / name


def expected(name: str) -> dict[str, Any]:
    return json.loads((EXPECTED_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


# ---------------------------------------------------------------------------
# 独立核算（答案来源与被测实现分离）
# ---------------------------------------------------------------------------


def recompute_r1() -> dict[str, Any]:
    rows = _read_rows(csv_path("hospital_revenue.csv"))
    current = [r for r in rows if r["period"] == "2025-09"]
    baseline = [r for r in rows if r["period"] == "2025-08"]
    revenue = sum(float(r["revenue"]) for r in current)
    visits = sum(int(r["visits"]) for r in current)
    baseline_revenue = sum(float(r["revenue"]) for r in baseline)
    return {
        "revenue_total": revenue,
        "visits_total": visits,
        "revenue_per_visit": revenue / visits,
        "mom_change": revenue - baseline_revenue,
        "mom_rate_pct": (revenue - baseline_revenue) / baseline_revenue * 100,
    }


def recompute_r2() -> dict[str, Any]:
    rows = _read_rows(csv_path("hospital_revenue.csv"))
    current = [r for r in rows if r["period"] == "2025-09" and r["branch"] == "A院区"]
    baseline = [r for r in rows if r["period"] == "2025-08" and r["branch"] == "A院区"]
    assert len(current) == 1 and len(baseline) == 1
    revenue = float(current[0]["revenue"])
    visits = int(current[0]["visits"])
    baseline_revenue = float(baseline[0]["revenue"])
    baseline_visits = int(baseline[0]["visits"])
    return {
        "revenue_total": revenue,
        "visits_total": visits,
        "revenue_per_visit": revenue / visits,
        "baseline_revenue_total": baseline_revenue,
        "baseline_visits_total": baseline_visits,
        "baseline_revenue_per_visit": baseline_revenue / baseline_visits,
        "mom_change": revenue - baseline_revenue,
        "mom_rate_pct": (revenue - baseline_revenue) / baseline_revenue * 100,
    }


def recompute_contribution() -> dict[str, Any]:
    rows = _read_rows(csv_path("hospital_revenue.csv"))
    by_branch: dict[str, dict[str, float]] = {}
    for row in rows:
        branch = row["branch"]
        slot = by_branch.setdefault(branch, {"current": 0.0, "baseline": 0.0})
        slot["current" if row["period"] == "2025-09" else "baseline"] += float(
            row["revenue"]
        )
    total_delta = sum(v["current"] - v["baseline"] for v in by_branch.values())
    branches = {}
    for branch, v in sorted(by_branch.items()):
        delta = v["current"] - v["baseline"]
        branches[branch] = {
            "current": v["current"],
            "baseline": v["baseline"],
            "delta": delta,
            "share_pct": round(delta / total_delta * 100, 2),
        }
    return {
        "branch_deltas": branches,
        "total": {
            "current": sum(v["current"] for v in by_branch.values()),
            "baseline": sum(v["baseline"] for v in by_branch.values()),
            "delta": total_delta,
        },
    }


def recompute_chart_topn(top_n: int = 3) -> dict[str, Any]:
    rows = _read_rows(csv_path("chart_series.csv"))
    branches = {r["branch"]: r for r in rows}
    ordered = sorted(branches, key=lambda b: float(branches[b]["revenue"]), reverse=True)
    top = ordered[:top_n]
    others = ordered[top_n:]

    def series(field: str) -> dict[str, Any]:
        # Top 类别保留原值（缺值保持 None）；「其他」= 其余成员合计（缺值按 0 计）。
        yuan: list[float | None] = [_num(branches[b][field]) for b in top]
        other_sum = sum(
            v for v in (_num(branches[b][field]) for b in others) if v is not None
        )
        return {
            "yuan": yuan + [other_sum],
            "missing_category": next(
                (b for b in top if _num(branches[b][field]) is None), None
            ),
        }

    revenue = series("revenue")
    expenses = series("expenses")
    return {
        "category_order": top + ["其他"],
        "revenue": {
            "yuan": revenue["yuan"],
            "wan": [
                round(v / 10000, 3) if v is not None else None for v in revenue["yuan"]
            ],
        },
        "expenses": {
            "yuan": expenses["yuan"],
            "wan": [
                round(v / 10000, 3) if v is not None else None
                for v in expenses["yuan"]
            ],
            "missing_category": expenses["missing_category"],
        },
        "other_members": others,
    }


def recompute_edge() -> dict[str, Any]:
    rows = _read_rows(csv_path("edge_cases.csv"))

    def pick(period: str, branch: str) -> dict[str, str] | None:
        return next(
            (r for r in rows if r["period"] == period and r["branch"] == branch), None
        )

    d_current, d_baseline = pick("2025-09", "D院区"), pick("2025-08", "D院区")
    e_current, e_baseline = pick("2025-09", "E院区"), pick("2025-08", "E院区")
    assert d_current is not None and d_baseline is not None
    assert e_current is not None and e_baseline is None
    change = float(d_current["revenue"]) - float(d_baseline["revenue"])
    return {
        "branch_d": {
            "current_revenue": float(d_current["revenue"]),
            "baseline_revenue": float(d_baseline["revenue"]),
            "mom_change": change,
            "mom_rate_pct": None if float(d_baseline["revenue"]) == 0 else change / float(d_baseline["revenue"]) * 100,
            "mom_rate_reason": "zero_denominator" if float(d_baseline["revenue"]) == 0 else None,
        },
        "branch_e": {
            "current_revenue": sum(
                float(r["revenue"]) for r in rows if r["period"] == "2025-09" and r["branch"] == "E院区" and r["revenue"] != ""
            ),
            "current_revenue_missing_count": sum(
                1 for r in rows if r["period"] == "2025-09" and r["branch"] == "E院区" and r["revenue"] == ""
            ),
            "mom": None,
            "mom_reason": "missing_baseline",
        },
    }


def recompute_boundaries() -> dict[str, Any]:
    rows = _read_rows(csv_path("boundaries.csv"))
    return {
        "record_count": len(rows),
        "names": [r["name"] for r in rows],
        "name_lengths": [len(r["name"]) for r in rows],
        "amounts": [int(r["amount"]) for r in rows],
    }


def wide_csv_bytes(rows: int = 3, columns: int = 60) -> bytes:
    """生成宽表 CSV（列数超过预览 50 列预算），用于 B1 受控列选择验证。"""

    header = ["row_id", *(f"c{i:03d}" for i in range(1, columns + 1))]
    lines = [",".join(header)]
    for r in range(1, rows + 1):
        lines.append(",".join([f"r{r:03d}", *(str(r * 100 + i) for i in range(1, columns + 1))]))
    return ("\n".join(lines) + "\n").encode("utf-8")


__all__ = [
    "CSV_DIR",
    "EXPECTED_DIR",
    "FIXTURES_DIR",
    "csv_path",
    "expected",
    "recompute_r1",
    "recompute_r2",
    "recompute_contribution",
    "recompute_chart_topn",
    "recompute_edge",
    "recompute_boundaries",
    "wide_csv_bytes",
]
