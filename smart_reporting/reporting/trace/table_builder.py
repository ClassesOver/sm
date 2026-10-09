"""服务端结构化表格装配核心（B2，计划 B2-3 与 4.2）。

从冻结确定性 facts 生成表格：行列键在生成时冻结、单元格逐格绑定
FactRef，不依赖最终 Markdown 里的位置猜测。总计行、比例列分别绑定
各自事实（由调用方以独立 spec 声明，本模块不发明聚合规则）。

生成产物：
- ``render_table_markdown``：进正文的 Markdown 表格文本（服务端唯一
  允许写 ``[[table:id]]`` 协议块的装配器）。
- ``build_table_trace``：进追溯索引的 TableTraceV1（与 Markdown 同源
  生成，保证行列键与单元格绑定一致）。

旧报告/人工表格没有 TableTrace：读取层如实显示"未绑定"，不猜测
（计划 1.2 / 6.3）。
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from ..models import ReportingError
from .contracts_v1 import (
    FactRefV1,
    TableCellBindingV1,
    TableTraceV1,
)
from .fact_index import fact_pointer

_TABLE_ID_PATTERN_RULES = "表格 ID 只允许字母数字与 _ . :-"


def _normalize_table_id(table_id: str) -> str:
    cleaned = table_id.strip()
    if not cleaned or len(cleaned) > 128 or any(ch in "\r\n" for ch in cleaned):
        raise ReportingError("request_invalid", _TABLE_ID_PATTERN_RULES)
    return cleaned


def _metric_value(fact: Any, key: str) -> float | None:
    value = getattr(fact, key, None)
    return float(value) if value is not None else None


def build_table_trace(
    bundle: DeterministicAnalysisBundle,
    spec: Mapping[str, Any],
    *,
    fact_file_resource_id: str,
) -> tuple[TableTraceV1, str]:
    """从确定性 facts 构建服务端表格与其追溯记录。

    spec 字段：
    - ``tableId``：表格协议 ID。
    - ``metricCodes``：列（顺序即列序），每列绑定该 code 的唯一 metric fact。
    - ``rows``：行清单，每行 ``{"key": <rowKey>, "label": <显示名>,
      "period": <periodValue 精确匹配>}``；period 取该 fact 的
      ``periodValues`` 中匹配项的值。
    - ``caption``：可选表题。

    ``fact_file_resource_id`` 是 bundle 文件在追溯索引中的资源 ID；
    单元格值来自冻结 fact 记录本身，行键是冻结结构键，排序变化不影响
    绑定（计划 3.2）。
    """

    table_id = _normalize_table_id(str(spec.get("tableId", "")))
    metric_codes = tuple(str(code) for code in spec.get("metricCodes", ()))
    rows_spec = tuple(spec.get("rows", ()))
    if not metric_codes or len(metric_codes) != len(set(metric_codes)):
        raise ReportingError("request_invalid", "表格列必须是非重复的指标 code 清单。")
    if not rows_spec:
        raise ReportingError("request_invalid", "表格至少需要一行。")

    facts_by_code: dict[str, Any] = {}
    selected_fact_ids = spec.get("factIds", {})
    for fact in bundle.metrics:
        for code in fact.metric_codes:
            if code in selected_fact_ids and fact.fact_id != selected_fact_ids[code]:
                continue
            # 同一 code 多个 fact（多数据集/多范围）时拒绝装配，避免猜。
            if code in facts_by_code:
                raise ReportingError(
                    "request_invalid",
                    f"指标 {code} 在分析中存在多条事实，表格装配需要更精确的规格。",
                )
            facts_by_code[code] = fact

    row_keys: list[str] = []
    cells: list[TableCellBindingV1] = []
    markdown_rows: list[list[str]] = []
    for row in rows_spec:
        if not isinstance(row, Mapping) or not row.get("key"):
            raise ReportingError("request_invalid", "表格行必须提供 key。")
        row_key = str(row["key"])
        if row_key in row_keys:
            raise ReportingError("request_invalid", f"表格 rowKey 重复: {row_key}")
        row_keys.append(row_key)
        period = str(row.get("period", ""))
        label = str(row.get("label", row_key))
        rendered_row = [label]
        for code in metric_codes:
            fact = facts_by_code.get(code)
            if fact is None:
                raise ReportingError(
                    "request_invalid", f"表格列引用了不存在的指标: {code}"
                )
            value = None
            if period:
                match = next(
                    (pv for pv in fact.period_values if pv.period == period), None
                )
                if match is None and not spec.get("allowMissingPeriods", False):
                    raise ReportingError(
                        "request_invalid",
                        f"行 {row_key} 的期间 {period} 在指标 {code} 中不存在。",
                    )
                value = float(match.value) if match is not None else None
            else:
                value = _metric_value(fact, "total")
            cell = TableCellBindingV1(
                rowKey=row_key,
                columnKey=spec.get("columnLabels", {}).get(code, code),
                factRefs=(
                    FactRefV1(
                        analysisId=bundle.analysis_id,
                        fileResourceId=fact_file_resource_id,
                        jsonPointer=fact_pointer(bundle, fact.fact_id) or "",
                        factKind="metric",
                        factKey=fact.fact_id,
                    ),
                ) if value is not None else (),
            )
            cells.append(cell)
            rendered_row.append(
                "—" if value is None else _format_number(value, fact.unit)
            )
        markdown_rows.append(rendered_row)

    trace = TableTraceV1(
        tableId=table_id,
        rowKeys=tuple(row_keys),
        columnKeys=tuple(spec.get("columnLabels", {}).get(code, code) for code in metric_codes),
        cells=tuple(cells),
    )
    markdown = render_table_markdown(
        table_id, trace.column_keys, markdown_rows,
        caption=str(spec["caption"]) if spec.get("caption") else None,
    )
    return trace, markdown


def _format_number(value: float, unit: str | None) -> str:
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def render_table_markdown(
    table_id: str,
    column_keys: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    caption: str | None = None,
) -> str:
    """渲染带协议块的 Markdown 表格；每行首项是行标签（不占 columnKey）。

    表头 = 空标签列 + columnKeys；数据行 = [label, *values]，长度必须
    等于 len(column_keys) + 1。
    """

    header = "| " + " | ".join(("", *column_keys)) + " |"
    separator = "| " + " | ".join(("---",) * (len(column_keys) + 1)) + " |"
    for row in rows:
        if len(row) != len(column_keys) + 1:
            raise ReportingError(
                "request_invalid", f"表格行单元格数与列数不一致: {row[:1]}"
            )
    body_lines = ["| " + " | ".join(row) + " |" for row in rows]
    lines = [header, separator, *body_lines]
    table = "\n".join(lines)
    # 空行隔离结束标记，避免 Milkdown 表格解析器把结束标记吞进表格最后一行。
    if caption:
        return f"{caption}\n\n[[table:{table_id}]]\n{table}\n\n[[/table:{table_id}]]"
    return f"[[table:{table_id}]]\n{table}\n\n[[/table:{table_id}]]"


def _period_display_label(period: str, granularity: str | None) -> str:
    """表格行标签按读者习惯显示期间；行键仍使用冻结期间文本。"""

    if re.fullmatch(r"\d{4}", period):
        return f"{period}年"
    match = re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", period)
    if match is None:
        return period
    year, month, day = match.groups()
    if day is None or (granularity == "month" and day == "01"):
        return f"{year}年{int(month)}月"
    return f"{year}年{int(month)}月{int(day)}日"


_MAX_METRIC_LABEL_LENGTH = 24


def _fact_label(
    fact: Any,
    dataset_contexts: Sequence[Mapping[str, Any]],
    metric_descriptions: Mapping[str, str] | None = None,
) -> str:
    """仅使用与冻结事实快照身份一致的字段说明，避免把成本误称为收入。

    数据集字段无说明时，退回 Profile 中与该事实指标代码唯一对应的简短指标说明；
    仍无可靠名称才显示字段名。
    """
    dataset_id = getattr(fact, "dataset_id", None) or getattr(fact, "current_dataset_id", None)
    sha256 = getattr(fact, "dataset_sha256", None) or getattr(fact, "current_dataset_sha256", None)
    for context in dataset_contexts:
        if context.get("datasetId") != dataset_id or context.get("sha256") != sha256:
            continue
        schema = context.get("schema", {})
        for table in schema.get("tables", ()):
            for column in table.get("columns", ()):
                ref = ".".join(str(value) for value in (
                    table.get("sourceId") or schema.get("sourceId"), table.get("database"),
                    table.get("name"), column.get("name"),
                ))
                description = column.get("description")
                if ref == fact.field_ref and isinstance(description, str) and description.strip():
                    return description.strip()
    profile_labels = {
        description.strip()
        for code in getattr(fact, "metric_codes", ()) or ()
        if isinstance(description := (metric_descriptions or {}).get(code), str)
        and 0 < len(description.strip()) <= _MAX_METRIC_LABEL_LENGTH
    }
    if len(profile_labels) == 1:
        return next(iter(profile_labels))
    return {"revenue": "收入", "indicator_value": "指标值"}.get(fact.field, fact.field)


def build_analysis_table(
    bundle: DeterministicAnalysisBundle,
    *,
    fact_file_resource_id: str,
    dataset_contexts: Sequence[Mapping[str, Any]] = (),
    metric_descriptions: Mapping[str, str] | None = None,
) -> tuple[TableTraceV1, str] | None:
    """按 B0 冻结规则从一个分析 bundle 自动生成服务端指标期间表。

    规则（不发明内容，缺依据就不生成）：
    - 列 = 唯一指标事实，或同代码下唯一的本期事实；其他歧义 code 跳过；
    - 行 = 这些指标 periodValues 的期间并集（按首个 fact 的冻结顺序）；
    - 无可用指标 → 返回 None；无分期间值 → 展示冻结指标合计。
    """

    if bundle.comparisons:
        table_id = f"table-{bundle.analysis_id}"
        comparisons = [fact for fact in bundle.comparisons if fact.fact_id]
        if not comparisons:
            return None
        types = {fact.comparison_type for fact in comparisons}
        metric_labels = {_fact_label(fact, dataset_contexts, metric_descriptions) for fact in comparisons}
        metric_label = next(iter(metric_labels)) if len(metric_labels) == 1 else "数值"
        baseline_label = ("同期" if types == {"yoy"} else "上期" if types == {"mom"} else "基期") + metric_label
        rate_label = "同比增幅" if types == {"yoy"} else "环比增幅" if types == {"mom"} else "变化率"
        columns = ("数值",) if len(comparisons) == 1 else tuple(
            f"对比 {index + 1}" for index in range(len(comparisons))
        )
        rows: list[list[str]] = []
        cells: list[TableCellBindingV1] = []
        row_keys: list[str] = []
        for field, label in (("currentTotal", "本期" + metric_label), ("baselineTotal", baseline_label), ("change", metric_label + "变化额"), ("changeRate", rate_label)):
            row_key = f"comparison:0:{field}"
            row_keys.append(row_key)
            row = [label]
            for column, fact in zip(columns, comparisons):
                value = fact.model_dump(mode="json", by_alias=True)[field]
                unit = "%" if field == "changeRate" else fact.unit
                row.append("—" if value is None else _format_number(value, unit) + (unit or ""))
                cells.append(TableCellBindingV1(
                    rowKey=row_key, columnKey=column,
                    factRefs=(FactRefV1(
                        analysisId=bundle.analysis_id, fileResourceId=fact_file_resource_id,
                        jsonPointer=fact_pointer(bundle, fact.fact_id) or "",
                        factKind="comparison", factKey=fact.fact_id,
                    ),),
                ))
            rows.append(row)
        return TableTraceV1(tableId=table_id, rowKeys=tuple(row_keys), columnKeys=columns, cells=tuple(cells)), render_table_markdown(
            table_id, columns, rows, caption=bundle.analysis_name or "指标对比",
        )

    candidates: dict[str, list[Any]] = {}
    for fact in bundle.metrics:
        for code in fact.metric_codes:
            candidates.setdefault(code, []).append(fact)
    facts_by_code: dict[str, Any] = {}
    for code, facts in candidates.items():
        current = [fact for fact in facts if "current" in fact.period_roles and fact.fact_id]
        if len(facts) == 1:
            facts_by_code[code] = facts[0]
        elif len(current) == 1:
            facts_by_code[code] = current[0]
    codes = list(facts_by_code)
    if not codes:
        return None
    selected = [facts_by_code[code] for code in codes]
    periods: list[str] = []
    for fact in selected:
        for period_value in fact.period_values:
            if period_value.period not in periods:
                periods.append(period_value.period)
    granularities = {fact.period_granularity for fact in selected}
    granularity = next(iter(granularities)) if len(granularities) == 1 else None
    labels_by_period = {period: _period_display_label(period, granularity) for period in periods}
    if len(set(labels_by_period.values())) != len(labels_by_period):
        # 不同冻结期间显示为同一标签时无法区分行，保留原始期间文本。
        labels_by_period = {period: period for period in periods}
    rows = [
        {"key": f"period:{period}", "label": labels_by_period[period], "period": period}
        for period in periods
    ] or [{"key": "total", "label": "合计"}]
    labels = {
        code: f"{_fact_label(facts_by_code[code], dataset_contexts, metric_descriptions)}（{facts_by_code[code].unit or '数值'}）"
        for code in codes
    }
    if len(set(labels.values())) != len(labels):
        labels = {code: f"{labels[code]} · {code}" for code in codes}
    spec: dict[str, Any] = {
        "tableId": f"table-{bundle.analysis_id}",
        "metricCodes": codes,
        "columnLabels": labels,
        "factIds": {code: fact.fact_id for code, fact in facts_by_code.items() if fact.fact_id},
        "rows": rows,
        "allowMissingPeriods": True,
        "caption": bundle.analysis_name or "分期间指标汇总",
    }
    return build_table_trace(bundle, spec, fact_file_resource_id=fact_file_resource_id)


def fill_table_trace_file_refs(
    trace: TableTraceV1,
    *,
    analysis_id: str,
    file_resource_id: str,
) -> TableTraceV1:
    """装配层把表格单元格 FactRef 的文件资源重写为真实登记 ID。

    供 spec 变化后复用已生成的行键结构时修正引用；正常路径直接在
    ``build_table_trace`` 传入 fact_file_resource_id，无需调用本函数。
    """

    cells = tuple(
        cell.model_copy(
            update={
                "fact_refs": tuple(
                    ref.model_copy(
                        update={
                            "analysis_id": analysis_id,
                            "file_resource_id": file_resource_id,
                        }
                    )
                    for ref in cell.fact_refs
                )
            }
        )
        for cell in trace.cells
    )
    return trace.model_copy(update={"cells": cells})
