"""Direct supplied-statistic oracles: these cases do not compute sample quartiles."""

import copy
import random

from scripts.standard_visualization_geometry_cases import parameters


def case(name, params, documents, expected="render", **assertions):
    return {
        "id": "summaries-" + name,
        "group": "summaries",
        "variant": name,
        "synthetic": True,
        "parameters": params,
        "documents": documents,
        "expected": expected,
        "assertions": assertions,
    }


def summary_spec():
    return dict(
        groupField="group",
        q1Field="q1",
        medianField="median",
        q3Field="q3",
        lowerWhiskerField="low",
        upperWhiskerField="high",
        countField="n",
    )


def summary_cases():
    periods = ["2026-10"]
    groups = ["东院", "西院", "门诊"]
    for seed in (3, 17, 51):
        for scale in (1e-10, 1, 1e10):
            rng = random.Random(seed)
            for mode in ("known-vertical", "known-horizontal", "unknown", "empty"):
                rows = []
                supplied = {}
                anomalies = []
                for i, group in enumerate(groups):
                    base = (-15 if seed == 17 else rng.randint(10, 20)) + i * 30
                    low, q1, median, q3, high = [
                        (base + offset) * scale for offset in (0, 5, 10, 15, 20)
                    ]
                    count = 100 + i * 50
                    rows.append([group, q1 / 1e4, median, q3, low, high / 1e8, count])
                    supplied[group] = [q1 / 1e4, median / 1e4, q3 / 1e4, low / 1e4, high / 1e4]
                    anomalies.extend(
                        [[group, (low - 5 * scale) / 1e4], [group, (high + 5 * scale) / 1e4]]
                    )
                # Duplicate source rows are duplicate observations, not a reason to deduplicate.
                anomalies.append(copy.deepcopy(anomalies[0]))
                doc = {
                    "columns": ["group", "q1", "median", "q3", "low", "high", "n"],
                    "rows": rows,
                    "columnMeta": {
                        **{
                            field: {"unit": "元", "periods": periods}
                            for field in ["q1", "median", "q3", "low", "high"]
                        },
                        "n": {"unit": "个", "periods": periods},
                    },
                }
                doc["columnMeta"]["q1"]["unit"] = "万元"
                doc["columnMeta"]["high"]["unit"] = "亿元"
                extra = {
                    "columns": ["group", "value"],
                    "rows": anomalies if mode != "empty" else [],
                    "columnMeta": {"value": {"unit": "万元", "periods": periods}},
                }
                spec = summary_spec()
                spec.update(
                    groupLabels=list(reversed(groups)),
                    orientation="horizontal" if mode == "known-horizontal" else "vertical",
                )
                if mode != "unknown":
                    spec["outlierSource"] = {
                        "sourceIndex": 1,
                        "groupField": "group",
                        "valueField": "value",
                    }
                else:
                    spec.pop("countField")
                if mode == "known-horizontal" and seed == 17:
                    spec["showFliers"] = False
                style = {
                    "labelRotation": 0,
                    "decimals": 4,
                    "series": [{"series": "东院", "color": "#8573a6"}],
                }
                params = parameters(
                    "boxplot",
                    standard_value_fields=["median"],
                    standard_box_summary=spec,
                    standard_display_unit="万元",
                    standard_style=style,
                    standard_axes={
                        "scale": "symlog" if seed == 17 else "log" if seed == 51 else "linear",
                        "linearThreshold": scale / 1e4,
                    },
                    standard_annotations=[{"kind": "values", "series": "median"}],
                )
                documents = [doc] if mode == "unknown" else [doc, extra]
                boxes = []
                for i, group in enumerate(reversed(groups)):
                    points = (
                        [value for name, value in extra["rows"] if name == group]
                        if mode != "unknown" and spec.get("showFliers", True)
                        else []
                    )
                    boxes.append(
                        {
                            "name": group,
                            "horizontal": spec["orientation"] == "horizontal",
                            "statistics": supplied[group],
                            "fliers": points,
                            "color": "#8573a6" if group == "东院" else ["#3066a3", "#dc884d"][i],
                        }
                    )
                texts = [
                    f"{group} (n未提供)"
                    if mode == "unknown"
                    else f"{group} (n={100 + groups.index(group) * 50})"
                    for group in groups
                ]
                texts += ["未从原始样本重算", "须不假定为IQR或最值"]
                if mode == "unknown":
                    texts += ["异常点未提供", "样本量未提供"]
                elif not spec.get("showFliers", True):
                    texts += ["已按参数隐藏"]
                elif mode == "empty":
                    texts += ["绑定异常点记录0项"]
                yield case(f"{mode}-{seed}-{scale}", params, documents, boxes=boxes, texts=texts)
    doc = {
        "columns": ["group", "q1", "median", "q3", "low", "high", "n"],
        "rows": [["东院", 10, 20, 30, 5, 40, 100], ["西院", 100, 200, 300, 50, 400, 80]],
        "columnMeta": {
            **{
                field: {"unit": "元", "periods": periods}
                for field in ["q1", "median", "q3", "low", "high"]
            },
            "n": {"unit": "个", "periods": periods},
        },
    }
    extra = {
        "columns": ["group", "value"],
        "rows": [["东院", 1], ["西院", 500]],
        "columnMeta": {"value": {"unit": "元", "periods": periods}},
    }
    for fault in (
        "ordering",
        "missing_field",
        "duplicate",
        "count_zero",
        "count_fraction",
        "count_money",
        "inside",
        "unknown_group",
        "extra_unit",
        "period",
        "log_zero",
        "unused_source",
    ):
        first, second = copy.deepcopy(doc), copy.deepcopy(extra)
        spec = summary_spec()
        spec["outlierSource"] = {"sourceIndex": 1, "groupField": "group", "valueField": "value"}
        params = parameters("boxplot", standard_value_fields=["median"], standard_box_summary=spec)
        if fault == "ordering":
            first["rows"][0][1] = 25
        elif fault == "missing_field":
            spec["q3Field"] = "不存在"
        elif fault == "duplicate":
            first["rows"].append(copy.deepcopy(first["rows"][0]))
        elif fault == "count_zero":
            first["rows"][0][-1] = 0
        elif fault == "count_fraction":
            first["rows"][0][-1] = 1.5
        elif fault == "count_money":
            first["columnMeta"]["n"]["unit"] = "元"
        elif fault == "inside":
            second["rows"][0][1] = 15
        elif fault == "unknown_group":
            second["rows"][0][0] = "不存在"
        elif fault == "extra_unit":
            second["columnMeta"]["value"]["unit"] = "人次"
        elif fault == "period":
            first["columnMeta"]["low"]["periods"] = ["2025-10"]
        elif fault == "log_zero":
            first["rows"][0][4] = 0
            params["standard_axes"] = {"scale": "log"}
        else:
            spec.pop("outlierSource")
        yield case("reject-" + fault, params, [first, second], "fallback")
