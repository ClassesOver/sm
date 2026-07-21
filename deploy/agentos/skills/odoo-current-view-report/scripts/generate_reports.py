#!/usr/bin/env python3
import hashlib
import html
import json
import math
import os
import re
import shutil
import sys
import tempfile
import textwrap
import uuid
from pathlib import Path, PurePosixPath

SCRIPT_PROTOCOL_VERSION = "agui.odoo.report.skill.v1"
DATASET_VERSION = "agui.report.dataset.v1"
CONFIG_VERSION = "agui.report.config.v1"
PDF_MIME_TYPE = "application/pdf"
MAX_ROWS = 100_000
MAX_COLUMNS = 30
MAX_PARTS = 16
MAX_PART_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_CONFIG_BYTES = 256 * 1024
MAX_GROUPS = 5_000
MAX_CHART_POINTS = 100
AGGREGATIONS = {"count", "sum", "avg", "min", "max"}
CHART_TYPES = {"bar", "line", "pie"}
SECTION_TYPES = {"overview", "notes", "chart", "analysis"}
NUMERIC_TYPES = {"float", "integer", "monetary"}
ORDERABLE_TYPES = NUMERIC_TYPES | {"date", "datetime"}
SCOPE_LABELS = {
    "domain": "当前列表完整范围",
    "selected": "当前列表与勾选记录交集",
}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReportFailure(ValueError):
    pass


def _artifact(report_id):
    return {
        "kind": "pdf",
        "path": f"报表/生成结果/{report_id}/分析报告.pdf",
        "mimeType": PDF_MIME_TYPE,
    }


def capabilities():
    return {
        "protocol": SCRIPT_PROTOCOL_VERSION,
        "operation": "capabilities",
        "ok": True,
        "operations": ["capabilities", "validate", "render"],
        "inputVersions": {"config": CONFIG_VERSION, "dataset": DATASET_VERSION},
        "dataBinding": "workspace-manifest",
        "artifacts": [
            {
                "kind": "pdf",
                "filename": "分析报告.pdf",
                "mimeType": PDF_MIME_TYPE,
            }
        ],
        "chartTypes": sorted(CHART_TYPES),
        "sectionTypes": ["overview", "notes", "chart", "analysis"],
        "aggregations": sorted(AGGREGATIONS),
        "limits": {
            "rows": MAX_ROWS,
            "columns": MAX_COLUMNS,
            "fragments": MAX_PARTS,
            "fragmentBytes": MAX_PART_BYTES,
            "totalBytes": MAX_TOTAL_BYTES,
        },
    }


def _json_loads(content):
    def reject_constant(value):
        raise ReportFailure(f"JSON 包含非有限数值：{value}")

    try:
        return json.loads(content, parse_constant=reject_constant)
    except (TypeError, UnicodeError, json.JSONDecodeError) as error:
        raise ReportFailure("JSON 文件格式无效") from error


def _uuid(value, label):
    if not isinstance(value, str) or not UUID_RE.fullmatch(value):
        raise ReportFailure(f"{label}不是规范 UUID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError as error:
        raise ReportFailure(f"{label}不是规范 UUID") from error
    return value


def _workspace_path(root, value, label, must_exist=False):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ReportFailure(f"{label}路径格式无效")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise ReportFailure(f"{label}路径越界")
    target = (root / Path(*relative.parts)).resolve()
    if target != root and root not in target.parents:
        raise ReportFailure(f"{label}路径越界")
    if must_exist and (not target.is_file() or target.is_symlink()):
        raise ReportFailure(f"{label}文件不存在或类型无效")
    return target


def _read_limited(path, limit, label):
    size = path.stat().st_size
    if size > limit:
        raise ReportFailure(f"{label}超过大小限制")
    return path.read_bytes()


def _load_config(root, config_value):
    parts = PurePosixPath(config_value).parts
    if len(parts) != 4 or parts[:2] != ("报表", "配置") or parts[3] != "报表配置.json":
        raise ReportFailure("配置路径必须由报表配置工具生成")
    report_id = _uuid(parts[2], "报表 ID")
    path = _workspace_path(root, config_value, "配置", must_exist=True)
    config = _json_loads(_read_limited(path, MAX_CONFIG_BYTES, "配置").decode("utf-8"))
    if not isinstance(config, dict) or set(config) != {
        "version",
        "reportId",
        "manifestPath",
        "datasetHash",
        "title",
        "analysis",
        "chart",
        "presentation",
    }:
        raise ReportFailure("报表配置字段无效")
    if config.get("version") != CONFIG_VERSION or config.get("reportId") != report_id:
        raise ReportFailure("报表配置版本或目录标识无效")
    title = config.get("title")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 160:
        raise ReportFailure("报表标题无效")
    config["title"] = title.strip()
    return config


def _load_manifest(root, config):
    manifest_value = config.get("manifestPath")
    parts = PurePosixPath(str(manifest_value or "")).parts
    if len(parts) != 4 or parts[:2] != ("报表", "原始数据") or parts[3] != "数据集.json":
        raise ReportFailure("数据集清单路径无效")
    dataset_id = _uuid(parts[2], "数据集 ID")
    path = _workspace_path(root, manifest_value, "数据集清单", must_exist=True)
    content = _read_limited(path, MAX_MANIFEST_BYTES, "数据集清单")
    expected_hash = config.get("datasetHash")
    if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
        raise ReportFailure("数据集清单摘要格式无效")
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise ReportFailure("数据集清单摘要不匹配")
    manifest = _json_loads(content.decode("utf-8"))
    if not isinstance(manifest, dict) or manifest.get("version") != DATASET_VERSION:
        raise ReportFailure("数据集清单版本不受支持")
    if manifest.get("datasetId") != dataset_id:
        raise ReportFailure("数据集清单与目录标识不一致")
    if any(key in manifest for key in ("domain", "context", "selectedIds", "rows")):
        raise ReportFailure("数据集清单包含禁止字段")
    row_count = manifest.get("rowCount")
    column_count = manifest.get("columnCount")
    total_size = manifest.get("totalSize")
    if (
        isinstance(row_count, bool)
        or not isinstance(row_count, int)
        or not 0 <= row_count <= MAX_ROWS
    ):
        raise ReportFailure("数据集清单行数无效")
    if (
        isinstance(column_count, bool)
        or not isinstance(column_count, int)
        or not 1 <= column_count <= MAX_COLUMNS
    ):
        raise ReportFailure("数据集清单列数无效")
    if (
        isinstance(total_size, bool)
        or not isinstance(total_size, int)
        or not 0 <= total_size <= MAX_TOTAL_BYTES
    ):
        raise ReportFailure("数据集清单总大小无效")
    fields = manifest.get("fields")
    if not isinstance(fields, list) or len(fields) != column_count:
        raise ReportFailure("数据集字段数量无效")
    names = []
    for field in fields:
        if not isinstance(field, dict):
            raise ReportFailure("数据集字段格式无效")
        name = field.get("name")
        label = field.get("label")
        field_type = field.get("type")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 128
            or not isinstance(label, str)
            or not label
            or len(label) > 160
            or not isinstance(field_type, str)
            or not field_type
        ):
            raise ReportFailure("数据集字段格式无效")
        names.append(name)
    if len(set(names)) != len(names):
        raise ReportFailure("数据集字段不能重复")
    fragments = manifest.get("fragments")
    if not isinstance(fragments, list) or not 1 <= len(fragments) <= MAX_PARTS:
        raise ReportFailure("数据集分片数量无效")
    base = f"报表/原始数据/{dataset_id}/分片"
    validated = []
    for index, fragment in enumerate(fragments, start=1):
        expected_path = f"{base}/数据-{index:04d}.jsonl"
        if not isinstance(fragment, dict) or set(fragment) != {"path", "size", "sha256"}:
            raise ReportFailure("数据集分片清单格式无效")
        size = fragment.get("size")
        digest = fragment.get("sha256")
        if fragment.get("path") != expected_path:
            raise ReportFailure("数据集分片路径或顺序无效")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_PART_BYTES:
            raise ReportFailure("数据集分片大小无效")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ReportFailure("数据集分片摘要无效")
        fragment_path = _workspace_path(root, expected_path, "数据集分片", must_exist=True)
        validated.append((fragment_path, size, digest))
    return manifest, names, validated


def _validate_config(config, manifest):
    fields = {field["name"]: field for field in manifest["fields"]}
    analysis = config.get("analysis")
    chart = config.get("chart")
    presentation = config.get("presentation")
    if not isinstance(analysis, dict) or set(analysis) != {"dimensions", "metrics", "notes"}:
        raise ReportFailure("分析配置格式无效")
    dimensions = analysis.get("dimensions")
    if (
        not isinstance(dimensions, list)
        or not 1 <= len(dimensions) <= 2
        or len(set(dimensions)) != len(dimensions)
        or any(name not in fields for name in dimensions)
    ):
        raise ReportFailure("分析维度无效")
    metrics = analysis.get("metrics")
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= 5:
        raise ReportFailure("分析指标无效")
    aliases = set()
    for metric in metrics:
        if not isinstance(metric, dict) or set(metric) != {"field", "aggregation", "label"}:
            raise ReportFailure("分析指标格式无效")
        field = metric.get("field")
        aggregation = metric.get("aggregation")
        label = metric.get("label")
        if field not in fields or aggregation not in AGGREGATIONS:
            raise ReportFailure("分析指标字段或聚合方式无效")
        if aggregation in {"sum", "avg"} and fields[field].get("type") not in NUMERIC_TYPES:
            raise ReportFailure("非数值字段不能求和或平均")
        if aggregation in {"min", "max"} and fields[field].get("type") not in ORDERABLE_TYPES:
            raise ReportFailure("字段类型不支持最小值或最大值")
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 80:
            raise ReportFailure("指标标签无效")
        alias = f"{field}:{aggregation}"
        if alias in aliases:
            raise ReportFailure("分析指标不能重复")
        aliases.add(alias)
    notes = analysis.get("notes")
    if (
        not isinstance(notes, list)
        or len(notes) > 10
        or any(not isinstance(note, str) or len(note) > 500 for note in notes)
    ):
        raise ReportFailure("分析说明无效")
    if not isinstance(chart, dict) or set(chart) != {"type", "metric", "title"}:
        raise ReportFailure("图表配置格式无效")
    chart_metric = chart.get("metric")
    metric = next(
        (item for item in metrics if f"{item['field']}:{item['aggregation']}" == chart_metric),
        None,
    )
    if chart.get("type") not in CHART_TYPES or metric is None:
        raise ReportFailure("图表类型或指标无效")
    if (
        metric["aggregation"] != "count"
        and fields[metric["field"]].get("type") not in NUMERIC_TYPES
    ):
        raise ReportFailure("图表指标必须是数值结果")
    if not isinstance(chart.get("title"), str) or len(chart["title"].strip()) > 160:
        raise ReportFailure("图表标题无效")
    if not isinstance(presentation, dict) or set(presentation) != {"purpose", "sections"}:
        raise ReportFailure("呈现配置格式无效")
    purpose = presentation.get("purpose")
    sections = presentation.get("sections")
    if not isinstance(purpose, str) or not purpose.strip() or len(purpose.strip()) > 500:
        raise ReportFailure("报表目的无效")
    if (
        not isinstance(sections, list)
        or not 1 <= len(sections) <= len(SECTION_TYPES)
        or len(set(sections)) != len(sections)
        or any(section not in SECTION_TYPES for section in sections)
    ):
        raise ReportFailure("报表章节无效")


def _rows(manifest, field_names, fragments):
    actual_total = 0
    actual_rows = 0
    for path, expected_size, expected_digest in fragments:
        size = 0
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for line in stream:
                size += len(line)
                digest.update(line)
                if not line.strip():
                    raise ReportFailure("数据集分片包含空行")
                if len(line) > MAX_PART_BYTES:
                    raise ReportFailure("数据集存在超大单行")
                row = _json_loads(line.decode("utf-8"))
                if not isinstance(row, dict) or list(row) != field_names:
                    raise ReportFailure("数据集行字段与清单不一致")
                actual_rows += 1
                if actual_rows > MAX_ROWS:
                    raise ReportFailure("数据集超过 100000 行")
                yield row
        if size != expected_size:
            raise ReportFailure("数据集分片大小与清单不一致")
        if digest.hexdigest() != expected_digest:
            raise ReportFailure("数据集分片 SHA-256 校验失败")
        actual_total += size
    if actual_total != manifest["totalSize"]:
        raise ReportFailure("数据集分片总大小与清单不一致")
    if actual_rows != manifest["rowCount"]:
        raise ReportFailure("数据集分片总行数与清单不一致")


def _format_value(value, field_type=None, aggregation=None):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else ("否" if field_type == "boolean" else "—")
    if field_type == "many2one" and isinstance(value, (list, tuple)) and len(value) == 2:
        return str(value[1])
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ReportFailure("报表包含非有限数值")
        if aggregation == "count" or field_type == "integer":
            return f"{value:,.0f}"
        if field_type in {"float", "monetary"} or aggregation in {"sum", "avg"}:
            return f"{value:,.2f}"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _display(value):
    return _format_value(value)


def _metric_state():
    return {"count": 0, "sum": 0.0, "min": None, "max": None}


def _update_metric(state, value, aggregation):
    if value is None:
        return
    state["count"] += 1
    if aggregation in {"sum", "avg"}:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ReportFailure("数值指标包含非有限或非数值内容")
        state["sum"] += value
    if aggregation in {"min", "max"}:
        if isinstance(value, (dict, list)):
            raise ReportFailure("最值指标包含不可排序内容")
        if state["min"] is None or value < state["min"]:
            state["min"] = value
        if state["max"] is None or value > state["max"]:
            state["max"] = value


def _metric_value(state, aggregation):
    if aggregation == "count":
        return state["count"]
    if aggregation == "sum":
        return state["sum"]
    if aggregation == "avg":
        return state["sum"] / state["count"] if state["count"] else None
    return state[aggregation]


def _analyze(config, manifest, field_names, fragments):
    analysis = config["analysis"]
    dimensions = analysis["dimensions"]
    metrics = analysis["metrics"]
    groups = {}
    for row in _rows(manifest, field_names, fragments):
        key = tuple(_display(row.get(name)) for name in dimensions)
        if key not in groups:
            if len(groups) >= MAX_GROUPS:
                raise ReportFailure("分析结果超过 5000 组")
            groups[key] = {
                f"{metric['field']}:{metric['aggregation']}": _metric_state() for metric in metrics
            }
        for metric in metrics:
            alias = f"{metric['field']}:{metric['aggregation']}"
            _update_metric(groups[key][alias], row.get(metric["field"]), metric["aggregation"])
    rows = []
    for key, states in groups.items():
        item = {name: value for name, value in zip(dimensions, key)}
        item["_chart_category"] = " / ".join(key)
        for metric in metrics:
            alias = f"{metric['field']}:{metric['aggregation']}"
            item[alias] = _metric_value(states[alias], metric["aggregation"])
        rows.append(item)
    chart_metric = config["chart"]["metric"]
    rows.sort(
        key=lambda item: (
            item.get(chart_metric)
            if isinstance(item.get(chart_metric), (int, float))
            else float("-inf")
        ),
        reverse=True,
    )
    return rows


def _chart_rows(config, analysis_rows):
    limit = 20 if config["chart"]["type"] == "pie" else MAX_CHART_POINTS
    rows = [
        row for row in analysis_rows if isinstance(row.get(config["chart"]["metric"]), (int, float))
    ]
    return rows[:limit] or [{"_chart_category": "无数据", config["chart"]["metric"]: 0}]


def _compact_number(value):
    absolute = abs(value)
    if absolute >= 100_000_000:
        return f"{value / 100_000_000:.1f}亿"
    if absolute >= 10_000:
        return f"{value / 10_000:.1f}万"
    if absolute >= 1_000:
        return f"{value:,.0f}"
    return f"{value:g}"


def _chart_label(value):
    return "\n".join(textwrap.wrap(str(value), width=10, max_lines=2, placeholder="…") or ["—"])


def _write_png(path, config, analysis_rows):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter
    except ImportError as error:
        raise ReportFailure("运行环境缺少 matplotlib") from error
    plt.rcParams.update(
        {
            "font.sans-serif": ["Noto Sans CJK SC", "Noto Sans CJK JP", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 9,
        }
    )
    rows = _chart_rows(config, analysis_rows)
    labels = [_chart_label(row["_chart_category"]) for row in rows]
    values = [row[config["chart"]["metric"]] for row in rows]
    figure, axis = plt.subplots(figsize=(10, 5.4), facecolor="white")
    try:
        chart_type = config["chart"]["type"]
        if chart_type == "pie":
            if any(value < 0 for value in values):
                raise ReportFailure("饼图指标不能包含负数")
            if not any(values):
                axis.text(0.5, 0.5, "暂无可绘制数据", ha="center", va="center")
                axis.axis("off")
            else:
                axis.pie(
                    values,
                    labels=labels,
                    autopct="%1.1f%%",
                    startangle=90,
                    colors=["#28634A", "#4F7C67", "#8AA295", "#B58A3B", "#7B8794"],
                    wedgeprops={"linewidth": 1, "edgecolor": "white"},
                    textprops={"color": "#263238", "fontsize": 8},
                )
        elif chart_type == "line":
            axis.plot(labels, values, marker="o", linewidth=2.2, color="#28634A")
            axis.fill_between(range(len(values)), values, color="#28634A", alpha=0.08)
            axis.tick_params(axis="x", rotation=25, labelsize=8)
        else:
            bars = axis.bar(labels, values, color="#28634A", width=0.68)
            axis.tick_params(axis="x", rotation=25, labelsize=8)
            if len(values) <= 20:
                axis.bar_label(
                    bars,
                    labels=[_compact_number(value) for value in values],
                    padding=3,
                    fontsize=7.5,
                    color="#43505C",
                )
                axis.margins(y=0.14)
        axis.set_title(
            config["chart"]["title"],
            loc="left",
            pad=16,
            fontsize=14,
            fontweight="bold",
            color="#1F2933",
        )
        if chart_type != "pie":
            axis.set_axisbelow(True)
            axis.yaxis.set_major_formatter(
                FuncFormatter(lambda value, _position: _compact_number(value))
            )
            axis.grid(axis="y", color="#DCE2DF", linewidth=0.7)
            axis.spines[["top", "right", "left"]].set_visible(False)
            axis.spines["bottom"].set_color("#AAB4AF")
            axis.tick_params(axis="y", length=0, colors="#53616C")
        figure.tight_layout()
        figure.savefig(str(path), format="png", dpi=180, facecolor="white", bbox_inches="tight")
    finally:
        plt.close(figure)


def _html_table(headers, rows, numeric_columns=None):
    numeric_columns = set(numeric_columns or [])
    head = "".join(f"<th>{html.escape(str(value))}</th>" for value in headers)
    body = []
    for row in rows:
        cells = []
        for index, value in enumerate(row):
            class_name = ' class="numeric"' if index in numeric_columns else ""
            cells.append(f"<td{class_name}>{html.escape(str(value))}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _report_document(png_path, config, manifest, analysis_rows):
    fields = {field["name"]: field for field in manifest["fields"]}
    metrics = config["analysis"]["metrics"]
    dimension_label = " / ".join(fields[name]["label"] for name in config["analysis"]["dimensions"])
    analysis_headers = [dimension_label] + [metric["label"] for metric in metrics]
    analysis_values = [
        [row["_chart_category"]]
        + [
            _format_value(
                row.get(f"{metric['field']}:{metric['aggregation']}"),
                fields[metric["field"]].get("type"),
                metric["aggregation"],
            )
            for metric in metrics
        ]
        for row in analysis_rows[:50]
    ]
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in config["analysis"]["notes"])
    analysis_table = _html_table(
        analysis_headers,
        analysis_values,
        numeric_columns=range(1, len(analysis_headers)),
    )
    scope_label = SCOPE_LABELS.get(manifest.get("scope"), str(manifest.get("scope") or "—"))
    selected_count = _format_value(manifest.get("selectedCount", 0), "integer")
    row_count = _format_value(manifest["rowCount"], "integer")
    timezone = html.escape(str(manifest.get("timezone") or "UTC"))
    generated_at = html.escape(str(manifest.get("generatedAt") or "—"))
    model_name = html.escape(str(manifest.get("model") or "—"))
    sections = []
    for section in config["presentation"]["sections"]:
        if section == "overview":
            sections.append(
                '<section><h2><span class="section-index">01</span>执行摘要</h2>'
                f'<p class="purpose">{html.escape(config["presentation"]["purpose"])}</p>'
                '<div class="summary-grid">'
                f'<div class="summary-item"><span>数据范围</span><strong>{html.escape(scope_label)}</strong></div>'
                f'<div class="summary-item"><span>数据行数</span><strong>{row_count}</strong></div>'
                f'<div class="summary-item"><span>勾选记录</span><strong>{selected_count}</strong></div>'
                f'<div class="summary-item"><span>业务时区</span><strong>{timezone}</strong></div>'
                "</div></section>"
            )
        elif section == "notes":
            sections.append(
                '<section><h2><span class="section-index">02</span>口径说明</h2>'
                f'<div class="notes"><ul>{notes or "<li>无补充说明</li>"}</ul></div></section>'
            )
        elif section == "chart":
            if png_path is None:
                raise ReportFailure("图表章节缺少渲染资源")
            chart_rows = _chart_rows(config, analysis_rows)
            chart_note = (
                f"图表展示按指标排序后的前 {len(chart_rows)} 项。"
                if len(chart_rows) < len(analysis_rows)
                else f"图表展示全部 {len(chart_rows)} 个分析分组。"
            )
            sections.append(
                '<section><h2><span class="section-index">03</span>趋势与对比</h2>'
                '<figure><img src="图表.png" alt="报表图表">'
                f"<figcaption>{html.escape(chart_note)}</figcaption></figure></section>"
            )
        elif section == "analysis":
            result_note = (
                f"共 {len(analysis_rows):,} 个分析分组，当前表格展示按图表指标排序后的前 50 组。"
                if len(analysis_rows) > 50
                else f"共 {len(analysis_rows):,} 个分析分组。"
            )
            sections.append(
                '<section><h2><span class="section-index">04</span>分析结果</h2>'
                f'<p class="section-note">{result_note}</p>{analysis_table}</section>'
            )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
      <title>{html.escape(config["title"])}</title>
      <meta name="author" content="Odoo">
      <meta name="description" content="{html.escape(config["presentation"]["purpose"], quote=True)}">
      <meta name="generator" content="agui.odoo.report.skill.v1">
      <style>
      @page {{
        size: A4; margin: 18mm 16mm 17mm;
        @top-left {{ content: "ODOO · 标准分析报告"; color: #607069; font-size: 7.5pt; }}
        @top-right {{ content: "内部分析资料"; color: #87938D; font-size: 7.5pt; }}
        @bottom-left {{ content: "生成时间  {generated_at}"; color: #87938D; font-size: 7.5pt; }}
        @bottom-right {{ content: "第 " counter(page) " / " counter(pages) " 页"; color: #607069; font-size: 7.5pt; }}
      }}
      @page:first {{ @top-left {{ content: none; }} @top-right {{ content: none; }} }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; font-family: "Noto Sans CJK SC", "Noto Sans CJK JP", sans-serif; color: #1F2933; font-size: 9.5pt; line-height: 1.55; }}
      .report-header {{ border-top: 4px solid #28634A; padding-top: 9mm; margin-bottom: 8mm; }}
      .eyebrow {{ color: #28634A; font-size: 8pt; font-weight: 700; margin: 0 0 3mm; }}
      h1 {{ margin: 0; font-size: 23pt; line-height: 1.25; font-weight: 700; color: #17212B; }}
      .document-meta {{ margin-top: 4mm; padding-top: 3mm; border-top: 1px solid #DCE2DF; color: #607069; font-size: 8pt; }}
      section {{ margin-top: 8mm; }}
      h2 {{ margin: 0 0 4mm; padding-bottom: 2.5mm; border-bottom: 1px solid #C8D2CD; color: #1F2933; font-size: 13pt; line-height: 1.3; break-after: avoid; }}
      .section-index {{ display: inline-block; margin-right: 3mm; color: #B58A3B; font-size: 8pt; font-weight: 700; vertical-align: middle; }}
      .purpose {{ margin: 0 0 5mm; padding-left: 4mm; border-left: 3px solid #28634A; color: #33414C; font-size: 10.5pt; line-height: 1.7; }}
      .summary-grid {{ display: table; width: 100%; table-layout: fixed; border: 1px solid #DCE2DF; background: #F7F9F8; }}
      .summary-item {{ display: table-cell; padding: 3.2mm; border-right: 1px solid #DCE2DF; vertical-align: top; }}
      .summary-item:last-child {{ border-right: 0; }}
      .summary-item span {{ display: block; color: #718078; font-size: 7.5pt; margin-bottom: 1.2mm; }}
      .summary-item strong {{ display: block; color: #24312B; font-size: 10pt; font-weight: 700; overflow-wrap: anywhere; }}
      .notes {{ padding: 3.5mm 5mm; border-left: 3px solid #B58A3B; background: #FAF8F3; break-inside: avoid; }}
      .notes ul {{ margin: 0; padding-left: 5mm; }} .notes li {{ margin: 1.2mm 0; }}
      figure {{ margin: 0; break-inside: avoid; }}
      img {{ display: block; width: 100%; max-height: 108mm; object-fit: contain; }}
      figcaption, .section-note {{ margin: 2mm 0 3mm; color: #718078; font-size: 7.5pt; }}
      .table-wrap {{ width: 100%; }}
      table {{ border-collapse: collapse; width: 100%; table-layout: fixed; font-size: 8pt; font-variant-numeric: tabular-nums; }}
      thead {{ display: table-header-group; }} tr {{ break-inside: avoid; }}
      th, td {{ border: 1px solid #C8D2CD; padding: 2.2mm 2.4mm; overflow-wrap: anywhere; vertical-align: top; }}
      th {{ background: #E8EFEB; color: #26352E; font-weight: 700; text-align: left; }}
      tbody tr:nth-child(even) td {{ background: #F8FAF9; }}
      td.numeric {{ text-align: right; white-space: nowrap; }}
      </style></head><body>
      <header class="report-header"><p class="eyebrow">ODOO 业务数据 · 标准分析报告</p>
      <h1>{html.escape(config["title"])}</h1>
      <div class="document-meta">数据模型：{model_name}　·　生成时间：{generated_at}</div></header>
      {"".join(sections)}
    </body></html>"""


def _write_pdf(path, png_path, config, manifest, analysis_rows):
    try:
        from weasyprint import HTML
    except ImportError as error:
        raise ReportFailure("运行环境缺少 weasyprint") from error
    document = _report_document(png_path, config, manifest, analysis_rows)
    HTML(string=document, base_url=str(path.parent)).write_pdf(str(path))


def _prepare(config_value):
    root = Path.cwd().resolve()
    config = _load_config(root, config_value)
    manifest, field_names, fragments = _load_manifest(root, config)
    _validate_config(config, manifest)
    analysis_rows = _analyze(config, manifest, field_names, fragments)
    return root, config, manifest, fragments, analysis_rows


def validate(config_value):
    _root, config, manifest, fragments, _analysis_rows = _prepare(config_value)
    return {
        "protocol": SCRIPT_PROTOCOL_VERSION,
        "operation": "validate",
        "ok": True,
        "reportId": config["reportId"],
        "dataset": {
            "rowCount": manifest["rowCount"],
            "columnCount": manifest["columnCount"],
            "fragmentCount": len(fragments),
        },
        "artifact": _artifact(config["reportId"]),
    }


def render(config_value):
    root, config, manifest, _fragments, analysis_rows = _prepare(config_value)
    report_id = config["reportId"]
    output_value = f"报表/生成结果/{report_id}"
    output_path = _workspace_path(root, output_value, "输出")
    if output_path.exists():
        raise ReportFailure("最终报表目录已经存在")
    parent = output_path.parent
    parent_existed = parent.exists()
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{report_id}-", dir=str(parent)))
    try:
        png_path = None
        pdf_path = temporary / "分析报告.pdf"
        if "chart" in config["presentation"]["sections"]:
            png_path = temporary / "图表.png"
            _write_png(png_path, config, analysis_rows)
        _write_pdf(pdf_path, png_path, config, manifest, analysis_rows)
        if not pdf_path.is_file() or pdf_path.stat().st_size <= 0:
            raise ReportFailure("PDF 报表产物为空")
        if png_path is not None:
            png_path.unlink()
        os.replace(str(temporary), str(output_path))
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        if not parent_existed:
            try:
                parent.rmdir()
            except OSError:
                pass
        raise
    return {
        "protocol": SCRIPT_PROTOCOL_VERSION,
        "operation": "render",
        "ok": True,
        "reportId": report_id,
        "artifacts": [_artifact(report_id)],
    }


def _emit(value, stream):
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True), file=stream)


def _error(operation, code, message):
    return {
        "protocol": SCRIPT_PROTOCOL_VERSION,
        "operation": operation,
        "ok": False,
        "error": {"code": code, "message": message},
    }


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    operation = arguments[0] if arguments else "unknown"
    if operation == "capabilities":
        if len(arguments) != 1:
            _emit(_error(operation, "invalid_arguments", "capabilities 操作不接受参数"), sys.stderr)
            return 2
        _emit(capabilities(), sys.stdout)
        return 0
    if operation not in {"validate", "render"}:
        _emit(
            _error(
                operation,
                "invalid_arguments",
                "必须指定 capabilities、validate 或 render 操作",
            ),
            sys.stderr,
        )
        return 2
    if len(arguments) != 2:
        _emit(
            _error(operation, "invalid_arguments", f"{operation} 操作需要一个配置路径"),
            sys.stderr,
        )
        return 2
    try:
        response = validate(arguments[1]) if operation == "validate" else render(arguments[1])
    except ReportFailure as error:
        _emit(_error(operation, "report_validation_failed", str(error)), sys.stderr)
        return 1
    except Exception:
        _emit(_error(operation, "report_execution_failed", "报表脚本执行失败"), sys.stderr)
        return 1
    _emit(response, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
