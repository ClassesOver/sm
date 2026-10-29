"""Numerical oracles for statistical chart encodings and frozen interval bands."""

import copy
import random


def parameters(form, **options):
    return {
        "chart_id": "geometry",
        "renderer": "matplotlib",
        "interactive_path": None,
        "source_path": "standard.png",
        "title": "统计图形标准编码（合成测试）",
        "visual_form": form,
        "standard_style": {"labelRotation": 0},
        **options,
    }


def case(identity, params, doc, expected="render", **assertions):
    return {
        "id": "geometry-" + identity,
        "group": "geometry",
        "variant": identity,
        "synthetic": True,
        "parameters": params,
        "documents": [doc],
        "expected": expected,
        "assertions": assertions,
    }


def geometry_cases():
    for seed in (3, 17, 51):
        for scale in (1e-10, 1, 1e10):
            rng = random.Random(seed)
            for form in ("scatter", "bubble"):
                rows = [
                    [
                        f"观测{i}",
                        "门诊" if i % 2 else "住院",
                        rng.randint(1, 80) * 1e4,
                        rng.uniform(10, 100) * scale,
                        rng.randint(1, 30),
                        rng.uniform(0.1, 0.9),
                    ]
                    for i in range(12)
                ]
                doc = {
                    "columns": ["label", "group", "x", "y", "size", "color"],
                    "rows": rows,
                    "columnMeta": {
                        "x": {"unit": "人次"},
                        "y": {"unit": "元"},
                        "size": {"unit": "人次"},
                        "color": {"unit": "%", "isPercent": False},
                    },
                }
                encoding = {
                    "xField": "x",
                    "yField": "y",
                    "xDisplayUnit": "万人次",
                    "yDisplayUnit": "万元",
                    "xCaption": "门诊人次",
                    "yCaption": "医疗收入",
                }
                if form == "bubble":
                    encoding.update(sizeField="size", maxArea=800, sizeCaption="样本量")
                if seed == 3:
                    encoding["groupField"] = "group"
                if seed == 17:
                    encoding.update(colorField="color", colorMap="cividis", colorCaption="完成率")
                params = parameters(form, standard_label_field="label", standard_encoding=encoding)
                if seed == 51:
                    doc["columns"] = doc["columns"][2:]
                    doc["rows"] = [row[2:] for row in rows]
                    params.pop("standard_label_field")
                groups = ["门诊", "住院"] if seed == 3 else ["y"]
                observations = []
                maximum = max(row[4] for row in rows)
                for group in groups:
                    selected = [row for row in rows if group == "y" or row[1] == group]
                    item = {
                        "name": group,
                        "offsets": [[row[2] / 1e4, row[3] / 1e4] for row in selected],
                    }
                    if form == "bubble":
                        item["sizes"] = [row[4] / maximum * 800 for row in selected]
                    if seed == 17:
                        item.update(
                            colorValues=[row[5] * 100 for row in selected],
                            colorMap="cividis",
                            colorMin=min(row[5] * 100 for row in rows),
                            colorMax=max(row[5] * 100 for row in rows),
                        )
                    observations.append(item)
                yield case(f"{form}-{seed}-{scale}", params, doc, observations=observations)
            for sparse in (False, True):
                xs = [f"2026-{i:02}" for i in range(1, 5)]
                ys = ["东院", "西院", "门诊"]
                raw = {(x, y): rng.uniform(-80, 120) * scale for x in xs for y in ys}
                raw[xs[0], ys[0]] = -80 * scale
                raw[xs[-1], ys[-1]] = 120 * scale
                raw[xs[2], ys[1]] = 0
                if sparse:
                    raw.pop((xs[1], ys[0]))
                rows = [[x, y, value] for (x, y), value in raw.items()]
                rng.shuffle(rows)
                doc = {
                    "columns": ["月份", "院区", "value"],
                    "rows": rows,
                    "columnMeta": {"value": {"unit": "元"}},
                }
                encoding = {
                    "xField": "月份",
                    "yField": "院区",
                    "valueField": "value",
                    "xLabels": xs,
                    "yLabels": ys,
                    "colorDisplayUnit": "万元",
                    "colorMap": "RdBu_r",
                    "colorCenter": 0,
                    "showValues": True,
                    "colorCaption": "金额",
                }
                matrix = [
                    [raw.get((x, y)) / 1e4 if (x, y) in raw else None for x in xs] for y in ys
                ]
                values = [v / 1e4 for v in raw.values()]
                yield case(
                    f"heatmap-{seed}-{scale}-{sparse}",
                    parameters(
                        "heatmap", standard_encoding=encoding, standard_axes={"allowNulls": True}
                    ),
                    doc,
                    matrices=[
                        {
                            "name": "value",
                            "values": matrix,
                            "colorMap": "RdBu_r",
                            "colorMin": min(values),
                            "colorMax": max(values),
                            "colorCenter": 0,
                        }
                    ],
                )
            for mode in ("single", "dual", "panels", "zoom"):
                percent = seed == 51
                months = [f"2026-{i:02}" for i in range(1, 6)]
                center = [rng.uniform(20, 100) * scale for _ in months]
                budget = [value * 1.3 for value in center]
                low, high = (
                    [value - 5 * scale for value in center],
                    [value + 5 * scale for value in center],
                )
                low_unit, high_unit = ("万元", "亿元") if seed == 17 else ("元", "元")
                lower_div, upper_div = (1e4, 1e8) if seed == 17 else (1, 1)
                doc = {
                    "columns": ["label", "实际", "预算", "下界", "上界"],
                    "rows": [
                        [m, c / 100 if percent else c, b, lower / lower_div, upper / upper_div]
                        for m, c, b, lower, upper in zip(months, center, budget, low, high)
                    ],
                    "columnMeta": {
                        "实际": {"unit": "%", "isPercent": False} if percent else {"unit": "元"},
                        "预算": {"unit": "%", "isPercent": True} if percent else {"unit": "元"},
                        "下界": {"unit": "%", "isPercent": True} if percent else {"unit": low_unit},
                        "上界": {"unit": "%", "isPercent": True}
                        if percent
                        else {"unit": high_unit},
                    },
                }
                if seed == 17:
                    doc["rows"][2][3:] = [None, None]
                    low[2] = high[2] = None
                axes = {"mode": mode, "allowNulls": True}
                if mode == "dual":
                    axes["rightFields"] = ["实际"]
                if mode == "zoom":
                    axes.update(zoomStart=months[1], zoomEnd=months[3])
                fields = (
                    ["预算", "实际"]
                    if mode == "dual"
                    else ["实际", "预算"]
                    if mode == "panels"
                    else ["实际"]
                )
                params = parameters(
                    "line",
                    standard_value_fields=fields,
                    standard_axes=axes,
                    standard_display_unit="%" if percent else "万元",
                    standard_bands=[{"series": "实际", "lowerField": "下界", "upperField": "上界"}],
                )
                factor = 1 if percent else 1e-4
                series = [
                    {
                        "name": name + (" · 右轴" if name == "实际" else " · 左轴")
                        if mode == "dual"
                        else name,
                        "kind": "line",
                        "values": [v * factor for v in (center if name == "实际" else budget)],
                    }
                    for name in fields
                ]
                yield case(
                    f"band-{seed}-{scale}-{mode}",
                    params,
                    doc,
                    series=series,
                    bands=[
                        {
                            "name": "实际 范围",
                            "lower": [None if v is None else v * factor for v in low],
                            "upper": [None if v is None else v * factor for v in high],
                        }
                    ],
                )
    point = {
        "columns": ["label", "x", "y", "size"],
        "rows": [["甲", 1, 2, 10], ["乙", 2, 3, 20]],
        "columnMeta": {"x": {"unit": "人次"}, "y": {"unit": "元"}, "size": {"unit": "人次"}},
    }
    for fault in (
        "unit",
        "negative_size",
        "all_zero_size",
        "tiny_size",
        "log_zero",
        "duplicate_label",
    ):
        doc = copy.deepcopy(point)
        encoding = {"xField": "x", "yField": "y", "sizeField": "size"}
        if fault == "unit":
            doc["columnMeta"].pop("x")
        elif fault == "negative_size":
            doc["rows"][0][3] = -1
        elif fault == "all_zero_size":
            for row in doc["rows"]:
                row[3] = 0
        elif fault == "tiny_size":
            doc["rows"][0][3] = 1e-20
        elif fault == "log_zero":
            encoding["xScale"] = "log"
            doc["rows"][0][1] = 0
        else:
            doc["rows"][1][0] = "甲"
        yield case(
            "reject-" + fault, parameters("bubble", standard_encoding=encoding), doc, "fallback"
        )
    heat = {
        "columns": ["x", "y", "value"],
        "rows": [["甲", "乙", 0]],
        "columnMeta": {"value": {"unit": "元"}},
    }
    for fault in (
        "duplicate_cell",
        "missing_cell",
        "color_log_zero",
        "color_center",
        "order",
        "bool",
    ):
        doc = copy.deepcopy(heat)
        encoding = {"xField": "x", "yField": "y", "valueField": "value"}
        if fault == "duplicate_cell":
            doc["rows"] *= 2
        elif fault == "missing_cell":
            doc["rows"].extend([["丙", "乙", 1], ["甲", "丁", 2]])
        elif fault == "color_log_zero":
            encoding["colorScale"] = "log"
        elif fault == "color_center":
            encoding["colorCenter"] = 0
        elif fault == "order":
            encoding["yLabels"] = ["不存在"]
        else:
            doc["rows"][0][2] = True
        yield case(
            "reject-" + fault, parameters("heatmap", standard_encoding=encoding), doc, "fallback"
        )
