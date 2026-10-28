"""Frozen-coordinate and geometry oracles for explicit two-interval value axes."""

import copy
import random

from scripts.standard_visualization_geometry_cases import parameters


def case(name, params, document, expected="render", **assertions):
    return {
        "id": "breaks-" + name,
        "group": "breaks",
        "variant": name,
        "synthetic": True,
        "parameters": params,
        "documents": [document],
        "expected": expected,
        "assertions": assertions,
    }


def break_cases():
    for seed in (3, 17, 51):
        for scale in (1e-10, 1, 1e10):
            rng = random.Random(seed)
            for mode in (
                "line",
                "bar",
                "stacked-bar",
                "stacked-area",
                "stacked-total",
                "mixed",
                "band",
                "long",
            ):
                actual = [
                    rng.randint(5, 15) * scale,
                    rng.randint(950, 1000) * scale,
                    rng.randint(20, 30) * scale,
                ]
                budget = [20 * scale, 1100 * scale, 35 * scale]
                if mode in {"stacked-bar", "stacked-area", "stacked-total"}:
                    budget = [10 * scale, 20 * scale, 5 * scale]
                if mode == "line" and seed == 17:
                    actual[-1], budget[-1] = 300 * scale, 350 * scale
                labels = ["2026-01", "2026-02", "2026-03"]
                doc = {
                    "columns": ["label", "actual", "budget"],
                    "rows": [
                        [label, a * 1e4, b * 1e4] for label, a, b in zip(labels, actual, budget)
                    ],
                    "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}},
                }
                lower = {
                    "min": 0,
                    "max": 50 * scale,
                    "ticks": [0, 25 * scale, 50 * scale],
                    "tickFormat": "scientific",
                    "decimals": 2,
                }
                upper = {
                    "min": 900 * scale,
                    "max": 1200 * scale,
                    "ticks": [900 * scale, 1050 * scale, 1200 * scale],
                    "tickFormat": "scientific",
                    "decimals": 2,
                }
                fraction = 0.4 if seed == 3 else 0.6 if seed == 17 else 0.5
                axis_break = {
                    "lower": lower,
                    "upper": upper,
                    "lowerFraction": fraction,
                    "gap": 0.12,
                }
                if mode == "line" and seed == 17:
                    axis_break["omittedValues"] = "annotate"
                params = parameters(
                    "line" if mode in {"mixed", "band", "long"} else mode,
                    standard_value_fields=["actual", "budget"],
                    standard_display_unit="万元",
                    standard_break=axis_break,
                    standard_annotations=[{"kind": "values", "series": "actual"}],
                    standard_canvas={
                        "sizeMode": "fixed",
                        "width": 14,
                        "height": 9,
                        "dpi": 100,
                        "layout": "tight"
                        if seed == 3
                        else "constrained"
                        if seed == 17
                        else "manual",
                    },
                )
                if mode == "mixed":
                    params["standard_style"] = {
                        "labelRotation": 0,
                        "series": [
                            {"series": "actual", "geometry": "bar"},
                            {"series": "budget", "geometry": "line"},
                        ],
                    }
                low, high = None, None
                if mode == "band":
                    low = [value - 2 * scale for value in actual]
                    high = [value + 2 * scale for value in actual]
                    doc["columns"].extend(["low", "high"])
                    for row, a, b in zip(doc["rows"], low, high):
                        row.extend([a * 1e4, b * 1e4])
                    doc["columnMeta"].update(low={"unit": "元"}, high={"unit": "元"})
                    params.update(
                        standard_value_fields=["actual"],
                        standard_bands=[
                            {"series": "actual", "lowerField": "low", "upperField": "high"}
                        ],
                    )
                if mode == "long":
                    rows = [
                        [label, name, value * 1e4]
                        for i, label in enumerate(labels)
                        for name, value in [("actual", actual[i]), ("budget", budget[i])]
                        if not (seed == 51 and i == 2 and name == "budget")
                    ]
                    doc = {
                        "columns": ["period", "kind", "amount"],
                        "rows": rows,
                        "columnMeta": {"amount": {"unit": "元"}},
                    }
                    params["standard_value_fields"] = ["amount"]
                    if seed == 51:
                        budget[-1] = None
                series = []
                areas = []
                bands = []
                for panel in ("upper", "lower"):
                    for name, values in [("actual", actual), ("budget", budget)]:
                        if mode == "band" and name == "budget":
                            continue
                        kind = (
                            "line"
                            if mode in {"line", "band", "long"}
                            or mode == "mixed"
                            and name == "budget"
                            else "bar"
                        )
                        if mode == "stacked-area":
                            starts = [0] * 3 if name == "actual" else actual
                            ends = (
                                actual
                                if name == "actual"
                                else [a + b for a, b in zip(actual, budget)]
                            )
                            areas.append(
                                {"name": name, "panel": panel, "lower": starts, "upper": ends}
                            )
                        else:
                            item = {"name": name, "panel": panel, "kind": kind, "values": values}
                            if kind == "bar":
                                item["bottoms"] = (
                                    actual
                                    if mode in {"stacked-bar", "stacked-total"} and name == "budget"
                                    else [0] * 3
                                )
                            series.append(item)
                    if mode == "stacked-total":
                        series.append(
                            {
                                "name": "分项合计（服务端求和）",
                                "panel": panel,
                                "kind": "line",
                                "values": [a + b for a, b in zip(actual, budget)],
                            }
                        )
                    if mode == "band":
                        bands.append(
                            {"name": "actual 范围", "panel": panel, "lower": low, "upper": high}
                        )
                yield case(
                    f"{mode}-{seed}-{scale}",
                    params,
                    doc,
                    series=series,
                    areas=areas,
                    bands=bands,
                    breaks=[
                        {
                            "upper": [upper["min"], upper["max"]],
                            "lower": [lower["min"], lower["max"]],
                            "lowerFraction": fraction,
                            "marksPerPanel": 2,
                        }
                    ],
                    texts=["断轴", "省略开区间", "上下段分别线性显示"],
                )
    source = {
        "columns": ["label", "actual", "budget"],
        "rows": [["一月", 10, 20], ["二月", 1000, 1100]],
        "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}},
    }
    for fault in (
        "gap",
        "outer",
        "empty",
        "zero",
        "dual",
        "log",
        "domains",
        "horizontal",
        "scatter",
        "unknown_unit",
        "band_gap",
        "band_outer",
        "stack_gap",
        "overlap",
        "incomplete",
        "bool",
    ):
        doc = copy.deepcopy(source)
        params = parameters(
            "line",
            standard_value_fields=["actual", "budget"],
            standard_break={"lower": {"min": 0, "max": 50}, "upper": {"min": 900, "max": 1200}},
        )
        spec = params["standard_break"]
        if fault == "gap":
            doc["rows"][1][1] = 500
        elif fault == "outer":
            spec["upper"]["max"] = 1050
        elif fault == "empty":
            spec["lower"] = {"min": -200, "max": -100}
        elif fault == "zero":
            params["standard_axes"] = {"zeroBaseline": True}
            spec["lower"]["min"] = 5
        elif fault == "dual":
            params["standard_axes"] = {"mode": "dual", "rightFields": ["budget"]}
        elif fault == "log":
            params["standard_axes"] = {"scale": "log"}
        elif fault == "domains":
            params["standard_domains"] = {"left": {"min": 0, "max": 1200}}
        elif fault == "horizontal":
            params["visual_form"] = "barh"
        elif fault == "scatter":
            params.update(
                visual_form="scatter",
                standard_value_fields=["budget"],
                standard_encoding={"xField": "actual", "yField": "budget"},
            )
        elif fault == "unknown_unit":
            doc["columnMeta"] = {}
        elif fault in {"band_gap", "band_outer"}:
            doc = {
                "columns": ["label", "actual", "low", "high"],
                "rows": [
                    ["一月", 10, 8, 12],
                    [
                        "二月",
                        1000,
                        500 if fault == "band_gap" else 950,
                        1300 if fault == "band_outer" else 1100,
                    ],
                ],
                "columnMeta": {field: {"unit": "元"} for field in ["actual", "low", "high"]},
            }
            params.update(
                standard_value_fields=["actual"],
                standard_bands=[{"series": "actual", "lowerField": "low", "upperField": "high"}],
            )
        elif fault == "stack_gap":
            params["visual_form"] = "stacked-bar"
            doc["rows"][1][1:] = [500, 500]
        elif fault == "overlap":
            spec["lower"]["max"] = 1000
        elif fault == "incomplete":
            spec["lower"] = {"min": 0}
        else:
            spec["lower"]["min"] = True
        yield case(
            "reject-" + fault,
            params,
            doc,
            "schema" if fault in {"overlap", "incomplete", "bool"} else "fallback",
        )
