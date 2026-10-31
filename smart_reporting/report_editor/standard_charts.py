"""Expose production standard parameters without accepting planner-owned identities."""

import json
import math
import re
from copy import deepcopy
from typing import Any, Literal, cast

from pydantic import Field, create_model

from ..reporting.contract import StrictModel
from ..reporting.workflow.runtime.chart_inputs import ChartInputFile, ChartInputMaterialization
from ..reporting.workflow.runtime.phase_models import MAX_SECTION_CHART_COUNT, ChartDraft
from ..reporting.workflow.runtime.standard_chart_pagination import expand_standard_pagination

STANDARD_CHART_FIELDS = {
    name: (field.annotation, deepcopy(field))
    for name, field in ChartDraft.model_fields.items()
    if name.startswith("standard_")
}
StandardChartEditParameters = create_model(
    "StandardChartEditParameters", __base__=StrictModel, **cast(Any, STANDARD_CHART_FIELDS)
)
EditorStandardChart = create_model(
    "EditorStandardChart", __base__=StandardChartEditParameters,
    chart_id=(str, Field(alias="chartId")),
    source_path=(str, Field(alias="sourcePath")),
    title=(str, ...), alt_text=(str, Field(alias="altText")),
    visual_form=(str, Field(alias="visualForm")),
    data_bindings=(tuple[dict[str, Any], ...], Field(alias="dataBindings")),
    comparison_type=(Literal['none', 'yoy'], Field(default='none', alias='comparisonType')),
    comparability=(Literal['strict'], 'strict'),
)
EditorStandardPlan = create_model(
    "EditorStandardPlan", __base__=StrictModel,
    charts=(tuple[EditorStandardChart, ...], Field(max_length=MAX_SECTION_CHART_COUNT)),  # type: ignore[valid-type]
    warnings=(tuple[str, ...], ()),
)


def standard_edit_plan(*, chart_id, output_path, title, alt_text, visual_form,
                       standard, bindings, plot_files):
    """Only source bytes and server-owned paths/ids determine the execution scope."""
    options = standard or StandardChartEditParameters()
    # 显式跨年同月选择声明比较意图；编译器仍逐项验证相邻年、月份及原始期间。
    monthly_sources = options.standard_sources
    comparison = 'yoy' if monthly_sources and all(
        source.label_mode == 'month_of_year' for source in monthly_sources
    ) else 'none'
    chart = EditorStandardChart.model_validate({
        "chartId":chart_id, "sourcePath":output_path, "title":title, "altText":alt_text,
        "visualForm":visual_form, "dataBindings":bindings,
        "comparisonType": comparison,
        **{name:getattr(options,name) for name in STANDARD_CHART_FIELDS},
    })
    inputs = ChartInputMaterialization(
        files=tuple(ChartInputFile(item.path, item.content) for item in plot_files),
        entries=tuple({"chartId": chart_id, "path": item.path, "sha256": item.sha256}
                      for item in plot_files),
    )
    plan = EditorStandardPlan.model_validate({"charts":(chart,)})
    plan = expand_standard_pagination(cast(Any, plan), inputs)
    # Each page shares the same verified full cohort. Never create extra plot-data
    # copies that would change L2 rebinding or multi-round lineage cardinality.
    inputs = ChartInputMaterialization(files=inputs.files, entries=tuple(
        {"chartId": page.chart_id, "path": item.path, "sha256": item.sha256}
        for page in plan.charts for item in plot_files
    ))
    return plan, inputs


def inherit_standard(previous, proposed):
    """Omitted groups persist; an explicitly supplied group replaces that group."""
    if not previous and proposed is None:
        return None
    values = dict(previous or {})
    if proposed is not None:
        values.update(proposed.model_dump(mode="json", by_alias=True, exclude_unset=True))
    return StandardChartEditParameters.model_validate(values)


def standard_plot_summary(plot_files):
    """Bounded summaries of already verified bytes; no paths or new fact grants."""
    result = []
    budget = 48000
    for item in plot_files[:50]:
        document = json.loads(item.content)
        columns = document.get("columns", [])
        rows = document.get("rows", [])
        metadata = document.get("columnMeta", {})
        summary: dict[str, Any] = {"columnMeta": {}, "textValues": {}, "numericExtent": {}}
        if not isinstance(columns, list) or not isinstance(rows, list):
            result.append(summary)
            continue
        for n, column in enumerate(columns[:64]):
            if not isinstance(column, str) or len(column)>200:
                summary["metadataOmitted"] = "字段名超出摘要边界，未缩写冒充原字段"
                continue
            meta = metadata.get(column, {}) if isinstance(metadata, dict) else {}
            if isinstance(meta, dict):
                value = {}
                if isinstance(meta.get("unit"), str):
                    if len(meta["unit"])<=80:
                        value["unit"] = meta["unit"]
                    else:
                        value["unitOmitted"] = True
                if isinstance(meta.get("isPercent"), bool):
                    value["isPercent"] = meta["isPercent"]
                if isinstance(meta.get("periods"), list):
                    value["periods"] = [period[:100] for period in meta["periods"][:12] if isinstance(period, str)]
                    value["periodsComplete"] = len(meta["periods"])<=12
                summary["columnMeta"][column] = value
            values = [row[n] for row in rows[:480] if isinstance(row, list) and len(row)>n]
            text = list(dict.fromkeys(value for value in values if isinstance(value, str)))
            if text:
                summary["textValues"][column] = {"values": [value[:200] for value in text[:60]],
                    "complete": len(text)<=60 and len(rows)<=480 and all(len(value)<=200 for value in text)}
            numeric = [value for value in values if _finite_number(value)]
            if numeric:
                summary["numericExtent"][column] = {"minimum":min(numeric),"maximum":max(numeric),
                    "basis":"observed_bound_rows_only", "complete":len(rows)<=480}
        # Do not flood planner context with unusually large registered metadata.
        if len(json.dumps(summary, ensure_ascii=False))>16000:
            summary = {"columnMeta": {key:{name:value for name,value in meta.items() if name in {"unit","isPercent"}}
                                      for key,meta in summary["columnMeta"].items()},
                       "summaryOmitted": "类别摘要过长，未截断冒充完整类别"}
        size = len(json.dumps(summary, ensure_ascii=False))
        if size>budget:
            summary = {"summaryOmitted":"总摘要容量不足；此输入未提供类别/单位摘要，不可猜测"}
            size = len(json.dumps(summary, ensure_ascii=False))
        budget -= size
        result.append(summary)
    return result


_PERIOD_LABEL = re.compile(r"^\d{4}(?:[-/年]\d{1,2}(?:月)?|[ -]?Q[1-4]|年)")


def _table_profile(content):
    document = json.loads(content)
    columns, rows = document.get("columns"), document.get("rows")
    metadata = document.get("columnMeta") or {}
    if not isinstance(columns, list) or not isinstance(rows, list) or not isinstance(metadata, dict):
        raise ValueError("chart input is not a table")
    rows = [row for row in rows if isinstance(row, list) and len(row) == len(columns)]
    text_columns, numeric_columns = [], []
    for index, _column in enumerate(columns):
        values = [row[index] for row in rows if row[index] is not None]
        if values and all(isinstance(value, str) for value in values):
            text_columns.append(index)
        elif values and all(_finite_number(value) for value in values):
            numeric_columns.append(index)
    numbers = [row[index] for row in rows for index in numeric_columns if row[index] is not None]
    units = {meta.get("unit") for column in (columns[index] for index in numeric_columns)
             if isinstance(meta := metadata.get(column), dict) and isinstance(meta.get("unit"), str)}
    periods = any(isinstance(metadata.get(columns[index]), dict) and metadata[columns[index]].get("periods")
                  for index in numeric_columns)
    categories = (list(dict.fromkeys(row[text_columns[0]] for row in rows if row[text_columns[0]] is not None))
                  if text_columns else [])
    return rows, text_columns, numeric_columns, numbers, units, periods, categories


def chart_data_profile(plot_files):
    """供编辑器推荐操作的粗粒度数据概况；只描述已核验字节，不作为作图或核验依据。

    类别、字段数以第一份作图输入（主表）为准；单位、负值与数值跨度汇总全部输入，
    多来源组合图也能识别量纲差异。任何结构异常返回 None，界面退回通用推荐。
    """
    if not plot_files:
        return None
    try:
        tables = [_table_profile(item.content) for item in plot_files]
        rows, text_columns, numeric_columns, _numbers, _units, _periods, categories = tables[0]
        numbers = [value for table in tables for value in table[3]]
        units = set().union(*(table[4] for table in tables))
        nonzero = [abs(value) for value in numbers if value]
        has_period = any(table[5] for table in tables) or bool(
            categories and all(_PERIOD_LABEL.match(str(value)) for value in categories))
        return {
            "inputCount": len(plot_files),
            "rowCount": len(rows),
            "categoryCount": len(categories),
            "textFieldCount": len(text_columns),
            "numericFieldCount": len(numeric_columns),
            "unitCount": len(units),
            "hasPeriod": has_period,
            "hasNegative": any(value < 0 for value in numbers),
            # 非零绝对值最大/最小之比；用于提示断轴或对数，不代表业务口径。
            "magnitudeRatio": round(max(nonzero) / min(nonzero), 2) if nonzero else None,
        }
    except (ValueError, TypeError, AttributeError, IndexError, KeyError):
        return None


def chart_recommendations(profile):
    """按数据概况给出改图推荐；编辑器唯一的推荐来源，前端只负责展示。

    suggestions：数据相关的 AI 建议（id 为固定标识，用于埋点）；
    suppress：当前数据下不应展示的通用建议标识；
    cautions：预设可能不适合当前数据的原因，仅作提示，最终以执行时校验为准。
    """
    if profile is None:
        return None
    categories, numeric = profile["categoryCount"], profile["numericFieldCount"]
    ratio, negative = profile["magnitudeRatio"], profile["hasNegative"]
    suggestions = []
    if categories > 12:
        suggestions.append({"id": "paginate", "text": "将全部类别分页展示，保持统一颜色和值域"})
    if profile["unitCount"] >= 2:
        suggestions.append({"id": "dual-axis", "text": "不同单位的系列分别使用左右坐标轴并标明单位"})
    if ratio is not None and ratio >= 50 and not negative:
        suggestions.append({"id": "break", "text": "数值差距很大，使用断轴让较小的值也能看清"})
    if profile["hasPeriod"]:
        suggestions.append({"id": "mark-extremes", "text": "标注最高和最低的期间"})
    cautions = {}
    if negative:
        cautions["pie"] = cautions["donut"] = "数据含负值，不适合构成图"
    if not 3 <= numeric <= 8:
        cautions["radar"] = f"需要 3–8 个数值字段，当前 {numeric} 个"
    if numeric < 2:
        cautions["scatter"] = f"需要两个数值字段，当前 {numeric} 个"
    if numeric < 3:
        cautions["bubble"] = f"需要三个数值字段，当前 {numeric} 个"
        cautions["bands"] = "需要中心值与上下界三个数值字段"
    if profile["textFieldCount"] < 2:
        cautions["heatmap"] = "需要两个分类字段"
    if categories < 3:
        cautions["funnel"] = "阶段少于 3 个"
    if profile["unitCount"] < 2:
        cautions["dual"] = cautions["dual-stack"] = "各系列单位一致，通常不需要双轴"
    if ratio is not None and ratio < 10:
        cautions["vertical-break"] = cautions["horizontal-break"] = "数值差距不大，通常不需要断轴"
    if categories <= 20:
        cautions["pagination"] = f"只有 {categories} 个类别，通常无需分页"
    return {
        "suggestions": suggestions,
        "suppress": ["top5"] if categories <= 5 else [],
        "cautions": cautions,
    }


def _finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False
