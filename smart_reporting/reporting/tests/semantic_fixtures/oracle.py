"""人工可复核的Decimal oracle；禁止依赖生产公式、SQL或度量模型。"""

import csv
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path


def read_amounts(path: Path) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            key = row["project_id"]
            totals[key] = totals.get(key, Decimal(0)) + Decimal(row["amount"])
    return totals


def execution_ratio(actual: dict[str, Decimal], budget: dict[str, Decimal]) -> Decimal | None:
    if not actual or not budget:
        return None
    denominator = sum(budget.values(), Decimal(0))
    if denominator == 0:
        return None
    return (sum(actual.values(), Decimal(0)) / denominator * 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )


def unique_document_total(rows: tuple[tuple[str, str], ...]) -> Decimal:
    documents: dict[str, Decimal] = {}
    for identity, amount in rows:
        value = Decimal(amount)
        if identity in documents and documents[identity] != value:
            raise ValueError("同一单据出现不同金额，不能自行裁定")
        documents[identity] = value
    return sum(documents.values(), Decimal(0))


def snapshot_changes(
    rows: tuple[tuple[str, str], ...], *, calendar_year_reset: bool = False,
) -> tuple[Decimal, ...]:
    changes = []
    previous = Decimal(0)
    year = None
    for period, amount in rows:
        if year is not None and period[:4] != year:
            if not calendar_year_reset:
                raise ValueError("跨年累计必须明确重置政策")
            previous = Decimal(0)
        current = Decimal(amount)
        changes.append(current - previous)
        previous, year = current, period[:4]
    return tuple(changes)
