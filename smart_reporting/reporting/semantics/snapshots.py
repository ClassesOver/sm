"""严格按登记粒度和完整月末快照差分，不臆造缺失基线。"""

from datetime import date, timedelta
from decimal import Decimal

from ..trace.decimal_math import snapshot_difference
from .values import dimension_values


def monthly_snapshot_values(query, metric, request, rows):
    snapshots, issues = {}, {}
    for row in rows:
        group = dimension_values(query, row)
        period = date.fromisoformat(row["snapshot_period"])
        value = Decimal(row["value"]) if row["value"] else None
        codes = []
        if (period + timedelta(days=1)).day != 1:
            codes.append("cumulative_month_end_required")
        if int(row["observed_count"]) != 1:
            codes.append("cumulative_duplicate_snapshot")
        if value is None or not value.is_finite() or int(row["nonnull_count"]) != int(row["observed_count"]):
            codes.append("null_observations")
        if any(int(row[f"join_max_{index}"] or 0) > 1 for index in range(len(query.join_checks))):
            codes.append("join_fanout")
        month = period.replace(day=1)
        key = (group, month)
        if key in snapshots:
            codes.append("cumulative_duplicate_snapshot")
        snapshots[key] = value
        issues.setdefault(group, []).extend(codes)
    outputs = {}
    for group in dict.fromkeys(key[0] for key in snapshots):
        output_group = tuple(group[query.dimensions.index(name)] for name in request.dimensions)
        amounts, codes = outputs.setdefault(output_group, ([], []))
        codes.extend(issues[group])
        month = request.period.start
        while month < request.period.end:
            current = snapshots.get((group, month))
            if current is None:
                codes.append("cumulative_snapshot_missing")
            elif month.month == 1 and metric.aggregation_policy.reset is None:
                codes.append("cumulative_reset_unresolved")
            else:
                baseline_month = (month - timedelta(days=1)).replace(day=1)
                baseline = Decimal(0) if month.month == 1 and metric.aggregation_policy.reset == "calendar_year_zero" else snapshots.get((group, baseline_month))
                if baseline is None:
                    codes.append("cumulative_baseline_missing")
                else:
                    amounts.append(snapshot_difference(current, baseline))
            month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    def total(amounts):
        value = Decimal(0)
        for amount in amounts:
            value = snapshot_difference(value, amount.copy_negate())
        return value
    return {group: (None if codes else total(amounts), tuple(dict.fromkeys(codes)) or ("cumulative_snapshot_change_not_flow",))
        for group, (amounts, codes) in outputs.items()}
