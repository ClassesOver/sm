"""Independent signed stack baselines and right-axis unit/total oracles."""

import copy
import random

from scripts.standard_visualization_geometry_cases import parameters


def dual_stack_cases():
    base = None
    for seed in (3, 17, 51):
        for scale in (1e-10, 1, 1e10):
            for mode in ("positive", "signed", "total", "missing"):
                rng = random.Random(seed)
                actual = [rng.randint(5, 15)*scale, 30*scale, 20*scale]
                budget = [20*scale, 40*scale, 25*scale]
                ratio = [.2, .4, .3]
                other = None
                if mode == "signed":
                    actual = [10*scale, -30*scale, 20*scale]
                    budget = [-20*scale, 40*scale, 25*scale]
                    other = [5*scale, -5*scale, -7*scale]
                if mode == "missing":
                    ratio[-1] = None
                labels = ["2026-01", "2026-02", "2026-03"]
                document = {"columns": ["label", "actual", "budget", "ratio"],
                    "rows": [[label, a*1e4, b, r] for label, a, b, r in zip(labels, actual, budget, ratio)],
                    "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "万元"}, "ratio": {"unit": "%", "isPercent": False}}}
                if other is not None:
                    document["columns"].insert(3, "other")
                    document["columnMeta"]["other"] = {"unit": "万元"}
                    for row, value in zip(document["rows"], other):
                        row.insert(3, value)
                form = "stacked-total" if mode in {"signed", "total"} else "stacked-bar"
                frozen = mode == "total" and seed != 17
                if frozen:
                    document["columns"].append("total")
                    document["columnMeta"]["total"] = {"unit": "元"}
                    for row in document["rows"]:
                        row.append(row[1]+row[2]*1e4)
                params = parameters(form, standard_value_fields=document["columns"][1:],
                    standard_axes={"mode": "dual", "rightFields": ["ratio"], "leftDisplayUnit": "万元", "allowNulls": mode=="missing"},
                    standard_annotations=[{"kind": "values", "series": "budget"}, {"kind": "peak", "series": "ratio", "highlight": True}],
                    standard_style={"labelRotation": 0, "points": [{"series": "actual", "label": labels[1], "color": "#b55d68"}]},
                    standard_canvas={"sizeMode": "fixed", "width": 14, "height": 8, "dpi": 100,
                        "layout": {3: "tight", 17: "constrained", 51: "manual"}[seed]},
                    standard_domains={"left": {"min": -100*scale if mode=="signed" else 0, "max": 100*scale,
                        "ticks": [-100*scale, 0, 100*scale] if mode=="signed" else [0, 50*scale, 100*scale], "tickFormat": "scientific", "decimals": 1},
                        "right": {"min": 0, "max": 100, "ticks": [0, 50, 100]}},
                    **({"standard_total_field": "total"} if frozen else {}))
                series = [
                    {"name": "actual · 左轴", "kind": "bar", "values": actual, "starts": [0]*3,
                        "centers": [0, 1, 2], "colors": ["#3066a3", "#b55d68", "#3066a3"]},
                    {"name": "budget · 左轴", "kind": "bar", "values": budget,
                        "starts": [a if (a>=0)==(b>=0) else 0 for a,b in zip(actual,budget)],
                        "centers": [0, 1, 2], "colors": ["#dc884d"]*3},
                    {"name": "ratio · 右轴", "kind": "line", "values": [None if r is None else r*100 for r in ratio]},
                ]
                if other is not None:
                    series.append({"name": "other · 左轴", "kind": "bar", "values": other,
                        "starts": [sum(value for value in (a,b) if (value>=0)==(c>=0)) for a,b,c in zip(actual,budget,other)],
                        "centers": [0,1,2], "colors": ["#36856b"]*3})
                if form == "stacked-total":
                    series.append({"name": "total（独立冻结总额，已对账）" if frozen else "分项合计（服务端求和）",
                        "kind": "line", "values": [a+b+c for a, b, c in zip(actual, budget, other or [0]*3)]})
                case = {"id": f"dual-stack-{mode}-{seed}-{scale}", "group": "dual-stack", "variant": mode,
                    "synthetic": True, "parameters": params, "documents": [document], "expected": "render",
                    "assertions": {"series": series, "domains": [{"index": index, "coordinate": "y",
                        "limits": [domain["min"], domain["max"]], "ticks": domain["ticks"]}
                        for index, domain in enumerate(params["standard_domains"].values())],
                        "texts": ["右轴折线独立单位，未计入分项合计"]+(["ratio 缺失1点，保留断点，未补零"] if mode=="missing" else [])}}
                if base is None:
                    base = copy.deepcopy(case)
                yield case
    for fault in ("left_null", "right_null", "units", "left_line", "right_bar", "nonlinear", "left_domain", "right_domain", "total_mismatch", "percent", "hidden_contribution", "overflow"):
        case = copy.deepcopy(base)
        case["id"] = "dual-stack-reject-"+fault
        case["variant"], case["expected"], case["assertions"] = fault, "fallback", {}
        params, document = case["parameters"], case["documents"][0]
        if fault == "left_null":
            document["rows"][0][1] = None
            params["standard_axes"]["allowNulls"] = True
        elif fault == "right_null":
            document["rows"][0][3] = None
        elif fault == "units":
            document["columnMeta"]["actual"]["unit"] = "人次"
        elif fault in {"left_line", "right_bar"}:
            params["standard_style"] = {"series": [{"series": "actual" if fault=="left_line" else "ratio", "geometry": "line" if fault=="left_line" else "bar"}]}
        elif fault == "nonlinear":
            params["standard_axes"]["scale"] = "symlog"
        elif fault in {"left_domain", "right_domain"}:
            side = "left" if fault=="left_domain" else "right"
            params["standard_domains"][side] = {"min": 0, "max": 60e-10 if side=="left" else 30}
        elif fault == "total_mismatch":
            params["visual_form"] = "stacked-total"
            params["standard_total_field"] = "budget"
        elif fault == "percent":
            params["standard_axes"].pop("leftDisplayUnit")
            document["columnMeta"]["actual"] = {"unit": "%", "isPercent": True}
            document["columnMeta"]["budget"] = {"unit": "%", "isPercent": True}
        elif fault == "hidden_contribution":
            document["rows"][0][1:3] = [1e24, 1]
        else:
            document["rows"][0][1:3] = [1e308, 1e308]
            params["standard_axes"]["leftDisplayUnit"] = "元"
        yield case
