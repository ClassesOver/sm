"""Shared descriptors of frozen deterministic facts for generation and editing."""

from collections.abc import Mapping
from typing import Any

from ...trace.fact_index import breakdown_partition_rows
from .chart_inputs import ranked_detail_scope


def breakdown_descriptors(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expose a whole breakdown only when it is one complete metric/dimension."""
    fields = ["parentFactId", "breakdownField", "breakdownLabel", "breakdownValue",
              "displayName", "total", "unit"]
    partitions = breakdown_partition_rows(payload)
    descriptors: list[dict[str, Any]] = []
    if len(partitions) == 1 and sum(map(len, partitions.values())) == len(payload.get("breakdowns") or ()):
        whole_rows = [row for _index, row in next(iter(partitions.values()))]
        common = [field for field in fields if all(
            field in row and (row[field] is None or isinstance(row[field], (str, int, float, bool)))
            for row in whole_rows
        )]
        # Historical snapshots may omit optional displayName/breakdownLabel.
        # Sign only real common fields instead of inventing empty cells.
        if {"parentFactId", "breakdownField", "breakdownValue", "total"}.issubset(common):
            descriptors.append({"dataPath": "breakdowns", "fields": common,
                                "dataScope": "同一指标同一维度的完整分组合计",
                                "standardHints": {"standardLabelField": "breakdownValue", "standardValueFields": ["total"]}})
    for rows in partitions.values():
        if len(rows) > 6:
            continue
        for index, item in rows:
            if len(partitions) > 1:
                descriptors.append({"dataPath": f"breakdowns[{index}]", "fields": [
                    field for field in fields if field in item
                    and (item[field] is None or isinstance(item[field], (str, int, float, bool)))
                ]})
            if item.get("periodValues"):
                descriptors.append({"dataPath": f"breakdowns[{index}].periodValues", "fields": ["period", "value"]})
    return descriptors


def deterministic_chart_descriptors(
    payload: Mapping[str, Any], *, include_all_breakdown_details: bool = False,
) -> list[dict[str, Any]]:
    """Sign exact selectors; ranked groups never stand in for a population."""
    descriptors: list[dict[str, Any]] = []
    for index, metric in enumerate(payload.get("metrics") or ()):
        if not isinstance(metric, Mapping):
            continue
        descriptors.append(_scalar_descriptor(f"metrics[{index}]", metric))
        for collection, fields in (
            ("periodValues", ["period", "value"]),
            ("topGroups", ["group", "value"]),
            ("bottomGroups", ["group", "value"]),
        ):
            path = f"metrics[{index}].{collection}"
            scope = ranked_detail_scope(path)
            descriptors.append({"dataPath": path, "fields": fields, **({"dataScope": scope} if scope else {})})
    descriptors.extend(breakdown_descriptors(payload))
    for collection in ("metrics", "breakdowns"):
        for index, metric in enumerate(payload.get(collection) or ()):
            if not isinstance(metric, Mapping):
                continue
            if collection == "breakdowns" and include_all_breakdown_details:
                descriptors.append(_scalar_descriptor(f"{collection}[{index}]", metric))
                descriptors.append({"dataPath": f"{collection}[{index}].periodValues", "fields": ["period", "value"]})
            # None/absent is unavailable, not proof of a complete population.
            population = metric.get("groupPopulation")
            if isinstance(population, (list, tuple)) and population and all(
                isinstance(row, Mapping) and isinstance(row.get("group"), str)
                and (row.get("value") is None or isinstance(row.get("value"), (int, float)))
                and "value" in row and not isinstance(row.get("value"), bool)
                for row in population
            ):
                descriptors.append({"dataPath": f"{collection}[{index}].groupPopulation", "fields": ["group", "value"],
                                    "dataScope": "冻结的完整分组；不得由 Top/Bottom 拼接替代"})
    for collection in ("derivedMetrics", "comparisons"):
        descriptors.extend(
            _scalar_descriptor(f"{collection}[{index}]", item)
            for index, item in enumerate(payload.get(collection) or ()) if isinstance(item, Mapping)
        )
    # The editor also keeps its historical per-group selectors. Shared narrower
    # selectors take precedence over duplicate paths, preserving their scope.
    unique: dict[str, dict[str, Any]] = {}
    for descriptor in descriptors:
        unique.setdefault(descriptor["dataPath"], descriptor)
    return list(unique.values())


def _scalar_descriptor(path: str, value: Mapping[str, Any]) -> dict[str, Any]:
    return {"dataPath": path, "fields": sorted(
        key for key, item in value.items() if item is None or isinstance(item, (str, int, float, bool))
    )}
