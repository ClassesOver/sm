"""Expand bounded categorical charts into fully registered, identity-bound pages.

Expansion happens before execution output paths and report registrations are
created. Each page retains the original data bindings and full input cohort;
standardLabels only controls its display window.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from loguru import logger

from ...units import unit_conversion_scale
from .chart_inputs import (
    ChartInputMaterialization,
    ChartInputWorkspace,
    _safe_name,
    prepare_chart_inputs,
)
from .phase_models import (
    MAX_SECTION_CHART_COUNT,
    ChartDraft,
    StandardChartDomains,
    VisualizationPlanDraft,
)
from .standard_chart_contract import resolve_standard_form


class PaginationUnsupported(ValueError):
    """This chart remains intact and is routed to Coding rather than truncated."""


def _pages(chart: ChartDraft, inputs: ChartInputMaterialization) -> tuple[ChartDraft, ...]:
    spec = chart.standard_pagination
    assert spec is not None
    if (resolve_standard_form(chart) not in {"bar", "barh"}
        or chart.standard_axes.mode != "single" or chart.standard_axes.scale != "linear"
        or chart.standard_axes.right_fields or chart.standard_axes.right_display_unit
        or chart.standard_labels or chart.standard_sources or chart.standard_source_labels
        or chart.standard_view or chart.standard_derivations or chart.standard_steps
        or chart.standard_encoding or chart.standard_bands or chart.standard_break
        or chart.standard_distribution or chart.standard_box_summary or chart.standard_waterfall
        or chart.standard_total_field or chart.standard_presentation.summaries
        or any(item.kind != "values" for item in chart.standard_annotations)
        or any(item.geometry != "auto" for item in chart.standard_style.series)):
        raise PaginationUnsupported("仅支持单线性轴宽表bar/barh；不分页统计/计算/范围带、混合几何、跨页重点或峰谷标注及摘要")
    order = chart.standard_presentation.order
    if order.mode != "source" or order.limit is not None or order.exclude_missing or order.labels:
        raise PaginationUnsupported("分页须保持完整来源顺序，不能与排序、TopN或类别截取混用")
    entries = [entry for entry in inputs.entries if entry.get("chartId") == chart.chart_id]
    if chart.chart_id in inputs.fallback_chart_ids or len(entries) != 1:
        raise PaginationUnsupported("分页需要一份完整、已核验的绑定宽表")
    source = next((item for item in inputs.files if item.path == entries[0].get("path")), None)
    if source is None or source.sha256 != entries[0].get("sha256"):
        raise PaginationUnsupported("分页输入身份不符")
    document = json.loads(source.content)
    if not isinstance(document, dict):
        raise PaginationUnsupported("分页输入须为登记宽表对象")
    columns, rows = document.get("columns"), document.get("rows")
    if (not isinstance(columns, list) or not columns or len(set(columns)) != len(columns)
        or not all(isinstance(name, str) and name for name in columns)
        or not isinstance(rows, list) or not 1 <= len(rows) <= 480
        or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)):
        raise PaginationUnsupported("分页宽表须有1至480行有效完整列")
    label = chart.standard_label_field or ("period" if "period" in columns else "label" if "label" in columns else None)
    if label is None:
        candidates = [name for n, name in enumerate(columns) if all(isinstance(row[n], str) for row in rows)]
        label = candidates[0] if len(candidates) == 1 else None
    if label not in columns:
        raise PaginationUnsupported("分页需要明确的唯一文本类别列")
    labels = [row[columns.index(label)] for row in rows]
    if any(not isinstance(value, str) or not value for value in labels) or len(set(labels)) != len(labels):
        raise PaginationUnsupported("分页类别须非空且唯一，长表须先规划为其他视图")
    fields = chart.standard_value_fields
    if not fields or len(set(fields)) != len(fields) or label in fields or not set(fields).issubset(columns):
        raise PaginationUnsupported("分页须显式选择存在且不重复的数值系列")
    if any(point.series not in fields or point.label not in labels for point in chart.standard_style.points):
        raise PaginationUnsupported("逐点颜色必须引用完整来源中存在的类别与系列")
    if spec.page_size * len(chart.standard_annotations) > 60:
        raise PaginationUnsupported("每页数值标注超过60项容量，请减小pageSize")
    metadata = document.get("columnMeta", {})
    if not isinstance(metadata, dict):
        raise PaginationUnsupported("分页缺少登记的单位元数据")
    metas = [metadata.get(field, {}) for field in fields]
    if (not all(isinstance(meta, dict) and isinstance(meta.get("unit"), str) and meta["unit"] for meta in metas)
        or len({(meta["unit"], meta.get("isPercent")) for meta in metas}) != 1):
        raise PaginationUnsupported("分页系列须有一致登记单位与百分数尺度")
    requested = chart.standard_display_unit or chart.standard_axes.left_display_unit
    if (chart.standard_display_unit and chart.standard_axes.left_display_unit
        and chart.standard_display_unit != chart.standard_axes.left_display_unit):
        raise PaginationUnsupported("分页显示单位与左轴单位声明冲突")
    conversion = unit_conversion_scale(metas[0]["unit"], requested) if requested else 1
    if conversion is None:
        raise PaginationUnsupported("分页显示单位不能由来源登记单位换算")
    factor = float(conversion) * (100 if metas[0]["unit"] == "%" and metas[0].get("isPercent") is False else 1)
    values = [0.0]
    for field in fields:
        for row in rows:
            value = row[columns.index(field)]
            if value is None and chart.standard_axes.allow_nulls:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise PaginationUnsupported("分页数值必须有限，缺失须明确allowNulls")
            converted = value * factor
            if not math.isfinite(converted):
                raise PaginationUnsupported("分页单位换算溢出")
            if value != 0 and converted == 0:
                raise PaginationUnsupported("分页单位换算使非零值下溢为零，须更换可表示的显示单位")
            values.append(converted)
    minimum, maximum = min(values), max(values)
    span = maximum - minimum
    if not math.isfinite(span):
        raise PaginationUnsupported("分页范围跨度溢出")
    pad = span * .1 if span else 1.0
    low, high = minimum - pad, maximum + pad
    if not math.isfinite(low) or not math.isfinite(high) or low >= high:
        raise PaginationUnsupported("分页统一范围不可表示")
    domains = chart.standard_domains
    if domains:
        if domains.right or domains.x or domains.zoom or domains.panels:
            raise PaginationUnsupported("分页只允许单一值轴范围")
        domain = domains.left
        if domain and (domain.out_of_range != "reject" or domain.minimum is not None and domain.minimum > minimum
                       or domain.maximum is not None and domain.maximum < maximum):
            raise PaginationUnsupported("分页值域必须覆盖全部页，不能裁切全表数据")
        left = domain.model_dump(by_alias=True) if domain else {}
        left["min"] = domain.minimum if domain and domain.minimum is not None else low
        left["max"] = domain.maximum if domain and domain.maximum is not None else high
        domains = StandardChartDomains.model_validate({"left": left})
    else:
        domains = StandardChartDomains.model_validate({"left": {"min": low, "max": high}})
    count = math.ceil(len(labels) / spec.page_size)
    if count > spec.max_pages:
        raise PaginationUnsupported(f"完整分页需要{count}页，超过maxPages={spec.max_pages}，保留完整原图")
    pages = []
    for index in range(count):
        selected = tuple(labels[index * spec.page_size:(index + 1) * spec.page_size])
        page_rows = rows[index * spec.page_size:(index + 1) * spec.page_size]
        if any(all(row[columns.index(field)] is None for row in page_rows) for field in fields):
            raise PaginationUnsupported("某页存在整系列缺失，不能隐藏该系列或补零")
        suffix = f"（第{index + 1}/{count}页）"
        path = PurePosixPath(chart.source_path)
        identifier = chart.chart_id
        if index:
            tag = f"__page_{index + 1}"
            digest = hashlib.sha256(identifier.encode()).hexdigest()[:12]
            identifier = (identifier[:128-len(tag)-13] + "-" + digest + tag) if len(identifier + tag) > 128 else identifier + tag
            path = path.with_name(f"{path.stem}--page-{index + 1}{path.suffix}")
        note = f"分页展示完整来源：第{index + 1}/{count}页，本页{len(selected)}类/总计{len(labels)}类；各页使用相同值域、系列顺序及单位，未截取TopN。"
        presentation = chart.standard_presentation.model_copy(update={"source_note": "\n".join(filter(None, (chart.standard_presentation.source_note, note)))})
        style = chart.standard_style.model_copy(update={"points": tuple(item for item in chart.standard_style.points if item.label in selected)})
        page = chart.model_copy(update={"chart_id": identifier, "source_path": path.as_posix(),
            "title": chart.title[:200-len(suffix)] + suffix, "alt_text": chart.alt_text[:200-len(suffix)] + suffix,
            "standard_pagination": None, "standard_labels": selected, "standard_domains": domains,
            "standard_presentation": presentation, "standard_style": style, "standard_label_field": label,
            "standard_display_unit": requested})
        pages.append(type(chart).model_validate(page.model_dump()))
    return tuple(pages)


def expand_standard_pagination(plan: VisualizationPlanDraft, inputs: ChartInputMaterialization,
                               *, max_charts: int | None = None) -> VisualizationPlanDraft:
    """Atomically replace each paginated chart, preserving unsupported originals."""
    if not any(chart.standard_pagination for chart in plan.charts):
        return plan
    limit = min(MAX_SECTION_CHART_COUNT, max_charts) if max_charts is not None else MAX_SECTION_CHART_COUNT
    charts: list[ChartDraft] = []
    warnings = list(plan.warnings)
    reserved_ids = {chart.chart_id for chart in plan.charts}
    reserved_names = {_safe_name(chart.chart_id) for chart in plan.charts}
    reserved_paths = {chart.source_path for chart in plan.charts}
    for n, chart in enumerate(plan.charts):
        if chart.standard_pagination is None:
            charts.append(chart)
            continue
        try:
            pages = _pages(chart, inputs)
            if len(charts) + len(pages) + len(plan.charts) - n - 1 > limit:
                raise PaginationUnsupported(f"完整分页超出章节/用户图数预算{limit}；不截断页面")
            if any(page.chart_id in reserved_ids or _safe_name(page.chart_id) in reserved_names
                   or page.source_path in reserved_paths for page in pages[1:]):
                raise PaginationUnsupported("分页生成的ID或输出路径与其他图冲突")
            charts.extend(pages)
            reserved_ids.update(page.chart_id for page in pages)
            reserved_names.update(_safe_name(page.chart_id) for page in pages)
            reserved_paths.update(page.source_path for page in pages)
        except (PaginationUnsupported, ValueError, TypeError, KeyError, OverflowError) as error:
            logger.warning("report_standard_pagination_fallback chart_id={} reason={}", chart.chart_id, str(error)[:300])
            charts.append(chart)
            warnings.append(f"{chart.chart_id}：标准分页未展开（{str(error)[:300]}），保留完整图交由Coding处理。")
    return type(plan).model_validate({"charts": charts, "warnings": warnings[-100:]})


async def prepare_standard_paginated_plan(plan: VisualizationPlanDraft, facts: Sequence[Mapping],
                                          workspace: ChartInputWorkspace, *, thread_id: str,
                                          output_root: str, max_charts: int | None = None) -> VisualizationPlanDraft:
    if not any(chart.standard_pagination for chart in plan.charts):
        return plan
    inputs = await prepare_chart_inputs(plan, facts, workspace, thread_id=thread_id, output_root=output_root)
    return expand_standard_pagination(plan, inputs or ChartInputMaterialization(), max_charts=max_charts)
