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
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle, _parse_period
from ..models import ReportingError
from .contracts_v1 import (
    FactRefV1,
    TableCellBindingV1,
    TableTraceV1,
)
from .fact_index import fact_pointer_index
from .numeric_text import (
    _MONEY_UNITS,
    PERCENT_POINT,
    format_fact_value,
    percent_point_field,
    primary_display_name,
)

_TABLE_ID_PATTERN_RULES = "表格 ID 只允许字母数字与 _ . :-"


def _normalize_table_id(table_id: str) -> str:
    cleaned = table_id.strip()
    if not cleaned or len(cleaned) > 128 or any(ch in "\r\n" for ch in cleaned):
        raise ReportingError("request_invalid", _TABLE_ID_PATTERN_RULES)
    return cleaned


def _metric_value(fact: Any, key: str) -> float | None:
    value = getattr(fact, key, None)
    return float(value) if value is not None else None


_RESERVED_ROW_KEYS = frozenset({"total", "currentTotal", "baselineTotal", "change", "changeRate"})


def _role_consistent_row_key(row_key: str, period: str) -> str:
    """保留命名空间的 rowKey 必须表达本行真实角色。

    核验端不允许保留角色（total/period:/comparison:）改指其他等值字段；调用方自定义
    的 key 若落入保留命名空间却与本行期间不符，按本行实际角色改写，其他自定义 key 原样保留。
    """

    if row_key not in _RESERVED_ROW_KEYS and not row_key.startswith(("period:", "comparison:")):
        return row_key
    return f"period:{period}" if period else "total"


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
    pointers = fact_pointer_index(bundle)
    metric_codes = tuple(str(code) for code in spec.get("metricCodes", ()))
    rows_spec = tuple(spec.get("rows", ()))
    if not metric_codes or len(metric_codes) != len(set(metric_codes)):
        raise ReportingError("request_invalid", "表格列必须是非重复的指标 code 清单。")
    if not rows_spec:
        raise ReportingError("request_invalid", "表格至少需要一行。")

    facts_by_code: dict[str, Any] = {}
    selected_fact_ids = spec.get("factIds", {})
    if not isinstance(selected_fact_ids, Mapping):
        selected_fact_ids = {}
    # 编辑器规格按不可变 factId 选择列；部分旧 bundle 没有 metricCodes，
    # 此时列别名可回退到 field，但仍由 factId 唯一锁定事实。
    facts_by_id = {fact.fact_id: fact for fact in bundle.metrics if fact.fact_id}
    for code in metric_codes:
        selected = selected_fact_ids.get(code)
        if selected in facts_by_id:
            facts_by_code[code] = facts_by_id[selected]
    for fact in bundle.metrics:
        for code in fact.metric_codes:
            if code not in metric_codes:
                continue
            if code in selected_fact_ids and fact.fact_id != selected_fact_ids[code]:
                continue
            # 同一 code 多个 fact（多数据集/多范围）时拒绝装配，避免猜。
            if code in facts_by_code and facts_by_code[code] is not fact:
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
        period = str(row.get("period", ""))
        row_key = _role_consistent_row_key(str(row["key"]), period)
        if row_key in row_keys:
            raise ReportingError("request_invalid", f"表格 rowKey 重复: {row_key}")
        row_keys.append(row_key)
        label = str(row.get("label", row_key))
        rendered_row = [label]
        for code in metric_codes:
            fact = facts_by_code.get(code)
            if fact is None:
                raise ReportingError(
                    "request_invalid", f"表格列引用了不存在的指标: {code}"
                )
            value = None
            value_selector = "total"
            if period:
                match = next(
                    ((index, pv) for index, pv in enumerate(fact.period_values) if pv.period == period), None
                )
                if match is None and not spec.get("allowMissingPeriods", False):
                    raise ReportingError(
                        "request_invalid",
                        f"行 {row_key} 的期间 {period} 在指标 {code} 中不存在。",
                    )
                value = float(match[1].value) if match is not None else None
                value_selector = f"periodValues.{match[0]}" if match is not None else None
            else:
                value = _metric_value(fact, "total")
            cell = TableCellBindingV1(
                rowKey=row_key,
                columnKey=spec.get("columnLabels", {}).get(code, code),
                valueSelector=value_selector,
                factRefs=(
                    FactRefV1(
                        analysisId=bundle.analysis_id,
                        fileResourceId=fact_file_resource_id,
                        jsonPointer=pointers.get(fact.fact_id) or "",
                        factKind="metric",
                        factKey=fact.fact_id,
                    ),
                ) if value is not None else (),
            )
            cells.append(cell)
            display_unit = spec.get("displayUnits", {}).get(code)
            rendered_row.append(
                "—" if value is None
                else _scaled_number(value, fact.unit, display_unit) if display_unit
                else _format_number(value, fact.unit)
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
        row_label_header=str(spec.get("rowLabelHeader", "项目")),
    )
    return trace, markdown


def _format_number(value: float, unit: str | None) -> str:
    if float(value).is_integer():
        return f"{int(value):,}"
    return format_fact_value(value, unit).removesuffix(unit or "")


# 百万以上的元/人次整列改用万元/万人次两位小数，“1,112,354,150”难以阅读。
_TABLE_SCALED_UNITS = {"元": "万元", "人次": "万人次"}
_TABLE_SCALE_THRESHOLD = 1_000_000


def _table_display_unit(unit: str | None, values: Sequence[float | None]) -> str | None:
    """整列（或整组对比值）最大绝对值达到百万时返回万元/万人次，否则沿用原单位。

    全院收入、成本等亿级金额写成“1,317,262.21万元”领导读不出量级：非零值都不少于
    1亿元时改用亿元（两位小数仍精确到百万）；有小额值的列仍用万元，避免舍入丢失精度。
    回放：同表“实际总医疗收入（亿元）”旁的“实际药品收入”月度约2.7亿元，因未到10亿元
    写成“27,201.40万元”，同表单位不一难以对比。
    """
    present = [abs(value) for value in values if value is not None]
    if unit not in _TABLE_SCALED_UNITS or not present or max(present) < _TABLE_SCALE_THRESHOLD:
        return unit
    nonzero = [value for value in present if value]
    if unit == "元" and min(nonzero) >= 100_000_000:
        return "亿元"
    return _TABLE_SCALED_UNITS[unit]


def _scaled_number(value: float, unit: str | None, display_unit: str) -> str:
    """按数值目录同一规则换算并舍入，单元格只写数字（单位在表头或另行追加）。"""
    return format_fact_value(value, unit, display_unit).removesuffix(display_unit)


def render_table_markdown(
    table_id: str,
    column_keys: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    caption: str | None = None,
    row_label_header: str | None = "项目",
) -> str:
    """渲染带协议块的 Markdown 表格；每行首项是行标签（不占 columnKey）。

    默认增加有名称的行标签列；原始数据表传 None，不添加展示列。
    """

    def literal_cell(value: str) -> str:
        # 标签是冻结的字面量；转义不能改变 columnKey/row label 的身份。
        value = value.replace("&", "&amp;")
        value = re.sub(r"([\\|`*_{}\[\]<>])", r"\\\1", value)
        return value.replace("\r", "&#13;").replace("\n", "&#10;")

    headers = ([row_label_header] if row_label_header is not None else []) + list(column_keys)
    header = "| " + " | ".join(literal_cell(key) for key in headers) + " |"
    # 行标签左对齐，数值列右对齐，便于逐行比较位数与小数点。
    separator = "| " + " | ".join(("---", *("---:",) * (len(headers) - 1))) + " |"
    for row in rows:
        if len(row) != len(headers):
            raise ReportingError(
                "request_invalid", f"表格行单元格数与列数不一致: {row[:1]}"
            )
    body_lines = ["| " + " | ".join(literal_cell(cell) for cell in row) + " |" for row in rows]
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
    *, legacy_fallback: bool = True,
) -> str:
    """仅使用与冻结事实快照身份一致的字段说明，避免把成本误称为收入。

    数据集字段无说明时，退回 Profile 中与该事实指标代码唯一对应的简短指标说明；
    仍无可靠名称才显示字段名。
    """
    if label := getattr(fact, "display_name", None):
        # 显示名常带别名（“收入金额，也称医疗收入金额”）；表头只取首个名称。
        return primary_display_name(label) or label
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
    return ({"revenue": "收入", "indicator_value": "指标值"}.get(fact.field, fact.field)
            if legacy_fallback else fact.field)


def _analysis_table_metrics(bundle: DeterministicAnalysisBundle) -> dict[str, Any]:
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
    # 各期金额均为零的收支项（未启用的医疗服务收入等）只占版面，不进表；合计仍在正文与溯源中可查。
    # 只省略金额指标：投诉、不良事件等计数为零本身就是结果。全部列都为零时保留原表。
    active = {code: fact for code, fact in facts_by_code.items()
              if fact.unit not in _MONEY_UNITS
              or any(item.value for item in fact.period_values) or (not fact.period_values and fact.total)}
    facts_by_code = active or facts_by_code
    return facts_by_code


def _analysis_table_periods(facts: Sequence[Any]) -> list[str]:
    periods = list(dict.fromkeys(pv.period for fact in facts for pv in fact.period_values))
    parsed = {period: _parse_period(period) for period in periods}
    if all(value is not None for value in parsed.values()):
        periods.sort(key=lambda period: parsed[period].value)
    return periods


def build_analysis_table(
    bundle: DeterministicAnalysisBundle,
    *,
    fact_file_resource_id: str,
    dataset_contexts: Sequence[Mapping[str, Any]] = (),
    metric_descriptions: Mapping[str, str] | None = None,
    column_offset: int = 0,
    column_limit: int | None = None,
    row_offset: int = 0,
    row_limit: int | None = None,
    part_index: int | None = None,
) -> tuple[TableTraceV1, str] | None:
    """按 B0 冻结规则从一个分析 bundle 自动生成服务端指标期间表。

    规则（不发明内容，缺依据就不生成）：
    - 列 = 唯一指标事实，或同代码下唯一的本期事实；其他歧义 code 跳过；
    - 行 = 这些指标 periodValues 的期间并集（日历期间按时间排序）；
    - 无可用指标 → 返回 None；无分期间值 → 展示冻结指标合计。
    """

    pointers = fact_pointer_index(bundle)
    table_id = f"table-{bundle.analysis_id}"
    if part_index is not None:
        table_id += f"-part-{part_index}"
    elif column_limit:
        table_id += f"-part-{column_offset // column_limit + 1}"
    if bundle.comparisons:
        comparisons = [fact for fact in bundle.comparisons if fact.fact_id]
        # 本期与基期金额均为零的比较（未启用的收入项）只占版面；全部为零时保留原表。
        comparisons = [fact for fact in comparisons
                       if fact.unit not in _MONEY_UNITS or fact.current_total or fact.baseline_total] or comparisons
        comparisons = comparisons[column_offset:column_offset + column_limit if column_limit else None]
        if not comparisons:
            return None
        types = {fact.comparison_type for fact in comparisons}
        # 比较事实没有显示名：同一分析中字段引用相同的指标事实带有业务名称，优先借用。
        metric_names = {metric.field_ref: _fact_label(metric, dataset_contexts, metric_descriptions)
                        for metric in bundle.metrics}

        def comparison_label(fact: Any) -> str:
            return metric_names.get(fact.field_ref) or _fact_label(fact, dataset_contexts, metric_descriptions)

        metric_labels = {comparison_label(fact) for fact in comparisons}
        metric_label = next(iter(metric_labels)) if len(metric_labels) == 1 else "数值"
        baseline_label = ("同期" if types == {"yoy"} else "上期" if types == {"mom"} else "基期") + metric_label
        rate_label = "同比增幅" if types == {"yoy"} else "环比增幅" if types == {"mom"} else "变化率"
        # 多项比较并列时列名用各自指标名称（“对比 1…对比 5”读者无法分辨）；同名时加序号。
        names = [comparison_label(fact) for fact in comparisons]
        counts = Counter(names)
        reserved = set(names)
        labels = []
        for name in names:
            label = name
            if counts[name] > 1:
                suffix = 1
                while (label := f"{name}（{suffix}）") in reserved:
                    suffix += 1
                reserved.add(label)
            labels.append(label)
        columns = ("数值",) if len(comparisons) == 1 else tuple(labels)
        rows: list[list[str]] = []
        cells: list[TableCellBindingV1] = []
        row_keys: list[str] = []
        # 百分数指标（床位使用率等）的变化是百分点差值，不是“变化额”，也不能显示为 %。
        change_label = metric_label + ("变化" if all(fact.unit == "%" for fact in comparisons) else "变化额")
        for field, label in (("currentTotal", "本期" + metric_label), ("baselineTotal", baseline_label), ("change", change_label), ("changeRate", rate_label)):
            row_key = f"comparison:0:{field}"
            row_keys.append(row_key)
            row = [label]
            for column, fact in zip(columns, comparisons):
                value = fact.model_dump(mode="json", by_alias=True)[field]
                unit = ("%" if field == "changeRate"
                        else PERCENT_POINT if percent_point_field(field, fact.unit) else fact.unit)
                display_unit = (
                    _table_display_unit(unit, (fact.current_total, fact.baseline_total, fact.change))
                    if field in {"currentTotal", "baselineTotal", "change"} else unit
                )
                row.append(
                    "—" if value is None
                    else _scaled_number(value, unit, display_unit) + display_unit
                    if display_unit != unit and display_unit
                    else _format_number(value, unit) + (unit or "")
                )
                cells.append(TableCellBindingV1(
                    rowKey=row_key, columnKey=column,
                    valueSelector=field,
                    factRefs=(FactRefV1(
                        analysisId=bundle.analysis_id, fileResourceId=fact_file_resource_id,
                        jsonPointer=pointers.get(fact.fact_id) or "",
                        factKind="comparison", factKey=fact.fact_id,
                    ),),
                ))
            rows.append(row)
        return TableTraceV1(tableId=table_id, rowKeys=tuple(row_keys), columnKeys=columns, cells=tuple(cells)), render_table_markdown(
            table_id, columns, rows, caption=bundle.analysis_name or "指标对比",
        )

    facts_by_code = _analysis_table_metrics(bundle)
    codes = list(facts_by_code)[column_offset:column_offset + column_limit if column_limit else None]
    if not codes:
        return None
    selected = [facts_by_code[code] for code in codes]
    periods = _analysis_table_periods(selected)
    granularities = {fact.period_granularity for fact in selected}
    granularity = next(iter(granularities)) if len(granularities) == 1 else None
    # 未声明序列粒度的分析把月度数据记为日期（2025-01-01、2025-02-01…），按月显示，与声明按月的同一数据表一致。
    # 只在至少两期、逐月连续时认定为月度数据，单个“2025-01-01”仍按日期显示。
    months = [int(period[:4]) * 12 + int(period[5:7]) for period in periods
              if re.fullmatch(r"\d{4}-\d{2}-01", period)]
    if (granularity == "day" and len(periods) >= 2 and len(months) == len(periods)
            and months == list(range(months[0], months[0] + len(months)))):
        granularity = "month"
    labels_by_period = {period: _period_display_label(period, granularity) for period in periods}
    if len(set(labels_by_period.values())) != len(labels_by_period):
        # 不同冻结期间显示为同一标签时无法区分行，保留原始期间文本。
        labels_by_period = {period: period for period in periods}
    rows = [
        {"key": f"period:{period}", "label": labels_by_period[period], "period": period}
        for period in periods
    ] or [{"key": "total", "label": "合计"}]
    rows = rows[row_offset:row_offset + row_limit if row_limit is not None else None]
    if not rows:
        return None
    display_units = {
        code: _table_display_unit(
            facts_by_code[code].unit,
            [item.value for item in facts_by_code[code].period_values]
            or [_metric_value(facts_by_code[code], "total")],
        )
        for code in codes
    }
    labels = {
        code: f"{_fact_label(facts_by_code[code], dataset_contexts, metric_descriptions)}（{display_units[code] or '数值'}）"
        for code in codes
    }
    if len(set(labels.values())) != len(labels):
        labels = {code: f"{labels[code]} · {code}" for code in codes}
    spec: dict[str, Any] = {
        "tableId": table_id,
        "metricCodes": codes,
        "columnLabels": labels,
        "rowLabelHeader": "期间" if periods else "项目",
        "factIds": {code: fact.fact_id for code, fact in facts_by_code.items() if fact.fact_id},
        "rows": rows,
        "allowMissingPeriods": True,
        "displayUnits": {
            code: unit for code, unit in display_units.items() if unit != facts_by_code[code].unit
        },
        "caption": f"{bundle.analysis_name}：{'分期间指标汇总' if periods else '指标合计'}" if bundle.analysis_name else (
            "分期间指标汇总" if periods else "指标合计"
        ),
    }
    return build_table_trace(bundle, spec, fact_file_resource_id=fact_file_resource_id)


def build_analysis_tables(
    bundle: DeterministicAnalysisBundle,
    *,
    fact_file_resource_id: str,
    dataset_contexts: Sequence[Mapping[str, Any]] = (),
    metric_descriptions: Mapping[str, str] | None = None,
) -> tuple[tuple[TableTraceV1, str], ...]:
    """按列数、行数和单元格预算分表；在完整 bundle 中解析原始事实指针。"""
    options = dict(fact_file_resource_id=fact_file_resource_id,
                   dataset_contexts=dataset_contexts, metric_descriptions=metric_descriptions)
    # 先统计实际列，再构建受限分表；不能先生成可能超过单元格预算的整张表。
    facts = list(_analysis_table_metrics(bundle).values()) if not bundle.comparisons else []
    count = (sum(bool(fact.fact_id) for fact in bundle.comparisons) if bundle.comparisons
             else len(facts))
    row_count = 4 if bundle.comparisons else max(1, len(_analysis_table_periods(facts)))
    column_limit = min(5, 2000 // min(row_count, 1000))
    if count <= column_limit and row_count <= 1000:
        table = build_analysis_table(bundle, **options)
        return (table,) if table is not None else ()
    tables = []
    for offset in range(0, count, column_limit):
        selected = facts[offset:offset + column_limit]
        rows = 4 if bundle.comparisons else max(1, len(_analysis_table_periods(selected)))
        row_limit = min(1000, 2000 // min(column_limit, count - offset))
        for row_offset in range(0, rows, row_limit):
            part = build_analysis_table(
                bundle, **options, column_offset=offset, column_limit=column_limit,
                row_offset=row_offset, row_limit=row_limit, part_index=len(tables) + 1,
            )
            if part is not None:
                tables.append(part)
    return tuple(tables)


# ---------------------------------------------------------------------------
# 编辑器 AI 改表装配（设计稿 2026-10-25 §14.1）
#
# 与生成阶段同源：单元格逐格绑定 FactRef，数字全部是登记值；模板与模型
# 输出的 TableEditSpec 经编辑器服务校验后调用这里的纯装配器，不经过模型
# 手写 Markdown。
# ---------------------------------------------------------------------------


def build_comparison_edit_table(
    bundle: DeterministicAnalysisBundle,
    comparisons: Sequence[Any],
    selectors: Sequence[str],
    *,
    table_id: str,
    caption: str | None,
    fact_file_resource_id: str,
    dataset_contexts: Sequence[Mapping[str, Any]] = (),
    metric_descriptions: Mapping[str, str] | None = None,
) -> tuple[TableTraceV1, str]:
    """同比/环比对比表：行 = 比较事实，列 = currentTotal/baselineTotal/change/changeRate 子集。"""

    if not comparisons or not selectors:
        raise ReportingError("request_invalid", "对比表至少需要一行比较事实与一列选择器。")
    pointers = fact_pointer_index(bundle)
    types = {fact.comparison_type for fact in comparisons}
    metric_names = {metric.field_ref: _fact_label(metric, dataset_contexts, metric_descriptions)
                    for metric in bundle.metrics}

    def label_of(fact: Any) -> str:
        return metric_names.get(fact.field_ref) or _fact_label(
            fact, dataset_contexts, metric_descriptions
        )

    names = [label_of(fact) for fact in comparisons]
    metric_labels = set(names)
    metric_label = next(iter(metric_labels)) if len(metric_labels) == 1 else "数值"
    baseline_word = ("同期" if types == {"yoy"} else "上期" if types == {"mom"} else "基期")
    rate_word = ("同比增幅" if types == {"yoy"} else "环比增幅" if types == {"mom"} else "变化率")
    # 百分数指标的变化是百分点差值，不能称“变化额”。
    change_word = "变化" if all(fact.unit == "%" for fact in comparisons) else "变化额"
    wording = {
        "currentTotal": ("本期" + metric_label, None),
        "baselineTotal": (baseline_word + metric_label, None),
        "change": (metric_label + change_word, None),
        "changeRate": (rate_word, "%"),
    }
    column_keys = [wording[selector][0] for selector in selectors]
    if len(set(column_keys)) != len(column_keys):
        raise ReportingError("request_invalid", "对比表列标签重复，请调整选择器组合。")
    rows: list[list[str]] = []
    cells: list[TableCellBindingV1] = []
    row_keys: list[str] = []
    for index, fact in enumerate(comparisons):
        row_key = f"comparison:{index}"
        row_keys.append(row_key)
        row = [names[index]]
        for selector in selectors:
            value = fact.model_dump(mode="json", by_alias=True)[selector]
            unit = ("%" if selector == "changeRate"
                    else PERCENT_POINT if percent_point_field(selector, fact.unit) else fact.unit)
            display_unit = (
                _table_display_unit(unit, (fact.current_total, fact.baseline_total, fact.change))
                if selector in {"currentTotal", "baselineTotal", "change"} else unit
            )
            row.append(
                "—" if value is None
                else _scaled_number(value, unit, display_unit) + display_unit
                if display_unit != unit and display_unit
                else _format_number(value, unit) + (unit or "")
            )
            cells.append(TableCellBindingV1(
                rowKey=row_key, columnKey=wording[selector][0],
                valueSelector=selector,
                factRefs=(FactRefV1(
                    analysisId=bundle.analysis_id, fileResourceId=fact_file_resource_id,
                    jsonPointer=pointers.get(fact.fact_id) or "",
                    factKind="comparison", factKey=fact.fact_id,
                ),),
            ))
        rows.append(row)
    trace = TableTraceV1(
        tableId=_normalize_table_id(table_id),
        rowKeys=tuple(row_keys),
        columnKeys=tuple(column_keys),
        cells=tuple(cells),
    )
    return trace, render_table_markdown(
        trace.table_id, column_keys, rows, caption=caption
    )


def build_group_edit_table(
    bundle: DeterministicAnalysisBundle,
    parent: Any,
    groups: Sequence[Any],
    *,
    table_id: str,
    caption: str | None,
    share: bool,
    fact_file_resource_id: str,
    dataset_contexts: Sequence[Mapping[str, Any]] = (),
    metric_descriptions: Mapping[str, str] | None = None,
) -> tuple[TableTraceV1, str]:
    """构成表：行 = 维度分组（降序）+ 合计行，列 = 数值（可选占比）。

    占比列由服务端按固定规则（分组值 ÷ 父指标合计）计算，单元格同时绑定
    分组事实与父指标事实（valueSelector 为空，登记值可逐格还原）。
    """

    if not groups:
        raise ReportingError("request_invalid", "构成表至少需要一组维度分组。")
    pointers = fact_pointer_index(bundle)
    ordered = sorted(groups, key=lambda item: -item.total)
    parent_label = _fact_label(parent, dataset_contexts, metric_descriptions)
    breakdown_label = ordered[0].breakdown_label or ordered[0].breakdown_field or "维度"
    value_unit = _table_display_unit(parent.unit, [item.total for item in ordered] + [parent.total])
    value_column = f"{parent_label}（{value_unit or '数值'}）"
    column_keys = [value_column]
    if share:
        column_keys.append("占比")
    if caption is None:
        caption = f"{parent_label}按{breakdown_label}构成"
    row_keys: list[str] = []
    cells: list[TableCellBindingV1] = []
    rows: list[list[str]] = []
    parent_ref = FactRefV1(
        analysisId=bundle.analysis_id, fileResourceId=fact_file_resource_id,
        jsonPointer=pointers.get(parent.fact_id) or "",
        factKind="metric", factKey=parent.fact_id,
    )

    def group_label(group: Any) -> str:
        return group.scope.get(group.breakdown_field) or group.display_name or group.field

    for group in ordered:
        row_key = f"group:{group.fact_id}"
        row_keys.append(row_key)
        row = [group_label(group)]
        row.append(
            _scaled_number(group.total, group.unit, value_unit)
            if value_unit != group.unit and value_unit
            else _format_number(group.total, group.unit)
        )
        cells.append(TableCellBindingV1(
            rowKey=row_key, columnKey=value_column, valueSelector="total",
            factRefs=(FactRefV1(
                analysisId=bundle.analysis_id, fileResourceId=fact_file_resource_id,
                jsonPointer=pointers.get(group.fact_id) or "",
                factKind="metric", factKey=group.fact_id,
            ),),
        ))
        if share:
            row.append(_percentage_text(group.total, parent.total))
            cells.append(TableCellBindingV1(
                rowKey=row_key, columnKey="占比", valueSelector=None,
                factRefs=(cells[-1].fact_refs[0], parent_ref),
            ))
        rows.append(row)
    # 合计行只能绑定已登记的父指标合计事实。
    row_keys.append("total")
    total_row = ["合计"]
    total_row.append(
        _scaled_number(parent.total, parent.unit, value_unit)
        if value_unit != parent.unit and value_unit
        else _format_number(parent.total, parent.unit)
    )
    cells.append(TableCellBindingV1(
        rowKey="total", columnKey=value_column, valueSelector="total",
        factRefs=(parent_ref,),
    ))
    if share:
        total_row.append("100.0%")
        cells.append(TableCellBindingV1(
            rowKey="total", columnKey="占比", valueSelector=None, factRefs=(parent_ref,),
        ))
    rows.append(total_row)
    trace = TableTraceV1(
        tableId=_normalize_table_id(table_id),
        rowKeys=tuple(row_keys),
        columnKeys=tuple(column_keys),
        cells=tuple(cells),
    )
    return trace, render_table_markdown(
        trace.table_id, column_keys, rows, caption=caption, row_label_header=breakdown_label,
    )


def _percentage_text(numerator: float, denominator: float) -> str:
    if not denominator:
        return "—"
    return f"{numerator / denominator * 100:.1f}%"


def build_budget_edit_table(
    bundle: DeterministicAnalysisBundle,
    budgets: Sequence[Mapping[str, Any]],
    *,
    table_id: str,
    caption: str | None,
    fact_file_resource_id: str,
    dataset_contexts: Sequence[Mapping[str, Any]] = (),
    metric_descriptions: Mapping[str, str] | None = None,
) -> tuple[TableTraceV1, str]:
    """预算执行表：行 = 预算/实际成对事实，列 = 预算、实际、差额、完成率。

    预算与实际列绑定各自事实的登记合计；差额与完成率由服务端按固定规则
    从两个登记值计算（与数值目录 budgetComparison 同一算法），单元格同时
    绑定两个事实。
    """

    pointers = fact_pointer_index(bundle)
    facts = {fact.fact_id: fact for fact in (*bundle.metrics, *bundle.breakdowns)
             if fact.fact_id}
    rows: list[list[str]] = []
    cells: list[TableCellBindingV1] = []
    row_keys: list[str] = []
    for index, entry in enumerate(budgets):
        actual = facts.get(entry["actualFactId"])
        budget = facts.get(entry["budgetFactId"])
        if actual is None or budget is None:
            raise ReportingError("request_invalid", "预算执行表引用的事实不在冻结登记中。")
        row_key = f"budget:{index}"
        row_keys.append(row_key)
        label = _fact_label(actual, dataset_contexts, metric_descriptions)
        unit = actual.unit
        display_unit = _table_display_unit(unit, (actual.total, budget.total))
        row = [label]
        for fact, value in ((budget, budget.total), (actual, actual.total)):
            row.append(
                _scaled_number(value, unit, display_unit) + display_unit
                if display_unit != unit and display_unit
                else _format_number(value, unit) + (unit or "")
            )
            cells.append(TableCellBindingV1(
                rowKey=row_key, columnKey="预算" if fact is budget else "实际",
                valueSelector="total",
                factRefs=(FactRefV1(
                    analysisId=bundle.analysis_id, fileResourceId=fact_file_resource_id,
                    jsonPointer=pointers.get(fact.fact_id) or "",
                    factKind="metric", factKey=fact.fact_id,
                ),),
            ))
        refs = (cells[-1].fact_refs[0], cells[-2].fact_refs[0])
        difference = actual.total - budget.total
        row.append(_format_number(difference, unit) + (unit or ""))
        cells.append(TableCellBindingV1(
            rowKey=row_key, columnKey="差额（实际－预算）", valueSelector=None, factRefs=refs,
        ))
        row.append(_percentage_text(actual.total, budget.total))
        cells.append(TableCellBindingV1(
            rowKey=row_key, columnKey="完成率", valueSelector=None, factRefs=refs,
        ))
        rows.append(row)
    if not rows:
        raise ReportingError("request_invalid", "预算执行表至少需要一对预算/实际事实。")
    trace = TableTraceV1(
        tableId=_normalize_table_id(table_id),
        rowKeys=tuple(row_keys),
        columnKeys=("预算", "实际", "差额（实际－预算）", "完成率"),
        cells=tuple(cells),
    )
    return trace, render_table_markdown(
        trace.table_id, trace.column_keys, rows, caption=caption
    )



_SUPPLEMENTAL_LABELS = {
    "value": "指标值", "current": "本期值", "baseline": "对照期值", "previous": "上期值",
    "change": "变动额", "changeRate": "变动幅度", "contribution": "增减贡献占比",
    "share": "占比", "rank": "排名", "ratio": "比率", "numerator": "分子值",
    "denominator": "分母值", "difference": "差值", "primaryTotal": "主维度合计",
    "primaryShare": "主维度占比", "secondaryTotal": "次维度合计",
    "secondaryShare": "次维度占比", "baselineTotal": "基准合计", "totalChange": "总变动额",
}


def build_supplemental_tables(
    document: Mapping[str, Any], *, file_resource_id: str, dataset_ids: Sequence[str] = (),
    dataset_contexts: Sequence[Mapping[str, Any]] = (),
) -> tuple[tuple[TableTraceV1, str], ...]:
    """完整发布冻结 findings 中的结构化表；不从列名推断指标与计算规则。"""
    import hashlib

    from .contracts_v1 import TableOperandV1
    from .table_sources import source_cell_display, source_cell_view

    tables: list[tuple[TableTraceV1, str]] = []
    field_labels: dict[str, set[str]] = {}
    for context in dataset_contexts:
        if context.get("datasetId") not in dataset_ids:
            continue
        for table in context.get("schema", {}).get("tables", ()):
            for column in table.get("columns", ()):
                label = primary_display_name(column.get("description"))
                if label:
                    field_labels.setdefault(column["name"], set()).add(label)

    def walk(node: Any, pointer: str) -> None:
        if isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f'{pointer}/{index}')
        elif isinstance(node, Mapping):
            if node.get('metricScopeRejected') is True:
                return
            if isinstance(node.get('columns'), list) and isinstance(node.get('rows'), list):
                columns, source_rows = node['columns'], node['rows']
                if (not columns or not source_rows or len(columns) > 200
                        or not all(isinstance(column, str) and column.strip() and len(column) <= 128 for column in columns)
                        or len(columns) != len(set(columns))
                        or any(not isinstance(row, list) or len(row) != len(columns) for row in source_rows)):
                    return
                metadata = node.get('columnMeta', {})
                headers = []
                for position, column in enumerate(columns):
                    meta = metadata.get(column, {}) if isinstance(metadata, Mapping) else {}
                    label = meta.get('label') or meta.get('displayName')
                    candidates = field_labels.get(meta.get('sourceField', column), set())
                    label = label or (next(iter(candidates)) if len(candidates) == 1 else None)
                    label = label or _SUPPLEMENTAL_LABELS.get(column, column)
                    unit = meta.get('unit')
                    values = [row[position] for row in source_rows
                              if type(row[position]) in (int, float)]
                    display_unit = _table_display_unit(unit, values)
                    if display_unit and not re.search(r'[（(]' + re.escape(display_unit) + r'[）)]$', label):
                        label += f'（{display_unit}）'
                    elif not unit and column in _SUPPLEMENTAL_LABELS and column != 'rank':
                        label += '（单位未提供）'
                    headers.append(label)
                if len(set(headers)) != len(headers):
                    headers = [f'{label} · {column}' for label, column in zip(headers, columns, strict=True)]
                # 宽表拆列时重复来源首列，保留读者逐行对照；没有任何业务列名推断。
                column_groups = ([list(range(len(columns)))] if len(columns) <= 5 else
                                 [[0, *range(offset, min(offset + 4, len(columns)))]
                                  for offset in range(1, len(columns), 4)])
                for selected_columns in column_groups:
                    labels = [headers[column] for column in selected_columns]
                    limit = min(1000, 2000 // len(labels))
                    for offset in range(0, len(source_rows), limit):
                        cells, rows, keys = [], [], []
                        for index in range(offset, min(offset + limit, len(source_rows))):
                            key = f'source-row:{index}'
                            keys.append(key)
                            row = []
                            for column in selected_columns:
                                operand = TableOperandV1(fileResourceId=file_resource_id, tablePointer=pointer,
                                                         rowIndex=index, columnIndex=column, coefficient='1')
                                selected = source_cell_view(operand, document)
                                if selected is None:
                                    return
                                row.append(source_cell_display(selected, headers[column], display_format='unit_formatted'))
                                cells.append(TableCellBindingV1(
                                    rowKey=key, columnKey=headers[column], sourceCell=operand,
                                    datasetIds=dataset_ids or document.get("datasetIds", ()),
                                ))
                            rows.append(row)
                        identity = hashlib.sha256(f'{file_resource_id}|{pointer}|{selected_columns}|{offset}'.encode()).hexdigest()[:20]
                        table_id = f'table-supplemental-{identity}'
                        caption = node.get('title') or node.get('name')
                        markdown = render_table_markdown(table_id, labels, rows,
                                                         caption=caption if isinstance(caption, str) else None,
                                                         row_label_header=None)
                        trace = TableTraceV1(tableId=table_id, rowKeys=keys, columnKeys=labels,
                                             cells=cells, originMarkdown=markdown, rowLabelColumn=False,
                                             sourceCellDisplay='unit_formatted')
                        tables.append((trace, markdown))
                return
            for key, child in node.items():
                escaped = str(key).replace('~', '~0').replace('/', '~1')
                walk(child, f'{pointer}/{escaped}')

    walk(document.get('findings'), '/findings')
    return tuple(tables)
