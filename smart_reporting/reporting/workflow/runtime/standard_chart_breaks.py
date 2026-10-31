"""Two explicit linear value-axis intervals over unchanged frozen chart data."""

import math

from .standard_chart_domains import _legacy_profiles
from .standard_chart_encoding import fail


def prepare_standard_break(chart, config, document, display):
    spec = getattr(chart, "standard_break", None)
    if spec is None:
        return
    form, axes, policy = config.form, config.axes_policy, config.policy
    if (
        form not in {"line", "bar", "barh", "stacked-bar", "stacked-area", "stacked-total"}
        or axes["mode"] != "single"
        or axes["scale"] != "linear"
        or axes["right_fields"]
        or getattr(chart, "standard_domains", None) is not None
    ):
        fail(
            "standard_break_combination_unsupported",
            "standardBreak",
            "断轴支持线性单值轴纵向柱线/堆叠/范围带或横向分组柱图，不能与多轴或standardDomains混用。",
        )
    profiles = _legacy_profiles(config, document, display)
    units = {item["unit"] for item in profiles.values()}
    if len(units) != 1 or not next(iter(units)):
        fail(
            "standard_break_units_missing", "standardBreak", "断轴需要同轴一致且有登记的显示单位。"
        )
    values = [value for item in profiles.values() for value in item["values"]]
    if not values or any(not math.isfinite(value) for value in values):
        fail("standard_break_values_invalid", "standardBreak", "断轴坐标必须有限且非空。")
    low_min, low_max, high_min, high_max = (
        spec.lower.minimum,
        spec.lower.maximum,
        spec.upper.minimum,
        spec.upper.maximum,
    )
    if axes["zero_baseline"] and not (low_min <= 0 <= low_max or high_min <= 0 <= high_max):
        fail(
            "standard_break_zero_conflict",
            "standardBreak",
            "强制零基线必须在某个可见区间，不能落在省略区间。",
        )
    for minimum, maximum in [(low_min, low_max), (high_min, high_max)]:
        if not any(
            item["values"] and min(item["values"]) <= maximum and max(item["values"]) >= minimum
            for item in profiles.values()
        ):
            fail(
                "standard_break_empty_interval",
                "standardBreak",
                "断轴某段与所有绘图坐标范围不相交。",
            )
    omitted = sum(low_max < value < high_min for value in values)
    below = sum(value < low_min for value in values)
    above = sum(value > high_max for value in values)
    if omitted and spec.omitted_values == "reject":
        fail(
            "standard_break_hides_values",
            "standardBreak.omittedValues",
            "真实数据或绘图边界落入省略区间；调整区间或显式声明annotate并说明。",
        )
    if (below or above) and spec.out_of_range == "reject":
        fail(
            "standard_break_clips_data",
            "standardBreak.outOfRange",
            "数据或绘图边界超出整体断轴范围；不得静默裁切。",
        )
    policy["broken_axis"] = {
        **spec.model_dump(),
        "unit": next(iter(units)),
        "omitted": omitted,
        "below": below,
        "above": above,
    }
    if policy["size_mode"] == "auto":
        if form == "barh":
            policy["width"] = max(policy["width"], 12)
        else:
            policy["height"] = max(policy["height"], 8)
    note = f"断轴：显示[{low_min}, {low_max}]及[{high_min}, {high_max}]{next(iter(units))}；省略开区间({low_max}, {high_min})，上下段分别线性显示"
    if form == "barh":
        note = note.replace("上下段", "左右段")
    if omitted:
        note += f"；省略区间内数据/边界值{omitted}项未显示，原值未改"
    if below or above:
        note += f"；整体范围外低于{below}、高于{above}项，仅裁切显示"
    columns, rows = document["columns"], document["rows"]
    fields, category = config.value_columns, config.category_column
    for name in policy["series_names"]:
        if category:
            known = sum(
                row[columns.index(category)] == name and row[columns.index(fields[0])] is not None
                for row in rows
            )
            missing = len(policy["labels"]) - known
        else:
            missing = sum(row[columns.index(name)] is None for row in rows)
        if missing:
            note += f"；{name} 缺失{missing}点，保留空位，未补零"
    presentation = policy["presentation"]
    presentation["source_note"] = "\n".join(
        [*([presentation["source_note"]] if presentation["source_note"] else []), note]
    )


BREAK_DISPATCH = """    if "broken_axis" in canvas:
        (render_horizontal_broken_chart if form == "barh" else render_broken_chart)(payload,canvas,form,title,output_path,label_column,value_columns,category_column,metadata,input_path)
        continue
"""


BREAK_SCRIPT = """def layout_standard_break(fig,policy):
    if policy["horizontal"]:
        return layout_horizontal_standard_break(fig,policy)
    spec=policy["broken_axis"]
    for ax,domain in zip(fig.axes,(spec["upper"],spec["lower"])):
        ax.set_ylim(domain["minimum"],domain["maximum"])
    reserved=policy["presentation"]
    if policy["layout"]=="constrained":
        fig.get_layout_engine().set(rect=(.02,reserved["footer_top"],.96,reserved["header_bottom"]-reserved["footer_top"]),hspace=spec["gap"])
    elif policy["layout"]=="manual":
        fig.subplots_adjust(left=policy["left"],right=policy["right"],bottom=policy["bottom"],top=policy["top"],hspace=spec["gap"])
    else:
        fig.tight_layout(pad=max(.7,policy["padding"]),rect=(.02,reserved["footer_top"],.98,reserved["header_bottom"]))
        fig.subplots_adjust(hspace=spec["gap"])

def render_broken_chart(payload,canvas,form,title,output_path,label_column,fields,category,metadata,input_path):
    import math
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    columns,rows=payload["columns"],payload["rows"]
    labels=list(dict.fromkeys(row[columns.index(label_column)] for row in rows))
    names=canvas["series_names"]
    if category:
        cells={(row[columns.index(label_column)],row[columns.index(category)]):row[columns.index(fields[0])] for row in rows}
        raw=[[cells.get((label,name),float("nan")) for label in labels] for name in names]
        metas=[metadata[0]]*len(names)
    else:
        raw=[[row[columns.index(name)] if row[columns.index(name)] is not None else float("nan") for row in rows] for name in names]
        metas=metadata
    factors=canvas["axis_factors"] if canvas["advanced"] else [DISPLAYS.get((input_path,output_path),(1,None))[0]]*len(names)
    if category:
        factors=[factors[0]]*len(names)
    series=[[value*factor*(100 if meta.get("unit")=="%" and meta.get("isPercent") is False else 1) for value in values]
            for values,meta,factor in zip(raw,metas,factors)]
    spec=canvas["broken_axis"]
    width=canvas["style"]["bar_group_width"]
    overrides={item["series"]:item for item in canvas["style"]["series"]}
    geometries=[overrides.get(name,{}).get("geometry","auto") for name in names]
    geometries=[("line" if form=="line" else "bar") if geometry=="auto" else geometry for geometry in geometries]
    fig,axes=plt.subplots(2,1,sharex=True,gridspec_kw={"height_ratios":[1-spec["lower_fraction"],spec["lower_fraction"]]},
                         **create_standard_canvas(canvas,labels,form,2))
    positions=list(range(len(labels)))
    canvas["band_data"]=standard_band_data(payload,canvas)
    precision=canvas["style"]["decimals"]
    total=canvas["total_field"]
    for panel,(ax,domain) in enumerate(zip(axes,(spec["upper"],spec["lower"]))):
        ax._standard_break_panel="upper" if panel==0 else "lower"
        if form=="stacked-area":
            ax.stackplot(positions,*series,labels=names)
        else:
            bottom=[0.]*len(labels)
            members=[i for i,geometry in enumerate(geometries) if geometry=="bar" and names[i]!=total]
            for index,(name,values) in enumerate(zip(names,series)):
                if name==total:
                    continue
                if form in {"stacked-bar","stacked-total"}:
                    ax.bar(positions,values,width=width,bottom=bottom,label=name)
                    bottom=[a+b for a,b in zip(bottom,values)]
                elif geometries[index]=="line":
                    ax.plot(positions,values,marker="o",label=name)
                else:
                    bar_width=width/len(members)
                    offsets=[position-width/2+bar_width/2+members.index(index)*bar_width for position in positions]
                    ax.bar(offsets,values,width=bar_width,label=name)
        if form=="stacked-total":
            totals=series[names.index(total)] if total else [math.fsum(values[i] for values in series) for i in positions]
            ax.plot(positions,totals,marker="o",color="black",label=total+"（独立冻结总额，已对账）" if total else "分项合计（服务端求和）")
        draw_standard_bands(ax,canvas,names,positions)
        ax.set_xticks(positions,standard_label_names(labels,canvas))
        ax.set_ylabel(spec["unit"]+(" · 上段" if panel==0 else " · 下段"))
        ax.set_ylim(domain["minimum"],domain["maximum"])
        if domain["ticks"]:
            ax.set_yticks(domain["ticks"])
            ax.set_ylim(domain["minimum"],domain["maximum"])
        decimals=domain["decimals"] if domain["decimals"] is not None else precision
        if domain["tick_format"]!="auto" or domain["decimals"] is not None:
            def formatter(value,position,decimals=decimals,mode=domain["tick_format"]):
                return format(value,f".{decimals}e") if mode=="scientific" else format_standard_number(value,decimals)
            ax.yaxis.set_major_formatter(FuncFormatter(formatter))
        for annotation_index,item in enumerate(canvas["annotation_specs"]):
            kind=item["kind"]
            if kind=="range":
                ax.axvspan(labels.index(item["label"])-.4,labels.index(item["end_label"])+.4,color=item["color"] or "#e8ae53",alpha=.12)
                continue
            name=item["series"] or names[0]
            series_index=names.index(name)
            values=series[series_index]
            finite=[value for value in values if math.isfinite(value)]
            if not finite:
                continue
            if kind=="reference":
                i=labels.index(item["label"])
                value=values[i]
                if domain["minimum"]<=value<=domain["maximum"]:
                    ax.axhline(value,color=item["color"] or "#b55d68",linestyle="--",linewidth=1.2)
                    ax.text(.99,value,(item["caption"] or "参考 "+labels[i])+": "+format_standard_number(value,precision)+spec["unit"],transform=ax.get_yaxis_transform(),ha="right",va="bottom",fontsize=8)
                continue
            indexes=([labels.index(item["label"])] if kind=="point" else [i for i,value in enumerate(values) if math.isfinite(value) and (kind=="values" or value==(max(finite) if kind=="peak" else min(finite)))])
            for i in indexes:
                value=values[i]
                height=value
                if form in {"stacked-bar","stacked-area","stacked-total"} and name!=total:
                    height+=sum(previous[i] for previous_name,previous in zip(names[:series_index],series[:series_index]) if previous_name!=total)
                if not domain["minimum"]<=height<=domain["maximum"]:
                    continue
                if kind=="values" and not standard_values_label_visible(i,series_index,[(part["kind"],names.index(part["series"] or names[0]),labels.index(part["label"]) if part["label"] in labels else None,None) for part in canvas["annotation_specs"] if part["kind"]!="range"],series):
                    continue
                coordinate=i
                if form in {"bar","line"} and geometries[series_index]=="bar":
                    members=[j for j,geometry in enumerate(geometries) if geometry=="bar"]
                    bar_width=width/len(members)
                    coordinate=i-width/2+bar_width/2+members.index(series_index)*bar_width
                extra=canvas["presentation"]["extras"].get((labels[i],name),"")
                auxiliary=[]
                for field in AUXILIARY.get((input_path,output_path),()):
                    matching=[row for row in rows if row[columns.index(label_column)]==labels[i] and (not category or row[columns.index(category)]==name)]
                    if len(matching)!=1:
                        raise ValueError("annotation row is ambiguous")
                    meta=payload["columnMeta"][field]
                    auxiliary_value=matching[0][columns.index(field)]*(100 if meta["unit"]=="%" and meta.get("isPercent") is False else 1)
                    auxiliary.append(field+": "+format_standard_number(auxiliary_value,precision)+meta["unit"])
                prefix=item["caption"]+" " if item["caption"] else {"peak":"峰值 ","trough":"谷值 ","point":"重点 "}.get(kind,"")
                text=prefix+format_standard_number(value,precision)+spec["unit"]
                suffix=" / ".join([*auxiliary,*([extra] if extra else [])])
                standard_annotation(ax,text+(" · "+suffix if suffix else ""),(coordinate,height),canvas,annotation_index,standard_series_color(name,canvas))
        ax.spines["bottom" if panel==0 else "top"].set_visible(False)
        d=spec["mark_size"]
        y=0 if panel==0 else 1
        for x in (0,1):
            line,=ax.plot((x-d,x+d),(y-d,y+d),transform=ax.transAxes,color="#475569",linewidth=1.2,clip_on=False)
            line._standard_axis_break_mark=True
        if panel==0 and (len(names)>1 or canvas.get("band_data") or form=="stacked-total"):
            ax.legend(frameon=False)
    axes[0].tick_params(axis="x",labelbottom=False)
    fig.suptitle(title)
    finish_standard_layout(fig,canvas)
    renderer=fig.canvas.get_renderer()
    for ax in axes:
        low,high=ax.get_ylim()
        boxes=[tick.get_window_extent(renderer) for value,tick in zip(ax.get_yticks(),ax.get_yticklabels()) if tick.get_visible() and low<=value<=high]
        if any(a.overlaps(b) for i,a in enumerate(boxes) for b in boxes[i+1:]):
            raise ValueError("standard_chart_layout_unresolved: 断轴数值刻度重叠")
        if canvas["crop"]=="canvas" and any(box.x0<0 or box.y0<0 or box.x1>fig.bbox.width or box.y1>fig.bbox.height for box in boxes):
            raise ValueError("standard_chart_layout_unresolved: 断轴数值刻度超出画布")
        for line in ax.lines:
            if getattr(line,"_standard_axis_break_mark",False) and canvas["crop"]=="canvas":
                bounds=line.get_window_extent(renderer)
                if bounds.x0<0 or bounds.y0<0 or bounds.x1>fig.bbox.width or bounds.y1>fig.bbox.height:
                    raise ValueError("standard_chart_layout_unresolved: 断轴标记超出画布")
    if axes[1].get_position().y1>=axes[0].get_position().y0:
        raise ValueError("standard_chart_layout_unresolved: 断轴上下区间重叠")
    save_standard_canvas(fig,output_path,canvas)
    plt.close(fig)

"""
