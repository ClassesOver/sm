"""Explicit statistical encodings over frozen columns; no inferred coordinates."""

import math
from typing import NoReturn

from ...units import unit_conversion_scale
from .standard_chart_presentation import (
    format_standard_number,
    prepare_standard_presentation,
    valid_standard_metadata,
)


class StandardChartEncodingError(ValueError):
    def __init__(self, code, parameter, message):
        self.code, self.parameter = code, parameter
        super().__init__(message)


def fail(code, parameter, message) -> NoReturn:
    raise StandardChartEncodingError(code, parameter, message)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def scaled_column(document, field, display_unit, allow_nulls):
    columns, rows = document["columns"], document["rows"]
    if field not in columns:
        fail(
            "standard_encoding_field_missing",
            "standardEncoding",
            "编码字段不在转换后的冻结数据中。",
        )
    metadata = document.get("columnMeta") or {}
    if not isinstance(metadata, dict):
        fail("standard_encoding_unit_missing", "columnMeta", "数值编码元数据必须为登记对象。")
    meta = metadata.get(field, {})
    if not valid_standard_metadata(meta) or not meta.get("unit"):
        fail("standard_encoding_unit_missing", "columnMeta", "数值编码需要登记单位及有效比例尺度。")
    scale = unit_conversion_scale(meta["unit"], display_unit) if display_unit else 1
    if scale is None:
        fail(
            "standard_encoding_unit_incompatible", "standardEncoding", "显示单位与冻结单位不兼容。"
        )
    factor = float(scale) * (100 if meta["unit"] == "%" and meta.get("isPercent") is False else 1)
    values: list[float | None] = []
    for row in rows:
        raw = row[columns.index(field)]
        if raw is None and allow_nulls:
            values.append(None)
            continue
        if not _finite(raw):
            fail("standard_encoding_values_invalid", field, "编码字段含缺失、布尔或非有限值。")
        value = raw * factor
        if not math.isfinite(value) or raw != 0 and value == 0:
            fail(
                "standard_encoding_scale_unrepresentable",
                field,
                "单位换算结果溢出或将非零值下溢为零。",
            )
        values.append(value)
    return values, dict(
        index=columns.index(field), factor=factor, unit=display_unit or meta["unit"]
    )


def prepare_encoded_chart(
    chart, document, original, form, label, canvas, style, presentation, axes
):
    encoding = getattr(chart, "standard_encoding", None)
    if encoding is None:
        fail(
            "standard_encoding_required", "standardEncoding", "散点/气泡/热力图须显式声明编码字段。"
        )
    if (
        axes.mode != "single"
        or axes.right_fields
        or axes.right_display_unit
        or axes.zoom_start
        or axes.zoom_end
        or axes.panel_limit
        or getattr(chart, "standard_bands", ())
        or getattr(chart, "standard_total_field", None)
        or getattr(chart, "standard_label_fields", ())
        or presentation.label_formats
    ):
        fail(
            "standard_encoding_combination_unsupported",
            "standardEncoding",
            "此编码暂不组合多轴、范围带或辅助字段标注。",
        )
    columns, rows = document["columns"], document["rows"]
    for field in (encoding.x_field, encoding.y_field, *((label,) if label is not None else ())):
        if field not in columns:
            fail(
                "standard_encoding_field_missing",
                "standardEncoding",
                "坐标或标签字段不在冻结数据中。",
            )
    policy = canvas.model_dump()
    policy.update(
        style=style.model_dump(),
        annotation_specs=[item.model_dump() for item in getattr(chart, "standard_annotations", ())],
        total_field=None,
        zero_baseline=axes.zero_baseline,
        special_form=form,
        categorical_x=form == "heatmap",
        categorical_y=form == "heatmap",
    )
    config = encoding.model_dump()
    config["axes"] = axes.model_dump()
    config["label_index"] = columns.index(label) if label is not None else None
    config["anonymous_labels"] = label is None
    annotations = list(getattr(chart, "standard_annotations", ()))
    notes = []
    labels = (
        [row[columns.index(label)] for row in rows]
        if label is not None
        else [str(i) for i in range(len(rows))]
    )
    if label is None and (
        style.points or any(item.kind in {"point", "reference", "range"} for item in annotations)
    ):
        fail(
            "standard_scatter_label_required",
            "standardLabelField",
            "逐点样式或指定观测标注需要明确冻结标签；不能用行号冒充业务标签。",
        )
    if form == "heatmap":
        if (
            label != encoding.x_field
            or encoding.x_field == encoding.y_field
            or not encoding.value_field
            or encoding.size_field
            or encoding.group_field
            or encoding.color_field
            or encoding.x_display_unit
            or encoding.y_display_unit
            or encoding.x_scale != "linear"
            or axes.scale != "linear"
            or axes.left_display_unit
            or axes.zero_baseline
            or style.series
            or style.points
        ):
            fail(
                "standard_heatmap_encoding_invalid",
                "standardEncoding",
                "热力图须绑定两个不同文本维度及一个数值字段。",
            )
        xi, yi = columns.index(encoding.x_field), columns.index(encoding.y_field)
        if any(not isinstance(row[i], str) or not row[i] for row in rows for i in (xi, yi)):
            fail(
                "standard_heatmap_dimension_invalid",
                "standardEncoding",
                "热力图维度须为非空冻结文本标签。",
            )
        xs = list(dict.fromkeys(row[xi] for row in rows))
        ys = list(dict.fromkeys(row[yi] for row in rows))
        for requested, existing, parameter in [
            (encoding.x_labels, xs, "xLabels"),
            (encoding.y_labels, ys, "yLabels"),
        ]:
            if requested:
                if len(set(requested)) != len(requested) or set(requested) != set(existing):
                    fail(
                        "standard_heatmap_order_invalid",
                        "standardEncoding." + parameter,
                        "热力图顺序须包含当前全部且唯一的冻结类别。",
                    )
                existing[:] = requested
        keys = [(row[xi], row[yi]) for row in rows]
        if len(set(keys)) != len(keys):
            fail(
                "standard_heatmap_duplicate_cell",
                "standardEncoding",
                "热力图单元重复；须先显式分组，不能自动求和。",
            )
        if max(len(xs), len(ys)) > 60 or len(xs) * len(ys) > 480:
            fail(
                "standard_heatmap_capacity_exceeded",
                "standardEncoding",
                "热力网格超过60×60维度或480单元预算。",
            )
        if len(keys) != len(xs) * len(ys) and not axes.allow_nulls:
            fail(
                "standard_heatmap_missing_cell",
                "standardAxes.allowNulls",
                "热力网格缺少组合；允许空白须显式allowNulls=true。",
            )
        display = encoding.color_display_unit or getattr(chart, "standard_display_unit", None)
        if encoding.color_display_unit and getattr(chart, "standard_display_unit", None) not in (
            None,
            display,
        ):
            fail(
                "standard_encoding_unit_conflict",
                "standardEncoding",
                "热力值显示单位重复且不一致。",
            )
        values, config["value"] = scaled_column(
            document, encoding.value_field, display, axes.allow_nulls
        )
        finite = [value for value in values if value is not None]
        names = [encoding.value_field]
        config.update(x_index=xi, y_index=yi, xs=xs, ys=ys)
        lookup = dict(zip(keys, values, strict=True))
        if len(finite) != len(xs) * len(ys):
            notes.append("灰色空白单元表示缺失，未补零")
        estimated = (
            len(finite)
            if encoding.show_values or any(item.kind == "values" for item in annotations)
            else 0
        )
        for item in annotations:
            if item.series not in (None, encoding.value_field):
                fail(
                    "standard_encoding_annotation_invalid",
                    "standardAnnotations",
                    "热力标注系列必须对应valueField。",
                )
            if item.kind in {"point", "range"}:
                if item.label not in xs or item.row_label not in ys:
                    fail(
                        "standard_encoding_annotation_invalid",
                        "standardAnnotations",
                        "热力标注须同时给出冻结列标签label和行标签rowLabel。",
                    )
                if item.kind == "point" and (
                    lookup.get((item.label, item.row_label)) is None
                    or item.end_label
                    or item.end_row_label
                ):
                    fail(
                        "standard_encoding_annotation_invalid",
                        "standardAnnotations",
                        "重点单元不存在或缺失。",
                    )
                if item.kind == "range" and (
                    item.end_label not in xs
                    or item.end_row_label not in ys
                    or xs.index(item.label) > xs.index(item.end_label)
                    or ys.index(item.row_label) > ys.index(item.end_row_label)
                ):
                    fail(
                        "standard_encoding_annotation_invalid",
                        "standardAnnotations",
                        "热力范围须指定有序的冻结起止行列。",
                    )
            elif item.kind not in {"values", "peak", "trough"} or any(
                (item.label, item.end_label, item.row_label, item.end_row_label)
            ):
                fail(
                    "standard_encoding_annotation_invalid",
                    "standardAnnotations",
                    "热力图支持单元值、峰谷、重点和矩形范围。",
                )
            estimated += (
                len(finite)
                if item.kind in {"peak", "trough"}
                else 0
                if item.kind == "values"
                else 1
            )
        policy["series_names"], policy["labels"] = names, xs
    else:
        if (
            encoding.value_field
            or encoding.show_values
            or encoding.x_labels
            or encoding.y_labels
            or presentation.label_mode != "source"
            or getattr(chart, "standard_display_unit", None)
            or encoding.group_field
            and encoding.color_field
            or (form == "bubble") != bool(encoding.size_field)
        ):
            fail(
                "standard_scatter_encoding_invalid",
                "standardEncoding",
                "散点绑定数值X/Y；气泡须sizeField，分组与连续颜色不能混用。",
            )
        if len(set(labels)) != len(labels):
            fail(
                "standard_scatter_labels_duplicate",
                "standardLabelField",
                "散点观测标签须唯一，以便准确绑定逐点样式与标注。",
            )
        xv, config["x"] = scaled_column(
            document, encoding.x_field, encoding.x_display_unit, axes.allow_nulls
        )
        if encoding.y_display_unit and axes.left_display_unit not in (
            None,
            encoding.y_display_unit,
        ):
            fail(
                "standard_encoding_unit_conflict",
                "standardEncoding.yDisplayUnit",
                "Y轴显示单位声明冲突。",
            )
        yv, config["y"] = scaled_column(
            document,
            encoding.y_field,
            encoding.y_display_unit or axes.left_display_unit,
            axes.allow_nulls,
        )
        extra = []
        for field, key, display in [
            (encoding.size_field, "size", None),
            (encoding.color_field, "color", encoding.color_display_unit),
        ]:
            if field:
                values, config[key] = scaled_column(document, field, display, axes.allow_nulls)
                extra.append(values)
        valid = [
            i
            for i in range(len(rows))
            if xv[i] is not None and yv[i] is not None and all(v[i] is not None for v in extra)
        ]
        if not valid:
            fail("standard_encoding_empty", "standardEncoding", "没有可绘制的完整观测。")
        for scale, values in ((encoding.x_scale, xv), (axes.scale, yv)):
            if scale == "log" and any(values[i] <= 0 for i in valid):
                fail(
                    "standard_encoding_log_domain_invalid",
                    "standardEncoding",
                    "对数坐标只接受严格正数；含零负值请显式选symlog。",
                )
        if axes.zero_baseline and axes.scale == "log":
            fail("standard_encoding_log_domain_invalid", "standardAxes", "普通对数不能强制零基线。")
        if encoding.group_field:
            if encoding.group_field not in columns:
                fail(
                    "standard_encoding_field_missing",
                    "standardEncoding.groupField",
                    "分组列不存在。",
                )
            gi = columns.index(encoding.group_field)
            if any(not isinstance(row[gi], str) or not row[gi] for row in rows):
                fail(
                    "standard_scatter_group_invalid",
                    "standardEncoding.groupField",
                    "分组值必须为冻结文本。",
                )
            groups = [row[gi] for row in rows]
            names = list(dict.fromkeys(groups))
            config["group_index"] = gi
        else:
            groups = [encoding.y_field] * len(rows)
            names = [encoding.y_field]
        if len(names) > 8:
            fail(
                "standard_scatter_group_capacity",
                "standardEncoding.groupField",
                "散点分组最多8类。",
            )
        if encoding.size_field:
            sizes = extra[0]
            if any(value is not None and value < 0 for value in sizes):
                fail(
                    "standard_bubble_size_invalid",
                    "standardEncoding.sizeField",
                    "气泡面积不能表示负值。",
                )
            maximum = max(sizes[i] for i in valid)
            if maximum <= 0 or any(
                0 < sizes[i] and sizes[i] / maximum * encoding.max_area < 1 for i in valid
            ):
                fail(
                    "standard_bubble_area_unreadable",
                    "standardEncoding.sizeField",
                    "全零或悬殊面积导致非零气泡不可见；请改用其他视图。",
                )
            config["size_maximum"] = maximum
            notes.append(
                "面积 ∝ "
                + (encoding.size_caption or encoding.size_field)
                + "；最大值 "
                + format_standard_number(maximum, style.decimals)
                + config["size"]["unit"]
            )
        for item in style.series:
            if (
                item.series not in names
                or item.geometry != "auto"
                or item.marker == "none"
                or encoding.color_field
                and item.color
            ):
                fail(
                    "standard_encoding_style_conflict",
                    "standardStyle.series",
                    "系列样式与散点分组/连续颜色映射不兼容。",
                )
        for point in style.points:
            if encoding.color_field or point.series not in names or point.label not in labels:
                fail(
                    "standard_encoding_style_conflict",
                    "standardStyle.points",
                    "逐点颜色与连续色标冲突或标签不存在。",
                )
            i = labels.index(point.label)
            if i not in valid or groups[i] != point.series:
                fail(
                    "standard_encoding_style_conflict",
                    "standardStyle.points",
                    "逐点样式不能绑定缺失观测或其他分组。",
                )
        estimated = 0
        for item in annotations:
            name = item.series or (names[0] if len(names) == 1 else None)
            if item.row_label or item.end_row_label:
                fail(
                    "standard_encoding_annotation_invalid",
                    "standardAnnotations",
                    "散点标注不使用矩阵行标签。",
                )
            if item.kind == "range":
                if item.series or item.label not in labels or item.end_label not in labels:
                    fail(
                        "standard_encoding_annotation_invalid",
                        "standardAnnotations",
                        "范围须绑定两个冻结观测标签。",
                    )
                a, b = labels.index(item.label), labels.index(item.end_label)
                if a not in valid or b not in valid or xv[a] > xv[b]:
                    fail(
                        "standard_encoding_annotation_invalid",
                        "standardAnnotations",
                        "范围端点缺失或X顺序反向。",
                    )
            elif name not in names or item.end_label:
                fail(
                    "standard_encoding_annotation_invalid",
                    "standardAnnotations",
                    "散点标注系列或结束标签无效。",
                )
            elif item.kind in {"point", "reference"}:
                if (
                    item.label not in labels
                    or labels.index(item.label) not in valid
                    or groups[labels.index(item.label)] != name
                ):
                    fail(
                        "standard_encoding_annotation_invalid",
                        "standardAnnotations",
                        "标注观测缺失或不属于指定分组。",
                    )
            elif item.kind not in {"values", "peak", "trough"} or item.label:
                fail(
                    "standard_encoding_annotation_invalid",
                    "standardAnnotations",
                    "散点标注种类或标签无效。",
                )
            elif item.kind in {"peak", "trough"} and not any(groups[i] == name for i in valid):
                fail(
                    "standard_encoding_annotation_invalid",
                    "standardAnnotations",
                    "指定分组没有可用于峰谷标注的有效观测。",
                )
            estimated += len(valid) if item.kind in {"values", "peak", "trough"} else 1
        finite = [extra[-1][i] for i in valid] if encoding.color_field else []
        policy["series_names"], policy["labels"] = names, labels
        config["valid"] = valid
        if len(valid) != len(rows):
            notes.append(f"缺失观测保留，未补零：{len(rows) - len(valid)}行")
    if estimated > 60:
        fail(
            "standard_annotation_capacity_exceeded", "standardAnnotations", "数值标注超过60项预算。"
        )
    if (form == "heatmap" or encoding.color_field) and not finite:
        fail("standard_encoding_empty", "standardEncoding", "色标没有有效数值。")
    if encoding.color_scale == "log" and any(value <= 0 for value in finite):
        fail(
            "standard_color_log_domain_invalid",
            "standardEncoding.colorScale",
            "对数色标只允许严格正数。",
        )
    if encoding.color_center is not None and (
        encoding.color_scale != "linear"
        or not finite
        or not min(finite) < encoding.color_center < max(finite)
    ):
        fail(
            "standard_color_center_invalid",
            "standardEncoding.colorCenter",
            "色标中点须用于线性尺度，且严格位于有效最小/最大值之间。",
        )
    prepared = prepare_standard_presentation(
        presentation, document, original, label, policy["series_names"], policy["labels"], None
    )
    if prepared is None:
        fail(
            "standard_encoding_presentation_invalid",
            "standardPresentation",
            "报告标签/摘要与编码数据不兼容。",
        )
    if notes:
        prepared["source_note"] = "\n".join(
            [*([prepared["source_note"]] if prepared["source_note"] else []), *notes]
        )
    if form != "heatmap":
        policy["labels"], prepared["display_labels"] = [], []
    policy.update(encoding=config, presentation=prepared)
    return policy


def prepare_bands(chart, document, names, form, category, factors, unit_policy):
    bands = getattr(chart, "standard_bands", ())
    if not bands:
        return []
    if form != "line" or category or len({band.series for band in bands}) != len(bands):
        fail("standard_band_combination_invalid", "standardBands", "范围带须唯一绑定宽表折线系列。")
    result = []
    columns, rows = document["columns"], document["rows"]
    meta = document.get("columnMeta") or {}
    for band in bands:
        style = getattr(chart, "standard_style", None)
        if style and any(
            item.series == band.series and item.geometry == "bar" for item in style.series
        ):
            fail("standard_band_combination_invalid", "standardBands", "范围带中心必须绘制为折线。")
        if band.series not in names or len({band.series, band.lower_field, band.upper_field}) != 3:
            fail(
                "standard_band_fields_invalid",
                "standardBands",
                "中心、下界和上界须为不同且存在的字段。",
            )
        center = meta.get(band.series, {})
        conversions = []
        for field in (band.series, band.lower_field, band.upper_field):
            candidate = meta.get(field, {})
            if (
                field not in columns
                or not valid_standard_metadata(candidate)
                or not candidate.get("unit")
                or candidate.get("periods") != center.get("periods")
                or candidate["unit"] != "%"
                and candidate.get("isPercent") is True
            ):
                fail(
                    "standard_band_units_incompatible",
                    "standardBands",
                    "范围上下界与中心值的单位、尺度、期间必须一致。",
                )
            conversion = unit_conversion_scale(candidate["unit"], center["unit"])
            if conversion is None:
                fail(
                    "standard_band_units_incompatible",
                    "standardBands",
                    "范围上下界与中心值量纲不能换算。",
                )
            center_percent = (
                100 if center["unit"] == "%" and center.get("isPercent") is False else 1
            )
            candidate_percent = (
                100 if candidate["unit"] == "%" and candidate.get("isPercent") is False else 1
            )
            conversions.append(float(conversion) * candidate_percent / center_percent)
        ci, li, ui = [
            columns.index(field) for field in (band.series, band.lower_field, band.upper_field)
        ]
        factor = factors[names.index(band.series)]
        lower_factor, upper_factor = conversions[1] * factor, conversions[2] * factor
        for row in rows:
            value, lower, upper = row[ci], row[li], row[ui]
            if lower is None and upper is None and unit_policy.allow_nulls:
                continue
            if not all(_finite(v) for v in (value, lower, upper)):
                fail(
                    "standard_band_bounds_invalid",
                    "standardBands",
                    "范围上下界或中心值缺失/非有限。",
                )
            scaled = [value * factor, lower * lower_factor, upper * upper_factor]
            if (
                not scaled[1] <= scaled[0] <= scaled[2]
                or unit_policy.scale == "log"
                and scaled[1] <= 0
            ):
                fail(
                    "standard_band_bounds_invalid",
                    "standardBands",
                    "范围上下界缺失、不包含中心值或不满足对数域。",
                )
            if any(
                not math.isfinite(v) or raw != 0 and v == 0
                for raw, v in zip((value, lower, upper), scaled, strict=True)
            ):
                fail(
                    "standard_band_scale_unrepresentable",
                    "standardBands",
                    "范围换算溢出或下溢为零。",
                )
        result.append(
            {
                **band.model_dump(),
                "lower_index": li,
                "upper_index": ui,
                "lower_factor": lower_factor,
                "upper_factor": upper_factor,
                "missing_count": sum(row[li] is None and row[ui] is None for row in rows),
            }
        )
    return result


ENCODING_SCRIPT = """def standard_encoded_values(payload, field):
    return [float("nan") if row[field["index"]] is None else row[field["index"]] * field["factor"]
            for row in payload["rows"]]

def standard_color_norm(values, encoding):
    import math
    from matplotlib.colors import Normalize, LogNorm, SymLogNorm, TwoSlopeNorm
    finite = [value for value in values if math.isfinite(value)]
    if encoding["color_scale"] == "log":
        return LogNorm(min(finite), max(finite))
    if encoding["color_scale"] == "symlog":
        return SymLogNorm(encoding["color_linear_threshold"], vmin=min(finite), vmax=max(finite))
    if encoding["color_center"] is not None:
        return TwoSlopeNorm(encoding["color_center"], min(finite), max(finite))
    return Normalize(min(finite), max(finite))

def standard_band_data(payload, policy):
    return [{**item, "lower": [float("nan") if row[item["lower_index"]] is None else row[item["lower_index"]]*item["lower_factor"] for row in payload["rows"]],
                    "upper": [float("nan") if row[item["upper_index"]] is None else row[item["upper_index"]]*item["upper_factor"] for row in payload["rows"]]}
            for item in policy.get("band_specs", [])]

def draw_standard_bands(ax, policy, names, positions, first=0, last=None):
    import math
    for item in policy.get("band_data", []):
        if item["series"] not in names:
            continue
        stop = len(item["lower"]) if last is None else last+1
        if not any(math.isfinite(a) and math.isfinite(b) for a,b in zip(item["lower"][first:stop],item["upper"][first:stop])):
            continue
        artist = ax.fill_between(positions, item["lower"][first:stop], item["upper"][first:stop],
            color=item["color"] or standard_series_color(item["series"], policy), alpha=item["alpha"],
            label=item["label"] or item["series"] + " 范围", zorder=1)
        artist._standard_band = True

def render_encoded_chart(payload, policy, form, title, output_path):
    import math
    import numpy as np
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    encoding = policy["encoding"]
    rows = payload["rows"]
    annotations = policy["annotation_specs"]
    precision = policy["style"]["decimals"]
    if form == "heatmap" and policy["size_mode"] == "auto":
        policy["height"] = min(24, max(policy["height"], len(encoding["ys"])*.36))
    fig, ax = plt.subplots(**create_standard_canvas(policy, policy["labels"], form))
    if form == "heatmap":
        xs, ys = encoding["xs"], encoding["ys"]
        values = standard_encoded_values(payload, encoding["value"])
        cells = {(row[encoding["x_index"]], row[encoding["y_index"]]): value for row, value in zip(rows, values)}
        matrix = np.array([[cells.get((x, y), float("nan")) for x in xs] for y in ys])
        cmap = plt.get_cmap(encoding["color_map"]).with_extremes(bad="#e5e7eb")
        artist = ax.imshow(np.ma.masked_invalid(matrix), aspect="auto", cmap=cmap,
                           norm=standard_color_norm(values, encoding))
        artist.set_label(encoding["value_field"])
        ax.set_xticks(range(len(xs)), standard_label_names(xs, policy))
        ax.set_yticks(range(len(ys)), ys)
        ax.set_xticks(np.arange(len(xs)+1)-.5, minor=True)
        ax.set_yticks(np.arange(len(ys)+1)-.5, minor=True)
        ax.tick_params(which="minor", length=0)
        ax.set_xlabel(encoding["x_caption"] or encoding["x_field"])
        ax.set_ylabel(encoding["y_caption"] or encoding["y_field"])
        unit = encoding["value"]["unit"]
        colorbar = fig.colorbar(artist, ax=ax, fraction=.035, pad=.025)
        colorbar.ax._standard_colorbar = True
        colorbar.set_label((encoding["color_caption"] or encoding["value_field"]) + " · " + unit)
        if encoding["color_scale"] != "linear":
            colorbar.set_label(colorbar.ax.get_ylabel() + ("（对数）" if encoding["color_scale"] == "log" else "（对称对数）"))
        highlighted = set()
        finite = [value for value in values if math.isfinite(value)]
        for number, item in enumerate(annotations):
            kind = item["kind"]
            if kind == "range":
                x1, x2 = xs.index(item["label"]), xs.index(item["end_label"])
                y1, y2 = ys.index(item["row_label"]), ys.index(item["end_row_label"])
                ax.add_patch(Rectangle((x1-.5, y1-.5), x2-x1+1, y2-y1+1,
                    fill=False, edgecolor=item["color"] or "#dc884d", linewidth=2.5))
                continue
            if kind == "values":
                continue
            selected = [(x, y) for y in range(len(ys)) for x in range(len(xs)) if math.isfinite(matrix[y,x]) and (
                (kind == "point" and xs[x] == item["label"] and ys[y] == item["row_label"]) or
                (kind == "peak" and matrix[y,x] == max(finite)) or (kind == "trough" and matrix[y,x] == min(finite)))]
            for x, y in selected:
                highlighted.add((x, y))
                text = (item["caption"] or {"peak":"峰值", "trough":"谷值", "point":"重点"}[kind]) + ": " + format_standard_number(matrix[y,x], precision) + unit
                standard_annotation(ax, text, (x, y), policy, number)
        cell_texts = []
        if encoding["show_values"] or any(item["kind"] == "values" for item in annotations):
            for y in range(len(ys)):
                for x in range(len(xs)):
                    if not math.isfinite(matrix[y,x]) or (x,y) in highlighted:
                        continue
                    color = cmap(artist.norm(matrix[y,x]))
                    brightness = .2126*color[0]+.7152*color[1]+.0722*color[2]
                    text = ax.text(x,y,format_standard_number(matrix[y,x],precision), ha="center",va="center",
                                   color="white" if brightness < .48 else "#172033", fontsize=policy["style"]["annotation_font_size"])
                    cell_texts.append((x,y,text))
    else:
        labels = [row[encoding["label_index"]] for row in rows] if encoding["label_index"] is not None else [str(i) for i in range(len(rows))]
        policy["labels"] = labels
        xv = standard_encoded_values(payload, encoding["x"])
        yv = standard_encoded_values(payload, encoding["y"])
        valid = set(encoding["valid"])
        groups = [row[encoding["group_index"]] for row in rows] if "group_index" in encoding else [encoding["y_field"]]*len(rows)
        overrides = {item["series"]: item for item in policy["style"]["series"]}
        colors = standard_encoded_values(payload, encoding["color"]) if "color" in encoding else None
        sizes = standard_encoded_values(payload, encoding["size"]) if "size" in encoding else None
        artists = []
        for name in policy["series_names"]:
            indexes = [i for i, group in enumerate(groups) if group == name]
            item = overrides.get(name,{})
            options = dict(marker=item.get("marker","o"), alpha=item.get("alpha",1), edgecolors="white", linewidths=.6)
            if colors is None:
                options["color"] = standard_series_color(name, policy)
            else:
                options.update(c=[colors[i] if i in valid else float("nan") for i in indexes],
                               cmap=encoding["color_map"], norm=standard_color_norm([colors[i] for i in valid],encoding))
            areas = [sizes[i]/encoding["size_maximum"]*encoding["max_area"] if i in valid else 0 for i in indexes] if sizes is not None else item.get("marker_size",5)**2
            points = ax.scatter([xv[i] if i in valid else float("nan") for i in indexes],
                                [yv[i] if i in valid else float("nan") for i in indexes], s=areas, label=name, **options)
            points._standard_labels = [labels[i] for i in indexes]
            points._standard_scatter = True
            points._standard_keep_colors = colors is not None
            artists.append(points)
        ax.set_xscale(encoding["x_scale"], **({"linthresh":encoding["x_linear_threshold"]} if encoding["x_scale"]=="symlog" else {}))
        axis = encoding["axes"]
        ax.set_yscale(axis["scale"], **({"linthresh":axis["linear_threshold"]} if axis["scale"]=="symlog" else {}))
        ax.set_xlabel((encoding["x_caption"] or encoding["x_field"])+" · "+encoding["x"]["unit"])
        ax.set_ylabel((encoding["y_caption"] or encoding["y_field"])+" · "+encoding["y"]["unit"])
        if colors is not None:
            colorbar = fig.colorbar(points, ax=ax, fraction=.035, pad=.025)
            colorbar.ax._standard_colorbar = True
            colorbar.set_label((encoding["color_caption"] or encoding["color_field"])+" · "+encoding["color"]["unit"])
        if colors is None or any(item.get("label") for item in overrides.values()):
            ax.legend(artists, policy["series_names"], frameon=False)
        for number, item in enumerate(annotations):
            kind = item["kind"]
            if kind == "range":
                ax.axvspan(xv[labels.index(item["label"])],xv[labels.index(item["end_label"])],color=item["color"] or "#dc884d",alpha=.12)
                continue
            name = item["series"] or policy["series_names"][0]
            indexes = [i for i in encoding["valid"] if groups[i] == name]
            if kind in {"point","reference"}:
                indexes = [labels.index(item["label"])]
            elif kind in {"peak","trough"}:
                extreme = (max if kind=="peak" else min)(yv[i] for i in indexes)
                indexes = [i for i in indexes if yv[i]==extreme]
            for i in indexes:
                caption = item["caption"] or overrides.get(name,{}).get("label") or (encoding["y_caption"] if not encoding["group_field"] else None) or name
                text = caption+": "+format_standard_number(yv[i],precision)+encoding["y"]["unit"]
                if kind == "reference":
                    ax.axhline(yv[i],color=item["color"] or standard_series_color(name,policy),linestyle="--",linewidth=1.2)
                standard_annotation(ax,text,(xv[i],yv[i]),policy,number,standard_series_color(name,policy))
    fig.suptitle(title)
    finish_standard_layout(fig, policy)
    if form == "heatmap":
        renderer = fig.canvas.get_renderer()
        for x,y,text in cell_texts:
            bounds = text.get_window_extent(renderer)
            left, top = ax.transData.transform((x-.48,y-.48))
            right, bottom = ax.transData.transform((x+.48,y+.48))
            if bounds.x0 < min(left,right) or bounds.x1 > max(left,right) or bounds.y0 < min(top,bottom) or bounds.y1 > max(top,bottom):
                raise ValueError("standard_chart_layout_unresolved: 热力单元文字超出单元，请扩大画布或降低标注密度")
    save_standard_canvas(fig,output_path,policy)
    plt.close(fig)

"""
