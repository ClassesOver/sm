"""Bound waterfall contributions and sample distributions using Matplotlib primitives."""

import math
from fractions import Fraction

from .standard_chart_encoding import fail, scaled_column
from .standard_chart_presentation import prepare_standard_presentation


def waterfall_levels(values, labels, absolute_labels):
    """Keep exact binary-float contributions until the final displayed coordinates."""
    absolute = set(absolute_labels)
    current = Fraction(0)
    levels = []
    for index, (label, value) in enumerate(zip(labels, values, strict=True)):
        if label in absolute:
            if index and not math.isclose(value, float(current), rel_tol=1e-12, abs_tol=0):
                fail(
                    "standard_waterfall_total_mismatch",
                    "standardWaterfall.absoluteLabels",
                    "绝对值小计/终点与前项累计不符。",
                )
            if index == 0:
                current = Fraction(value)
            # Checkpoints validate the existing sum, never silently reset it.
            start, stop = 0.0, float(current)
        else:
            start = float(current)
            current += Fraction(value)
            stop = float(current)
            if value != 0 and stop == start:
                fail(
                    "standard_waterfall_increment_unrepresentable",
                    "standardWaterfall",
                    "贡献相对基数过小，浮点坐标无法表示；请采用其他视图。",
                )
        if not math.isfinite(start) or not math.isfinite(stop):
            fail("standard_waterfall_overflow", "standardWaterfall", "累计坐标超出有限数值范围。")
        levels.append((start, stop))
    return levels


def prepare_statistical_chart(
    chart, document, original, form, label, canvas, style, presentation, axes, selected
):
    waterfall = getattr(chart, "standard_waterfall", None)
    distribution = getattr(chart, "standard_distribution", None)
    spec = waterfall if form == "waterfall" else distribution
    if (
        spec is None
        or (waterfall is not None) != (form == "waterfall")
        or (distribution is not None) != (form == "boxplot")
    ):
        fail(
            "standard_statistics_configuration_required",
            "standardWaterfall/standardDistribution",
            "图形须提供唯一且匹配的标准统计参数。",
        )
    if (
        getattr(chart, "standard_encoding", None)
        or getattr(chart, "standard_bands", ())
        or getattr(chart, "standard_total_field", None)
        or getattr(chart, "standard_label_fields", ())
        or axes.mode != "single"
        or axes.right_fields
        or axes.right_display_unit
        or axes.zoom_start
        or axes.zoom_end
        or axes.panel_limit
        or presentation.label_formats
        or presentation.summaries
    ):
        fail(
            "standard_statistics_combination_unsupported",
            "standardChart",
            "统计图暂不组合多轴、辅助字段、冻结行摘要或其他图形编码。",
        )
    if (
        getattr(chart, "standard_labels", ())
        or presentation.order.mode != "source"
        or presentation.order.limit is not None
        or presentation.order.exclude_missing
    ):
        fail(
            "standard_statistics_order_unsupported",
            "standardPresentation.order",
            "瀑布贡献链/原始分布样本不能排序截取；箱线分组顺序用groupLabels。",
        )
    if selected and tuple(selected) != (spec.value_field,):
        fail(
            "standard_statistics_selection_conflict",
            "standardValueFields",
            "仅选择明确绑定的度量字段，不能把其他数值列当作样本。",
        )
    display_unit = getattr(chart, "standard_display_unit", None) or axes.left_display_unit
    if axes.left_display_unit and getattr(chart, "standard_display_unit", None) not in (
        None,
        axes.left_display_unit,
    ):
        fail("standard_statistics_unit_conflict", "standardDisplayUnit", "重复显示单位声明不一致。")
    values, field = scaled_column(
        document, spec.value_field, display_unit, axes.allow_nulls and form == "boxplot"
    )
    columns, rows = document["columns"], document["rows"]
    if label not in columns or any(
        not isinstance(row[columns.index(label)], str) or not row[columns.index(label)]
        for row in rows
    ):
        fail(
            "standard_statistics_label_invalid",
            "standardLabelField",
            "类别须是明确的非空冻结文本。",
        )
    labels = [row[columns.index(label)] for row in rows]
    notes = []
    config = spec.model_dump()
    config.update(
        value=field,
        label_index=columns.index(label),
        scale=axes.scale,
        linear_threshold=axes.linear_threshold,
    )
    if form == "waterfall":
        if (
            len(labels) > 60
            or len(set(labels)) != len(labels)
            or len(set(spec.absolute_labels)) != len(spec.absolute_labels)
            or not set(spec.absolute_labels).issubset(labels)
            or labels[0] not in spec.absolute_labels
        ):
            fail(
                "standard_waterfall_roles_invalid",
                "standardWaterfall.absoluteLabels",
                "瀑布图须唯一标签、首项绝对值和存在且唯一的小计/终点标签，最多60项。",
            )
        if field["unit"] == "%" or axes.scale != "linear" or style.series:
            fail(
                "standard_waterfall_semantics_unsupported",
                "standardWaterfall",
                "瀑布只支持可加度量的线性坐标；角色颜色由瀑布参数及逐点颜色声明。",
            )
        try:
            waterfall_levels(values, labels, spec.absolute_labels)
        except OverflowError:
            fail(
                "standard_waterfall_overflow",
                "standardWaterfall",
                "累计值溢出；改用其他视图，不截断数值。",
            )
        names = [spec.value_field]
        for point in style.points:
            if point.series != spec.value_field or point.label not in labels:
                fail(
                    "standard_statistics_style_invalid",
                    "standardStyle.points",
                    "逐贡献颜色必须绑定度量和唯一冻结标签。",
                )
        notes.append("绝对值与有符号增减分开；小计/终点已与前项累计对账")
    else:
        if label != spec.group_field or spec.group_field == spec.value_field or style.points:
            fail(
                "standard_distribution_group_invalid",
                "standardDistribution.groupField",
                "箱线必须按冻结文本组绑定原始样本，不支持逐观测颜色。",
            )
        groups = list(dict.fromkeys(labels))
        if spec.group_labels:
            if len(set(spec.group_labels)) != len(spec.group_labels) or set(
                spec.group_labels
            ) != set(groups):
                fail(
                    "standard_distribution_order_invalid",
                    "standardDistribution.groupLabels",
                    "分组顺序须完整且唯一，不能删组。",
                )
            groups = list(spec.group_labels)
        if len(groups) > 24:
            fail(
                "standard_distribution_capacity",
                "standardDistribution",
                "最多24组原始分布，不能静默截取。",
            )
        if any(
            not any(value is not None for group, value in zip(labels, values) if group == name)
            for name in groups
        ):
            fail(
                "standard_distribution_empty_group",
                "standardDistribution",
                "分组没有有效样本，不能虚构箱体。",
            )
        if axes.scale == "log" and (
            axes.zero_baseline or any(value is not None and value <= 0 for value in values)
        ):
            fail(
                "standard_distribution_log_domain_invalid",
                "standardAxes.scale",
                "对数分布样本须严格正数且不能强制零基线。",
            )
        for item in style.series:
            if (
                item.series not in groups
                or item.geometry != "auto"
                or spec.show_fliers
                and item.marker == "none"
            ):
                fail(
                    "standard_statistics_style_invalid",
                    "standardStyle.series",
                    "箱线系列样式须绑定冻结分组，不替换几何形状。",
                )
        config["groups"] = groups
        names, labels = groups, groups
        # Check Matplotlib's real percentile/whisker arithmetic before selecting the route.
        import numpy as np
        from matplotlib.cbook import boxplot_stats

        with np.errstate(over="ignore", invalid="ignore"):
            for group in groups:
                samples = [
                    value
                    for row, value in zip(rows, values)
                    if row[columns.index(label)] == group and value is not None
                ]
                stats = boxplot_stats(samples, whis=spec.whisker_iqr)[0]
                if any(
                    not math.isfinite(float(stats[key]))
                    for key in ("q1", "med", "q3", "iqr", "whislo", "whishi")
                ):
                    fail(
                        "standard_distribution_statistics_overflow",
                        "standardDistribution",
                        "四分位/须计算溢出；不能用截断值表示分布。",
                    )
        missing = sum(value is None for value in values)
        notes.append(f"仅绑定样本；线性四分位，须={spec.whisker_iqr:g}×IQR；各组显示有效样本数n")
        if missing:
            notes.append(f"排除明确缺失的样本值{missing}项，未补零")
        if not spec.show_fliers:
            notes.append("异常点已按参数隐藏，四分位与须仍使用全部有效样本")
    annotations = list(getattr(chart, "standard_annotations", ()))
    estimate = 0
    for item in annotations:
        if (
            item.row_label
            or item.end_row_label
            or item.kind == "reference"
            or item.series not in (None, spec.value_field)
        ):
            fail(
                "standard_statistics_annotation_invalid",
                "standardAnnotations",
                "统计标注须引用绑定度量，不支持矩阵坐标或参考线。",
            )
        if item.kind in {"point", "range"}:
            if item.label not in labels or (
                item.kind == "range"
                and (
                    item.end_label not in labels
                    or labels.index(item.label) > labels.index(item.end_label)
                )
            ):
                fail(
                    "standard_statistics_annotation_invalid",
                    "standardAnnotations",
                    "标注起止标签须存在且有序。",
                )
        elif item.label or item.end_label:
            fail(
                "standard_statistics_annotation_invalid",
                "standardAnnotations",
                "批量统计标注不能携带指定标签。",
            )
        if item.kind == "point" and item.end_label:
            fail(
                "standard_statistics_annotation_invalid",
                "standardAnnotations",
                "重点标注不接受结束标签。",
            )
        estimate += len(labels) if item.kind in {"values", "peak", "trough"} else 1
    if estimate > 60:
        fail("standard_annotation_capacity_exceeded", "standardAnnotations", "统计值标注超过60项。")
    prepared = prepare_standard_presentation(presentation, document, original, label, names, labels)
    if prepared is None:
        fail(
            "standard_statistics_presentation_invalid",
            "standardPresentation",
            "当前类别不支持此展示标签参数。",
        )
    prepared["source_note"] = "\n".join(
        [*([prepared["source_note"]] if prepared["source_note"] else []), *notes]
    )
    policy = canvas.model_dump()
    horizontal = form == "boxplot" and spec.orientation == "horizontal"
    policy.update(
        style=style.model_dump(),
        annotation_specs=[item.model_dump() for item in annotations],
        total_field=None,
        zero_baseline=axes.zero_baseline,
        special_form=form,
        labels=labels,
        series_names=names,
        categorical_x=not horizontal,
        categorical_y=horizontal,
        statistics=config,
        presentation=prepared,
    )
    return policy


STATISTICS_SCRIPT = """def render_statistical_chart(payload, policy, form, title, output_path):
    import math
    from fractions import Fraction
    import numpy as np
    import matplotlib.pyplot as plt
    from matplotlib.cbook import boxplot_stats
    from matplotlib.patches import Rectangle
    spec = policy["statistics"]
    values = [None if row[spec["value"]["index"]] is None else row[spec["value"]["index"]]*spec["value"]["factor"] for row in payload["rows"]]
    raw_labels = [row[spec["label_index"]] for row in payload["rows"]]
    horizontal = form == "boxplot" and spec["orientation"] == "horizontal"
    fig, ax = plt.subplots(**create_standard_canvas(policy, policy["labels"], "barh" if horizontal else form))
    labels = policy["labels"]
    unit = spec["value"]["unit"]
    precision = policy["style"]["decimals"]
    overrides = {item["series"]:item for item in policy["style"]["series"]}
    if form == "waterfall":
        current = Fraction(0)
        starts, ends, colors = [], [], []
        for i,(label,value) in enumerate(zip(raw_labels,values)):
            absolute = label in spec["absolute_labels"]
            start = 0 if absolute else float(current)
            if i == 0 or not absolute:
                current = Fraction(value) if i == 0 else current+Fraction(value)
            end = float(current)
            starts.append(start)
            ends.append(end)
            color = spec["absolute_color"] if absolute else spec["increase_color"] if value >= 0 else spec["decrease_color"]
            point = next((point for point in policy["style"]["points"] if point["label"] == label),None)
            colors.append(point["color"] if point else color)
        width = policy["style"]["bar_group_width"]
        container = ax.bar(range(len(labels)), [b-a for a,b in zip(starts,ends)], bottom=starts, width=width, color=colors)
        container._standard_waterfall = True
        if spec["connectors"]:
            for i,end in enumerate(ends[:-1]):
                line, = ax.plot([i+width/2,i+1-width/2],[end,end],color="#94a3b8",linewidth=1)
                line._standard_connector = True
        for caption,color in [("绝对值",spec["absolute_color"]),("增加",spec["increase_color"]),("减少",spec["decrease_color"])]:
            ax.add_patch(Rectangle((0,0),0,0,transform=ax.transAxes,label=caption,facecolor=color))
        ax.legend(frameon=False)
        if policy["legend_position"] == "auto":
            policy["legend_position"] = "outside"
        ax.set_xticks(range(len(labels)),standard_label_names(labels,policy))
        ax.set_ylabel(unit)
        ax.axhline(0,color="#94a3b8",linewidth=.8)
        positions = [(i,end) for i,end in enumerate(ends)]
        selected_values = values
        descriptions = [("绝对值 " if label in spec["absolute_labels"] else "变动 ")+format_standard_number(value,precision,show_sign=label not in spec["absolute_labels"])+unit for label,value in zip(labels,values)]
    else:
        stats = []
        ticks = []
        for group,display in zip(labels,standard_label_names(labels,policy)):
            samples = [value for label,value in zip(raw_labels,values) if label == group and value is not None]
            item = boxplot_stats(samples,whis=spec["whisker_iqr"])[0]
            item["label"] = group
            stats.append(item)
            ticks.append((overrides.get(group,{}).get("label") or display)+f" (n={len(samples)})")
        artists = ax.bxp(stats,positions=range(len(labels)),widths=.55,patch_artist=True,
                         orientation=spec["orientation"],showfliers=spec["show_fliers"],manage_ticks=False)
        for i,name in enumerate(labels):
            item = overrides.get(name,{})
            color = standard_series_color(name,policy)
            artists["boxes"][i].set(facecolor=color,edgecolor=color,alpha=item.get("alpha",.25))
            artists["boxes"][i]._standard_box_group = name
            for key,indexes in [("whiskers",[2*i,2*i+1]),("caps",[2*i,2*i+1]),("medians",[i])]:
                for index in indexes:
                    line = artists[key][index]
                    line.set(color=color,linewidth=item.get("line_width",1.8),linestyle=item.get("line_style","-"))
                    line._standard_box_part = (name,key)
            if spec["show_fliers"]:
                artists["fliers"][i].set(marker=item.get("marker","o"),markersize=item.get("marker_size",4),markerfacecolor="none",markeredgecolor=color)
                artists["fliers"][i]._standard_box_part = (name,"fliers")
        set_ticks = ax.set_yticks if horizontal else ax.set_xticks
        set_ticks(range(len(labels)),ticks)
        if horizontal:
            ax.set_xlabel(unit)
            ax.invert_yaxis()
        else:
            ax.set_ylabel(unit)
        (ax.set_xscale if horizontal else ax.set_yscale)(spec["scale"],**({"linthresh":spec["linear_threshold"]} if spec["scale"]=="symlog" else {}))
        if spec["scale"] != "linear":
            (ax.set_xlabel if horizontal else ax.set_ylabel)(unit+("（对数刻度）" if spec["scale"]=="log" else "（对称对数刻度）"))
        selected_values = [item["med"] for item in stats]
        positions = [(value,i) if horizontal else (i,value) for i,value in enumerate(selected_values)]
        descriptions = ["中位数 "+format_standard_number(value,precision)+unit for value in selected_values]
    # A separate highlight marker could be mistaken for a sample; highlight only the text box.
    targeted = {item["label"] for item in policy["annotation_specs"] if item["kind"]=="point"}
    for number,item in enumerate(policy["annotation_specs"]):
        kind = item["kind"]
        if kind == "range":
            span = ax.axhspan if horizontal else ax.axvspan
            span(labels.index(item["label"])-.4,labels.index(item["end_label"])+.4,color=item["color"] or "#e8ae53",alpha=.1)
            continue
        indexes = [labels.index(item["label"])] if kind=="point" else [i for i,value in enumerate(selected_values) if kind=="values" or value==(max(selected_values) if kind=="peak" else min(selected_values))]
        for i in indexes:
            if kind == "values" and labels[i] in targeted:
                continue
            highlight = item["highlight"]
            item["highlight"] = False
            text = (item["caption"]+" · " if item["caption"] else "")+descriptions[i]
            annotation = standard_annotation(ax,text,positions[i],policy,number)
            annotation.set_bbox(dict(boxstyle="round,pad=.15",fc="white",ec="none",alpha=.9))
            item["highlight"] = highlight
            if highlight:
                annotation.set_bbox(dict(boxstyle="round,pad=.2",fc="white",ec=item["color"] or "#475569",lw=.8))
    fig.suptitle(title)
    finish_standard_layout(fig,policy)
    save_standard_canvas(fig,output_path,policy)
    plt.close(fig)

"""

STATISTICS_DISPATCH = """    if form in {"waterfall", "boxplot"}:
        render_statistical_chart(payload, canvas, form, title, output_path)
        continue
"""
