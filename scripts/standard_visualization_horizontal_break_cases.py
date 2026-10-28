"""Independent complete signed-bar geometry for horizontal broken value axes."""

import copy
import random

from scripts.standard_visualization_geometry_cases import parameters


def horizontal_break_cases():
    for seed in (3, 17, 51):
        for scale in (1e-10, 1, 1e10):
            for mode in ("positive", "negative", "long", "missing"):
                rng = random.Random(seed)
                actual = [rng.randint(5, 15) * scale, 1000 * scale, 20 * scale]
                budget = [25 * scale, 1100 * scale, 30 * scale]
                labels = ["东院", "西院", "南院"]
                if mode == "long":
                    labels = ["2026-01", "2026-02", "2026-03"]
                if mode == "negative":
                    actual = [-1000 * scale, -950 * scale, 20 * scale]
                    budget = [10 * scale, -1100 * scale, 30 * scale]
                if mode == "missing":
                    actual[-1] = None
                lower = [-1200 * scale, -900 * scale] if mode == "negative" else [0, 50 * scale]
                upper = [0, 50 * scale] if mode == "negative" else [900 * scale, 1200 * scale]
                fraction = {3: .3, 17: .6, 51: .5}[seed]
                spec = {
                    "lower": {"min": lower[0], "max": lower[1], "ticks": [lower[0], sum(lower)/2, lower[1]], "tickFormat": "scientific", "decimals": 1},
                    "upper": {"min": upper[0], "max": upper[1], "ticks": [upper[0], sum(upper)/2, upper[1]], "tickFormat": "scientific", "decimals": 1},
                    "lowerFraction": fraction, "gap": .14,
                }
                doc = {
                    "columns": ["label", "actual", "budget"],
                    "rows": [[label, None if a is None else a*1e4, b*1e4] for label, a, b in zip(labels, actual, budget)],
                    "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}},
                }
                params = parameters("barh", standard_value_fields=["actual", "budget"],
                    standard_display_unit="万元", standard_break=spec,
                    standard_axes={"allowNulls": mode == "missing"},
                    standard_annotations=[{"kind": "values", "series": "actual", "position": "auto" if mode=="negative" else "right"}],
                    standard_style={"labelRotation": 0, "barGroupWidth": .8, "grid": "x", "points": [{"series": "actual", "label": labels[1], "color": "#b55d68"}]},
                    standard_canvas={"sizeMode": "fixed", "width": 16, "height": 8, "dpi": 100,
                        "layout": {3: "tight", 17: "constrained", 51: "manual"}[seed]})
                if mode == "long":
                    doc = {"columns": ["period", "kind", "amount"],
                        "rows": [[label, name, value*1e4] for label, a, b in zip(labels, actual, budget) for name, value in [("actual", a), ("budget", b)]],
                        "columnMeta": {"amount": {"unit": "元"}}}
                    params["standard_value_fields"] = ["amount"]
                yield {
                    "id": f"horizontal-breaks-{mode}-{seed}-{scale}", "group": "horizontal-breaks",
                    "variant": mode, "synthetic": True, "parameters": params, "documents": [doc], "expected": "render",
                    "assertions": {
                        "series": [{"name": name, "panel": panel, "kind": "bar", "values": values, "starts": [0]*3,
                                    "centers": [i-.4+.2+index*.4 for i in range(3)],
                                    "colors": ["#3066a3", "#b55d68", "#3066a3"] if name=="actual" else ["#dc884d"]*3}
                                   for panel in ("lower", "upper") for index, (name, values) in enumerate([("actual", actual), ("budget", budget)])],
                        "breaks": [{"orientation": "horizontal", "lower": lower, "upper": upper, "lowerFraction": fraction, "marksPerPanel": 2,
                                    "categoryLabels": labels}],
                        "texts": ["左右段分别线性显示", "省略开区间"] + (["缺失1点，保留空位，未补零"] if mode=="missing" else []),
                    },
                }
    base = {
        "columns": ["label", "actual", "budget"], "rows": [["东院", 10, 20], ["西院", 1000, 1100]],
        "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}},
    }
    for fault in ("omitted", "outer", "zero", "empty", "units", "log", "panels", "dual", "domains", "mixed", "overlap", "incomplete"):
        doc = copy.deepcopy(base)
        params = parameters("barh", standard_value_fields=["actual", "budget"], standard_break={"lower": {"min": 0, "max": 50}, "upper": {"min": 900, "max": 1200}})
        spec = params["standard_break"]
        if fault == "omitted":
            doc["rows"][1][1] = 500
        elif fault == "outer":
            spec["upper"]["max"] = 1050
        elif fault == "zero":
            params["standard_axes"] = {"zeroBaseline": True}
            spec["lower"]["min"] = 5
        elif fault == "empty":
            spec["lower"] = {"min": -200, "max": -100}
        elif fault == "units":
            doc["columnMeta"] = {}
        elif fault == "log":
            params["standard_axes"] = {"scale": "log"}
        elif fault in {"panels", "dual"}:
            params["standard_axes"] = {"mode": fault, **({"rightFields": ["budget"]} if fault == "dual" else {})}
        elif fault == "domains":
            params["standard_domains"] = {"left": {"min": 0, "max": 1200}}
        elif fault == "mixed":
            params["standard_style"] = {"series": [{"series": "actual", "geometry": "line"}]}
        elif fault == "overlap":
            spec["lower"]["max"] = 1000
        else:
            spec["lower"] = {"min": 0}
        yield {"id": "horizontal-breaks-reject-"+fault, "group": "horizontal-breaks", "variant": fault,
            "synthetic": True, "parameters": params, "documents": [doc],
            "expected": "schema" if fault in {"overlap", "incomplete"} else "fallback", "assertions": {}}
