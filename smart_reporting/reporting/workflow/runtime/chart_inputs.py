"""按已校验的图表数据绑定预物化统一表格输入（chart-input/v1）。

宿主只做确定性的形状转换：按 descriptor 声明的 dataPath 取值，统一成
``columns + rows``，不计算任何业务指标。绑定不在本轮签发目录中或形状不符
时，该图整体回退为原始 facts 路径并软告警，其余图照常物化。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from loguru import logger

from .phase_models import ChartDataBinding, ChartDraft, VisualizationPlanDraft

CHART_INPUT_SCHEMA = "chart-input/v1"
CHART_INPUT_PREVIEW_ROWS = 3
_PATH_TOKEN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")
_MAX_CHART_INPUT_BYTES = 8 * 1024 * 1024


class ChartInputError(ValueError):
    """单个绑定无法确定性物化；调用方对该图回退原始 facts。"""


@dataclass(frozen=True, slots=True)
class ChartInputFile:
    path: str
    content: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True, slots=True)
class ChartInputMaterialization:
    files: tuple[ChartInputFile, ...] = ()
    entries: tuple[dict[str, Any], ...] = ()
    fallback_chart_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def read_paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.files)


def parse_data_path(data_path: str) -> tuple[str | int, ...]:
    """把 ``metrics[0].periodValues`` 解析为 ``("metrics", 0, "periodValues")``。"""

    tokens: list[str | int] = []
    for part in data_path.split("."):
        if not part:
            raise ChartInputError(f"dataPath 无效：{data_path}")
        consumed = 0
        for match in _PATH_TOKEN.finditer(part):
            if match.start() != consumed:
                raise ChartInputError(f"dataPath 无效：{data_path}")
            name, index = match.groups()
            tokens.append(int(index) if index is not None else name)
            consumed = match.end()
        if consumed != len(part):
            raise ChartInputError(f"dataPath 无效：{data_path}")
    if not tokens or not isinstance(tokens[0], str):
        raise ChartInputError(f"dataPath 无效：{data_path}")
    return tuple(tokens)


def _navigate(document: Any, tokens: Sequence[str | int]) -> Any:
    current = document
    for token in tokens:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                raise ChartInputError("dataPath 下标越界")
            current = current[token]
        else:
            if not isinstance(current, Mapping) or token not in current:
                raise ChartInputError(f"dataPath 字段不存在：{token}")
            current = current[token]
    return current


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _columns_rows_table(
    columns: Any, rows: Any, fields: Sequence[str]
) -> tuple[list[str], list[list[Any]]]:
    if not isinstance(columns, list) or not all(isinstance(item, str) for item in columns):
        raise ChartInputError("columns 必须是字符串列表")
    if not isinstance(rows, list):
        raise ChartInputError("rows 必须是列表")
    width = len(columns)
    for row in rows:
        if not isinstance(row, list) or len(row) != width:
            raise ChartInputError("rows 与 columns 不等长")
        if not all(_is_scalar(value) for value in row):
            raise ChartInputError("rows 只能包含标量")
    missing = [name for name in fields if name not in columns]
    if missing:
        raise ChartInputError(f"绑定字段不在 columns 中：{missing}")
    return list(columns), [list(row) for row in rows]


def _table_for_binding(
    document: Any, binding: ChartDataBinding
) -> tuple[list[str], list[list[Any]], Any]:
    """返回 (columns, rows, columnMeta)；形状以 dataPath 指向的值为准，不猜测。"""

    tokens = parse_data_path(binding.data_path)
    value = _navigate(document, tokens)
    fields = list(binding.fields)
    if tokens[-1] == "rows" and isinstance(value, list):
        parent = _navigate(document, tokens[:-1])
        if isinstance(parent, Mapping) and "columns" in parent:
            columns, rows = _columns_rows_table(parent.get("columns"), value, ())
            return columns, rows, parent.get("columnMeta")
    if isinstance(value, Mapping) and "columns" in value and "rows" in value:
        columns, rows = _columns_rows_table(value.get("columns"), value.get("rows"), ())
        return columns, rows, value.get("columnMeta")
    if isinstance(value, list):
        rows = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ChartInputError("行对象数组包含非对象元素")
            missing = [name for name in fields if name not in item]
            if missing:
                raise ChartInputError(f"行对象缺少字段：{missing}")
            row = [item[name] for name in fields]
            if not all(_is_scalar(cell) for cell in row):
                raise ChartInputError("行对象字段必须是标量")
            rows.append(row)
        return fields, rows, None
    if isinstance(value, Mapping):
        columns = [name for name in fields if name in value and _is_scalar(value[name])]
        if not columns:
            raise ChartInputError("对象中没有可物化的标量字段")
        return columns, [[value[name] for name in columns]], None
    raise ChartInputError("dataPath 指向的值无法转换为表格")


def _binding_catalog(
    facts: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str], tuple[frozenset[str], Mapping[str, Any]]]:
    """(analysisId, 文件路径, dataPath) → (声明字段, 文件身份)。"""

    catalog: dict[tuple[str, str, str], tuple[frozenset[str], Mapping[str, Any]]] = {}

    def register(analysis_id: Any, identity: Any, descriptors: Any) -> None:
        path = identity.get("path") if isinstance(identity, Mapping) else None
        if not isinstance(analysis_id, str) or not isinstance(path, str):
            return
        for descriptor in descriptors if isinstance(descriptors, (list, tuple)) else ():
            if not isinstance(descriptor, Mapping):
                continue
            data_path = descriptor.get("dataPath")
            fields = descriptor.get("fields")
            if isinstance(data_path, str) and isinstance(fields, (list, tuple)):
                catalog[(analysis_id, path, data_path)] = (
                    frozenset(str(item) for item in fields),
                    identity,
                )

    for analysis in facts:
        if not isinstance(analysis, Mapping):
            continue
        analysis_id = analysis.get("analysisId")
        register(analysis_id, analysis.get("factFile"), analysis.get("dataDescriptors"))
        for source in analysis.get("supplementalEvidenceSources") or ():
            if isinstance(source, Mapping):
                register(analysis_id, source.get("sourceFile"), source.get("dataDescriptors"))
    return catalog


def _safe_name(chart_id: str) -> str:
    name = _UNSAFE_NAME.sub("-", chart_id).strip("-.")
    if not name or name != chart_id:
        digest = hashlib.sha256(chart_id.encode("utf-8")).hexdigest()[:10]
        name = f"{name or 'chart'}-{digest}"
    return name[:96]


def _materialize_chart(
    chart: ChartDraft,
    catalog: Mapping[tuple[str, str, str], tuple[frozenset[str], Mapping[str, Any]]],
    documents: Mapping[str, Any],
    output_root: str,
) -> tuple[list[ChartInputFile], list[dict[str, Any]]]:
    files: list[ChartInputFile] = []
    entries: list[dict[str, Any]] = []
    for index, binding in enumerate(chart.data_bindings, start=1):
        key = (binding.analysis_id, binding.fact_path, binding.data_path)
        declared = catalog.get(key)
        if declared is None or not set(binding.fields).issubset(declared[0]):
            raise ChartInputError("绑定未逐字引用本轮签发的事实描述")
        identity = declared[1]
        if binding.fact_path not in documents:
            raise ChartInputError("绑定事实文件未加载")
        columns, rows, column_meta = _table_for_binding(documents[binding.fact_path], binding)
        nullable = [
            column
            for position, column in enumerate(columns)
            if any(row[position] is None for row in rows)
        ]
        payload: dict[str, Any] = {
            "schema": CHART_INPUT_SCHEMA,
            "chartId": chart.chart_id,
            "role": binding.role,
            "source": {
                "analysisId": binding.analysis_id,
                "path": binding.fact_path,
                "sha256": identity.get("sha256"),
                "dataPath": binding.data_path,
            },
            "columns": columns,
            "rows": rows,
            "nullableColumns": nullable,
            "rowCount": len(rows),
        }
        if isinstance(column_meta, Mapping) and column_meta:
            payload["columnMeta"] = dict(column_meta)
        content = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        if len(content) > _MAX_CHART_INPUT_BYTES:
            raise ChartInputError("chart-input 超过大小上限")
        path = f"{output_root}/{_safe_name(chart.chart_id)}--{index}.json"
        files.append(ChartInputFile(path=path, content=content))
        entry: dict[str, Any] = {
            "chartId": chart.chart_id,
            "role": binding.role,
            "path": path,
            "columns": columns,
            "rowCount": len(rows),
            "nullableColumns": nullable,
            "preview": rows[:CHART_INPUT_PREVIEW_ROWS],
        }
        if "columnMeta" in payload:
            entry["columnMeta"] = payload["columnMeta"]
        entries.append(entry)
    return files, entries


def materialize_chart_inputs(
    plan: VisualizationPlanDraft,
    facts: Sequence[Mapping[str, Any]],
    documents: Mapping[str, Any],
    *,
    output_root: str,
) -> ChartInputMaterialization:
    """纯函数：documents 为 {事实文件相对路径: 已按 SHA 校验并解析的 JSON}。"""

    catalog = _binding_catalog(facts)
    files: list[ChartInputFile] = []
    entries: list[dict[str, Any]] = []
    fallback: set[str] = set()
    for chart in plan.charts:
        try:
            chart_files, chart_entries = _materialize_chart(
                chart, catalog, documents, output_root.rstrip("/")
            )
        except ChartInputError as error:
            fallback.add(chart.chart_id)
            logger.bind(chart_id=chart.chart_id).warning(
                "report_visualization_chart_input_fallback chart_id={} reason={}",
                chart.chart_id,
                str(error),
            )
            continue
        files.extend(chart_files)
        entries.extend(chart_entries)
    return ChartInputMaterialization(
        files=tuple(files), entries=tuple(entries), fallback_chart_ids=frozenset(fallback)
    )


def bound_fact_identities(
    plan: VisualizationPlanDraft, facts: Sequence[Mapping[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    """返回计划绑定引用、且在签发目录中出现的事实文件身份。"""

    catalog = _binding_catalog(facts)
    identities: dict[str, Mapping[str, Any]] = {}
    for chart in plan.charts:
        for binding in chart.data_bindings:
            declared = catalog.get((binding.analysis_id, binding.fact_path, binding.data_path))
            if declared is not None:
                identities[binding.fact_path] = declared[1]
    return identities


class ChartInputWorkspace(Protocol):
    async def read_limited_regular_file(
        self, thread_id: str, path: str, *, max_bytes: int
    ) -> bytes: ...

    async def awrite_bytes(
        self, thread_id: str, path: str, content: bytes, *, overwrite: bool = False
    ) -> Mapping[str, Any]: ...


async def prepare_chart_inputs(
    plan: VisualizationPlanDraft,
    facts: Sequence[Mapping[str, Any]],
    workspace: ChartInputWorkspace,
    *,
    thread_id: str,
    output_root: str,
) -> ChartInputMaterialization | None:
    """按 SHA 读取绑定事实文件并写入 chart-input；任何宿主侧异常整体回退原路径。"""

    try:
        documents: dict[str, Any] = {}
        for path, identity in bound_fact_identities(plan, facts).items():
            size = identity.get("size")
            content = await workspace.read_limited_regular_file(
                thread_id, path, max_bytes=int(size) if isinstance(size, int) else 0
            )
            if hashlib.sha256(content).hexdigest() != identity.get("sha256"):
                raise ChartInputError(f"事实文件身份不一致：{path}")
            documents[path] = json.loads(content)
        materialized = materialize_chart_inputs(
            plan, facts, documents, output_root=output_root
        )
        for item in materialized.files:
            await workspace.awrite_bytes(thread_id, item.path, item.content, overwrite=True)
    except Exception as error:  # noqa: BLE001 - 物化是优化路径，失败回退原始 facts
        logger.bind(error_type=type(error).__name__).warning(
            "report_visualization_chart_inputs_unavailable error={}", str(error)[:300]
        )
        return None
    return materialized


def _numbers(values: Any) -> list[float]:
    if isinstance(values, Mapping) and "bdata" in values:
        return []  # 二进制编码数组不解码，交由其余 trace 判定
    if not isinstance(values, (list, tuple)):
        return []
    flat: list[float] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            flat.extend(_numbers(value))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            flat.append(float(value))
    return flat


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-6, 0.006 * max(abs(left), abs(right)))


def plotly_trace_matches_chart_inputs(
    figure: Mapping[str, Any], chart_inputs: Sequence[Mapping[str, Any]]
) -> bool:
    """任一 trace 数值数组与任一 chart-input 数值列一致即视为已核对。

    允许显示舍入与 ×100 百分比换算；只做软告警依据，不改变交付。
    """

    columns: list[list[float]] = []
    for item in chart_inputs:
        names = item.get("columns")
        rows = item.get("rows")
        if not isinstance(names, list) or not isinstance(rows, list):
            continue
        for position in range(len(names)):
            values = [
                float(row[position])
                for row in rows
                if isinstance(row, list)
                and position < len(row)
                and isinstance(row[position], (int, float))
                and not isinstance(row[position], bool)
            ]
            if values:
                columns.append(values)
    if not columns:
        return True
    for trace in figure.get("data") or ():
        if not isinstance(trace, Mapping):
            continue
        for key in ("y", "x", "values", "z", "r", "text"):
            trace_values = _numbers(trace.get(key))
            if not trace_values:
                continue
            for column in columns:
                for scale in (1.0, 100.0, 0.01):
                    scaled = [value * scale for value in column]
                    if all(
                        any(_close(value, candidate) for candidate in scaled)
                        for value in trace_values
                    ):
                        return True
    return False


async def verify_plotly_chart_inputs(
    plan: VisualizationPlanDraft,
    materialized: ChartInputMaterialization,
    workspace: Any,
    *,
    thread_id: str,
) -> None:
    """Plotly 产物与 chart-input 数值核对；无一匹配时记软告警。"""

    payloads: dict[str, list[dict[str, Any]]] = {}
    for item in materialized.files:
        try:
            decoded = json.loads(item.content)
        except ValueError:
            continue
        payloads.setdefault(str(decoded.get("chartId")), []).append(decoded)
    for chart in plan.charts:
        if chart.interactive_path is None or chart.chart_id not in payloads:
            continue
        try:
            content, _mime = await workspace.afile_bytes(thread_id, chart.interactive_path)
            figure = json.loads(content)
        except Exception:  # noqa: BLE001 - 核对只是软告警
            continue
        if isinstance(figure, Mapping) and not plotly_trace_matches_chart_inputs(
            figure, payloads[chart.chart_id]
        ):
            logger.bind(chart_id=chart.chart_id).warning(
                "report_visualization_chart_data_unverified chart_id={} path={} "
                "Plotly trace 数值未能与 chart-input 数值列对应，继续交付。",
                chart.chart_id,
                chart.interactive_path,
            )


def fallback_plan(
    plan: VisualizationPlanDraft, chart_ids: frozenset[str]
) -> VisualizationPlanDraft:
    """只保留需要回退原始 facts 的图，用于投影 visualizationFacts。"""

    return plan.model_copy(
        update={"charts": tuple(chart for chart in plan.charts if chart.chart_id in chart_ids)}
    )


__all__ = [
    "CHART_INPUT_SCHEMA",
    "ChartInputError",
    "ChartInputFile",
    "ChartInputMaterialization",
    "bound_fact_identities",
    "fallback_plan",
    "materialize_chart_inputs",
    "parse_data_path",
    "plotly_trace_matches_chart_inputs",
    "prepare_chart_inputs",
    "verify_plotly_chart_inputs",
]
