"""Signed additive stacks with independent right-axis frozen line series."""

import math
from fractions import Fraction

from .standard_chart_encoding import fail


def dual_stack_values(config, document):
    columns, rows = document["columns"], document["rows"]
    fields, metadata, policy = config[6], config[12], config[14]
    result = {}
    for index, (field, meta) in enumerate(zip(fields, metadata, strict=True)):
        factor = policy["axis_factors"][index] * (100 if meta.get("unit") == "%" and meta.get("isPercent") is False else 1)
        raw = [row[columns.index(field)] for row in rows]
        values = [None if value is None else value * factor for value in raw]
        if any(value is not None and (not math.isfinite(value) or value == 0 and original != 0)
               for value, original in zip(values, raw, strict=True)):
            fail("standard_dual_stack_conversion_invalid", "standardAxes", "换算坐标溢出或非零值下溢，不修改冻结值。")
        result[field] = values
    return result


def dual_stack_levels(series, components):
    """Exact positive/negative accumulation; floats only at plotting boundaries."""
    positive = [Fraction(0)] * len(series[components[0]])
    negative = positive.copy()
    boundaries = {}
    for name in components:
        starts, ends = [], []
        for i, value in enumerate(series[name]):
            if value is None:
                raise ValueError("left stack is missing")
            target = negative if value < 0 else positive
            before = float(target[i])
            target[i] += Fraction(value)
            after = before + value
            if not math.isfinite(after) or value != 0 and after == before:
                raise ValueError("stack contribution is not representable")
            starts.append(before)
            ends.append(after)
        boundaries[name] = (starts, ends)
    totals = [float(p + n) for p, n in zip(positive, negative, strict=True)]
    if any(not math.isfinite(value) for value in totals):
        raise ValueError("stack total is not representable")
    return boundaries, totals


def prepare_dual_stack(chart, config, document):
    form, axes, total, policy = config[4], config[11], config[13], config[14]
    if axes["mode"] != "dual" or form not in {"stacked-bar", "stacked-total"}:
        return
    right = set(axes["right_fields"])
    names = policy["series_names"]
    components = [name for name in names if name not in right and name != total]
    if (config[7] or axes["scale"] != "linear" or not components
            or total is not None and (form != "stacked-total" or total in right or total not in names)
            or any(meta.get("unit") == "%" for name, meta in zip(config[6], config[12], strict=True) if name in components)):
        fail("standard_dual_stack_combination_invalid", "standardAxes/standardTotalField", "堆叠双轴需要线性宽表及左侧可加分项；冻结总额须在左轴，百分比不能堆叠。")
    for item in policy["style"]["series"]:
        allowed = {"auto", "line"} if item["series"] in right or item["series"] == total else {"auto", "bar"}
        if item["geometry"] not in allowed:
            fail("standard_dual_stack_geometry_invalid", "standardStyle.series", "左侧分项必须堆叠柱，右侧及冻结总额必须折线。")
    series = dual_stack_values(config, document)
    if any(value is None for name in components for value in series[name]):
        fail("standard_dual_stack_component_missing", "standardAxes.allowNulls", "左侧分项缺失不能补零或构造不完整堆叠；右轴折线可显式保留缺失。")
    try:
        boundaries, totals = dual_stack_levels(series, components)
    except (ValueError, OverflowError):
        fail("standard_dual_stack_overflow", "standardAxes", "堆叠边界溢出或贡献在累计尺度中不可表示。")
    if total is not None and any(value is None or not math.isclose(value, expected, rel_tol=1e-12, abs_tol=0)
                                 for value, expected in zip(series[total], totals, strict=True)):
        fail("standard_dual_stack_total_mismatch", "standardTotalField", "冻结总额须与换算后的左侧有符号分项净和对账，右轴字段不计入总额。")
    policy["dual_stack"] = {"components": components, "right": list(axes["right_fields"])}
    if policy["legend_position"] == "auto" and len(components) + (form == "stacked-total") > 3:
        # Both value axes share one plotting rectangle. The ordinary >3-series
        # outside anchor has no reserved column here; choose bounded inside
        # placement and let the shared collision scorer place both legends.
        policy["legend_position"] = "inside"
    notes = ["堆叠双轴：左侧分项按正负分别累计；右轴折线独立单位，未计入分项合计"]
    if form == "stacked-total":
        notes.append("总额为左侧有符号分项净和，非正负外包络" + ("；冻结总额已对账，未重复堆叠" if total else "；服务端计算，未增加来源事实"))
    for name in axes["right_fields"]:
        missing = sum(value is None for value in series[name])
        if missing:
            notes.append(f"{name} 缺失{missing}点，保留断点，未补零")
    note = policy["presentation"]["source_note"]
    policy["presentation"]["source_note"] = "\n".join([*([note] if note else []), *notes])


def dual_stack_profiles(config, document):
    policy = config[14]
    series = dual_stack_values(config, document)
    boundaries, totals = dual_stack_levels(series, policy["dual_stack"]["components"])
    result = {}
    for index, name in enumerate(config[6]):
        values = [value for value in series[name] if value is not None]
        if name in boundaries:
            starts, ends = boundaries[name]
            values = [value for pair in zip(starts, ends, strict=True) for value in pair]
        result[name] = {"values": values, "unit": policy["axis_units"][index]}
    if config[4] == "stacked-total" and config[13] is None:
        # The calculated net sum belongs only to the left axis.
        # Attach calculated line endpoints to a real left-axis profile instead
        # of inventing a dictionary key which could collide with a source field.
        result[policy["dual_stack"]["components"][0]]["values"].extend(totals)
    return result


DUAL_STACK_DISPATCH = '''    if canvas.get("dual_stack"):
        render_dual_stack(payload,canvas,form,title,output_path,label_column,value_columns,metadata,input_path)
        continue
'''


DUAL_STACK_SCRIPT = '''def render_dual_stack(payload,canvas,form,title,output_path,label_column,fields,metadata,input_path):
    import math
    from fractions import Fraction
    import matplotlib.pyplot as plt
    columns,rows=payload["columns"],payload["rows"]
    labels=[row[columns.index(label_column)] for row in rows]
    spec=canvas["dual_stack"]
    components=spec["components"]
    right=spec["right"]
    total=canvas["total_field"]
    names=canvas["series_names"]
    series={name:[float("nan") if row[columns.index(name)] is None else row[columns.index(name)]*factor*(100 if meta.get("unit")=="%" and meta.get("isPercent") is False else 1)
                  for row in rows] for name,factor,meta in zip(fields,canvas["axis_factors"],metadata)}
    positive=[Fraction(0)]*len(labels)
    negative=positive.copy()
    starts,ends={},{}
    for name in components:
        starts[name],ends[name]=[],[]
        for i,value in enumerate(series[name]):
            target=negative if value<0 else positive
            starts[name].append(float(target[i]))
            target[i]+=Fraction(value)
            ends[name].append(starts[name][-1]+value)
    totals=[float(p+n) for p,n in zip(positive,negative)]
    fig,left=plt.subplots(**create_standard_canvas(canvas,labels,form))
    right_axis=left.twinx()
    positions=list(range(len(labels)))
    for name in components:
        left.bar(positions,series[name],bottom=starts[name],width=canvas["style"]["bar_group_width"],label=name+" · 左轴")
    if form=="stacked-total":
        caption=total+"（独立冻结总额，已对账）" if total else "分项合计（服务端求和）"
        left.plot(positions,series[total] if total else totals,marker="o",label=caption)
    for name in right:
        right_axis.plot(positions,series[name],marker="o",label=name+" · 右轴")
    left.set_ylabel("左轴 · "+canvas["axis_units"][fields.index(components[0])])
    right_axis.set_ylabel("右轴 · "+canvas["axis_units"][fields.index(right[0])])
    left.set_xticks(positions,standard_label_names(labels,canvas))
    left.legend(frameon=False,loc="upper left")
    right_axis.legend(frameon=False,loc="upper right")
    precision=canvas["style"]["decimals"]
    annotations=[(item["kind"],names.index(item["series"]) if item["series"] in names else None,labels.index(item["label"]) if item["label"] in labels else None,None)
                 for item in canvas["annotation_specs"]]
    for number,item in enumerate(canvas["annotation_specs"]):
        kind=item["kind"]
        if kind=="range":
            left.axvspan(labels.index(item["label"])-.4,labels.index(item["end_label"])+.4,color=item["color"] or "#e8ae53",alpha=.12)
            continue
        name=item["series"] or names[0]
        index=names.index(name)
        axis=right_axis if name in right else left
        values=series[name]
        finite=[value for value in values if math.isfinite(value)]
        if not finite:
            continue
        unit=canvas["axis_units"][fields.index(name)]
        if kind=="reference":
            i=labels.index(item["label"])
            value=values[i]
            # A reference to a component denotes its frozen height, not its cumulative boundary.
            axis.axhline(value,color=item["color"] or "#b55d68",linestyle="--",linewidth=1.2)
            axis.text(.99,value,(item["caption"] or "参考 "+item["label"])+": "+format_standard_number(value,precision)+unit,
                      transform=axis.get_yaxis_transform(),ha="right",va="bottom",fontsize=8)
            continue
        indexes=([labels.index(item["label"])] if kind=="point" else [i for i,value in enumerate(values) if math.isfinite(value) and (kind=="values" or value==(max(finite) if kind=="peak" else min(finite)))])
        for i in indexes:
            value=values[i]
            if not math.isfinite(value) or kind=="values" and not standard_values_label_visible(i,index,annotations,[series[n] for n in names]):
                continue
            endpoint=ends[name][i] if name in ends else value
            caption=item["caption"] or name
            prefix={"peak":"峰值 ","trough":"谷值 ","point":"重点 "}.get(kind,"")
            text=prefix+caption+": "+format_standard_number(value,precision)+unit
            extra=canvas["presentation"]["extras"].get((labels[i],name),"")
            auxiliary=[]
            for field in AUXILIARY.get(input_path,()):
                meta=payload["columnMeta"][field]
                auxiliary_value=rows[i][columns.index(field)]*(100 if meta["unit"]=="%" and meta.get("isPercent") is False else 1)
                auxiliary.append(field+": "+format_standard_number(auxiliary_value,precision)+meta["unit"])
            suffix=" / ".join([*auxiliary,*([extra] if extra else [])])
            annotation=standard_annotation(axis,text+(" · "+suffix if suffix else ""),(i,endpoint),canvas,number,standard_series_color(name,canvas))
            annotation.set_bbox(dict(boxstyle="round,pad=.18",fc="white",ec="none",alpha=.94))
    fig.suptitle(title)
    finish_standard_layout(fig,canvas)
    save_standard_canvas(fig,output_path,canvas)
    plt.close(fig)

'''
