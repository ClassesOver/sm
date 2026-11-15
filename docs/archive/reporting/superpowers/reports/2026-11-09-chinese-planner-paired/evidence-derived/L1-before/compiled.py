CONFIGS = [('input-0.json', '646f8cc92acd46ea59ddaacdc3b9a50b88d59d762a0b01e3f067001233976e02', 'chart.png', '2025年1月唯一分类人次净变化为-12人次', 'barh', 'label', ['value'], None, '人次', None, [('values', 0, None, None)], {'mode': 'single', 'scale': 'linear', 'linear_threshold': 1.0, 'zero_baseline': True, 'right_fields': (), 'allow_nulls': True, 'left_display_unit': '人次', 'right_display_unit': None, 'panel_limit': None, 'panel_descending': True, 'zoom_start': None, 'zoom_end': None, 'zoom_bounds': (0.56, 0.5, 0.4, 0.4)}, [{'unit': '人次'}], None, {'size_mode': 'fixed', 'width': 4.0, 'height': 3.0, 'dpi': 150, 'layout': 'manual', 'crop': 'canvas', 'padding': 0.2, 'left': 0.32, 'right': 0.94, 'bottom': 0.2, 'top': 0.9, 'label_wrap': 13, 'tick_font_size': 9, 'max_category_ticks': 18, 'legend_position': 'outside', 'style': {'palette': 'report', 'theme': 'report', 'series': (), 'points': (), 'background': '#ffffff', 'grid': 'x', 'grid_alpha': 0.2, 'title_font_size': 14, 'axis_font_size': 9, 'label_rotation': 0, 'legend_columns': 1, 'legend_font_size': 9, 'legend_location': 'auto', 'decimals': 0, 'annotation_font_size': 8, 'annotation_offset_x': 8, 'annotation_offset_y': 8, 'value_margin': 0.2, 'bar_group_width': 0.5, 'annotation_leader': False, 'annotation_color': 'series'}, 'presentation': {'subtitle': '期间2025-01，分类粒度category，仅1个类别', 'source_note': '来源：合成冻结数据（2025-01）', 'label_mode': 'source', 'order': {'mode': 'source', 'fields': (), 'field': None, 'descending': False, 'labels': (), 'limit': None, 'exclude_missing': False}, 'label_formats': (), 'summaries': (), 'extras': {}, 'badges': [], 'display_labels': ['合成机构超长中文分类标签用于验证画布边缘完整显示']}, 'annotation_specs': [{'kind': 'values', 'series': 'value', 'label': None, 'end_label': None, 'row_label': None, 'end_row_label': None, 'color': None, 'highlight': False, 'position': 'auto', 'caption': None}], 'series_names': ['value'], 'labels': ['合成机构超长中文分类标签用于验证画布边缘完整显示'], 'zero_baseline': True, 'total_field': None, 'advanced': False, 'axis_factors': [1.0], 'axis_units': ['人次'], 'band_specs': []})]
ALIGNED = {}
AUXILIARY = {}
DISPLAYS = {('input-0.json', 'chart.png'): (1.0, '人次')}
def standard_wrap(text, width):
    """按字符数均分换行：保留原有换行，不拆开连续字母数字及数字单位，行尾不留开括号、行首不放闭合标点。"""
    import math
    import re
    width = max(1, int(width))
    opening, closing = "（([【《“‘", "）)]】》”’，。、；：！？,.;:!?%"
    wrapped = []
    for paragraph in str(text).split("\n"):
        tokens = []
        # 数字连同紧随的一个中文单位字（年、月、元等）不拆开。
        for token in re.findall(r"\d[\d.,%]*[^\x00-\x7f（(【《“‘，。、；：！？]?|[A-Za-z0-9][A-Za-z0-9.,%:/_+\-]*|\s+|.",
                                paragraph):
            tokens.extend(token[i:i + width] for i in range(0, len(token), width))
        if len(paragraph) <= width:
            wrapped.append(paragraph)
            continue
        target = math.ceil(len(paragraph) / math.ceil(len(paragraph) / width))
        lines = [""]
        for token in tokens:
            if lines[-1] and len(lines[-1]) + len(token.rstrip()) > target:
                lines.append("")
            lines[-1] += token
        lines = [line.strip() for line in lines if line.strip()]
        for index in range(len(lines) - 1):
            while len(lines[index]) > 1 and lines[index][-1] in opening:
                lines[index], lines[index + 1] = lines[index][:-1], lines[index][-1] + lines[index + 1]
            while len(lines[index + 1]) > 1 and lines[index + 1][0] in closing:
                lines[index], lines[index + 1] = lines[index] + lines[index + 1][0], lines[index + 1][1:]
        wrapped.extend(lines)
    return "\n".join(wrapped)

def format_standard_number(value, precision=2, show_sign=False):
    scientific = value != 0 and (abs(value) < .5 * 10 ** -precision or abs(value) >= 1e12)
    return format(value, ("+" if show_sign else "") + (f".{max(2, precision)}e" if scientific else f",.{precision}f"))

def standard_values_label_visible(index, series_index, annotations, series):
    import math
    values = series[series_index]
    finite = [value for value in values if math.isfinite(value)]
    for kind, selected, first, last in annotations:
        if selected != series_index:
            continue
        if kind == "point" and index == first:
            return False
        if kind in ("peak", "trough") and finite and values[index] == (max(finite) if kind == "peak" else min(finite)):
            return False
    return True

def standard_label_names(labels, canvas):
    return canvas["presentation"]["display_labels"]

def standard_annotation(ax, text, xy, canvas, number, color=None, highlight=False):
    from matplotlib.text import Annotation
    spec = canvas["annotation_specs"][number]
    style = canvas["style"]
    color = spec["color"] or color or "#475569"
    position = spec["position"]
    dx, dy = style["annotation_offset_x"], style["annotation_offset_y"]
    negative_bar = position == "auto" and canvas.get("horizontal", False) and xy[0] < 0
    if negative_bar:
        dx = -abs(dx)
    if position == "below":
        dy = -abs(dy) - 6
    elif position == "left":
        dx, dy = -abs(dx) - 8, 0
    elif position == "right":
        dx, dy = abs(dx) + 5, 0
    elif position == "above":
        dy = abs(dy) + 4
    annotation = ax.annotate(text, xy, xytext=(dx, dy), textcoords="offset points",
        fontsize=style["annotation_font_size"], color=color,
        ha="right" if position == "left" or negative_bar else "center" if dx == 0 else "left",
        va="top" if dy < 0 else "bottom" if dy > 0 else "center",
        arrowprops={"arrowstyle": "-", "color": color, "lw": .7} if style["annotation_leader"] else None)
    annotation._standard_custom_position = True
    if spec["highlight"] or highlight:
        if canvas.get("special_form") == "heatmap":
            from matplotlib.patches import Rectangle
            ax.add_patch(Rectangle((xy[0]-.48,xy[1]-.48),.96,.96,fill=False,edgecolor=color,linewidth=2))
        elif canvas.get("special_form") in {"scatter", "bubble"}:
            annotation.set_bbox(dict(boxstyle="round,pad=.2",fc="white",ec=color,lw=.8))
        else:
            ax.scatter([xy[0]], [xy[1]], s=85, color=color, edgecolors="white", linewidths=1.5, zorder=6)
    return annotation

def finish_standard_presentation(fig, canvas):
    presentation = canvas["presentation"]
    width, height = fig.get_size_inches()
    title_size = canvas["style"]["title_font_size"]
    cursor = .982
    if fig._suptitle is None and len(fig.axes) == 1:
        heading = fig.axes[0].get_title()
        fig.axes[0].set_title("")
        fig.suptitle(heading)
    if fig._suptitle is not None:
        heading = standard_wrap(fig._suptitle.get_text(), max(12, int(width * 72 * .87 / title_size)))
        fig._suptitle.set_text(heading)
        fig._suptitle.set_position((.065, .982))
        fig._suptitle.set_ha("left")
        fig._suptitle.set_fontsize(canvas["style"]["title_font_size"])
        fig._suptitle.set_fontweight("bold" if canvas["style"]["theme"] == "report" else "normal")
        fig._suptitle.set_color("#1e293b")
        cursor -= len(heading.splitlines()) * title_size / 72 / height * 1.35 + .025
    if presentation["subtitle"]:
        subtitle = standard_wrap(presentation["subtitle"], max(16, int(width * 72 * .87 / 10)))
        fig.text(.065, cursor, subtitle,
                 ha="left", va="top", fontsize=10, color="#64748b")
        cursor -= len(subtitle.splitlines()) * 10 / 72 / height * 1.5 + .025
    footer_height = .02
    if presentation["source_note"]:
        source = standard_wrap(presentation["source_note"], max(20, int(width * 72 * .87 / 8)))
        fig.text(.065, .022, source,
                 ha="left", va="bottom", fontsize=8, color="#64748b")
        footer_height = .055 + len(source.splitlines()) * 8 / 72 / height * 1.4
    badges = presentation["badges"]
    if badges:
        cursor -= .03
    for index, (text, color) in enumerate(badges):
        fig.text(.5 + (index - (len(badges) - 1) / 2) * .22, cursor, text,
                 ha="center", va="center", fontsize=11, color=color,
                 bbox={"boxstyle": "round,pad=.55", "fc": "#f8fafc", "ec": color, "lw": .7})
    presentation["header_bottom"] = cursor - (.06 if badges else .015)
    presentation["footer_top"] = footer_height
    if presentation["header_bottom"] - footer_height < .3:
        raise ValueError("standard_chart_layout_unresolved: 标题脚注占用过多，请扩大画布或简写")

def standard_series_name(artist, policy):
    label = artist.get_label()
    for name in policy["series_names"]:
        if label in (name, name + " · 左轴", name + " · 右轴", name + "（独立冻结总额，已对账）"):
            return name
    return "分项合计" if label == "分项合计（服务端求和）" else None

def standard_series_color(name, policy):
    import matplotlib.pyplot as plt
    overrides = {item["series"]: item for item in policy["style"]["series"]}
    if overrides.get(name, {}).get("color"):
        return overrides[name]["color"]
    if name == policy["total_field"] or name == "分项合计":
        return "#1f2937"
    index = policy["series_names"].index(name)
    if policy["style"]["palette"] == "report":
        return ["#3066a3", "#dc884d", "#36856b", "#b55d68", "#8573a6", "#58a3ae", "#b49b53", "#718096"][index % 8]
    palette = plt.get_cmap(policy["style"]["palette"])
    return palette(index / max(1, len(policy["series_names"]) - 1) if palette.N > 20 else index)

def apply_standard_style(fig, policy):
    from matplotlib.container import BarContainer
    from matplotlib.text import Annotation
    import matplotlib.pyplot as plt
    style = policy["style"]
    overrides = {item["series"]: item for item in style["series"]}
    all_axes = list(fig.axes)
    for ax in fig.axes:
        all_axes.extend(ax.child_axes)
    fig.set_facecolor(style["background"])
    for ax in all_axes:
        ax.set_facecolor(style["background"])
        if getattr(ax, "_standard_colorbar", False):
            ax.tick_params(labelsize=policy["tick_font_size"])
            ax.yaxis.label.set_fontsize(style["axis_font_size"])
            continue
        for artist in [*ax.lines, *ax.containers, *ax.collections]:
            if getattr(artist, "_standard_band", False):
                continue
            name = standard_series_name(artist, policy)
            if name is None:
                continue
            item = overrides.get(name, {})
            color = standard_series_color(name, policy)
            targets = artist.patches if isinstance(artist, BarContainer) else [artist]
            for target in targets:
                if not getattr(artist, "_standard_keep_colors", False):
                    target.set_color(color)
                target.set_alpha(item.get("alpha", 1))
                if isinstance(artist, BarContainer):
                    target.set_hatch(item.get("hatch", ""))
                    target.set_edgecolor(color)
                elif artist in ax.lines:
                    target.set_linewidth(item.get("line_width", 2))
                    target.set_linestyle(item.get("line_style", "-"))
                    target.set_marker(item.get("marker", "o"))
                    target.set_markersize(item.get("marker_size", 5))
                    if style["theme"] == "report":
                        target.set_markeredgecolor("white")
                        target.set_markeredgewidth(.8)
            for point in style["points"]:
                if point["series"] != name:
                    continue
                drawn_labels = getattr(artist, "_standard_labels", policy["labels"])
                if point["label"] not in drawn_labels:
                    continue
                index = drawn_labels.index(point["label"])
                if isinstance(artist, BarContainer):
                    artist.patches[index].set_facecolor(point["color"])
                    artist.patches[index].set_edgecolor(point["color"])
                elif artist in ax.lines:
                    ax.scatter([artist.get_xdata()[index]], [artist.get_ydata()[index]],
                               s=point["marker_size"] ** 2, color=point["color"],
                               edgecolors="white", linewidths=1, zorder=6)
                elif getattr(artist, "_standard_scatter", False):
                    from matplotlib.colors import to_rgba
                    import numpy as np
                    count = len(artist.get_offsets())
                    colors = artist.get_facecolors()
                    colors = np.tile(colors, (count, 1)) if len(colors) == 1 else colors.copy()
                    colors[index] = to_rgba(point["color"])
                    artist.set_facecolors(colors)
                    if policy.get("special_form") != "bubble":
                        sizes = artist.get_sizes()
                        sizes = np.full(count, sizes[0]) if len(sizes) == 1 else sizes.copy()
                        sizes[index] = point["marker_size"] ** 2
                        artist.set_sizes(sizes)
        ax.grid(False)
        if style["grid"] != "none":
            ax.grid(axis=style["grid"], which="minor" if policy.get("special_form") == "heatmap" else "major",
                    alpha=style["grid_alpha"], linestyle="--", color="#94a3b8", linewidth=.7)
        ax.set_axisbelow(True)
        ax.title.set_fontsize(style["title_font_size"])
        if style["theme"] == "report":
            ax.title.set_fontweight("bold")
            ax.title.set_color("#1e293b")
            ax.tick_params(axis="both", length=0, pad=8, colors="#475569")
            for key, spine in ax.spines.items():
                spine.set_color("#cbd5e1")
                spine.set_linewidth(.7)
                if key == "top" or key == "right" and len(fig.axes) == 1:
                    spine.set_visible(False)
        ax.xaxis.label.set_fontsize(style["axis_font_size"])
        ax.yaxis.label.set_fontsize(style["axis_font_size"])
        rotation = style["label_rotation"] if policy.get("categorical_x", not policy["horizontal"]) else 0
        for tick in ax.get_xticklabels():
            tick.set_rotation(rotation)
            tick.set_ha("right" if rotation > 0 else "left" if rotation < 0 else "center")
        ax.margins(**({"x": style["value_margin"]} if policy["horizontal"] else {"y": style["value_margin"]}))
        if policy["zero_baseline"]:
            low, high = ax.get_xlim() if policy["horizontal"] else ax.get_ylim()
            (ax.set_xlim if policy["horizontal"] else ax.set_ylim)(min(low, 0), max(high, 0))
        if ax.get_legend() is not None:
            location = style["legend_location"]
            if location == "auto":
                location = ("upper left" if ax is fig.axes[0] else "upper right") if len(fig.axes) > 1 else "best"
            legend_options = {}
            if policy.get("special_form") in {"scatter", "bubble"}:
                legend_options = dict(handles=ax.get_legend().legend_handles,
                                      labels=[text.get_text() for text in ax.get_legend().get_texts()])
            ax.legend(frameon=False, loc=location,
                      ncols=style["legend_columns"], fontsize=style["legend_font_size"], **legend_options)
            for text in ax.get_legend().get_texts():
                for name, item in overrides.items():
                    if item.get("label") and text.get_text() in (name, name + " · 左轴", name + " · 右轴"):
                        text.set_text(text.get_text().replace(name, item["label"], 1))
                        break
        for text in ax.texts:
            text.set_fontsize(style["annotation_font_size"])
            if isinstance(text, Annotation) and not getattr(text, "_standard_custom_position", False):
                text.set_position((style["annotation_offset_x"], style["annotation_offset_y"]))
    if fig._suptitle is not None:
        fig._suptitle.set_fontsize(style["title_font_size"])

def create_standard_canvas(policy, labels, form, panels=1):
    policy["horizontal"] = form == "barh"
    width, height = policy["width"], policy["height"]
    if policy["size_mode"] == "auto":
        if form == "barh":
            height = min(24, max(height, len(labels) * .42))
        else:
            width = min(20, max(width, len(labels) * .45))
        height = min(24, max(height, panels * 2.5))
    if width * height * policy["dpi"] ** 2 > 24000000:
        raise ValueError("standard_canvas_pixel_budget_exceeded")
    return {"figsize": (width, height), "dpi": policy["dpi"],
            "layout": "constrained" if policy["layout"] == "constrained" else None}

def save_standard_canvas(fig, output_path, policy):
    fig.savefig(output_path, dpi=policy["dpi"],
                bbox_inches="tight" if policy["crop"] == "tight" else None,
                pad_inches=policy["padding"])

def place_standard_legends(fig, policy):
    if policy["style"]["legend_location"] != "auto" or policy["legend_position"] == "outside":
        return
    import math
    from matplotlib.transforms import Bbox
    for ax in fig.axes:
        legend = ax.get_legend()
        if legend is None or policy["legend_position"] == "auto" and len(legend.get_texts()) > 3:
            continue
        points, bars = [], []
        for line in ax.lines:
            if standard_series_name(line, policy) is None:
                continue
            points.extend(ax.transData.transform((x, y)) for x, y in zip(line.get_xdata(), line.get_ydata())
                          if math.isfinite(x) and math.isfinite(y))
        for container in ax.containers:
            if standard_series_name(container, policy) is not None:
                bars.extend(patch.get_window_extent() for patch in container.patches
                            if math.isfinite(patch.get_width()) and math.isfinite(patch.get_height()))
        for collection in ax.collections:
            if not getattr(collection, "_standard_scatter", False):
                continue
            import numpy as np
            offsets = np.ma.filled(collection.get_offsets(), np.nan)
            sizes = collection.get_sizes()
            for index, (x, y) in enumerate(offsets):
                if math.isfinite(x) and math.isfinite(y):
                    px, py = ax.transData.transform((x,y))
                    radius = math.sqrt(sizes[index if len(sizes) > 1 else 0])/2*fig.dpi/72
                    bars.append(Bbox.from_bounds(px-radius,py-radius,2*radius,2*radius))
        best = None
        for location in ("upper right", "upper left", "lower right", "lower left", "upper center", "lower center"):
            legend.set_loc(location)
            fig.canvas.draw()
            bounds = legend.get_window_extent(fig.canvas.get_renderer())
            if not fig.bbox.contains(bounds.x0, bounds.y0) or not fig.bbox.contains(bounds.x1, bounds.y1):
                continue
            score = sum(bounds.contains(x, y) for x, y in points)
            score += sum(Bbox.intersection(bounds, bar) is not None for bar in bars)
            score += 10 * sum(bounds.overlaps(other.get_legend().get_window_extent(fig.canvas.get_renderer()))
                              for other in fig.axes if other is not ax and other.get_legend() is not None)
            if best is None or score < best[0]:
                best = (score, location)
        if best is not None:
            legend.set_loc(best[1])

def finish_standard_layout(fig, policy):
    from matplotlib.text import Annotation
    apply_standard_style(fig, policy)
    if policy.get("domains"):
        apply_standard_domains(fig, policy)
    finish_standard_presentation(fig, policy)
    for ax in fig.axes:
        if getattr(ax, "_standard_colorbar", False):
            continue
        if policy.get("categorical_x", not policy["horizontal"]):
            ticks, texts = ax.get_xticks(), ax.get_xticklabels()
            if len(texts) > policy["max_category_ticks"]:
                import math
                stride = math.ceil((len(texts) - 1) / (policy["max_category_ticks"] - 1))
                indexes = list(range(0, len(texts) - 1, stride)) + [len(texts) - 1]
                ax.set_xticks([ticks[index] for index in indexes], [texts[index].get_text() for index in indexes])
        for axis, ticks, setter in ((ax.xaxis, ax.get_xticks(), ax.set_xticks),
                                    (ax.yaxis, ax.get_yticks(), ax.set_yticks)):
            texts = [tick.get_text() for tick in axis.get_ticklabels()]
            is_category_axis = ((axis is ax.xaxis and policy.get("categorical_x", not policy["horizontal"])) or
                                (axis is ax.yaxis and policy.get("categorical_y", policy["horizontal"])))
            if is_category_axis and any(len(text) > policy["label_wrap"] for text in texts):
                setter(ticks, [standard_wrap(text, policy["label_wrap"]) for text in texts])
            for tick in axis.get_ticklabels():
                tick.set_fontsize(policy["tick_font_size"])
        legend = ax.get_legend()
        if legend is not None and (policy["legend_position"] == "outside" or
                                  policy["legend_position"] == "auto" and len(legend.get_texts()) > 3):
            legend.set_bbox_to_anchor((1.01, 1))
            legend.set_loc("upper left")
    if policy.get("broken_axis"):
        layout_standard_break(fig, policy)
    elif policy["layout"] == "tight":
        reserved = policy["presentation"]
        top, bottom = reserved["header_bottom"], reserved["footer_top"]
        fig.tight_layout(pad=max(.7, policy["padding"]), rect=(.02, bottom, .98, top))
    elif policy["layout"] == "manual":
        fig.subplots_adjust(left=policy["left"], right=policy["right"],
                            bottom=policy["bottom"], top=policy["top"])
    elif policy["layout"] == "constrained":
        reserved = policy["presentation"]
        fig.get_layout_engine().set(rect=(.02, reserved["footer_top"], .96,
            reserved["header_bottom"] - reserved["footer_top"]))
    fig.canvas.draw()
    place_standard_legends(fig, policy)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    if policy["crop"] == "canvas":
        for ax in fig.axes:
            legend = ax.get_legend()
            if legend is not None:
                bounds = legend.get_window_extent(renderer)
                if bounds.x0 < 0 or bounds.y0 < 0 or bounds.x1 > fig.bbox.width or bounds.y1 > fig.bbox.height:
                    raise ValueError("standard_chart_layout_unresolved: 图例超出画布，请增加右侧留白或使用自适应布局")
    annotations = [text for ax in fig.axes for text in ax.texts if isinstance(text, Annotation) and text.get_visible()]
    obstacles = [ax.get_legend().get_window_extent(renderer).expanded(1.02, 1.05)
                 for ax in fig.axes if ax.get_legend() is not None]
    obstacles.extend(ax.title.get_window_extent(renderer) for ax in fig.axes if ax.title.get_text())
    # Path及裁剪框均转换到显示坐标；双轴、参考线和NaN断点不能按ax.transData猜测。
    from matplotlib.path import Path
    from matplotlib.transforms import Bbox
    line_paths = []
    for ax in [*fig.axes, *(child for ax in fig.axes for child in ax.child_axes)]:
        for line in ax.lines:
            if (not line.get_visible() or line.get_alpha() == 0 or line.get_linewidth() <= 0
                    or line.get_linestyle() in ("None", "none", "", " ")):
                continue
            path = line.get_path().transformed(line.get_transform()).cleaned(remove_nans=True)
            # intersects_bbox对复合路径会跨MOVETO误判；独立检测Matplotlib保留的连续子路径。
            starts = [index for index, code in enumerate(path.codes) if code == Path.MOVETO]
            paths = [Path(path.vertices[start:end]) for start, end in zip(starts, starts[1:] + [len(path.vertices) - 1])
                     if end - start > 1]
            clip = line.get_clip_box() if line.get_clip_on() else None
            clip_path, transform = line.get_transformed_clip_path_and_affine() if line.get_clip_on() else (None, None)
            line_paths.append((paths, clip, clip_path.transformed(transform) if clip_path is not None else None,
                               renderer.points_to_pixels(line.get_linewidth()) / 2))

    def crosses_line(bounds):
        for paths, clip, clip_path, radius in line_paths:
            visible = bounds.padded(radius + 1)
            if clip is not None:
                visible = Bbox.intersection(visible, clip)
                if visible is None:
                    continue
            if clip_path is not None and not clip_path.intersects_bbox(visible, filled=True):
                continue
            if any(path.intersects_bbox(visible, filled=False) for path in paths):
                return True
        return False

    placed = []
    for annotation in annotations:
        original_x, original_y = annotation.get_position()
        offsets = [(0, 0)] + [(0, 12 * step) for step in range(1, 16)]
        offsets += [(0, -12 * step) for step in range(1, 16)]
        offsets += [(direction * 12 * step, 0) for step in range(1, 16) for direction in (-1, 1)]
        for dx, dy in offsets:
            annotation.set_position((original_x + dx, original_y + dy))
            annotation.update_positions(renderer)
            # Exclude the leader line: only text glyph bounds define collisions.
            from matplotlib.text import Text
            bounds = Text.get_window_extent(annotation, renderer).expanded(1.04, 1.12)
            if policy["crop"] == "canvas" and (bounds.x0 < 0 or bounds.y0 < 0 or
                    bounds.x1 > fig.bbox.width or bounds.y1 > fig.bbox.height):
                continue
            if not any(bounds.overlaps(previous) for previous in [*placed, *obstacles]) and not crosses_line(bounds):
                placed.append(bounds)
                break
        else:
            raise ValueError("standard_chart_layout_unresolved: 标注重叠，请减少密度或调整布局")
    for ax in fig.axes:
        if getattr(ax, "_standard_colorbar", False):
            continue
        for axis, categorical in ((ax.xaxis, policy.get("categorical_x", not policy["horizontal"])),
                                  (ax.yaxis, policy.get("categorical_y", policy["horizontal"]))):
            if not categorical:
                continue
            boxes = [text.get_window_extent(renderer) for text in axis.get_ticklabels()
                     if text.get_visible() and text.get_text()]
            if any(left.overlaps(right) for index, left in enumerate(boxes) for right in boxes[index + 1:]):
                raise ValueError("standard_chart_layout_unresolved: 分类标签重叠，请扩大画布或减少标签密度")
            if policy["crop"] == "canvas" and any(
                    box.x0 < 0 or box.y0 < 0 or box.x1 > fig.bbox.width or box.y1 > fig.bbox.height for box in boxes):
                raise ValueError("standard_chart_layout_unresolved: 分类标签超出画布，请调整边距或扩大画布")

def standard_encoded_values(payload, field):
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

def render_advanced(labels, names, raw_series, metadata, policy, form, title, output_path, annotations, canvas):
    import math
    import matplotlib.pyplot as plt
    mode = policy["mode"]
    precision = canvas["style"]["decimals"]
    series = [[value * (100 if meta.get("unit") == "%" and meta.get("isPercent") is False else 1) * factor
               for value in values] for values, meta, factor in zip(raw_series, metadata, canvas["axis_factors"], strict=True)]
    metadata = [{**meta, "unit": unit} for meta, unit in zip(metadata, canvas["axis_units"], strict=True)]
    overrides = {item["series"]: item for item in canvas["style"]["series"]}
    geometries = [overrides.get(name, {}).get("geometry", "auto") for name in names]
    geometries = [("line" if form == "line" or mode == "dual" and name in policy["right_fields"] else "bar")
                  if geometry == "auto" else geometry for name, geometry in zip(names, geometries, strict=True)]
    positions = list(range(len(labels)))
    if mode == "panels":
        fig, panels = plt.subplots(1 if form == "barh" else len(series), len(series) if form == "barh" else 1,
                                   sharex=form != "barh", squeeze=False,
                                   **create_standard_canvas(canvas, labels, form, len(series)))
        axes = list(panels.flat)
        targets = axes
    else:
        fig, primary = plt.subplots(**create_standard_canvas(canvas, labels, form))
        axes = [primary]
        secondary = primary.twinx() if mode == "dual" else None
        if secondary is not None:
            axes.append(secondary)
        targets = [secondary if name in policy["right_fields"] else primary for name in names]
    colors = plt.get_cmap("tab10")
    visible_indexes = []
    for index, (name, values, target, meta) in enumerate(zip(names, series, targets, metadata, strict=True)):
        side = "右轴" if mode == "dual" and name in policy["right_fields"] else "左轴"
        caption = f"{name} · {side}" if mode == "dual" else name
        draw_standard_bands(target, canvas, [name], positions)
        visible = list(range(len(labels)))
        if form == "barh":
            visible = [i for i in visible if math.isfinite(values[i])]
            visible.sort(key=lambda i: values[i], reverse=policy["panel_descending"])
            if policy["panel_limit"] is not None:
                visible = visible[:policy["panel_limit"]]
            drawn_labels = [labels[i] for i in visible]
            artist = target.barh(range(len(visible)), [values[i] for i in visible], label=caption)
            artist._standard_labels = drawn_labels
            formatted_labels = standard_label_names(labels, canvas)
            target.set_yticks(range(len(visible)), [formatted_labels[i] for i in visible])
            target.invert_yaxis()
            target.set_xlabel(meta["unit"])
            target.set_xscale(policy["scale"], **({"linthresh": policy["linear_threshold"]} if policy["scale"] == "symlog" else {}))
        elif geometries[index] == "bar":
            members = [i for i, item in enumerate(targets) if item is target and geometries[i] == "bar"]
            group_width = canvas["style"]["bar_group_width"]
            width = group_width / len(members)
            offsets = [position - group_width / 2 + width / 2 + members.index(index) * width for position in positions]
            target.bar(offsets, values, width=width, color=colors(index), label=caption)
        else:
            target.plot(positions, values, marker="o", color=colors(index), label=caption)
        visible_indexes.append(visible)
        if form != "barh":
            target.set_ylabel(f"{side} · {meta['unit']}" if mode == "dual" else meta["unit"])
            target.set_yscale(policy["scale"], **({"linthresh": policy["linear_threshold"]} if policy["scale"] == "symlog" else {}))
            target.set_xticks(positions, standard_label_names(labels, canvas), rotation=45, ha="right")
        if mode == "panels":
            alias = overrides.get(name, {}).get("label") or name
            target.set_title(alias + ("（独立排序）" if form == "barh" else "（独立纵轴）"), fontsize=10)
        missing = [labels[i] for i, value in enumerate(values) if not math.isfinite(value)]
        if missing:
            alias = overrides.get(name, {}).get("label") or name
            target.text(.01, .02 + .035 * index, alias + " 缺失（保留空位）: " + "、".join(missing),
                        transform=target.transAxes, fontsize=7, color="#64748b")
    for target in axes:
        target.legend(frameon=False, loc="upper left" if target is axes[0] else "upper right")
        target.grid(axis="y", linestyle="--", alpha=.2)
        if policy["scale"] == "log":
            target.set_ylabel(target.get_ylabel() + "（对数刻度）")
        elif policy["scale"] == "symlog":
            if form == "barh":
                target.set_xlabel(target.get_xlabel() + "（对称对数刻度）")
            else:
                target.set_ylabel(target.get_ylabel() + "（对称对数刻度）")
    visible_series = [[value if i in visible_indexes[j] else float("nan") for i, value in enumerate(values)]
                      for j, values in enumerate(series)]
    for number, (kind, series_index, first, last) in enumerate(annotations):
        if kind == "range":
            for target in axes:
                target.axvspan(first - .4, last + .4, alpha=.12, color=canvas["annotation_specs"][number]["color"] or "#e8ae53")
            continue
        target = targets[series_index]
        values = series[series_index]
        unit = metadata[series_index]["unit"]
        visible = visible_indexes[series_index]
        finite = [values[i] for i in visible if math.isfinite(values[i])]
        if not finite:
            continue
        if kind == "reference":
            color = canvas["annotation_specs"][number]["color"] or "#b55d68"
            if form == "barh":
                target.axvline(values[first], color=color, linestyle="--", linewidth=1.2)
                target.text(values[first], 1.01, f"参考 {format_standard_number(values[first], precision)}{unit}",
                            transform=target.get_xaxis_transform(), fontsize=8)
                continue
            target.axhline(values[first], color=color, linestyle="--", linewidth=1.2)
            caption = canvas["annotation_specs"][number]["caption"] or f"参考 {labels[first]}"
            target.text(.99, values[first], f"{caption}: {format_standard_number(values[first], precision)}{unit}",
                        transform=target.get_yaxis_transform(), va="bottom", ha="right", fontsize=8, color=color,
                        bbox={"fc": "white", "ec": "none", "pad": 2})
            continue
        indexes = ([first] if kind == "point" else
                   [index for index in visible if math.isfinite(values[index]) and (kind == "values" or
                    values[index] == (max(finite) if kind == "peak" else min(finite)))])
        for index in indexes:
            if kind == "values" and not standard_values_label_visible(index, series_index, annotations, visible_series):
                continue
            coordinate = index
            if form != "barh" and geometries[series_index] == "bar":
                members = [i for i, item in enumerate(targets) if item is target and geometries[i] == "bar"]
                group_width = canvas["style"]["bar_group_width"]
                width = group_width / len(members)
                coordinate = index - group_width / 2 + width / 2 + members.index(series_index) * width
            extra = canvas["presentation"]["extras"].get((labels[index], names[series_index]), "")
            caption = canvas["annotation_specs"][number]["caption"] or overrides.get(names[series_index], {}).get("label") or names[series_index]
            text = f"{caption}: {format_standard_number(values[index], precision)}{unit}" + (" · " + extra if extra else "")
            xy = (values[index], visible.index(index)) if form == "barh" else (coordinate, values[index])
            standard_annotation(target, text, xy, canvas, number,
                                standard_series_color(names[series_index], canvas))
    if mode == "zoom":
        first = labels.index(policy["zoom_start"])
        last = labels.index(policy["zoom_end"])
        inset = axes[0].inset_axes(policy["zoom_bounds"])
        draw_standard_bands(inset, canvas, names, positions[first:last+1], first, last)
        local_values = []
        for index, values in enumerate(series):
            if geometries[index] == "bar":
                group_width = canvas["style"]["bar_group_width"]
                members = [i for i, geometry in enumerate(geometries) if geometry == "bar"]
                width = group_width / len(members)
                offsets = [position - group_width / 2 + width / 2 + members.index(index) * width for position in positions[first:last + 1]]
                artist = inset.bar(offsets, values[first:last + 1], width=width, color=colors(index), label=names[index])
            else:
                artist = inset.plot(positions[first:last + 1], values[first:last + 1], marker="o", color=colors(index), label=names[index])[0]
            artist._standard_labels = labels[first:last + 1]
            local_values.extend(value for value in values[first:last + 1] if math.isfinite(value))
        for band in canvas.get("band_data", []):
            local_values.extend(value for value in [*band["lower"][first:last+1], *band["upper"][first:last+1]]
                                if math.isfinite(value))
        if not local_values:
            raise ValueError("standard_chart_empty_zoom")
        low, high = min(local_values), max(local_values)
        padding = (high - low) * .1 or abs(high) * .1 or 1
        edge = canvas["style"]["bar_group_width"] / 2 + .08 if "bar" in geometries else .2
        inset.set_xlim(first - edge, last + edge)
        if policy["scale"] == "log":
            inset.set_yscale("log")
            inset.set_ylim(low / 1.2, high * 1.2)
        else:
            if policy["scale"] == "symlog":
                inset.set_yscale("symlog", linthresh=policy["linear_threshold"])
            inset.set_ylim(low - padding, high + padding)
        inset.set_xticks(positions[first:last + 1], standard_label_names(labels, canvas)[first:last + 1], rotation=45, fontsize=7)
        inset.set_title("局部放大 · " + metadata[0]["unit"], fontsize=9)
        axes[0].axvspan(first - .2, last + .2, color="#f59e0b", alpha=.1)
    fig.suptitle(title)
    finish_standard_layout(fig, canvas)
    save_standard_canvas(fig, output_path, canvas)
    plt.close(fig)

import hashlib
import json
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
for input_path, digest, output_path, title, form, label_column, value_columns, category_column, unit, is_percent, annotations, axes_policy, metadata, total_field, canvas in CONFIGS:
    precision = canvas["style"]["decimals"]
    with open(input_path, "rb") as handle:
        raw = handle.read()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("chart input identity changed")
    payload = json.loads(raw)
    scope = (input_path, output_path)
    if scope in ALIGNED:
        payload, dependencies = ALIGNED[scope]
        for dependency_path, dependency_digest in dependencies:
            with open(dependency_path, "rb") as handle:
                dependency_raw = handle.read()
            if hashlib.sha256(dependency_raw).hexdigest() != dependency_digest:
                raise ValueError("aligned chart input identity changed")
    columns = payload["columns"]
    if form in {"pie", "donut", "radar", "funnel", "sankey"}:
        render_family_chart(payload, canvas, form, title, output_path)
        continue
    if form in {"scatter", "bubble", "heatmap"}:
        render_encoded_chart(payload, canvas, form, title, output_path)
        continue
    if form in {"waterfall", "boxplot"}:
        render_statistical_chart(payload, canvas, form, title, output_path)
        continue
    if canvas.get("dual_stack"):
        render_dual_stack(payload,canvas,form,title,output_path,label_column,value_columns,metadata,input_path)
        continue
    if "broken_axis" in canvas:
        (render_horizontal_broken_chart if form == "barh" else render_broken_chart)(payload,canvas,form,title,output_path,label_column,value_columns,category_column,metadata,input_path)
        continue
    canvas["band_data"] = standard_band_data(payload, canvas)
    label_index = columns.index(label_column)
    labels = list(dict.fromkeys(row[label_index] for row in payload["rows"]))
    if category_column:
        category_index = columns.index(category_column)
        names = list(dict.fromkeys(row[category_index] for row in payload["rows"]))
        cells = {(row[label_index], row[category_index]): row[columns.index(value_columns[0])]
                 for row in payload["rows"]}
        series = [[cells.get((label, name), float("nan")) for label in labels] for name in names]
    else:
        names = value_columns
        series = [[row[columns.index(column)] if row[columns.index(column)] is not None else float("nan")
                   for row in payload["rows"]] for column in names]
    if canvas["advanced"]:
        render_advanced(labels, names, series, metadata, axes_policy, form, title, output_path, annotations, canvas)
        continue
    if unit == "%" and is_percent is False:
        series = [[value * 100 for value in values] for values in series]
    if scope in DISPLAYS:
        factor, unit = DISPLAYS[scope]
        series = [[value * factor for value in values] for values in series]
    fig, ax = plt.subplots(**create_standard_canvas(canvas, labels, form))
    draw_standard_bands(ax, canvas, names, positions=list(range(len(labels))))
    positions = list(range(len(labels)))
    if form == "stacked-area":
        ax.stackplot(positions, *series, labels=names)
    else:
        bottom = [0.0] * len(labels)
        group_width = canvas["style"]["bar_group_width"]
        width = group_width / len(series)
        for index, (name, values) in enumerate(zip(names, series, strict=True)):
            if name == total_field:
                continue
            if form == "line":
                ax.plot(positions, values, marker="o", label=name)
            elif form in {"stacked-bar", "stacked-total"}:
                ax.bar(positions, values, width=group_width, bottom=bottom, label=name)
                bottom = [left + right for left, right in zip(bottom, values, strict=True)]
            else:
                offsets = [position - group_width / 2 + width / 2 + index * width for position in positions]
                if form == "barh":
                    ax.barh(offsets, values, height=width, label=name)
                else:
                    ax.bar(offsets, values, width=width, label=name)
    if form == "stacked-total":
        totals = (series[names.index(total_field)] if total_field else
                  [math.fsum(values[index] for values in series) for index in positions])
        caption = total_field + "（独立冻结总额，已对账）" if total_field else "分项合计（服务端求和）"
        ax.plot(positions, totals, marker="o", color="black", label=caption)
    if form == "barh":
        ax.set_yticks(positions, standard_label_names(labels, canvas))
        ax.invert_yaxis()
        ax.set_xlabel(unit or "")
    else:
        ax.set_xticks(positions, standard_label_names(labels, canvas), rotation=45, ha="right")
        ax.set_ylabel(unit or "")
    if len(series) > 1 or form == "stacked-total":
        ax.legend(frameon=False)
    for index, (name, values) in enumerate(zip(names, series, strict=True)):
        missing = [labels[i] for i, value in enumerate(values) if not math.isfinite(value)]
        if missing and axes_policy["allow_nulls"]:
            alias = next((item["label"] for item in canvas["style"]["series"] if item["series"] == name and item["label"]), name)
            ax.text(.01, .02 + .035 * index, alias + " 缺失（保留空位）: " + "、".join(missing),
                    transform=ax.transAxes, fontsize=7, color="#64748b")
    for annotation_index, (kind, series_index, first, last) in enumerate(annotations):
        if kind == "range":
            span = ax.axhspan if form == "barh" else ax.axvspan
            span(first - 0.4, last + 0.4, color=canvas["annotation_specs"][annotation_index]["color"] or "#e8ae53", alpha=0.12)
            continue
        values = series[series_index]
        finite = [value for value in values if math.isfinite(value)]
        if not finite:
            continue
        if kind == "reference":
            draw = ax.axvline if form == "barh" else ax.axhline
            color = canvas["annotation_specs"][annotation_index]["color"] or "#b55d68"
            draw(values[first], linestyle="--", color=color, alpha=0.8, linewidth=1.2)
            caption = canvas["annotation_specs"][annotation_index]["caption"] or f"参考 {labels[first]} · {names[series_index]}"
            text = f"{caption}: {format_standard_number(values[first], precision)}{unit or ''}"
            if form == "barh":
                ax.text(values[first], 1.02, text, transform=ax.get_xaxis_transform(),
                        va="bottom", fontsize=8, color=color, bbox={"fc": "white", "ec": "none", "pad": 2})
            else:
                ax.text(.99, values[first], text, transform=ax.get_yaxis_transform(),
                        va="bottom", ha="right", fontsize=8, color=color, bbox={"fc": "white", "ec": "none", "pad": 2})
            continue
        indexes = ([first] if kind == "point" else
                   [index for index, value in enumerate(values) if math.isfinite(value) and
                    (kind == "values" or value == (max(finite) if kind == "peak" else min(finite)))])
        for index in indexes:
            if kind == "values" and not standard_values_label_visible(index, series_index, annotations, series):
                continue
            value = values[index]
            coordinate = index
            height = value
            if form in {"stacked-bar", "stacked-area", "stacked-total"} and names[series_index] != total_field:
                height += sum(previous[index] for previous_name, previous in zip(names[:series_index], series[:series_index], strict=True)
                              if previous_name != total_field)
            elif form in {"bar", "barh"}:
                coordinate = index - group_width / 2 + group_width / (2 * len(series)) + series_index * group_width / len(series)
            xy = (height, coordinate) if form == "barh" else (coordinate, height)
            prefix = {"peak": "峰值 ", "trough": "谷值 ", "point": "重点 "}.get(kind, "")
            caption = canvas["annotation_specs"][annotation_index]["caption"]
            if caption:
                prefix = caption + " "
            auxiliary_text = []
            for field in AUXILIARY.get(scope, ()):
                matching = [row for row in payload["rows"] if row[label_index] == labels[index]
                            and (not category_column or row[category_index] == names[series_index])]
                if len(matching) != 1:
                    raise ValueError("annotation row is ambiguous")
                meta = payload["columnMeta"][field]
                auxiliary_value = matching[0][columns.index(field)]
                if meta["unit"] == "%" and meta.get("isPercent") is False:
                    auxiliary_value *= 100
                auxiliary_text.append(f"{field}: {format_standard_number(auxiliary_value, precision)}{meta['unit']}")
            suffix = " · " + " / ".join(auxiliary_text) if auxiliary_text else ""
            extra = canvas["presentation"]["extras"].get((labels[index], names[series_index]), "")
            if extra:
                suffix += " · " + extra
            color = standard_series_color(names[series_index], canvas) if canvas["style"]["annotation_color"] == "series" else "#475569"
            point = next((item for item in canvas["style"]["points"] if item["series"] == names[series_index] and item["label"] == labels[index]), None)
            if point is not None:
                color = point["color"]
            standard_annotation(ax, f"{prefix}{format_standard_number(value, precision)}{unit or ''}{suffix}", xy,
                                canvas, annotation_index, color)
    ax.set_title(title)
    ax.spines[["top", "right"]].set_visible(False)
    finish_standard_layout(fig, canvas)
    save_standard_canvas(fig, output_path, canvas)
    plt.close(fig)
