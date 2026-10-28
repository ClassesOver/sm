"""Independent numerical expectations for contributions and raw sample distributions."""

import copy
import math
import random

from scripts.standard_visualization_geometry_cases import parameters


def quartiles(samples, whis=1.5):
    ordered = sorted(samples)

    def percentile(fraction):
        position = (len(ordered) - 1) * fraction
        low = math.floor(position)
        high = math.ceil(position)
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    q1, median, q3 = [percentile(fraction) for fraction in (0.25, 0.5, 0.75)]
    iqr = q3 - q1
    low = min((value for value in ordered if value >= q1 - whis * iqr), default=q1)
    high = max((value for value in ordered if value <= q3 + whis * iqr), default=q3)
    low = min(low, q1)
    high = max(high, q3)
    return [q1, median, q3, low, high], [value for value in ordered if value < low or value > high]


def case(identity, params, document, expected="render", **assertions):
    return {
        "id": "statistics-" + identity,
        "group": "statistics",
        "variant": identity,
        "synthetic": True,
        "parameters": params,
        "documents": [document],
        "expected": expected,
        "assertions": assertions,
    }


def statistics_cases():
    for seed in (3, 17, 51):
        for scale in (1e-10, 1, 1e10):
            rng = random.Random(seed)
            # Integers before scaling give an independent complete contribution chain.
            increase = rng.randint(10, 40)
            decrease = -rng.randint(50, 90)
            adjustment = -200 if seed == 51 else rng.randint(10, 30)
            subtotal = 100 + increase + decrease
            final = subtotal + adjustment
            labels = ["期初", "新增", "减少", "小计", "调整", "期末"]
            raw = [100, increase, decrease, subtotal, adjustment, final]
            values = [value * scale for value in raw]
            document = {
                "columns": ["label", "value"],
                "rows": [[label, value] for label, value in zip(labels, values)],
                "columnMeta": {"value": {"unit": "元"}},
            }
            starts = [0, 100, 100 + increase, 0, subtotal, 0]
            heights = raw
            for connectors in (True, False):
                params = parameters(
                    "waterfall",
                    standard_style={"labelRotation": 0, "decimals": 4},
                    standard_label_field="label",
                    standard_value_fields=["value"],
                    standard_waterfall={
                        "valueField": "value",
                        "absoluteLabels": ["期初", "小计", "期末"],
                        "connectors": connectors,
                    },
                    standard_display_unit="万元",
                    standard_annotations=[{"kind": "values", "series": "value"}],
                )
                colors = [
                    "#3066a3",
                    "#36856b",
                    "#b55d68",
                    "#3066a3",
                    "#36856b" if adjustment >= 0 else "#b55d68",
                    "#3066a3",
                ]
                yield case(
                    f"waterfall-{seed}-{scale}-{connectors}",
                    params,
                    document,
                    waterfalls=[
                        {
                            "positions": list(range(len(labels))),
                            "starts": [v * scale / 1e4 for v in starts],
                            "heights": [v * scale / 1e4 for v in heights],
                            "colors": colors,
                            "connectors": [
                                v * scale / 1e4
                                for v in [100, 100 + increase, subtotal, subtotal, final]
                            ]
                            if connectors
                            else [],
                        }
                    ],
                )
            samples = {
                "甲": [rng.randint(1, 30) * scale for _ in range(25)] + [200 * scale],
                "乙": [10 * scale] * 3,
                "丙": [rng.randint(1, 10) * scale for _ in range(4)],
            }
            if seed == 17:
                samples["甲"] += [-40 * scale]
            rows = [[group, value] for group, values in samples.items() for value in values]
            if seed == 17:
                rows.append(["丙", None])
            rng.shuffle(rows)
            document = {
                "columns": ["group", "value"],
                "rows": rows,
                "columnMeta": {"value": {"unit": "元"}},
            }
            groups = ["丙", "乙", "甲"]
            for orientation in ("vertical", "horizontal"):
                show = seed != 17
                spec = {
                    "valueField": "value",
                    "groupField": "group",
                    "groupLabels": groups,
                    "orientation": orientation,
                    "showFliers": show,
                    "whiskerIqr": 1.5,
                }
                params = parameters(
                    "boxplot",
                    standard_value_fields=["value"],
                    standard_distribution=spec,
                    standard_display_unit="万元",
                    standard_axes={
                        "allowNulls": True,
                        "scale": "symlog" if seed == 17 else "log" if seed == 51 else "linear",
                        "linearThreshold": scale / 1e4,
                    },
                    standard_style={
                        "labelRotation": 0,
                        "series": [{"series": "甲", "color": "#8573a6"}],
                    },
                    standard_annotations=[{"kind": "values", "series": "value"}],
                )
                boxes = []
                for index, group in enumerate(groups):
                    stats, fliers = quartiles([value / 1e4 for value in samples[group]])
                    boxes.append(
                        {
                            "name": group,
                            "horizontal": orientation == "horizontal",
                            "statistics": stats,
                            "fliers": fliers if show else [],
                            "color": "#8573a6" if group == "甲" else ["#3066a3", "#dc884d"][index],
                        }
                    )
                yield case(
                    f"boxplot-{seed}-{scale}-{orientation}",
                    params,
                    document,
                    boxes=boxes,
                    texts=[f"{group} (n={len(samples[group])})" for group in groups],
                )
    waterfall = {
        "columns": ["label", "value"],
        "rows": [["起点", 100], ["增减", -20], ["终点", 80]],
        "columnMeta": {"value": {"unit": "元"}},
    }
    waterfall_params = parameters(
        "waterfall",
        standard_label_field="label",
        standard_value_fields=["value"],
        standard_waterfall={"valueField": "value", "absoluteLabels": ["起点", "终点"]},
    )
    for fault in (
        "total",
        "null",
        "bool",
        "unit",
        "first_role",
        "duplicate_role",
        "tiny_increment",
    ):
        doc, params = copy.deepcopy(waterfall), copy.deepcopy(waterfall_params)
        if fault == "total":
            doc["rows"][-1][1] = 81
        elif fault == "null":
            doc["rows"][1][1] = None
        elif fault == "bool":
            doc["rows"][1][1] = True
        elif fault == "unit":
            doc["columnMeta"] = {}
        elif fault == "first_role":
            params["standard_waterfall"]["absoluteLabels"] = ["终点"]
        elif fault == "duplicate_role":
            params["standard_waterfall"]["absoluteLabels"] = ["起点", "终点", "终点"]
        else:
            doc["rows"] = [["起点", 1e20], ["增减", 1], ["终点", 1e20]]
        yield case("reject-waterfall-" + fault, params, doc, "fallback")
    box = {
        "columns": ["group", "value"],
        "rows": [["甲", 1], ["甲", 2], ["乙", 3]],
        "columnMeta": {"value": {"unit": "元"}},
    }
    box_params = parameters(
        "boxplot", standard_distribution={"groupField": "group", "valueField": "value"}
    )
    for fault in ("empty_group", "order", "log_zero", "overflow", "label_subset"):
        doc, params = copy.deepcopy(box), copy.deepcopy(box_params)
        if fault == "empty_group":
            doc["rows"][-1][1] = None
            params["standard_axes"] = {"allowNulls": True}
        elif fault == "order":
            params["standard_distribution"]["groupLabels"] = ["甲"]
        elif fault == "log_zero":
            doc["rows"][0][1] = 0
            params["standard_axes"] = {"scale": "log"}
        elif fault == "overflow":
            doc["rows"] = [["甲", -1.7e308], ["甲", 1.7e308]]
        else:
            params["standard_labels"] = ["甲"]
        yield case("reject-boxplot-" + fault, params, doc, "fallback")
