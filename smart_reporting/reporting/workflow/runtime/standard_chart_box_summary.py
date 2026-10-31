"""Verified summary statistics passed directly to Matplotlib.bxp, never resampled."""

import json
import math

from ...units import unit_conversion_scale
from .standard_chart_encoding import fail, scaled_column
from .standard_chart_presentation import prepare_standard_presentation, valid_standard_metadata


def _table(document, limit, allow_empty=False):
    if not isinstance(document, dict):
        fail("standard_box_summary_shape_invalid", "chartInputs", "统计输入必须是已绑定表格。")
    columns, rows = document.get("columns"), document.get("rows")
    if document.get("columnMeta") is not None and not isinstance(document["columnMeta"], dict):
        fail("standard_box_summary_units_invalid", "columnMeta", "统计元数据必须为登记对象。")
    if (
        not isinstance(columns, list)
        or not columns
        or any(not isinstance(c, str) or not c for c in columns)
        or len(set(columns)) != len(columns)
        or not isinstance(rows, list)
        or len(rows) > limit
        or not rows
        and not allow_empty
        or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)
    ):
        fail(
            "standard_box_summary_shape_invalid",
            "chartInputs",
            "汇总最多24组、异常点最多480行，列名须唯一且行宽一致。",
        )
    return columns, rows


def prepare_box_summary(
    chart, document, entries, files, canvas, style, presentation, axes, selected
):
    spec = chart.standard_box_summary
    if (
        getattr(chart, "standard_distribution", None)
        or getattr(chart, "standard_waterfall", None)
        or getattr(chart, "standard_encoding", None)
        or getattr(chart, "standard_bands", ())
        or getattr(chart, "standard_sources", ())
        or getattr(chart, "standard_source_labels", ())
        or getattr(chart, "standard_view", None)
        or getattr(chart, "standard_derivations", ())
        or getattr(chart, "standard_steps", ())
        or getattr(chart, "standard_labels", ())
        or getattr(chart, "standard_label_fields", ())
        or getattr(chart, "standard_total_field", None)
        or axes.mode != "single"
        or axes.right_fields
        or axes.right_display_unit
        or axes.zoom_start
        or axes.zoom_end
        or axes.panel_limit
        or presentation.label_formats
        or presentation.summaries
        or presentation.order.mode != "source"
        or presentation.order.limit is not None
        or presentation.order.exclude_missing
        or style.points
    ):
        fail(
            "standard_box_summary_combination_unsupported",
            "standardBoxSummary",
            "冻结分位数不能与原始样本、聚合/计算、截取、多轴或辅助编码混用。",
        )
    if (
        getattr(chart, "standard_label_field", None) not in (None, spec.group_field)
        or selected
        and tuple(selected) != (spec.median_field,)
    ):
        fail(
            "standard_box_summary_selection_invalid",
            "standardLabelField/standardValueFields",
            "汇总箱线须绑定分组列，只选择主中位数字段；其他统计量由专用参数声明。",
        )
    expected_sources = 2 if spec.outlier_source else 1
    if len(entries) != expected_sources:
        fail(
            "standard_box_summary_sources_invalid",
            "standardBoxSummary.outlierSource",
            "汇总为第一个绑定输入，可选异常点为第二个；不能忽略其他绑定来源。",
        )
    columns, rows = _table(document, 24)
    if spec.group_field not in columns:
        fail(
            "standard_box_summary_group_invalid",
            "standardBoxSummary.groupField",
            "分组列不在冻结汇总表中。",
        )
    gi = columns.index(spec.group_field)
    labels = [row[gi] for row in rows]
    if any(not isinstance(label, str) or not label for label in labels) or len(set(labels)) != len(
        labels
    ):
        fail(
            "standard_box_summary_group_invalid",
            "standardBoxSummary.groupField",
            "每组汇总只能一行且标签须为非空文本，不能自动合并分位数。",
        )
    groups = list(spec.group_labels) if spec.group_labels else labels
    if len(set(groups)) != len(groups) or set(groups) != set(labels):
        fail(
            "standard_box_summary_order_invalid",
            "standardBoxSummary.groupLabels",
            "显示顺序须完整包含全部唯一冻结分组。",
        )
    median_meta = (document.get("columnMeta") or {}).get(spec.median_field, {})
    if not valid_standard_metadata(median_meta) or not median_meta.get("unit"):
        fail("standard_box_summary_units_invalid", "columnMeta", "统计量需要登记单位及有效元数据。")
    display = (
        getattr(chart, "standard_display_unit", None)
        or axes.left_display_unit
        or median_meta["unit"]
    )
    if axes.left_display_unit and getattr(chart, "standard_display_unit", None) not in (
        None,
        axes.left_display_unit,
    ):
        fail(
            "standard_box_summary_units_invalid", "standardDisplayUnit", "两个显示单位声明不一致。"
        )
    fields = {}
    values = {}
    for key, field in [
        ("q1", spec.q1_field),
        ("med", spec.median_field),
        ("q3", spec.q3_field),
        ("whislo", spec.lower_whisker_field),
        ("whishi", spec.upper_whisker_field),
    ]:
        meta = (document.get("columnMeta") or {}).get(field, {})
        if (
            not valid_standard_metadata(meta)
            or meta.get("periods") != median_meta.get("periods")
            or meta.get("unit") != "%"
            and meta.get("isPercent") is True
        ):
            fail(
                "standard_box_summary_units_invalid",
                "columnMeta",
                "五个统计量必须具有同期间、可换算量纲和一致的比例语义。",
            )
        values[key], fields[key] = scaled_column(document, field, display, False)
    rounding_difference = False
    for i in range(len(rows)):
        ordered = [values[key][i] for key in ("whislo", "q1", "med", "q3", "whishi")]
        for left, right in zip(ordered, ordered[1:]):
            if left > right:
                if not math.isclose(left, right, rel_tol=1e-12, abs_tol=0):
                    fail(
                        "standard_box_summary_ordering_invalid",
                        "standardBoxSummary",
                        "必须满足下须≤Q1≤中位数≤Q3≤上须，不能排序或修改原值修复。",
                    )
                rounding_difference = True
    counts: dict[str, int | None] = {group: None for group in labels}
    count_index = None
    if spec.count_field:
        meta = (document.get("columnMeta") or {}).get(spec.count_field, {})
        if (
            spec.count_field not in columns
            or not valid_standard_metadata(meta)
            or not meta.get("unit")
            or unit_conversion_scale(meta["unit"], "元") is not None
            or meta["unit"] == "%"
            or meta.get("isPercent") is True
            or meta.get("periods") != median_meta.get("periods")
        ):
            fail(
                "standard_box_summary_count_invalid",
                "standardBoxSummary.countField",
                "样本量须为同期间的已登记计数字段，不能用金额或百分比。",
            )
        count_index = columns.index(spec.count_field)
        for row, group in zip(rows, labels):
            count = row[count_index]
            if (
                not isinstance(count, (int, float))
                or isinstance(count, bool)
                or not math.isfinite(count)
                or count <= 0
                or isinstance(count, float)
                and (not count.is_integer() or count > 2**53)
            ):
                fail(
                    "standard_box_summary_count_invalid",
                    "standardBoxSummary.countField",
                    "已声明样本量必须为可精确表示的正整数，不能用汇总行数替代。",
                )
            counts[group] = int(count)
    outlier_config = None
    outliers: dict[str, list[float]] = {group: [] for group in groups}
    if spec.outlier_source:
        entry = entries[1]
        source = next((item for item in files if item.path == entry["path"]), None)
        if source is None or source.sha256 != entry["sha256"]:
            fail(
                "standard_box_summary_outlier_identity_mismatch",
                "chartInputs.sha256",
                "异常点输入身份与登记不一致。",
            )
        extra = json.loads(source.content)
        ec, er = _table(extra, 480, allow_empty=True)
        binding = spec.outlier_source
        if binding.group_field not in ec or binding.group_field == binding.value_field:
            fail(
                "standard_box_summary_outlier_invalid",
                "standardBoxSummary.outlierSource",
                "异常点须包含不同的分组和数值列。",
            )
        meta = (extra.get("columnMeta") or {}).get(binding.value_field, {})
        if (
            not valid_standard_metadata(meta)
            or meta.get("periods") != median_meta.get("periods")
            or meta.get("unit") != "%"
            and meta.get("isPercent") is True
        ):
            fail(
                "standard_box_summary_units_invalid",
                "standardBoxSummary.outlierSource",
                "异常点单位/期间须与汇总值一致且可换算。",
            )
        extra_values, value_config = scaled_column(extra, binding.value_field, display, False)
        egi = ec.index(binding.group_field)
        for row, value in zip(er, extra_values):
            group = row[egi]
            if not isinstance(group, str) or group not in labels:
                fail(
                    "standard_box_summary_outlier_invalid",
                    "standardBoxSummary.outlierSource",
                    "异常点分组未登记在本图汇总中。",
                )
            i = labels.index(group)
            if values["whislo"][i] <= value <= values["whishi"][i]:
                fail(
                    "standard_box_summary_outlier_invalid",
                    "standardBoxSummary.outlierSource",
                    "登记异常点必须严格位于该组须的外侧；不按IQR重算或重分类。",
                )
            outliers[group].append(value)
        if any(
            count is not None and len(outliers[group]) > count for group, count in counts.items()
        ):
            fail(
                "standard_box_summary_count_invalid",
                "standardBoxSummary.countField",
                "绑定异常点记录数不能超过已登记样本量。",
            )
        outlier_config = dict(
            path=source.path, sha256=source.sha256, group_index=egi, value=value_config
        )
    all_values = [value for column in values.values() for value in column] + [
        value for points in outliers.values() for value in points
    ]
    if axes.scale == "log" and (axes.zero_baseline or any(value <= 0 for value in all_values)):
        fail(
            "standard_box_summary_log_invalid",
            "standardAxes.scale",
            "对数箱线的登记统计量和异常点须严格正数。",
        )
    for item in style.series:
        if (
            item.series not in groups
            or item.geometry != "auto"
            or spec.show_fliers
            and item.marker == "none"
        ):
            fail(
                "standard_box_summary_style_invalid",
                "standardStyle.series",
                "样式须绑定冻结分组，不能更换几何或静默隐藏异常点。",
            )
    annotations = list(getattr(chart, "standard_annotations", ()))
    estimated = 0
    for item in annotations:
        if (
            item.series not in (None, spec.median_field)
            or item.row_label
            or item.end_row_label
            or item.kind == "reference"
            or item.kind in {"point", "range"}
            and item.label not in groups
            or item.kind == "range"
            and (
                item.end_label not in groups
                or groups.index(item.label) > groups.index(item.end_label)
            )
            or item.kind == "point"
            and item.end_label
            or item.kind not in {"point", "range"}
            and (item.label or item.end_label)
        ):
            fail(
                "standard_box_summary_annotation_invalid",
                "standardAnnotations",
                "标注须绑定冻结中位数及存在且有序的分组，不能引用原始样本点。",
            )
        estimated += len(groups) if item.kind in {"values", "peak", "trough"} else 1
    if estimated > 60:
        fail("standard_annotation_capacity_exceeded", "standardAnnotations", "统计标注超过60项。")
    prepared = prepare_standard_presentation(
        presentation, document, document, spec.group_field, groups, groups
    )
    if prepared is None:
        fail(
            "standard_box_summary_presentation_invalid",
            "standardPresentation",
            "当前冻结分组不支持此显示标签。",
        )
    notes = ["来源登记分位数/须，未从原始样本重算；须不假定为IQR或最值"]
    if rounding_difference:
        notes.append("相邻统计值按1e-12浮点相对容差比较，原值未改")
    notes.append(
        "样本量读取绑定字段 " + spec.count_field
        if spec.count_field
        else "样本量未提供，不以汇总行数作为n"
    )
    if outlier_config is None:
        notes.append("异常点未提供，不能据此判断无异常点")
    else:
        notes.append(
            f"绑定异常点记录{sum(len(v) for v in outliers.values())}项"
            + ("；已按参数隐藏" if not spec.show_fliers else "；保留重复观测")
        )
    prepared["source_note"] = "\n".join(
        [*([prepared["source_note"]] if prepared["source_note"] else []), *notes]
    )
    statistics = dict(
        value=fields["med"],
        summary_fields=fields,
        label_index=gi,
        count_index=count_index,
        outlier_source=outlier_config,
        orientation=spec.orientation,
        show_fliers=spec.show_fliers,
        scale=axes.scale,
        linear_threshold=axes.linear_threshold,
    )
    policy = canvas.model_dump()
    policy.update(
        style=style.model_dump(),
        annotation_specs=[item.model_dump() for item in annotations],
        total_field=None,
        zero_baseline=axes.zero_baseline,
        special_form="boxplot",
        labels=groups,
        series_names=groups,
        categorical_x=spec.orientation != "horizontal",
        categorical_y=spec.orientation == "horizontal",
        statistics=statistics,
        presentation=prepared,
    )
    return policy, dict(values=dict(values=all_values, unit=display))


SUMMARY_SCRIPT = """def read_summary_box_stats(payload,policy,overrides):
    import hashlib
    import json
    spec=policy["statistics"]
    outliers={name:[] for name in policy["labels"]}
    source=spec["outlier_source"]
    if source is not None:
        with open(source["path"],"rb") as handle:
            raw=handle.read()
        if hashlib.sha256(raw).hexdigest()!=source["sha256"]:
            raise ValueError("summary outlier input identity changed")
        extra=json.loads(raw)
        for row in extra["rows"]:
            outliers[row[source["group_index"]]].append(row[source["value"]["index"]]*source["value"]["factor"])
    rows={row[spec["label_index"]]:row for row in payload["rows"]}
    stats,ticks=[],[]
    for group,display in zip(policy["labels"],standard_label_names(policy["labels"],policy)):
        row=rows[group]
        item={key:row[field["index"]]*field["factor"] for key,field in spec["summary_fields"].items()}
        item.update(label=group,fliers=outliers[group])
        stats.append(item)
        count="n未提供" if spec["count_index"] is None else "n="+str(int(row[spec["count_index"]]))
        ticks.append((overrides.get(group,{}).get("label") or display)+" ("+count+")")
    return stats,ticks

"""
