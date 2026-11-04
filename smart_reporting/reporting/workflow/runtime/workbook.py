"""从冻结事实和实际使用的数据集装配工作簿，不读取 Markdown 展示数值。"""
from __future__ import annotations

import csv
import io
import math
import re
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

from ...trace.fact_index import FACT_ARRAYS
from ...trace.fact_service import fact_display_unit, fact_display_value

_PERIOD_ROLES = {"current": "本期", "yoy": "同比基期", "mom": "环比基期"}


def workbook_dataset_rows(
    content: bytes, *, dataset_id: str, measures: set[str], schema: dict[str, Any],
) -> tuple[list[str], list[list[Any]], list[dict[str, Any]]]:
    """仅按已登记的字段类型转换明细，未登记或类型冲突的维度保留原文。"""
    registered_types: dict[str, set[str]] = {}
    for table in schema.get("tables", ()):
        for column in table.get("columns", ()):
            registered_types.setdefault(column["name"], set()).add(column["dataType"].strip().upper())
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    columns = list(reader.fieldnames or ())
    rows: list[list[Any]] = []
    issues: list[dict[str, Any]] = []
    for record in reader:
        row: list[Any] = []
        for column in columns:
            value: Any = record.get(column)
            types = registered_types.get(column, set())
            data_type = next(iter(types)) if len(types) == 1 else ""
            if value == "":
                value = None
            elif value is not None:
                issue_code = None
                if data_type in {"BOOL", "BOOLEAN"}:
                    boolean = {"true": True, "false": False, "1": True, "0": False}
                    if value.strip().lower() in boolean:
                        value = boolean[value.strip().lower()]
                    else:
                        issue_code = "xlsx_boolean_value_invalid"
                elif column in measures or re.fullmatch(
                    r"(?:TINYINT|SMALLINT|MEDIUMINT|INT|INTEGER|BIGINT|LARGEINT|FLOAT|DOUBLE|REAL|DECIMAL|NUMERIC)"
                    r"(?:\s*\([^)]*\))?(?:\s+UNSIGNED)?", data_type,
                ):
                    try:
                        number = Decimal(value)
                        if not number.is_finite():
                            raise InvalidOperation
                        floating = float(number)
                        # Node 使用双精度，Excel 只保证 15 位有效数且不保留非正规数。
                        # 在转换前核对十进制原值，不能用已舍入的 float 反推精度。
                        if (
                            not math.isfinite(floating)
                            or (number != 0 and abs(floating) < sys.float_info.min)
                            or Decimal(format(floating, ".15g")) != number
                        ):
                            issue_code = "xlsx_numeric_precision_preserved"
                        else:
                            value = int(number) if number == number.to_integral_value() and abs(floating) <= 2**53 - 1 else floating
                    except InvalidOperation:
                        issue_code = "xlsx_numeric_value_invalid"
                if issue_code:
                    message = ("冻结数值超过 Excel 15 位有效数或可表达范围，已保留原始文本，避免舍入。"
                               if issue_code == "xlsx_numeric_precision_preserved" else "冻结数据与登记字段类型不符，保留原值并待核验。")
                    issues.append({"code": issue_code, "message": message,
                        "datasetId": dataset_id, "column": column})
            row.append(value)
        rows.append(row)
    return columns, rows, issues


def _fact_period_label(fact: dict[str, Any], report_period: str) -> str:
    def window(start: Any, end: Any, fallback: str) -> str:
        if start and end:
            return str(start) if start == end else f"{start} 至 {end}"
        if start:
            return f"{start} 起（结束未登记）"
        if end:
            return f"截至 {end}（起始未登记）"
        return fallback

    current = window(fact.get("periodStart"), fact.get("periodEnd"), f"{report_period}（事实期间未登记）")
    if fact.get("comparisonType"):
        baseline = window(fact.get("baselinePeriodStart"), fact.get("baselinePeriodEnd"), "期间未登记")
        role = _PERIOD_ROLES.get(fact["comparisonType"], str(fact["comparisonType"]))
        return f"本期：{current}；{role}：{baseline}"
    roles = [fact["periodRole"]] if fact.get("periodRole") else fact.get("periodRoles") or ()
    label = "/".join(_PERIOD_ROLES.get(role, role) for role in roles)
    return f"{current}（{label}）" if label else current


def _fact_metric_label(
    fact: dict[str, Any], array_name: str, names: dict[str, str], field_names: dict[str, str],
) -> str:
    codes = [fact["code"]] if fact.get("code") else fact.get("metricCodes") or ()
    name = fact.get("displayName") or fact.get("metricName") or fact.get("name")
    name = name or "/".join(names.get(code, code) for code in codes)
    name = name or field_names.get(fact.get("fieldRef", "")) or fact.get("field") or fact.get("fieldRef")
    if array_name == "correlationDetails":
        name = name or f"{fact.get('leftField', '')} / {fact.get('rightField', '')}"
    name = name or array_name
    if array_name == "comparisons":
        kind = {"yoy": "同比", "mom": "环比"}.get(fact.get("comparisonType"), "比较") + "变化额"
    elif array_name == "derivedMetrics":
        kind = "百分比" if fact.get("percentage") is not None else "比值"
    elif array_name == "reconciliations":
        kind = "对账差额"
    elif array_name == "correlationDetails":
        kind = "相关系数"
    else:
        kind = {"sum": "合计", "average": "平均值", "min": "最小值", "max": "最大值",
                "count": "计数", "count_distinct": "去重计数"}.get(fact.get("aggregation"), "数值")
    scope = dict(fact.get("scope") or {})
    if fact.get("breakdownField") and fact.get("breakdownValue") is not None:
        scope[fact["breakdownField"]] = fact["breakdownValue"]
    labels = [f"{fact.get('breakdownLabel') or key if key == fact.get('breakdownField') else key}={value}"
              for key, value in sorted(scope.items())]
    return " · ".join([str(name), kind, *labels])


def build_workbook_sheets(
    *, manifest: Any, outline: Any, fact_documents: dict[str, dict[str, Any]],
    datasets: dict[str, dict[str, Any]], period: str,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    used_names = {"汇总"}

    def sheet_name(value: str) -> str:
        base = re.sub(r"[\[\]:*?/\\]", "_", value).strip(" '")[:31] or "报表"
        name, index = base, 2
        while name.casefold() in {item.casefold() for item in used_names}:
            suffix = f"_{index}"
            name, index = base[:31 - len(suffix)] + suffix, index + 1
        used_names.add(name)
        return name

    sources: dict[str, Any] = {"version": "1", "period": period, "datasets": datasets, "cells": []}
    # 明细只保留身份和工作表定位，避免在来源映射中重复整批数据。
    sources["datasets"] = {key: {k: v for k, v in value.items() if k not in {"rows", "columns"}}
                           for key, value in datasets.items()}
    evidence_by_id = {item.analysis_id: item for item in manifest.evidence}
    metric_names = {item.code: item.name for item in getattr(manifest, "metric_definitions", ())}
    summary: dict[str, Any] = {"name": "汇总", "headerRow": 0,
        "rows": [["主题", "分析编号", "指标", "数值", "单位", "期间", "结论"]]}
    sheets = [summary]
    sections = list(outline.sections)
    covered = {item for section in sections for item in section.analysis_ids}
    remaining = [item.analysis_id for item in manifest.evidence if item.analysis_id not in covered]
    if remaining:
        from types import SimpleNamespace
        sections.append(SimpleNamespace(code="additional", title="补充分析", analysis_ids=remaining))
    for section in sections:
        name = sheet_name(section.title)
        rows: list[list[Any]] = [["分析编号", "指标", "数值", "单位", "期间", "数据集", "事实编号"]]
        for analysis_id in section.analysis_ids:
            evidence = evidence_by_id.get(analysis_id)
            if evidence is None:
                continue
            document = fact_documents.get(analysis_id, {})
            field_names = {item["fieldRef"]: item["displayName"]
                           for item in [*document.get("metrics", ()), *document.get("breakdowns", ())]
                           if item.get("fieldRef") and item.get("displayName")}
            fact_count = 0
            for _, array_name in FACT_ARRAYS:
                for fact in document.get(array_name) or ():
                    if not isinstance(fact, dict):
                        continue
                    fact_count += 1
                    metric = _fact_metric_label(fact, array_name, metric_names, field_names)
                    value = fact_display_value(fact)
                    unit = fact_display_unit(fact)
                    fact_period = _fact_period_label(fact, period)
                    dataset_ids = fact.get("datasetIds") or ([fact["datasetId"]] if fact.get("datasetId") else
                        [fact[key] for key in ("currentDatasetId", "baselineDatasetId") if fact.get(key)] or list(evidence.dataset_ids))
                    rows.append([analysis_id, metric, value, unit, fact_period, ", ".join(dataset_ids), fact.get("factId")])
                    row_number = len(rows)
                    quoted_name = name.replace("'", "''")
                    summary["rows"].append([section.title, analysis_id, metric,
                        {"value": value, "formula": f"='{quoted_name}'!C{row_number}"} if value is not None else None,
                        unit, fact_period, evidence.summary])
                    sources["cells"].append({"sheet": name, "cell": f"C{row_number}",
                        "sectionId": section.code, "analysisId": analysis_id, "factId": fact.get("factId"),
                        "datasetIds": dataset_ids, "factArray": array_name,
                        **{key: fact[key] for key in ("code", "metricCodes", "scope", "periodRole", "periodRoles",
                            "periodStart", "periodEnd", "baselinePeriodStart", "baselinePeriodEnd", "comparisonType",
                            "breakdownField", "breakdownLabel", "breakdownValue") if key in fact}})
            if not fact_count:
                rows.append([analysis_id, "结论", None, None, period, ", ".join(evidence.dataset_ids), None])
                summary["rows"].append([section.title, analysis_id, "结论", None, None, period, evidence.summary])
        sheets.append({"name": name, "rows": rows, "headerRow": 0,
            "sectionId": section.code, "analysisIds": list(section.analysis_ids)})
    for index, (dataset_id, data) in enumerate(datasets.items(), 1):
        name = sheet_name(f"明细{index}_{dataset_id}")
        sheets.append({"name": name, "headerRow": 0, "rows": [data["columns"], *data["rows"]]})
        sources["datasets"][dataset_id]["sheet"] = name
    return tuple(sheets), sources


def validate_workbook_snapshot(
    model: dict[str, Any], sheets: tuple[dict[str, Any], ...],
    sources: dict[str, Any], content: bytes,
) -> list[dict[str, Any]]:
    """核对读回的数值、公式与来源登记；问题以可发布的验收记录返回。"""
    import io
    import json
    import zipfile

    from openpyxl.utils.cell import get_column_letter

    issues: list[dict[str, Any]] = []
    cached_workbook = None
    actual_sheets = model.get("sheets", [])
    if [item.get("name") for item in actual_sheets] != [item["name"] for item in sheets]:
        issues.append({"code": "xlsx_sheet_structure_mismatch", "message": "工作表结构与冻结计划不一致。"})
    by_name = {item.get("name"): item for item in actual_sheets}
    for sheet in sheets:
        cells = by_name.get(sheet["name"], {}).get("cells", {})
        for row_index, row in enumerate(sheet["rows"], 1):
            for column_index, cell in enumerate(row, 1):
                expected = cell if isinstance(cell, dict) else {"value": cell}
                address = f"{get_column_letter(column_index)}{row_index}"
                actual = cells.get(address, {"value": None})
                value = expected.get("value")
                actual_value = actual.get("value")
                # 上游编辑模型故意不展示公式缓存；成稿验收读取文件中的冻结缓存。
                if actual.get("formula") and actual_value is None:
                    from openpyxl import load_workbook
                    if cached_workbook is None:
                        cached_workbook = load_workbook(io.BytesIO(content), data_only=True)
                    actual_value = cached_workbook[sheet["name"]][address].value
                if actual_value != value or isinstance(actual_value, bool) != isinstance(value, bool):
                    issues.append({"code": "xlsx_cell_data_mismatch", "message": "工作簿数值与冻结数据不一致。", "sheet": sheet["name"], "cell": address})
                if str(actual.get("formula") or "").lstrip("=") != str(expected.get("formula") or "").lstrip("="):
                    issues.append({"code": "xlsx_formula_mismatch", "message": "工作簿公式与冻结计算口径不一致。", "sheet": sheet["name"], "cell": address})
                if len(issues) >= 20:
                    break
            if len(issues) >= 20:
                break
        if len(issues) >= 20:
            break
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            registered = json.loads(package.read("smart-reporting/source-mapping.json"))
        if not isinstance(registered, dict) or registered.get("sources") != sources:
            issues.append({"code": "xlsx_source_mapping_mismatch", "message": "工作簿来源登记与冻结来源不一致。"})
    except (KeyError, ValueError, zipfile.BadZipFile):
        issues.append({"code": "xlsx_source_mapping_unavailable", "message": "工作簿来源登记无法读取。"})
    if cached_workbook is not None:
        cached_workbook.close()
    return issues
