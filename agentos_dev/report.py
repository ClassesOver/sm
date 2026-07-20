import json
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Any

import pandas as pd
from agno.run import RunContext
from agno.tools.function import Function
from agno.tools.pandas import PandasTools

from .workspace import WorkspaceError, WorkspaceService

MAX_DATASET_ROWS = 100_000
MAX_DATASET_COLUMNS = 100
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_RESULT_BYTES = 32 * 1024
MAX_CHART_POINTS = 1000
MAX_PIE_CATEGORIES = 20
SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".json", ".jsonl"}
AGGREGATIONS = {"count", "sum", "avg", "min", "max"}
CHART_TYPES = {"bar", "line", "scatter", "pie", "histogram", "box"}


def _thread(run_context: RunContext | None) -> str:
    if not run_context or not run_context.session_id:
        raise WorkspaceError("报表工具需要绑定对话的运行上下文")
    return run_context.session_id


def _ensure_columns(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [str(value) for value in frame.columns]
    if len(set(columns)) != len(columns):
        raise WorkspaceError("数据集字段名称转为文本后存在重复")
    frame.columns = columns
    if len(frame.index) > MAX_DATASET_ROWS:
        raise WorkspaceError("数据集超过 100000 行")
    if len(frame.columns) > MAX_DATASET_COLUMNS:
        raise WorkspaceError("数据集超过 100 列")
    expanded = int(frame.memory_usage(index=True, deep=True).sum())
    if expanded > MAX_EXPANDED_BYTES:
        raise WorkspaceError("数据集展开内存超过 128 MiB")
    return frame


@contextmanager
def _load_frames(
    service: WorkspaceService,
    thread: str,
    paths: list[str],
    sheet: str | int | None = None,
):
    toolkit = PandasTools(
        enable_create_pandas_dataframe=True,
        enable_run_dataframe_operation=False,
    )
    with tempfile.TemporaryDirectory(prefix="agui-report-") as directory:
        frames: list[pd.DataFrame] = []
        try:
            for index, path in enumerate(paths):
                suffix = PurePosixPath(path).suffix.lower()
                if suffix not in SUPPORTED_SUFFIXES:
                    raise WorkspaceError("报表仅支持 CSV、XLSX、JSON 和 JSONL 文件")
                content, _mime_type = service.file_bytes(thread, path)
                local_path = PurePosixPath(directory) / (f"dataset-{index}{suffix}")
                with open(str(local_path), "wb") as output:
                    output.write(content)
                function_name = {
                    ".csv": "read_csv",
                    ".xlsx": "read_excel",
                    ".json": "read_json",
                    ".jsonl": "read_json",
                }[suffix]
                parameters: dict[str, Any]
                if suffix == ".csv":
                    parameters = {"filepath_or_buffer": str(local_path)}
                elif suffix == ".xlsx":
                    parameters = {"io": str(local_path)}
                    if sheet is not None:
                        parameters["sheet_name"] = sheet
                else:
                    parameters = {"path_or_buf": str(local_path)}
                    if suffix == ".jsonl":
                        parameters["lines"] = True
                name = f"dataset_{index}"
                toolkit.create_pandas_dataframe(name, function_name, parameters)
                frame = toolkit.dataframes.get(name)
                if frame is None:
                    # PandasTools intentionally does not retain empty frames.
                    loader = getattr(pd, function_name)
                    frame = loader(**parameters)
                    toolkit.dataframes[name] = frame
                frames.append(_ensure_columns(frame))
            yield frames
        finally:
            toolkit.dataframes.clear()
            frames.clear()


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _bounded(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    if len(encoded) <= MAX_RESULT_BYTES:
        return payload
    result = dict(payload, truncated=True)
    for key in ("rows", "columns", "sample"):
        values = result.get(key)
        if not isinstance(values, list):
            continue
        values = list(values)
        result[key] = values
        while (
            values
            and len(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
            > MAX_RESULT_BYTES
        ):
            values.pop()
    if (
        len(
            json.dumps(
                result,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        > MAX_RESULT_BYTES
    ):
        raise WorkspaceError("报表工具结果超过 32 KiB")
    return result


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame.columns:
        raise WorkspaceError(f"数据集不存在字段：{name}")
    return frame[name]


def _validate_dimensions(frame: pd.DataFrame, dimensions: list[str]) -> None:
    if not isinstance(dimensions, list) or len(dimensions) > 2:
        raise WorkspaceError("分组维度最多 2 个")
    if len(set(dimensions)) != len(dimensions):
        raise WorkspaceError("分组维度不能重复")
    for name in dimensions:
        _column(frame, name)


def _metric_spec(frame: pd.DataFrame, metrics: list[dict[str, str]]):
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= 5:
        raise WorkspaceError("聚合指标必须为 1 至 5 个")
    result = []
    aliases = set()
    for metric in metrics:
        if not isinstance(metric, dict) or set(metric) != {"field", "aggregation"}:
            raise WorkspaceError("聚合指标格式无效")
        field = metric["field"]
        aggregation = metric["aggregation"]
        series = _column(frame, field)
        if aggregation not in AGGREGATIONS:
            raise WorkspaceError(f"不支持的聚合方式：{aggregation}")
        if aggregation in {"sum", "avg"} and not pd.api.types.is_numeric_dtype(series):
            raise WorkspaceError(f"字段 {field} 不是数值类型")
        alias = f"{field}:{aggregation}"
        if alias in aliases:
            raise WorkspaceError("聚合指标不能重复")
        aliases.add(alias)
        result.append((alias, field, "mean" if aggregation == "avg" else aggregation))
    return result


def _group_frame(
    frame: pd.DataFrame,
    dimensions: list[str],
    metrics: list[dict[str, str]],
) -> pd.DataFrame:
    _validate_dimensions(frame, dimensions)
    specs = _metric_spec(frame, metrics)
    named = {
        alias: pd.NamedAgg(column=field, aggfunc=aggregation) for alias, field, aggregation in specs
    }
    if dimensions:
        return frame.groupby(dimensions, dropna=False, observed=True).agg(**named).reset_index()
    values = {alias: getattr(frame[field], aggregation)() for alias, field, aggregation in specs}
    return pd.DataFrame([values])


def report_tools(service: WorkspaceService) -> list[Function]:
    def profile_dataset(
        path: str,
        sheet: str | int | None = None,
        run_context: RunContext | None = None,
    ):
        """概览当前对话工作区中的 CSV、XLSX、JSON 或 JSONL 数据集。"""
        with _load_frames(service, _thread(run_context), [path], sheet=sheet) as frames:
            frame = frames[0]
            columns = []
            for name in frame.columns:
                series = frame[name]
                item: dict[str, Any] = {
                    "name": name,
                    "dtype": str(series.dtype),
                    "nullCount": int(series.isna().sum()),
                    "uniqueCount": int(series.nunique(dropna=True)),
                }
                if pd.api.types.is_numeric_dtype(series):
                    item.update(
                        {
                            "min": None if series.dropna().empty else float(series.min()),
                            "max": None if series.dropna().empty else float(series.max()),
                            "mean": None if series.dropna().empty else float(series.mean()),
                        }
                    )
                columns.append(item)
            return _bounded(
                {
                    "path": path,
                    "rowCount": len(frame.index),
                    "columnCount": len(frame.columns),
                    "memoryBytes": int(frame.memory_usage(index=True, deep=True).sum()),
                    "columns": columns,
                    "sample": _records(frame.head(10)),
                }
            )

    def group_dataset(
        path: str,
        dimensions: list[str],
        metrics: list[dict[str, str]],
        run_context: RunContext | None = None,
    ):
        """按最多两个维度和五个语义化指标聚合当前对话的数据集。"""
        with _load_frames(service, _thread(run_context), [path]) as frames:
            result = _group_frame(frames[0], dimensions, metrics)
            return _bounded(
                {
                    "path": path,
                    "dimensions": dimensions,
                    "metrics": metrics,
                    "rowCount": len(result.index),
                    "rows": _records(result),
                }
            )

    def pivot_dataset(
        path: str,
        rows: list[str],
        columns: list[str],
        value: str,
        aggregation: str,
        run_context: RunContext | None = None,
    ):
        """用受控聚合方式创建当前对话数据集的透视结果。"""
        with _load_frames(service, _thread(run_context), [path]) as frames:
            frame = frames[0]
            if (
                not isinstance(rows, list)
                or not isinstance(columns, list)
                or not rows
                or not columns
            ):
                raise WorkspaceError("透视表必须提供行维度和列维度")
            if len(rows) > 2 or len(columns) > 2:
                raise WorkspaceError("透视表行维度和列维度各最多 2 个")
            for name in rows + columns + [value]:
                _column(frame, name)
            if aggregation not in AGGREGATIONS:
                raise WorkspaceError("不支持的透视聚合方式")
            if aggregation in {"sum", "avg"} and not pd.api.types.is_numeric_dtype(frame[value]):
                raise WorkspaceError("透视值字段不是数值类型")
            result = pd.pivot_table(
                frame,
                index=rows,
                columns=columns,
                values=value,
                aggfunc="mean" if aggregation == "avg" else aggregation,
                observed=True,
            ).reset_index()
            result.columns = [
                " / ".join(str(part) for part in name if str(part))
                if isinstance(name, tuple)
                else str(name)
                for name in result.columns
            ]
            return _bounded(
                {
                    "path": path,
                    "rowCount": len(result.index),
                    "rows": _records(result),
                }
            )

    def concat_datasets(
        paths: list[str],
        source_labels: list[str],
        run_context: RunContext | None = None,
    ):
        """显式纵向合并结构完全一致的数据集，并标注各行来源。"""
        if not isinstance(paths, list) or not 2 <= len(paths) <= 5:
            raise WorkspaceError("纵向合并必须选择 2 至 5 个数据集")
        if not isinstance(source_labels, list) or len(source_labels) != len(paths):
            raise WorkspaceError("每个数据集都必须提供来源标签")
        thread = _thread(run_context)
        with _load_frames(service, thread, paths) as frames:
            expected = list(frames[0].columns)
            if "_source" in expected or any(
                list(frame.columns) != expected for frame in frames[1:]
            ):
                raise WorkspaceError("仅支持字段结构和顺序完全一致的数据集纵向合并")
            labeled = []
            for frame, label in zip(frames, source_labels):
                item = frame.copy()
                item.insert(0, "_source", str(label)[:120])
                labeled.append(item)
            result = _ensure_columns(pd.concat(labeled, ignore_index=True))
            path = f"reports/data/{uuid.uuid4()}.jsonl"
            content = result.to_json(orient="records", lines=True, force_ascii=False).encode(
                "utf-8"
            )
            service.upload(thread, path, content)
            return _bounded(
                {
                    "path": path,
                    "rowCount": len(result.index),
                    "columnCount": len(result.columns),
                    "sourceLabels": source_labels,
                }
            )

    def generate_chart(
        path: str,
        chart_type: str,
        x: str,
        y: str | None = None,
        group: str | None = None,
        aggregation: str | None = None,
        title: str | None = None,
        run_context: RunContext | None = None,
    ):
        """为当前对话数据集生成 PNG 和独立 HTML 图表产物。"""
        if chart_type not in CHART_TYPES:
            raise WorkspaceError("不支持的图表类型")
        thread = _thread(run_context)
        with _load_frames(service, thread, [path]) as frames:
            frame = frames[0]
            selected = [name for name in (x, y, group) if name]
            for name in selected:
                _column(frame, name)
            plot_frame = frame[selected].copy()
            if chart_type in {"bar", "line", "scatter"} and not y:
                raise WorkspaceError("柱状图、折线图和散点图必须提供 y 字段")
            if aggregation:
                if (
                    aggregation not in AGGREGATIONS
                    or not y
                    or chart_type in {"scatter", "histogram", "box"}
                ):
                    raise WorkspaceError("该图表不支持所选聚合方式")
                plot_frame = _group_frame(
                    plot_frame,
                    [x] + ([group] if group else []),
                    [{"field": y, "aggregation": aggregation}],
                ).rename(columns={f"{y}:{aggregation}": y})
            if chart_type in {"bar", "line"} and group and not aggregation:
                if bool(plot_frame.duplicated([x, group]).any()):
                    raise WorkspaceError("分组图存在重复坐标，请指定聚合方式")
            if chart_type == "pie":
                if y:
                    if not pd.api.types.is_numeric_dtype(plot_frame[y]):
                        raise WorkspaceError("饼图数值字段不是数值类型")
                    plot_frame = (
                        plot_frame.groupby(
                            x,
                            dropna=False,
                            observed=True,
                        )[y]
                        .sum()
                        .reset_index()
                    )
                else:
                    plot_frame = (
                        plot_frame.groupby(
                            x,
                            dropna=False,
                            observed=True,
                        )
                        .size()
                        .reset_index(name="_count")
                    )
                    y = "_count"
                if len(plot_frame.index) > MAX_PIE_CATEGORIES:
                    raise WorkspaceError("饼图分类超过 20 个")
            if len(plot_frame.index) > MAX_CHART_POINTS:
                raise WorkspaceError("图表绘制点超过 1000 个")

            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import plotly.express as px

            if chart_type == "histogram":
                html_figure = px.histogram(plot_frame, x=y or x, title=title)
            elif chart_type == "box":
                html_figure = px.box(plot_frame, x=group, y=y or x, title=title)
            elif chart_type == "pie":
                html_figure = px.pie(plot_frame, names=x, values=y, title=title)
            else:
                html_factory = {
                    "bar": px.bar,
                    "line": px.line,
                    "scatter": px.scatter,
                }[chart_type]
                html_figure = html_factory(plot_frame, x=x, y=y, color=group, title=title)

            identifier = str(uuid.uuid4())
            png_path = f"reports/{identifier}.png"
            html_path = f"reports/{identifier}.html"
            figure, axis = plt.subplots(figsize=(9, 5.5))
            try:
                if chart_type in {"bar", "line"}:
                    if group:
                        table = plot_frame.pivot(index=x, columns=group, values=y)
                        table.plot(kind=chart_type, ax=axis)
                    else:
                        plot_frame.plot(x=x, y=y, kind=chart_type, ax=axis, legend=False)
                elif chart_type == "scatter":
                    if group:
                        for label, values in plot_frame.groupby(group, dropna=False):
                            axis.scatter(values[x], values[y], label=str(label))
                        axis.legend()
                    else:
                        axis.scatter(plot_frame[x], plot_frame[y])
                elif chart_type == "pie":
                    plot_frame.set_index(x)[y].plot(kind="pie", ax=axis, ylabel="")
                elif chart_type == "histogram":
                    plot_frame[y or x].plot(kind="hist", ax=axis)
                else:
                    plot_frame.boxplot(column=y or x, by=group, ax=axis)
                axis.set_title((title or "数据图表")[:160])
                figure.tight_layout()
                with tempfile.TemporaryDirectory(prefix="agui-chart-") as directory:
                    local_png = f"{directory}/chart.png"
                    figure.savefig(local_png, format="png", dpi=144)
                    with open(local_png, "rb") as source:
                        png = source.read()
            finally:
                plt.close(figure)
            html = html_figure.to_html(
                full_html=True,
                include_plotlyjs=True,
            ).encode("utf-8")
            service.upload(thread, png_path, png)
            try:
                service.upload(thread, html_path, html)
            except Exception:
                service.delete_file(thread, png_path)
                raise
            return _bounded(
                {
                    "sourcePath": path,
                    "chartType": chart_type,
                    "pointCount": len(plot_frame.index),
                    "pngPath": png_path,
                    "htmlPath": html_path,
                }
            )

    return [
        Function(name="pandas_profile_dataset", entrypoint=profile_dataset),
        Function(name="pandas_group_dataset", entrypoint=group_dataset),
        Function(name="pandas_pivot_dataset", entrypoint=pivot_dataset),
        Function(name="pandas_concat_datasets", entrypoint=concat_datasets),
        Function(name="pandas_generate_chart", entrypoint=generate_chart),
    ]
