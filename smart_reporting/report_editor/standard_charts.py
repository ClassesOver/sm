"""Expose production standard parameters without accepting planner-owned identities."""

import json
import math
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
    renderer=(Literal["matplotlib"], "matplotlib"),
    interactive_path=(None, Field(default=None, alias="interactivePath")),
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


def _finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False
