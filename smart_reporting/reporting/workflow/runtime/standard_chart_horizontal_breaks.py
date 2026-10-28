"""Horizontal two-interval rendering over the complete frozen grouped bars.

Only injected for batches containing horizontal breaks, keeping older compiled
scripts byte-identical. Range validation stays in standard_chart_breaks.
"""

HORIZONTAL_BREAK_SCRIPT = '''def layout_horizontal_standard_break(fig,policy):
    spec=policy["broken_axis"]
    for ax,domain in zip(fig.axes,(spec["lower"],spec["upper"])):
        ax.set_xlim(domain["minimum"],domain["maximum"])
    reserved=policy["presentation"]
    if policy["layout"]=="constrained":
        fig.get_layout_engine().set(rect=(.02,reserved["footer_top"],.96,reserved["header_bottom"]-reserved["footer_top"]),wspace=spec["gap"])
    elif policy["layout"]=="manual":
        fig.subplots_adjust(left=policy["left"],right=policy["right"],bottom=policy["bottom"],top=policy["top"],wspace=spec["gap"])
    else:
        fig.tight_layout(pad=max(.7,policy["padding"]),rect=(.02,reserved["footer_top"],.98,reserved["header_bottom"]))
        fig.subplots_adjust(wspace=spec["gap"])

def render_horizontal_broken_chart(payload,canvas,form,title,output_path,label_column,fields,category,metadata,input_path):
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
    factors=canvas["axis_factors"] if canvas["advanced"] else [DISPLAYS.get(input_path,(1,None))[0]]*len(names)
    if category:
        factors=[factors[0]]*len(names)
    series=[[value*factor*(100 if meta.get("unit")=="%" and meta.get("isPercent") is False else 1) for value in values]
            for values,meta,factor in zip(raw,metas,factors)]
    spec=canvas["broken_axis"]
    fig,axes=plt.subplots(1,2,sharey=True,gridspec_kw={"width_ratios":[spec["lower_fraction"],1-spec["lower_fraction"]]},
                         **create_standard_canvas(canvas,labels,form))
    group_height=canvas["style"]["bar_group_width"]
    height=group_height/len(names)
    precision=canvas["style"]["decimals"]
    annotations=[(item["kind"],names.index(item["series"] or names[0]),labels.index(item["label"]) if item["label"] in labels else None,None)
                 for item in canvas["annotation_specs"] if item["kind"]!="range"]
    for panel,(ax,domain) in enumerate(zip(axes,(spec["lower"],spec["upper"]))):
        ax._standard_break_panel="lower" if panel==0 else "upper"
        for index,(name,values) in enumerate(zip(names,series)):
            offsets=[i-group_height/2+height/2+index*height for i in range(len(labels))]
            ax.barh(offsets,values,height=height,label=name)
        ax.set_yticks(range(len(labels)),standard_label_names(labels,canvas))
        ax.set_xlabel(spec["unit"]+(" · 左段" if panel==0 else " · 右段"))
        ax.set_xlim(domain["minimum"],domain["maximum"])
        if domain["ticks"]:
            ax.set_xticks(domain["ticks"])
            ax.set_xlim(domain["minimum"],domain["maximum"])
        decimals=domain["decimals"] if domain["decimals"] is not None else precision
        if domain["tick_format"]!="auto" or domain["decimals"] is not None:
            def formatter(value,position,decimals=decimals,mode=domain["tick_format"]):
                return format(value,f".{decimals}e") if mode=="scientific" else format_standard_number(value,decimals)
            ax.xaxis.set_major_formatter(FuncFormatter(formatter))
        for number,item in enumerate(canvas["annotation_specs"]):
            kind=item["kind"]
            color=item["color"] or "#b55d68"
            if kind=="range":
                ax.axhspan(labels.index(item["label"])-.4,labels.index(item["end_label"])+.4,color=item["color"] or "#e8ae53",alpha=.12)
                continue
            name=item["series"] or names[0]
            index=names.index(name)
            values=series[index]
            finite=[value for value in values if math.isfinite(value)]
            if not finite:
                continue
            if kind=="reference":
                value=values[labels.index(item["label"])]
                if domain["minimum"]<=value<=domain["maximum"]:
                    ax.axvline(value,color=color,linestyle="--",linewidth=1.2)
                    ax.text(value,.99,(item["caption"] or "参考 "+item["label"])+": "+format_standard_number(value,precision)+spec["unit"],
                            transform=ax.get_xaxis_transform(),ha="left",va="top",rotation=90,fontsize=8,color=color)
                continue
            indexes=([labels.index(item["label"])] if kind=="point" else [i for i,value in enumerate(values) if math.isfinite(value) and (kind=="values" or value==(max(finite) if kind=="peak" else min(finite)))])
            for i in indexes:
                value=values[i]
                if not math.isfinite(value) or not domain["minimum"]<=value<=domain["maximum"]:
                    continue
                if kind=="values" and not standard_values_label_visible(i,index,annotations,series):
                    continue
                extra=canvas["presentation"]["extras"].get((labels[i],name),"")
                auxiliary=[]
                for field in AUXILIARY.get(input_path,()):
                    matching=[row for row in rows if row[columns.index(label_column)]==labels[i] and (not category or row[columns.index(category)]==name)]
                    if len(matching)!=1:
                        raise ValueError("annotation row is ambiguous")
                    meta=payload["columnMeta"][field]
                    auxiliary_value=matching[0][columns.index(field)]*(100 if meta["unit"]=="%" and meta.get("isPercent") is False else 1)
                    auxiliary.append(field+": "+format_standard_number(auxiliary_value,precision)+meta["unit"])
                prefix=item["caption"]+" " if item["caption"] else {"peak":"峰值 ","trough":"谷值 ","point":"重点 "}.get(kind,"")
                text=prefix+format_standard_number(value,precision)+spec["unit"]
                suffix=" / ".join([*auxiliary,*([extra] if extra else [])])
                coordinate=i-group_height/2+height/2+index*height
                annotation=standard_annotation(ax,text+(" · "+suffix if suffix else ""),(value,coordinate),canvas,number,standard_series_color(name,canvas))
                if item["position"]=="auto" and value<0:
                    annotation.set_position((-abs(canvas["style"]["annotation_offset_x"])-8,0))
                    annotation.set_ha("right")
                    annotation.set_va("center")
        ax.spines["right" if panel==0 else "left"].set_visible(False)
        d=spec["mark_size"]
        x=1 if panel==0 else 0
        for y in (0,1):
            line,=ax.plot((x-d,x+d),(y-d,y+d),transform=ax.transAxes,color="#475569",linewidth=1.2,clip_on=False)
            line._standard_axis_break_mark=True
        if panel==0 and len(names)>1:
            ax.legend(frameon=False)
    axes[0].invert_yaxis()
    axes[1].tick_params(axis="y",labelleft=False)
    fig.suptitle(title)
    finish_standard_layout(fig,canvas)
    renderer=fig.canvas.get_renderer()
    numeric_boxes=[]
    for ax in axes:
        low,high=ax.get_xlim()
        boxes=[tick.get_window_extent(renderer) for value,tick in zip(ax.get_xticks(),ax.get_xticklabels()) if tick.get_visible() and low<=value<=high]
        numeric_boxes.extend(boxes)
        if any(a.overlaps(b) for i,a in enumerate(boxes) for b in boxes[i+1:]):
            raise ValueError("standard_chart_layout_unresolved: 横向断轴数值刻度重叠")
        if canvas["crop"]=="canvas" and any(box.x0<0 or box.y0<0 or box.x1>fig.bbox.width or box.y1>fig.bbox.height for box in boxes):
            raise ValueError("standard_chart_layout_unresolved: 横向断轴数值刻度超出画布")
        for line in ax.lines:
            if getattr(line,"_standard_axis_break_mark",False) and canvas["crop"]=="canvas":
                bounds=line.get_window_extent(renderer)
                if bounds.x0<0 or bounds.y0<0 or bounds.x1>fig.bbox.width or bounds.y1>fig.bbox.height:
                    raise ValueError("standard_chart_layout_unresolved: 横向断轴标记超出画布")
    if any(a.overlaps(b) for i,a in enumerate(numeric_boxes) for b in numeric_boxes[i+1:]):
        raise ValueError("standard_chart_layout_unresolved: 横向断轴跨段数值刻度重叠")
    if axes[0].get_position().x1>=axes[1].get_position().x0:
        raise ValueError("standard_chart_layout_unresolved: 断轴左右区间重叠")
    save_standard_canvas(fig,output_path,canvas)
    plt.close(fig)

'''
