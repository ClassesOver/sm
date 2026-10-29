"""按已校验的图表数据绑定预物化统一表格输入（chart-input/v1）。

宿主只做确定性的形状转换：按 descriptor 声明的 dataPath 取值，统一成
``columns + rows``，不计算任何业务指标。绑定不在本轮签发目录中或形状不符
时，该图整体回退为原始 facts 路径并软告警，其余图照常物化。
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from typing import Any, Protocol

from loguru import logger

from .phase_models import ChartDataBinding, ChartDraft, VisualizationPlanDraft

CHART_INPUT_SCHEMA = "chart-input/v1"
CHART_INPUT_PREVIEW_ROWS = 3
_PATH_TOKEN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")
_MAX_CHART_INPUT_BYTES = 8 * 1024 * 1024


def ranked_detail_scope(data_path: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"metrics\[\d+\]\.(?:topGroups|bottomGroups)", data_path):
        return None
    return {
        "coverage": "ranked_subset",
        "grain": "complete_dimension_combination",
        "canRepresentFullDistribution": False,
        "meaning": "完整维度组合的排序明细子集，不能作为院区、科室或类别的完整汇总；"
        "构成和贡献分析应使用对应粒度、期间的完整分组补证，并与同范围总额对账。",
    }


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
    missing = [name for name in fields if name not in columns]
    if missing:
        raise ChartInputError(f"绑定字段不在 columns 中：{missing}")
    selected = list(fields) if fields else list(columns)
    positions = [columns.index(name) for name in selected]
    width = len(columns)
    projected_rows: list[list[Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != width:
            raise ChartInputError("rows 与 columns 不等长")
        projected = [row[index] for index in positions]
        if not all(_is_scalar(value) for value in projected):
            raise ChartInputError("rows 只能包含标量")
        projected_rows.append(projected)
    return selected, projected_rows


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
            # findings[i].rows 的 descriptor.fields 就是 columns，绑定字段必须全部存在。
            columns, rows = _columns_rows_table(parent.get("columns"), value, fields)
            return columns, rows, parent.get("columnMeta")
    if isinstance(value, Mapping) and "columns" in value and "rows" in value:
        # findings[i] 的 descriptor.fields 是 finding 对象键（name/columns/rows…），
        # 不是表格列名，因此不按列名校验。
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
        column_meta = None
        # periodValues.value inherits the exact signed metric unit, never a name/title guess.
        if (len(tokens) == 3 and tokens[0] == 'metrics' and isinstance(tokens[1], int)
                and tokens[2] == 'periodValues' and 'value' in fields):
            metric = _navigate(document, tokens[:-1])
            unit = metric.get('unit')
            if isinstance(unit, str) and unit.strip():
                column_meta = {'value': {'unit': unit}}
                if isinstance(metric.get('isPercent'), bool):
                    column_meta['value']['isPercent'] = metric['isPercent']
        return fields, rows, column_meta
    if isinstance(value, Mapping):
        missing = [name for name in fields if name not in value]
        nested = [name for name in fields if name in value and not _is_scalar(value[name])]
        if missing or nested:
            # 绑定字段缺失或是嵌套结构时不能静默丢列，整图回退原始 facts。
            raise ChartInputError(f"对象绑定字段缺失或非标量：{missing + nested}")
        return fields, [[value[name] for name in fields]], None
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
    """文件名与 chartId 一一对应：改写或截断时追加完整 chartId 的摘要。"""

    name = _UNSAFE_NAME.sub("-", chart_id).strip("-.")
    if name and name == chart_id and len(name) <= 80:
        return name
    digest = hashlib.sha256(chart_id.encode("utf-8")).hexdigest()[:12]
    return f"{(name or 'chart')[:80]}-{digest}"


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
        scope = ranked_detail_scope(binding.data_path)
        if scope is not None:
            payload["dataScope"] = scope
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
            # B3：文件身份随 entry 提交链路上报，由服务端重验后冻结进
            # AnalysisChart.plotDataFiles，形成图片↔作图数据证据链。
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "columns": columns,
            "rowCount": len(rows),
            "nullableColumns": nullable,
            "preview": rows[:CHART_INPUT_PREVIEW_ROWS],
        }
        if "columnMeta" in payload:
            entry["columnMeta"] = payload["columnMeta"]
        if "dataScope" in payload:
            entry["dataScope"] = payload["dataScope"]
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
    names = [_safe_name(chart.chart_id) for chart in plan.charts]
    if len(names) != len(set(names)):
        # 计划校验已保证 chartId 唯一；文件名仍冲突说明映射失效，整体不物化。
        logger.warning("report_visualization_chart_input_name_conflict")
        return ChartInputMaterialization(
            fallback_chart_ids=frozenset(chart.chart_id for chart in plan.charts)
        )
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
        materialized = materialize_chart_inputs(plan, facts, documents, output_root=output_root)
        for item in materialized.files:
            await workspace.awrite_bytes(thread_id, item.path, item.content, overwrite=True)
    except Exception as error:  # noqa: BLE001 - 物化是优化路径，失败回退原始 facts
        logger.bind(error_type=type(error).__name__).warning(
            "report_visualization_chart_inputs_unavailable error={}", str(error)[:300]
        )
        return None
    return materialized


def _decode_bdata(values: Mapping[str, Any]) -> list[float | None]:
    """解码 Plotly 6 write_json 的 typed array（{dtype, bdata, shape?}）。"""

    try:
        import numpy as np

        dtype = np.dtype(values["dtype"])
        if dtype.kind not in "iuf":
            return [math.nan]
        array = np.frombuffer(base64.b64decode(values["bdata"], validate=True), dtype=dtype)
        if values.get("shape") is not None and str(values["shape"]).strip() != str(len(array)):
            return [math.nan]  # Multi-dimensional axes need a registered grid transform.
        return [None if np.isnan(item) else float(item) for item in array.ravel()]
    except Exception:  # noqa: BLE001 - 无法解码时核对失败，由调用方软告警
        return [math.nan]


def _numbers(values: Any) -> list[float | None] | None:
    """保留数值数组的位置；纯分类标签返回 None，混合非法值使核对失败。"""
    if isinstance(values, Mapping) and "bdata" in values and "dtype" in values:
        return _decode_bdata(values)
    if not isinstance(values, (list, tuple)):
        return None
    flat: list[float | None] = []
    numeric = False
    for value in values:
        if isinstance(value, (list, tuple)):
            return [math.nan]  # Flattening changes point identities.
        elif value is None:
            numeric = True
            flat.append(None)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = True
            try:
                converted = float(value)
            except (OverflowError, ValueError):
                return [math.nan]
            flat.append(None if math.isnan(converted) else converted)
        else:
            flat.append(math.nan)
    return flat if numeric or not values else None


def _close(left: float, right: float) -> bool:
    # Display rounding is an absolute decimal-place operation. A relative
    # tolerance would approve, for example, 100500 in place of 100000.
    return (
        math.isfinite(left)
        and math.isfinite(right)
        and any(
            abs(left - candidate) <= math.ulp(left) + math.ulp(candidate)
            for candidate in (right, *_display_roundings(right))
        )
    )


def _display_roundings(value: float) -> tuple[float, ...]:
    # 图上标注既可能按内置 round（银行家舍入、二进制尾差：2.675 → 2.67），也可能与正文
    # 一样按十进制四舍五入（2.675 → 2.68）；两种写法都是对同一来源值的合法显示舍入。
    if not math.isfinite(value):
        return ()
    exact = Decimal(repr(value))
    # 浮点上限约 1.8e308，保留 6 位小数需要三百余位有效数字；默认 28 位精度会抛 InvalidOperation。
    with localcontext() as context:
        context.prec = 400
        return tuple(
            candidate
            for places in range(7)
            for candidate in (
                round(value, places),
                float(exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)),
            )
        )


def _axis_scales(
    figure: Mapping[str, Any], trace: Mapping[str, Any], key: str, metadata: Any
) -> tuple[float, ...]:
    """Conversions require a frozen source unit and an explicit target axis."""
    from ...units import unit_conversion_scale

    source = metadata.get("unit") if isinstance(metadata, Mapping) else None
    if key not in {"x", "y"}:
        return (1.0,)
    axis_name = trace.get(key + "axis", key)
    if not isinstance(axis_name, str) or re.fullmatch(key + r"\d*", axis_name) is None:
        return ()
    layout = figure.get("layout") or {}
    if not isinstance(layout, Mapping):
        return ()
    axis = layout.get(key + "axis" + axis_name[1:], {})
    if not isinstance(axis, Mapping):
        return ()
    if isinstance(axis.get("tickformat"), str) and "%" in axis["tickformat"]:
        if re.fullmatch(r",?(?:\.\d{1,2})?%", axis["tickformat"]) is None:
            return ()
        return (0.01,) if source == "%" else (1.0,) if source == "1" else ()
    title = axis.get("title") or ""
    title = title.get("text", "") if isinstance(title, Mapping) else title
    if not isinstance(title, str):
        return ()
    target = re.findall(r"[（(]\s*(亿元|万元|元|万人次|人次|%)\s*[）)]", title)
    if not target:
        return (1.0,)
    if len(set(target)) != 1:
        return ()
    if not isinstance(source, str):
        return ()
    if source == "1" and target[0] == "%":
        return (100.0,)
    scale = unit_conversion_scale(source, target[0])
    return (float(scale),) if scale is not None else ()


def _array_matches(values: Any, column: list[Any], scales: tuple[float, ...]) -> bool:
    numbers = _numbers(values)
    candidates = _numbers(column)
    if numbers is not None:
        return candidates is not None and any(
            len(numbers) == len(candidates)
            and all(
                value is candidate
                if value is None or candidate is None
                else _close(value, candidate * scale)
                for value, candidate in zip(numbers, candidates, strict=True)
            )
            for scale in scales
        )
    return isinstance(values, (list, tuple)) and list(values) == column


def plotly_trace_matches_chart_inputs(
    figure: Mapping[str, Any], chart_inputs: Sequence[Mapping[str, Any]]
) -> bool:
    """Match complete label/value pairs to the same frozen table and row order.

    This verifies registered arrays, not image pixels, title semantics or the
    upstream business population. Unsupported transformations remain unknown.
    """
    tables = []
    for item in chart_inputs:
        names = item.get("columns")
        rows = item.get("rows")
        if (
            not isinstance(names, list)
            or not names
            or not all(isinstance(name, str) for name in names)
            or len(set(names)) != len(names)
            or not isinstance(rows, list)
            or not rows
            or any(
                not isinstance(row, list)
                or len(row) != len(names)
                or any(not _is_scalar(value) for value in row)
                or any(isinstance(value, float) and not math.isfinite(value) for value in row)
                for row in rows
            )
        ):
            continue
        tables.append(
            (
                names,
                [[row[position] for row in rows] for position in range(len(names))],
                item.get("columnMeta") or {},
                item.get("dataScope") or {},
            )
        )
    traces = figure.get("data")
    if not tables or not isinstance(traces, (list, tuple)) or not traces:
        return False
    layout = figure.get("layout") or {}
    if not isinstance(layout, Mapping) or layout.get("barnorm"):
        return False
    for trace in traces:
        if not isinstance(trace, Mapping) or "z" in trace:
            return False  # Grids need an explicitly registered row/column transform.
        if (
            trace.get("type", "scatter")
            not in {"scatter", "scattergl", "bar", "pie", "scatterpolar", "barpolar"}
            or trace.get("groupnorm")
            or trace.get("histnorm")
            or trace.get("transforms")
        ):
            return False
        groups = [
            tuple(key for key in pair if key in trace)
            for pair in (("x", "y"), ("labels", "values"), ("theta", "r"))
        ]
        groups = [group for group in groups if group]
        if len(groups) != 1:
            return False
        keys = groups[0]
        numeric_keys = [key for key in keys if _numbers(trace[key]) is not None]
        measure = (
            "values"
            if "values" in keys
            else "r"
            if "r" in keys
            else "x"
            if trace.get("orientation") == "h" or "y" not in keys
            else "y"
        )
        if measure not in numeric_keys or not any(
            value is not None and math.isfinite(value) for value in (_numbers(trace[measure]) or ())
        ):
            return False
        matched = False
        for names, columns, metadata, scope in tables:
            if (
                measure == "values"
                and isinstance(scope, Mapping)
                and (
                    scope.get("coverage") == "ranked_subset"
                    or scope.get("canRepresentFullDistribution") is False
                )
            ):
                continue  # A pie normalizes its subset into a false full distribution.
            if len(keys) == 1 and len(columns) != 1:
                continue  # Missing category/period identity cannot be inferred.
            candidates = {
                key: [
                    position
                    for position, column in enumerate(columns)
                    if _array_matches(
                        trace[key],
                        column,
                        _axis_scales(
                            figure,
                            trace,
                            key,
                            metadata.get(names[position])
                            if isinstance(metadata, Mapping)
                            else None,
                        ),
                    )
                ]
                for key in keys
            }
            assignments = (
                [(position,) for position in candidates[keys[0]]]
                if len(keys) == 1
                else [
                    (left, right)
                    for left in candidates[keys[0]]
                    for right in candidates[keys[1]]
                    if left != right
                ]
            )
            for assignment in assignments:
                # Numeric annotations must belong to this trace's own data,
                # rather than borrowing an unrelated input column/table.
                text = _numbers(trace.get("text"))
                if text is not None and not any(
                    _array_matches(
                        trace["text"],
                        columns[position],
                        _axis_scales(
                            figure,
                            trace,
                            key,
                            metadata.get(names[position])
                            if isinstance(metadata, Mapping)
                            else None,
                        ),
                    )
                    for key, position in zip(keys, assignment, strict=True)
                    if key in numeric_keys
                ):
                    continue
                if not any(
                    any(
                        value is not None and math.isfinite(value)
                        for value in (_numbers(trace[key]) or ())
                    )
                    for key in numeric_keys
                ):
                    continue
                matched = True
                break
            if matched:
                break
        if not matched:
            return False
    return True


async def verify_plotly_chart_inputs(
    plan: VisualizationPlanDraft,
    materialized: ChartInputMaterialization,
    workspace: Any,
    *,
    thread_id: str,
) -> dict[str, dict[str, str]]:
    """Plotly 产物与 chart-input 数值核对；无法完整对应时记软告警。"""

    payloads: dict[str, list[dict[str, Any]]] = {}
    results: dict[str, dict[str, str]] = {}
    for item in materialized.files:
        try:
            decoded = json.loads(item.content)
        except ValueError:
            continue
        if isinstance(decoded, dict):
            payloads.setdefault(str(decoded.get("chartId")), []).append(decoded)
    for chart in plan.charts:
        if chart.interactive_path is None:
            results[chart.chart_id] = {"status": "unknown", "reason": "static_image_not_evaluated"}
            continue
        reason = "chart_input_unavailable"
        if chart.chart_id not in payloads:
            results[chart.chart_id] = {"status": "unknown", "reason": reason}
            continue
        try:
            content, _mime = await workspace.afile_bytes(thread_id, chart.interactive_path)
            figure = json.loads(content)
            reason = "chart_data_unverified"
            matched = isinstance(figure, Mapping) and plotly_trace_matches_chart_inputs(
                figure, payloads[chart.chart_id]
            )
        except Exception:  # noqa: BLE001 - 核对只是软告警
            matched = False
            reason = "chart_check_failed"
        results[chart.chart_id] = {
            "status": "verified" if matched else "unknown",
            "reason": "registered_arrays_match" if matched else reason,
        }
        if not matched:
            logger.bind(chart_id=chart.chart_id).warning(
                "report_visualization_chart_data_unverified chart_id={} path={} "
                "Plotly 类别、数值或单位未能与冻结 chart-input 对应，继续交付。",
                chart.chart_id,
                chart.interactive_path,
            )
    return results

def chart_input_root_for(chart_output_root: str) -> str:
    """chart-input 根目录：chartOutputRoot 的只读兄弟目录。

    B3 起供提交工具做路径安全校验（作图数据文件必须落在该目录内），
    与 analysis.py 的物化入口共用同一推导，防止两处口径漂移。
    """

    marker = "/analysis/charts/"
    if marker in chart_output_root:
        return chart_output_root.replace(marker, "/analysis/chart-inputs/", 1)
    return f"{chart_output_root.rstrip('/')}-chart-inputs"


def verify_static_chart_inputs_referenced(
    plan: Any,
    materialized: ChartInputMaterialization,
    script_source: str,
) -> list[str]:
    """静态（matplotlib）图是否引用了预物化 chart-input（软告警依据）。

    回退图（绑定失败走原始 facts）不检查。返回未引用其作图数据的
    chartId 列表；由调用方记软告警，不阻断交付。
    """

    referenced_paths: dict[str, list[str]] = {}
    for item in materialized.files:
        try:
            decoded = json.loads(item.content)
        except ValueError:
            continue
        chart_id = str(decoded.get("chartId"))
        referenced_paths.setdefault(chart_id, []).append(item.path)
    unresolved: list[str] = []
    for chart in plan.charts:
        if chart.interactive_path is not None:
            continue  # Plotly 图由数值核对负责
        if chart.chart_id in materialized.fallback_chart_ids:
            continue
        paths = referenced_paths.get(chart.chart_id)
        if not paths:
            continue
        tokens = {path for path in paths} | {Path(path).stem for path in paths}
        if not any(token in script_source for token in tokens):
            unresolved.append(chart.chart_id)
    return unresolved


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
