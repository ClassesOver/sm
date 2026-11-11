"""正式指标结果的冻结附表；只展示回执值，不重新聚合或换算。"""

from hashlib import sha256

from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from ..models import ReportingError
from ..trace.contracts_v1 import FactRefV1, TableCellBindingV1, TableTraceV1
from .presentation import semantic_issue_message


def result_row_key(fact_id: str) -> str:
    return "result:" + sha256(fact_id.encode()).hexdigest()


def build_registered_result_tables(
    bundle: DeterministicAnalysisBundle, *, fact_file_resource_id: str,
) -> tuple[tuple[TableTraceV1, str], ...]:
    from ..trace.table_builder import render_table_markdown

    context = bundle.metric_context
    if context is None:
        raise ReportingError("report_analysis_facts_invalid", "正式指标表缺少本报告计算依据。")
    definitions = {metric.version_ref(): metric for metric in context.metrics}
    tables = []
    seen_ids = set()
    for calculation_index, calculation in enumerate(context.calculations):
        groups = {}
        for result_index, result in enumerate(calculation.results):
            if (result.metric_version not in definitions or result.basis_id != context.basis_id
                    or result.fact_id in seen_ids or result.unit != definitions[result.metric_version].unit):
                raise ReportingError("report_analysis_facts_invalid", "正式指标表的事实身份或单位与计算依据不一致。")
            seen_ids.add(result.fact_id)
            groups.setdefault(result.metric_version, []).append((result_index, result))
        for metric_index, (version, results) in enumerate(groups.items()):
            metric = definitions[version]
            column = f"计算结果（{metric.unit}）"
            for offset in range(0, len(results), 500):
                page = results[offset:offset + 500]
                rows, cells, row_keys = [], [], []
                for result_index, result in page:
                    key = result_row_key(result.fact_id)
                    label = f"[{result.period.start.isoformat()}, {result.period.end.isoformat()})"
                    if result.dimensions:
                        label += " · " + "、".join(f"{item.dimension_id}={item.value}" for item in result.dimensions)
                    if result.issue_codes:
                        label += " · " + ("暂不可计算：" if result.status == "unavailable" else "限制：") + "；".join(semantic_issue_message(code) for code in result.issue_codes)
                    rows.append((label, format(result.value, 'f') if result.value is not None else "—"))
                    row_keys.append(key)
                    cells.append(TableCellBindingV1(rowKey=key, columnKey=column, valueSelector="value",
                        factRefs=(FactRefV1(analysisId=bundle.analysis_id, fileResourceId=fact_file_resource_id,
                            jsonPointer=f"/metricContext/calculations/{calculation_index}/results/{result_index}",
                            factKind="metric", factKey=result.fact_id),)))
                table_id = f"table-{bundle.analysis_id}-registered-{calculation_index}-{metric_index}-{offset // 500}"
                markdown = render_table_markdown(table_id, (column,), rows,
                    caption=f"{metric.name}（指标版本 {version.revision}；期间含起日、不含止日）", row_label_header="期间与范围")
                trace = TableTraceV1(tableId=table_id, rowKeys=tuple(row_keys), columnKeys=(column,),
                    cells=tuple(cells), originMarkdown=markdown)
                tables.append((trace, markdown))
    return tuple(tables)
