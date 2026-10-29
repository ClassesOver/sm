"""Replacement-data pipelines with an independent arithmetic oracle."""

import copy
import math
import random


def pipeline_cases():
    for seed in (3, 17, 51):
        for scale in (1e-12, 1, 1e12):
            rng = random.Random(seed)
            months = [f"{2025 + index // 12}-{index % 12 + 1:02}" for index in range(24)]
            branches = ["东院", "西院"]
            rows = [
                [
                    month,
                    branch,
                    rng.uniform(10, 100) * scale,
                    rng.uniform(80, 120) * scale,
                    rng.randint(1, 50),
                ]
                for month in months
                for branch in branches
                for _ in range(2)
            ]
            expected = {}
            for branch in branches:
                sums, weighted, ratios = [], [], []
                for month in months:
                    selected = [row for row in rows if row[0] == month and row[1] == branch]
                    amount = math.fsum(row[2] for row in selected)
                    sums.append(amount)
                    weighted.append(
                        math.fsum(row[2] * row[4] for row in selected)
                        / math.fsum(row[4] for row in selected)
                    )
                    ratios.append(amount / math.fsum(row[3] for row in selected) * 100)
                expected[branch] = {
                    "weighted_mean": weighted,
                    "cumulative_sum": [math.fsum(sums[: i + 1]) for i in range(24)],
                    "cumulative_year": [math.fsum(sums[i // 12 * 12 : i + 1]) for i in range(24)],
                    "mom_percent": [None]
                    + [(sums[i] - sums[i - 1]) / sums[i - 1] * 100 for i in range(1, 24)],
                    "yoy_percent": [None] * 12
                    + [(sums[i] - sums[i - 12]) / sums[i - 12] * 100 for i in range(12, 24)],
                    "rolling_sum": [None] * 2
                    + [math.fsum(sums[i - 2 : i + 1]) for i in range(2, 24)],
                    "rolling_mean": [None] * 2
                    + [math.fsum(sums[i - 2 : i + 1]) / 3 for i in range(2, 24)],
                    "rolling_ratio": [None] * 2
                    + [math.fsum(ratios[i - 2 : i + 1]) / 3 for i in range(2, 24)],
                }
            rng.shuffle(rows)
            document = {
                "columns": ["月份", "院区", "收入", "预算", "权重"],
                "rows": rows,
                "columnMeta": {
                    "收入": {"unit": "元"},
                    "预算": {"unit": "元"},
                    "权重": {"unit": "人次"},
                },
            }
            for operation in expected[branches[0]]:
                group = {
                    "kind": "group",
                    "labelField": "月份",
                    "groupBy": ["院区"],
                    "valueFields": ["收入", "预算"],
                }
                steps = [{"view": group}]
                field = "收入"
                if operation == "weighted_mean":
                    group.update(aggregation="weighted_mean", weightField="权重")
                else:
                    if operation == "rolling_ratio":
                        steps.append(
                            {
                                "derivation": {
                                    "kind": "ratio_percent",
                                    "name": "完成率",
                                    "numerator": "收入",
                                    "denominator": "预算",
                                }
                            }
                        )
                        field = "完成率"
                    kind = {
                        "cumulative_year": "cumulative_sum",
                        "rolling_ratio": "rolling_mean",
                    }.get(operation, operation)
                    derivation = {
                        "kind": kind,
                        "name": "计算值",
                        "numerator": field,
                        "labelField": "月份",
                        "groupBy": ["院区"],
                    }
                    if kind.startswith("rolling"):
                        derivation["window"] = 3
                    if operation == "cumulative_year":
                        derivation["reset"] = "year"
                    steps.append({"derivation": derivation})
                    field = "计算值"
                steps.append(
                    {
                        "view": {
                            "kind": "pivot",
                            "labelField": "月份",
                            "seriesField": "院区",
                            "seriesValues": branches,
                            "valueFields": [field],
                        }
                    }
                )
                parameters = {
                    "chart_id": "pipeline",
                    "renderer": "matplotlib",
                    "interactive_path": None,
                    "source_path": "standard.png",
                    "title": "多维流水线换数据回放（合成测试）",
                    "visual_form": "line",
                    "standard_value_fields": branches,
                    "standard_label_field": "月份",
                    "standard_axes": {"allowNulls": True},
                    "standard_steps": steps,
                }
                if operation == "weighted_mean":
                    parameters["standard_presentation"] = {"order": {"mode": "label"}}
                yield {
                    "id": f"pipeline-{operation}-{seed}-{scale}",
                    "group": "pipeline",
                    "variant": operation,
                    "synthetic": True,
                    "expected": "render",
                    "parameters": parameters,
                    "documents": [document],
                    "assertions": {
                        "series": [
                            {"name": branch, "kind": "line", "values": expected[branch][operation]}
                            for branch in branches
                        ]
                    },
                }
    base = {
        "columns": ["月份", "院区", "收入", "权重"],
        "rows": [["2026-01", "甲", 10, 1], ["2026-02", "甲", 20, 2]],
        "columnMeta": {"收入": {"unit": "元"}, "权重": {"unit": "人次"}},
    }
    for fault in (
        "negative_weight",
        "missing_weight_unit",
        "missing_month",
        "duplicate_month",
        "overwrite",
        "too_many_steps",
    ):
        doc = copy.deepcopy(base)
        step = {
            "derivation": {
                "kind": "cumulative_sum",
                "name": "累计",
                "numerator": "收入",
                "labelField": "月份",
                "groupBy": ["院区"],
            }
        }
        expected_route = "fallback"
        if fault in {"negative_weight", "missing_weight_unit"}:
            step = {
                "view": {
                    "kind": "group",
                    "labelField": "院区",
                    "valueFields": ["收入"],
                    "aggregation": "weighted_mean",
                    "weightField": "权重",
                }
            }
            if fault == "negative_weight":
                doc["rows"][0][3] = -1
            else:
                doc["columnMeta"].pop("权重")
        elif fault == "missing_month":
            doc["rows"][1][0] = "2026-03"
        elif fault == "duplicate_month":
            doc["rows"][1][0] = "2026-01"
        elif fault == "overwrite":
            step["derivation"]["name"] = "收入"
        steps = [step] * 9 if fault == "too_many_steps" else [step]
        yield {
            "id": "pipeline-reject-" + fault,
            "group": "pipeline",
            "variant": fault,
            "synthetic": True,
            "expected": expected_route,
            "documents": [doc],
            "parameters": {
                "chart_id": "pipeline",
                "renderer": "matplotlib",
                "interactive_path": None,
                "source_path": "standard.png",
                "title": "流水线异常回放",
                "visual_form": "line",
                "standard_label_field": "月份",
                "standard_value_fields": ["收入"],
                "standard_steps": steps,
            },
        }
