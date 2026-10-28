"""Axis viewports checked independently of the renderer and in display units."""

import copy
import random

from scripts.standard_visualization_geometry_cases import parameters


def case(name, params, document, expected="render", **assertions):
    return {
        "id": "domains-" + name,
        "group": "domains",
        "variant": name,
        "synthetic": True,
        "parameters": params,
        "documents": [document],
        "expected": expected,
        "assertions": assertions,
    }


def domain_cases():
    for seed in (3, 17, 51):
        for scale in (1e-10, 1, 1e10):
            rng = random.Random(seed)
            values = [rng.randint(5, 15) * scale, rng.randint(25, 30) * scale]
            source = {
                "columns": ["label", "actual", "budget"],
                "rows": [["一月", values[0], 20 * scale], ["二月", values[1], 40 * scale]],
                "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}},
            }
            for mode in ("single", "dual", "panels", "zoom", "stack", "scatter", "barh", "band"):
                doc = copy.deepcopy(source)
                params = parameters(
                    "line", standard_value_fields=["actual", "budget"], standard_annotations=[]
                )
                limit = 25 * scale if seed == 17 and mode == "single" else 50 * scale
                domain = {
                    "min": 0,
                    "max": limit,
                    "ticks": [0, limit / 2, limit],
                    "tickFormat": "scientific",
                    "decimals": 2,
                }
                if seed == 17 and mode == "single":
                    domain["outOfRange"] = "annotate"
                params["standard_domains"] = {"left": domain}
                oracle = [
                    {
                        "coordinate": "y",
                        "limits": [0, limit],
                        "ticks": domain["ticks"],
                        "tickLabels": [format(value, ".2e") for value in domain["ticks"]],
                    }
                ]
                assertions = {
                    "series": [
                        {
                            "name": name,
                            "kind": "line",
                            "values": [row[index] for row in doc["rows"]],
                        }
                        for index, name in [(1, "actual"), (2, "budget")]
                    ]
                }
                if mode == "dual":
                    doc["columns"] = ["label", "actual", "ratio"]
                    doc["rows"] = [
                        [row[0], row[1] * 1e4, value] for row, value in zip(doc["rows"], (0.2, 0.4))
                    ]
                    doc["columnMeta"] = {
                        "actual": {"unit": "元"},
                        "ratio": {"unit": "%", "isPercent": False},
                    }
                    params.update(
                        standard_value_fields=["actual", "ratio"],
                        standard_axes={
                            "mode": "dual",
                            "rightFields": ["ratio"],
                            "leftDisplayUnit": "万元",
                        },
                        standard_domains={
                            "left": domain,
                            "right": {"min": 0, "max": 100, "ticks": [0, 50, 100]},
                        },
                    )
                    oracle.append(
                        {"index": 1, "coordinate": "y", "limits": [0, 100], "ticks": [0, 50, 100]}
                    )
                    assertions = {
                        "series": [
                            {"name": "actual · 左轴", "kind": "line", "values": values},
                            {"name": "ratio · 右轴", "kind": "line", "values": [20, 40]},
                        ]
                    }
                elif mode == "panels":
                    params["standard_axes"] = {"mode": "panels"}
                    override = {"min": 0, "max": 35 * scale, "ticks": [0, 35 * scale]}
                    params["standard_domains"] = {
                        "left": domain,
                        "panels": [{"series": "actual", "domain": override}],
                    }
                    oracle = [
                        {"coordinate": "y", "limits": [0, 35 * scale], "ticks": override["ticks"]},
                        {
                            "index": 1,
                            "coordinate": "y",
                            "limits": [0, limit],
                            "ticks": domain["ticks"],
                        },
                    ]
                elif mode == "zoom":
                    doc["rows"].insert(0, ["期初", 1000 * scale, 2000 * scale])
                    params["standard_axes"] = {
                        "mode": "zoom",
                        "zoomStart": "一月",
                        "zoomEnd": "二月",
                    }
                    params["standard_domains"] = {
                        "left": {"min": 0, "max": 2100 * scale},
                        "zoom": domain,
                    }
                    oracle = [
                        {"coordinate": "y", "limits": [0, 2100 * scale]},
                        {
                            "coordinate": "y",
                            "inset": True,
                            "limits": [0, limit],
                            "ticks": domain["ticks"],
                        },
                    ]
                    assertions["series"] = [
                        {
                            "name": name,
                            "kind": "line",
                            "values": [row[index] for row in doc["rows"]],
                        }
                        for index, name in [(1, "actual"), (2, "budget")]
                    ]
                elif mode == "stack":
                    params["visual_form"] = "stacked-bar"
                    domain = {"min": 0, "max": 80 * scale, "ticks": [0, 40 * scale, 80 * scale]}
                    params["standard_domains"] = {"left": domain}
                    oracle = [
                        {"coordinate": "y", "limits": [0, 80 * scale], "ticks": domain["ticks"]}
                    ]
                    assertions["series"] = [
                        {**item, "kind": "bar"} for item in assertions["series"]
                    ]
                elif mode == "scatter":
                    doc["columns"] = ["label", "x", "y", "color"]
                    doc["rows"] = [["甲", 1e4, values[0], 0.2], ["乙", 3e4, values[1], 0.8]]
                    doc["columnMeta"] = {
                        "x": {"unit": "人次"},
                        "y": {"unit": "元"},
                        "color": {"unit": "%", "isPercent": False},
                    }
                    params.update(
                        visual_form="scatter",
                        standard_value_fields=["y"],
                        standard_encoding={
                            "xField": "x",
                            "yField": "y",
                            "xDisplayUnit": "万人次",
                            "colorField": "color",
                        },
                        standard_domains={
                            "left": domain,
                            "x": {"min": 0, "max": 4, "ticks": [0, 2, 4]},
                        },
                    )
                    oracle.append({"coordinate": "x", "limits": [0, 4], "ticks": [0, 2, 4]})
                    assertions = {
                        "observations": [
                            {
                                "name": "y",
                                "offsets": [[1, values[0]], [3, values[1]]],
                                "colorValues": [20, 80],
                                "colorMap": "viridis",
                            }
                        ]
                    }
                elif mode == "barh":
                    params["visual_form"] = "barh"
                    oracle[0]["coordinate"] = "x"
                    assertions["series"] = [
                        {**item, "kind": "bar"} for item in assertions["series"]
                    ]
                elif mode == "band":
                    doc["columns"] = ["label", "actual", "low", "high"]
                    doc["rows"] = [
                        ["一月", values[0], values[0] - 2 * scale, values[0] + 2 * scale],
                        ["二月", values[1], values[1] - 2 * scale, values[1] + 2 * scale],
                    ]
                    doc["columnMeta"] = {name: {"unit": "元"} for name in doc["columns"][1:]}
                    params.update(
                        standard_value_fields=["actual"],
                        standard_bands=[
                            {"series": "actual", "lowerField": "low", "upperField": "high"}
                        ],
                    )
                    assertions = {
                        "series": [{"name": "actual", "kind": "line", "values": values}],
                        "bands": [
                            {
                                "name": "actual 范围",
                                "lower": [row[2] for row in doc["rows"]],
                                "upper": [row[3] for row in doc["rows"]],
                            }
                        ],
                    }
                if seed == 17 and mode == "single":
                    assertions["texts"] = ["超界图形端点", "原值未改"]
                yield case(f"{mode}-{seed}-{scale}", params, doc, domains=oracle, **assertions)
    source = {
        "columns": ["label", "actual", "budget"],
        "rows": [["一月", 10, 20], ["二月", 30, 40]],
        "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}},
    }
    for fault in (
        "right",
        "x",
        "zoom",
        "panels",
        "heatmap",
        "center",
        "baseline",
        "stack",
        "band",
        "log",
        "zero",
        "empty",
        "joint",
        "reversed",
        "duplicate_ticks",
        "bool",
    ):
        doc = copy.deepcopy(source)
        params = parameters(
            "line",
            standard_value_fields=["actual", "budget"],
            standard_domains={"left": {"min": 0, "max": 50}},
        )
        if fault in {"right", "x", "zoom"}:
            params["standard_domains"] = {fault: {"min": 0, "max": 50}}
        elif fault == "panels":
            params["standard_domains"] = {
                "panels": [{"series": "actual", "domain": {"min": 0, "max": 50}}]
            }
        elif fault == "heatmap":
            doc = {
                "columns": ["x", "y", "value"],
                "rows": [["一月", "东院", 1]],
                "columnMeta": {"value": {"unit": "元"}},
            }
            params.update(
                visual_form="heatmap",
                standard_value_fields=["value"],
                standard_encoding={"xField": "x", "yField": "y", "valueField": "value"},
            )
        elif fault == "center":
            params["standard_domains"]["left"]["max"] = 25
        elif fault == "baseline":
            params.update(visual_form="bar", standard_domains={"left": {"min": 5, "max": 50}})
        elif fault == "stack":
            params.update(
                visual_form="stacked-bar", standard_domains={"left": {"min": 0, "max": 50}}
            )
        elif fault == "band":
            doc["columns"].extend(["low", "high"])
            for row in doc["rows"]:
                row.extend([row[1] - 5, row[1] + 100])
            doc["columnMeta"].update(low={"unit": "元"}, high={"unit": "元"})
            params.update(
                standard_bands=[{"series": "actual", "lowerField": "low", "upperField": "high"}]
            )
        elif fault == "log":
            params["standard_axes"] = {"scale": "log"}
        elif fault == "zero":
            params.update(
                standard_axes={"zeroBaseline": True},
                standard_domains={"left": {"min": 5, "max": 50, "outOfRange": "annotate"}},
            )
        elif fault == "empty":
            params["standard_domains"] = {"left": {"min": 60, "max": 100, "outOfRange": "annotate"}}
        elif fault == "joint":
            params.update(
                visual_form="scatter",
                standard_value_fields=["budget"],
                standard_encoding={"xField": "actual", "yField": "budget"},
                standard_domains={
                    "x": {"min": 0, "max": 20, "outOfRange": "annotate"},
                    "left": {"min": 30, "max": 50, "outOfRange": "annotate"},
                },
            )
        elif fault == "reversed":
            params["standard_domains"] = {"left": {"min": 50, "max": 0}}
        elif fault == "duplicate_ticks":
            params["standard_domains"] = {"left": {"ticks": [0, 0, 50]}}
        else:
            params["standard_domains"] = {"left": {"min": True, "max": 50}}
        yield case(
            "reject-" + fault,
            params,
            doc,
            "schema" if fault in {"reversed", "duplicate_ticks", "bool"} else "fallback",
        )
