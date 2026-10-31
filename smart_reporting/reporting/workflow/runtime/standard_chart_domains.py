"""Numeric axis viewports in registered display units, without changing plotted values."""

import math
from typing import Any

from .standard_chart_dual_stack import dual_stack_profiles
from .standard_chart_encoding import fail
from .standard_chart_statistics import waterfall_levels


def _values(document, index, factor, indexes=None):
    rows = document["rows"]
    return [
        row[index] * factor
        for i, row in enumerate(rows)
        if row[index] is not None and (indexes is None or i in indexes)
    ]


def _legacy_profiles(config, document, display):
    if config.policy.get("dual_stack"):
        return dual_stack_profiles(config, document)
    _, _, _, _, form, label, fields, category, _, _, _, axes, metadata, total, policy = config
    rows, columns = document["rows"], document["columns"]
    names = policy["series_names"]
    profiles: dict[str, dict[str, Any]] = {}
    for name in names:
        field = fields[0] if category else name
        index = fields.index(field)
        meta = metadata[index]
        factor = policy["axis_factors"][index] if policy["advanced"] else display[0]
        factor *= 100 if meta.get("unit") == "%" and meta.get("isPercent") is False else 1
        selected = [
            i for i, row in enumerate(rows) if not category or row[columns.index(category)] == name
        ]
        values = _values(document, columns.index(field), factor, selected)
        if form == "barh" and axes["mode"] == "panels":
            values.sort(reverse=axes["panel_descending"])
            if axes["panel_limit"] is not None:
                values = values[: axes["panel_limit"]]
        override: dict[str, Any] = next(
            (item for item in policy["style"]["series"] if item["series"] == name), {}
        )
        geometry = override.get("geometry", "auto")
        bars = (
            form in {"bar", "barh", "stacked-bar", "stacked-total"}
            and geometry != "line"
            or geometry == "bar"
        ) and not (axes["mode"] == "dual" and name in axes["right_fields"] and geometry == "auto")
        unit = (
            policy["axis_units"][index]
            if policy["advanced"]
            else display[1] or meta.get("unit") or ""
        )
        profiles[name] = dict(
            values=[endpoint for value in values for endpoint in (0.0, value)]
            if bars and name != total
            else values,
            unit=unit,
        )
    if form in {"stacked-bar", "stacked-area", "stacked-total"}:
        # Rendered stack boundaries, including the baseline, must fit the viewport.
        for name in names:
            if name != total:
                profiles[name]["values"] = []
        for current_label in policy["labels"]:
            bottom = 0.0
            for name in names:
                if name == total:
                    continue
                row = next(
                    row
                    for row in rows
                    if row[columns.index(label)] == current_label
                    and (not category or row[columns.index(category)] == name)
                )
                field = fields[0] if category else name
                index = fields.index(field)
                meta = metadata[index]
                factor = display[0] * (
                    100 if meta.get("unit") == "%" and meta.get("isPercent") is False else 1
                )
                top = math.fsum((bottom, row[columns.index(field)] * factor))
                profiles[name]["values"].extend((bottom, top))
                bottom = top
    # Include frozen interval bounds, not just the center line.
    for band in policy.get("band_specs", []):
        profiles[band["series"]]["values"].extend(
            _values(document, band["lower_index"], band["lower_factor"])
        )
        profiles[band["series"]]["values"].extend(
            _values(document, band["upper_index"], band["upper_factor"])
        )
    return profiles


def prepare_standard_domains(chart, config, document, display, *, profiles_override=None):
    domains = getattr(chart, "standard_domains", None)
    if domains is None:
        return
    form, axes, policy = config.form, config.axes_policy, config.policy
    mode = axes["mode"]
    if (
        form == "heatmap"
        or domains.right is not None
        and mode != "dual"
        or domains.panels
        and mode != "panels"
        or domains.zoom is not None
        and mode != "zoom"
        or domains.x is not None
        and form not in {"scatter", "bubble"}
    ):
        fail(
            "standard_domain_target_invalid",
            "standardDomains",
            "数值轴参数与当前图形/轴布局不匹配；不能裁切类别轴或热力单元。",
        )
    if mode == "panels" and not {item.series for item in domains.panels}.issubset(
        policy["series_names"]
    ):
        fail(
            "standard_domain_target_invalid", "standardDomains.panels", "面板须绑定现有冻结系列名。"
        )
    horizontal = (
        form == "barh" or form == "boxplot" and policy["statistics"]["orientation"] == "horizontal"
    )
    coordinate = "x" if horizontal else "y"
    bindings = []
    if form in {"scatter", "bubble"}:
        encoding = policy["encoding"]
        valid = set(encoding["valid"])
        xv = _values(document, encoding["x"]["index"], encoding["x"]["factor"], valid)
        yv = _values(document, encoding["y"]["index"], encoding["y"]["factor"], valid)
        profiles = {"values": dict(values=yv, unit=encoding["y"]["unit"])}
        if domains.x is not None:
            bindings.append(
                (
                    domains.x,
                    dict(values=xv, unit=encoding["x"]["unit"]),
                    0,
                    "x",
                    False,
                    encoding["x_scale"],
                    "X轴",
                )
            )

        def inside(value, domain):
            return (
                domain is None
                or (domain.minimum is None or value >= domain.minimum)
                and (domain.maximum is None or value <= domain.maximum)
            )

        if not any(inside(x, domains.x) and inside(y, domains.left) for x, y in zip(xv, yv)):
            fail("standard_domain_empty_view", "standardDomains", "显式XY范围内没有完整有效观测。")
    elif form in {"boxplot", "waterfall"}:
        statistics = policy["statistics"]
        if profiles_override is not None:
            profiles = profiles_override
        else:
            values = _values(document, statistics["value"]["index"], statistics["value"]["factor"])
            if form == "waterfall":
                labels = [row[statistics["label_index"]] for row in document["rows"]]
                values = [
                    value
                    for pair in waterfall_levels(values, labels, statistics["absolute_labels"])
                    for value in pair
                ]
            profiles = {"values": dict(values=values, unit=statistics["value"]["unit"])}
    else:
        profiles = _legacy_profiles(config, document, display)
    if mode == "panels":
        overrides = {item.series: item.domain for item in domains.panels}
        for index, name in enumerate(policy["series_names"]):
            spec = overrides.get(name, domains.left)
            if spec is not None:
                bindings.append(
                    (spec, profiles[name], index, coordinate, False, axes["scale"], name)
                )
    else:
        for side, spec in [("left", domains.left), ("right", domains.right)]:
            if spec is None:
                continue
            names = [
                name
                for name in profiles
                if mode != "dual" or (name in axes["right_fields"]) == (side == "right")
            ]
            values = [value for name in names for value in profiles[name]["values"]]
            units = {profiles[name]["unit"] for name in names}
            if len(units) != 1:
                fail(
                    "standard_domain_units_ambiguous",
                    "standardDomains",
                    "同一个显式值域必须具有一致的显示单位。",
                )
            bindings.append(
                (
                    spec,
                    dict(values=values, unit=next(iter(units))),
                    int(side == "right"),
                    coordinate,
                    False,
                    axes["scale"],
                    "右轴" if side == "right" else "值轴",
                )
            )
    if domains.zoom is not None:
        columns, rows = document["columns"], document["rows"]
        first, last = [policy["labels"].index(axes[name]) for name in ("zoom_start", "zoom_end")]
        zoom_labels = set(policy["labels"][first : last + 1])
        local = {
            **document,
            "rows": [row for row in rows if row[columns.index(config.label_column)] in zoom_labels],
        }
        local_profiles = _legacy_profiles(config, local, display)
        bindings.append(
            (
                domains.zoom,
                dict(
                    values=[v for profile in local_profiles.values() for v in profile["values"]],
                    unit=next(iter(local_profiles.values()))["unit"],
                ),
                0,
                "y",
                True,
                axes["scale"],
                "局部图",
            )
        )
    result = []
    notes = []
    for spec, profile, index, coordinate, inset, scale, caption in bindings:
        values = profile["values"]
        if not values or any(not math.isfinite(value) for value in values):
            fail("standard_domain_values_invalid", "standardDomains", "显示坐标为空或非有限值。")
        if scale == "log" and any(
            value is not None and value <= 0 for value in (spec.minimum, spec.maximum, *spec.ticks)
        ):
            fail(
                "standard_domain_log_invalid",
                "standardDomains",
                "普通对数的范围与刻度必须严格正数。",
            )
        if not profile["unit"] and (
            spec.minimum is not None or spec.maximum is not None or spec.ticks
        ):
            fail(
                "standard_domain_units_missing",
                "standardDomains",
                "显式数值范围需要已登记的显示单位；未知单位时可移除非业务必需的 "
                "standardDomains 和单位换算，保留原值使用自动坐标；不得从标题猜测单位。",
            )
        zero_required = (
            axes["zero_baseline"]
            and not inset
            and (form not in {"scatter", "bubble"} or coordinate == "y")
        )
        if zero_required:
            if (
                spec.minimum is not None
                and spec.minimum > 0
                or spec.maximum is not None
                and spec.maximum < 0
            ):
                fail(
                    "standard_domain_zero_conflict", "standardDomains", "显式范围与强制零基线冲突。"
                )
        if (
            spec.minimum is not None
            and max(values) < spec.minimum
            or spec.maximum is not None
            and min(values) > spec.maximum
        ):
            fail("standard_domain_empty_view", "standardDomains", "显式范围与全部绘制坐标不相交。")
        below = sum(value < spec.minimum for value in values) if spec.minimum is not None else 0
        above = sum(value > spec.maximum for value in values) if spec.maximum is not None else 0
        if (below or above) and spec.out_of_range == "reject":
            fail(
                "standard_domain_clips_data",
                "standardDomains",
                "范围会裁切数据或几何边界；保留完整范围或显式outOfRange=annotate。",
            )
        prepared = spec.model_dump()
        prepared.update(
            index=index,
            coordinate=coordinate,
            inset=inset,
            caption=caption,
            unit=profile["unit"],
            below=below,
            above=above,
        )
        result.append(prepared)
        extent = f"[{spec.minimum if spec.minimum is not None else '自动'}, {spec.maximum if spec.maximum is not None else '自动'}]"
        note = (
            caption + "显示范围 " + extent + profile["unit"]
            if spec.minimum is not None or spec.maximum is not None
            else caption + "使用显式刻度/格式"
        )
        if below or above:
            note += f"；超界图形端点：低于{below}、高于{above}，仅裁切显示，原值未改"
        notes.append(note)
    policy["domains"] = result
    presentation = policy["presentation"]
    presentation["source_note"] = "\n".join(
        [*([presentation["source_note"]] if presentation["source_note"] else []), *notes]
    )


DOMAIN_SCRIPT = """def standard_domain_target(fig,spec):
    target=fig.axes[spec["index"]]
    return target.child_axes[0] if spec["inset"] else target

def apply_standard_domains(fig,policy):
    from matplotlib.text import Annotation
    from matplotlib.ticker import FuncFormatter
    for spec in policy.get("domains",[]):
        ax=standard_domain_target(fig,spec)
        horizontal=spec["coordinate"]=="x"
        getter,setter=(ax.get_xlim,ax.set_xlim) if horizontal else (ax.get_ylim,ax.set_ylim)
        low,high=getter()
        ticks=spec["ticks"]
        low=spec["minimum"] if spec["minimum"] is not None else min([low,*ticks])
        high=spec["maximum"] if spec["maximum"] is not None else max([high,*ticks])
        if not low<high:
            raise ValueError("standard_domain_empty_view")
        if ticks:
            (ax.set_xticks if horizontal else ax.set_yticks)(ticks)
        setter(low,high)
        axis=ax.xaxis if horizontal else ax.yaxis
        decimals=spec["decimals"] if spec["decimals"] is not None else policy["style"]["decimals"]
        if spec["tick_format"]!="auto" or spec["decimals"] is not None:
            def formatter(value,position,decimals=decimals,mode=spec["tick_format"]):
                return format(value,f".{decimals}e") if mode=="scientific" else format_standard_number(value,decimals)
            axis.set_major_formatter(FuncFormatter(formatter))
        for text in ax.texts:
            if isinstance(text,Annotation) and text.xycoords=="data":
                value=text.xy[0 if horizontal else 1]
            elif text.get_transform()==(ax.get_xaxis_transform() if horizontal else ax.get_yaxis_transform()):
                value=text.get_position()[0 if horizontal else 1]
            else:
                continue
            if value<low or value>high:
                text.set_visible(False)

_finish_without_domains=finish_standard_layout
def finish_standard_layout(fig,policy):
    _finish_without_domains(fig,policy)
    renderer=fig.canvas.get_renderer()
    for spec in policy.get("domains",[]):
        ax=standard_domain_target(fig,spec)
        axis=ax.xaxis if spec["coordinate"]=="x" else ax.yaxis
        limits=ax.get_xlim() if spec["coordinate"]=="x" else ax.get_ylim()
        boxes=[tick.get_window_extent(renderer) for value,tick in zip(axis.get_ticklocs(),axis.get_ticklabels()) if tick.get_visible() and limits[0]<=value<=limits[1]]
        if policy["crop"]=="canvas" and any(box.x0<0 or box.y0<0 or box.x1>fig.bbox.width or box.y1>fig.bbox.height for box in boxes):
            raise ValueError("standard_chart_layout_unresolved: 显式数值刻度超出画布，请调整留白或字号")
        if any(left.overlaps(right) for index,left in enumerate(boxes) for right in boxes[index+1:]):
            raise ValueError("standard_chart_layout_unresolved: 显式数值刻度重叠，请减少刻度或扩大画布")

"""
