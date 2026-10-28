"""Offline replay of the uploaded OS report; explicit manual standard parameters."""

import hashlib
import json
import subprocess
import sys
import tarfile
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from scripts.replay_standard_visualization_variants import AUDITOR, plan_from_saved
from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
    _table_for_binding,
)
from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_script,
)


def parameters(title, form, fields, **options):
    return dict(
        chart_id="replay",
        renderer="matplotlib",
        interactive_path=None,
        source_path="standard.png",
        title=title,
        visual_form=form,
        standard_value_fields=fields,
        standard_canvas={"sizeMode": "fixed", "width": 14, "height": 8, "dpi": 150},
        standard_style={
            "labelRotation": 0,
            "titleFontSize": 16,
            "annotationFontSize": 8,
            "annotationOffsetX": 0,
            "annotationOffsetY": 9,
            "valueMargin": 0.3,
        },
        standard_presentation={"sourceNote": "数据来源：原报告登记的冻结事实及补证。"},
        **options,
    )


def select(index, docs):
    """Policies use frozen field names; no copied values from original PNGs."""
    titles = [
        "医疗收入月度净额与环比",
        "收入类型构成",
        "收入环比变化分项归因",
        "医疗收入预算执行",
        "预算偏差前8项",
        "门诊人次与每门诊人次收入",
        "成本月度走势",
        "成本类型构成",
        "成本环比变化",
        "月度预算支出与实际支出",
        "预算类型支出执行前10项",
        "预算、合同与支付项目汇总",
        "门诊与出院人次月度走势",
        "院区工作量占比",
        "门诊与出院科室前10项",
        "实际与预算医疗收入期间覆盖",
    ]
    p = parameters(titles[index - 1], "bar", [])

    def update(**options):
        p.update(options)

    def sources(specs):
        return [
            dict(sourceIndex=i, labelField=label, valueField=value, seriesName=name, **extra)
            for i, label, value, name, extra in specs
        ]

    def dual(right, **extra):
        return dict(mode="dual", rightFields=right, **extra)

    def annotations(fields):
        return [dict(kind="values", series=name) for name in fields]

    note = "标准参数回放；统一报告主题，未逐像素复刻原图。"
    if index == 1:
        update(
            standard_label_field="月份",
            standard_value_fields=["医疗收入总额", "计算环比"],
            standard_derivations=[
                dict(
                    kind="mom_percent", name="计算环比", numerator="医疗收入总额", labelField="月份"
                )
            ],
            standard_axes=dual(["计算环比"], allowNulls=True, leftDisplayUnit="亿元"),
        )
        p["standard_presentation"]["subtitle"] = "环比由连续月份收入计算；首月无基数保留空位"
        note = "显式月份列；从冻结收入计算环比，不猜原未登记比例的单位；首月断点，左右轴亿元/%。"
    elif index == 2:
        update(
            visual_form="barh",
            standard_value_fields=["amount"],
            standard_display_unit="亿元",
            standard_annotations=annotations(["amount"]),
        )
        p["standard_presentation"].update(
            order=dict(mode="value", field="amount", descending=True),
            labelFormats=[dict(field="share_pct", caption="占比")],
        )
    elif index == 3:
        names = ["2025-03-01", "2025-11-01"]
        update(
            standard_label_field="income_type",
            standard_value_fields=names,
            standard_display_unit="亿元",
            standard_view=dict(
                kind="pivot",
                labelField="income_type",
                valueFields=["mom_diff"],
                seriesField="period",
                seriesValues=names,
            ),
        )
        p["standard_presentation"].update(
            order=dict(mode="max_abs", fields=names, descending=True),
            subtitle="按两个月最大绝对变化额排序",
        )
        p["standard_style"]["series"] = [
            dict(series=names[0], label="3月"),
            dict(series=names[1], label="11月"),
        ]
        note = "收入类型×两个冻结期间透视，11类全部保留；按两列最大绝对变化额降序，支持负数。"
    elif index == 4:
        update(
            standard_value_fields=["预算医疗收入", "实际医疗收入", "完成率"],
            standard_sources=sources(
                [
                    (0, "period", "value", "预算医疗收入", dict(labelMode="month")),
                    (1, "period", "value", "实际医疗收入", dict(labelMode="month")),
                    (
                        2,
                        "期间",
                        "完成率(%)",
                        "完成率",
                        dict(labelMode="month", excludedLabels=["全年累计"]),
                    ),
                ]
            ),
            standard_labels=[f"2025-{m:02}" for m in range(1, 13)],
            standard_axes=dual(["完成率"], leftDisplayUnit="亿元"),
        )
        note = "保留原3来源绑定；明确月度规范化、排除合计、选择共同12个月，左轴亿元右轴%。"
    elif index == 5:
        update(
            visual_form="barh",
            standard_value_fields=["deviation"],
            standard_display_unit="亿元",
            standard_annotations=[dict(kind="values", series="deviation", position="left")],
        )
        p["standard_presentation"].update(
            order=dict(mode="value", field="deviation", limit=8),
            labelFormats=[dict(field="deviation_rate", caption="偏差率")],
            subtitle="偏差金额前8项排序子集，不代表完整构成",
        )
    elif index == 6:
        update(
            standard_value_fields=["门诊人次", "每门诊人次收入"],
            standard_sources=sources(
                [
                    (
                        0,
                        "月份",
                        "门诊人次",
                        "门诊人次",
                        dict(labelMode="month", excludedLabels=["年度合计"]),
                    ),
                    (1, "月份", "每门诊人次收入(元)", "每门诊人次收入", dict(labelMode="month")),
                ]
            ),
            standard_labels=[f"2025-{m:02}" for m in range(1, 13)],
            standard_axes=dual(["每门诊人次收入"], allowNulls=True, leftDisplayUnit="万人次"),
        )
        note = "原双来源12个月对齐；保留11—12月零门诊人次和缺失单位人次收入，不裁掉月份或补零。"
    elif index == 7:
        update(
            standard_value_fields=["value"],
            standard_display_unit="亿元",
            standard_annotations=annotations(["value"]),
        )
        p["standard_presentation"]["labelMode"] = "month"
    elif index == 8:
        update(
            visual_form="barh",
            standard_value_fields=["成本金额"],
            standard_display_unit="亿元",
            standard_annotations=annotations(["成本金额"]),
        )
        p["standard_presentation"].update(
            order=dict(mode="value", field="成本金额", descending=True),
            labelFormats=[dict(field="占比", caption="占比")],
        )
    elif index == 9:
        update(
            standard_value_fields=["环比差额", "环比变化率"],
            standard_axes=dual(["环比变化率"], allowNulls=True, leftDisplayUnit="亿元"),
        )
        p["standard_presentation"].update(
            labelMode="month", subtitle="首月无上月基数；差额与变化率保留空位"
        )
        p["standard_style"]["points"] = [
            dict(series="环比差额", label=row[0], color="#c0504d" if row[3] > 0 else "#4a7ebb")
            for row in docs[0]["rows"]
            if row[3] is not None
        ]
        note = "保留1—9月，首月差额与变化率为空；正负柱红蓝，左轴亿元右轴%。"
    elif index == 10:
        update(
            standard_value_fields=["budget_expenditure", "actual_expenditure", "completion_rate"],
            standard_axes=dual(["completion_rate"], leftDisplayUnit="亿元"),
            standard_labels=[f"2025-{m:02}" for m in range(1, 13)],
        )
        p["standard_presentation"]["labelMode"] = "month"
        p["standard_style"]["series"] = [
            dict(series=name, label=label)
            for name, label in zip(p["standard_value_fields"], ["预算支出", "实际支出", "完成率"])
        ]
        note = "12个月预算/实际/完成率，保留一月大额原值及末月零值；亿元/%和中文图例。"
    elif index == 11:
        update(
            visual_form="barh",
            standard_value_fields=["budget_expenditure", "actual_expenditure"],
            standard_display_unit="亿元",
        )
        p["standard_presentation"].update(
            order=dict(mode="value", field="budget_expenditure", descending=True, limit=10),
            subtitle="预算规模前10项（含合计），排序子集",
            labelFormats=[
                dict(field="completion_rate", caption="完成率", series=["actual_expenditure"])
            ],
        )
        update(
            standard_annotations=[
                dict(kind="values", series=name, position="right")
                for name in p["standard_value_fields"]
            ]
        )
        p["standard_style"]["series"] = [
            dict(series=name, label=label)
            for name, label in zip(p["standard_value_fields"], ["预算支出", "实际支出"])
        ]
    elif index == 12:
        fields = ["budget_project_amount", "contract_amount", "payment_amount"]
        update(
            standard_label_field="budget_type",
            standard_value_fields=fields,
            standard_display_unit="亿元",
            standard_view=dict(kind="group", labelField="budget_type", valueFields=fields),
        )
        p["standard_presentation"].update(
            subtitle="仅汇总绑定的36条项目明细，不代表全院总体",
            labelFormats=[
                dict(
                    numerator="contract_amount",
                    denominator="budget_project_amount",
                    caption="合同率",
                    series=["contract_amount"],
                ),
                dict(
                    numerator="payment_amount",
                    denominator="budget_project_amount",
                    caption="支付率",
                    series=["payment_amount"],
                ),
            ],
        )
        update(
            standard_annotations=[
                dict(kind="values", series=name, caption=label)
                for name, label in zip(fields, ["预算", "合同", "支付"])
            ]
        )
        p["standard_style"]["series"] = [
            dict(series=name, label=label) for name, label in zip(fields, ["预算", "合同", "支付"])
        ]
        p["standard_canvas"]["width"] = 17
        p["standard_style"]["annotationFontSize"] = 8
        note = "36条项目明细按预算类型汇总；合同率/支付率由汇总后分子分母计算，不求和明细百分比。"
    elif index == 13:
        update(
            visual_form="line",
            standard_value_fields=["门诊人次", "出院人次"],
            standard_sources=sources(
                [(0, "period", "value", "门诊人次", {}), (1, "period", "value", "出院人次", {})]
            ),
            standard_axes=dual(["出院人次"], leftDisplayUnit="万人次", rightDisplayUnit="万人次"),
        )
        p["standard_presentation"]["labelMode"] = "month"
        p["standard_style"]["series"] = [
            dict(series="门诊人次", color="#1f77b4"),
            dict(series="出院人次", color="#d62728", marker="s"),
        ]
    elif index == 14:
        fields = ["门诊人次占比", "出院人次占比", "实际开放床日数占比", "出院者占用床日数占比"]
        update(standard_value_fields=fields)
        p["standard_style"]["series"] = [
            dict(series=name, color=color)
            for name, color in zip(fields, ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e"])
        ]
        p["standard_presentation"]["subtitle"] = "5院区完整范围｜4类工作量占比（%）"
    elif index == 15:
        fields = ["门诊人次", "出院人次"]
        update(
            visual_form="barh",
            standard_label_field="stlevel_analytic_unit",
            standard_value_fields=fields,
            standard_axes=dict(mode="panels", panelLimit=10),
            standard_display_unit="万人次",
        )
        p["standard_presentation"]["subtitle"] = "两个指标分别排序前10科室，不代表完整分布"
        rows = [dict(zip(docs[0]["columns"], row)) for row in docs[0]["rows"]]
        ordered = []
        for field in fields:
            for row in sorted(rows, key=lambda row: row[field], reverse=True)[:10]:
                if row["stlevel_analytic_unit"] not in ordered:
                    ordered.append(row["stlevel_analytic_unit"])
        from matplotlib.colors import to_hex

        colors = {name: to_hex(plt.get_cmap("tab20")(i % 20)) for i, name in enumerate(ordered)}
        p["standard_style"]["points"] = [
            dict(series=field, label=name, color=color)
            for field in fields
            for name, color in colors.items()
        ]
        p["standard_style"]["annotationFontSize"] = 8
        p["standard_canvas"]["width"] = 19
        p["standard_canvas"]["labelWrap"] = 12
        update(
            standard_annotations=[
                dict(kind="values", series=field, caption="", position="right") for field in fields
            ]
        )
        note = (
            "单张图两个横向面板，各自按指标独立排序Top10；同科室跨面板同色，万人次换算仅改变显示。"
        )
    else:
        update(
            standard_value_fields=["实际医疗收入", "预算医疗收入"],
            standard_display_unit="亿元",
            standard_sources=sources(
                [
                    (0, "period", "value", "实际医疗收入", {}),
                    (1, "period", "value", "预算医疗收入", {}),
                ]
            ),
        )
        p["standard_style"]["series"] = [
            dict(series="实际医疗收入", geometry="bar", color="#3066a3"),
            dict(
                series="预算医疗收入",
                geometry="line",
                color="#c44e52",
                lineStyle="--",
                marker="none",
            ),
        ]
        p["standard_presentation"]["labelMode"] = "month"
        note = "同一亿元轴柱图+预算水平线；保持同单位同尺度，不借用右轴。"
    if p["visual_form"] == "barh":
        p["standard_style"].update(
            grid="x", annotationOffsetX=8, annotationOffsetY=0, valueMargin=0.5
        )
    return p, [], note


def expected_plot(params, docs):
    """Independent arithmetic oracle: does not call production transforms."""
    import math

    sources = params.get("standard_sources", [])
    if sources:
        lookups = []
        for selection in sources:
            doc = docs[selection["sourceIndex"]]
            li = doc["columns"].index(selection["labelField"])
            vi = doc["columns"].index(selection["valueField"])
            lookup = {}
            for row in doc["rows"]:
                label = row[li]
                if label in selection.get("excludedLabels", []):
                    continue
                if selection.get("labelMode") == "month":
                    label = label[:7]
                assert label not in lookup
                lookup[label] = row[vi]
            lookups.append(lookup)
        labels = params.get("standard_labels") or list(lookups[0])
        assert all(set(labels).issubset(item) for item in lookups)
        rows = [
            dict(
                label=label,
                **{
                    selection["seriesName"]: lookup[label]
                    for selection, lookup in zip(sources, lookups)
                },
            )
            for label in labels
        ]
        label = "label"
        metadata = {
            selection["seriesName"]: docs[selection["sourceIndex"]]["columnMeta"][
                selection["valueField"]
            ]
            for selection in sources
        }
    else:
        doc = docs[0]
        rows = [dict(zip(doc["columns"], row)) for row in doc["rows"]]
        metadata = dict(doc.get("columnMeta") or {})
        text = [
            column for column in doc["columns"] if all(isinstance(row[column], str) for row in rows)
        ]
        label = params.get("standard_label_field") or (
            "period"
            if "period" in doc["columns"]
            else "label"
            if "label" in doc["columns"]
            else text[0]
        )
    view = params.get("standard_view")
    if view:
        label = view["labelField"]
        groups = {}
        if view["kind"] == "group":
            for row in rows:
                group = groups.setdefault(row[label], {field: [] for field in view["valueFields"]})
                for field in view["valueFields"]:
                    group[field].append(row[field])
            rows = [
                {label: key, **{field: math.fsum(values) for field, values in group.items()}}
                for key, group in groups.items()
            ]
        else:
            field = view["valueFields"][0]
            names = view["seriesValues"]
            for row in rows:
                if row[view["seriesField"]] in names:
                    group = groups.setdefault(row[label], {})
                    assert row[view["seriesField"]] not in group
                    group[row[view["seriesField"]]] = row[field]
            rows = [{label: key, **group} for key, group in groups.items()]
            metadata = {name: metadata[field] for name in names}
    for spec in params.get("standard_derivations", []):
        assert spec["kind"] == "mom_percent"
        rows.sort(key=lambda row: row[spec["labelField"]])
        for i, row in enumerate(rows):
            previous = rows[i - 1][spec["numerator"]] if i else None
            row[spec["name"]] = (
                (row[spec["numerator"]] - previous) / previous * 100
                if previous and previous > 0
                else None
            )
        metadata[spec["name"]] = {"unit": "%", "isPercent": True}
    if params.get("standard_labels"):
        rows = [row for row in rows if row[label] in params["standard_labels"]]
    order = params.get("standard_presentation", {}).get("order", {})
    if order.get("mode") == "value":
        rows = sorted(
            rows, key=lambda row: row[order["field"]], reverse=order.get("descending", False)
        )
    if order.get("mode") == "max_abs":
        rows = sorted(
            rows,
            key=lambda row: max(abs(row[field]) for field in order["fields"]),
            reverse=order.get("descending", False),
        )
    if order.get("limit"):
        rows = rows[: order["limit"]]
    axes = params.get("standard_axes", {})
    form = params["visual_form"]
    styles = params.get("standard_style", {})
    scales = {"元": 1, "万元": 1e4, "亿元": 1e8, "人次": 1, "万人次": 1e4}
    result = []
    for number, name in enumerate(params["standard_value_fields"]):
        shown = rows
        if axes.get("mode") == "panels" and form == "barh":
            shown = sorted(
                rows, key=lambda row: row[name], reverse=axes.get("panelDescending", True)
            )[: axes.get("panelLimit", len(rows))]
        values = [row[name] for row in shown]
        meta = metadata[name]
        right = name in axes.get("rightFields", [])
        unit = axes.get("rightDisplayUnit" if right else "leftDisplayUnit") or params.get(
            "standard_display_unit"
        )
        factor = scales[meta["unit"]] / scales[unit] if unit else 1
        factor *= 100 if meta.get("unit") == "%" and meta.get("isPercent") is False else 1
        values = [None if value is None else value * factor for value in values]
        caption = name + (" · 右轴" if right else " · 左轴") if axes.get("mode") == "dual" else name
        style = next((item for item in styles.get("series", []) if item["series"] == name), {})
        kind = style.get("geometry") or (
            "line" if form == "line" or axes.get("mode") == "dual" and right else "bar"
        )
        item = dict(name=caption, kind=kind, values=values)
        if form == "barh":
            base = style.get("color", ["#3066a3", "#dc884d"][number % 2])
            item["colors"] = [
                next(
                    (
                        point["color"]
                        for point in styles.get("points", [])
                        if point["series"] == name and point["label"] == row[label]
                    ),
                    base,
                )
                for row in shown
            ]
        result.append(item)
    return {"series": result}


def main():
    archive_path, output_path = sys.argv[1:3]
    output = Path(output_path).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in ["replay.json", "comparison.pdf", "README.md"]:
        (output / name).unlink(missing_ok=True)
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        index_member = next(
            m for m in members if m.name.endswith("/revision-2/trace-index-v1.json")
        )
        index = json.load(archive.extractfile(index_member))
        registered = {f["resourceId"]: f for f in index["files"]}
        wanted = {"workspace/" + f["path"]: rid for rid, f in registered.items()}
        data = {}
        for member in members:
            if member.name in wanted:
                assert member.isfile()
                raw = archive.extractfile(member).read()
                rid = wanted[member.name]
                identity = registered[rid]
                assert (
                    len(raw) == identity["size"]
                    and hashlib.sha256(raw).hexdigest() == identity["sha256"]
                ), identity["path"]
                data[rid] = raw
        assert len(data) == len(registered)
    print("verified registered resources:", len(data), flush=True)
    records = []
    for position, trace in enumerate(index["chartTraces"], 1):
        folder = output / f"chart-{position:03}"
        folder.mkdir(exist_ok=True)
        (folder / "original.png").write_bytes(data[trace["imageFileResourceId"]])
        documents = []
        inputs = []
        provenance = []
        for source_index, rid in enumerate(trace["plotDataFileResourceIds"]):
            raw = data[rid]
            original = json.loads(raw)
            doc = original
            (folder / f"frozen-input-{source_index}.json").write_bytes(raw)
            source = doc.get("source", {})
            fact_rid = next(
                (
                    key
                    for key, value in registered.items()
                    if value["sha256"] == source.get("sha256")
                ),
                None,
            )
            if fact_rid:
                fact_raw = data[fact_rid]
                binding = ChartDataBinding(
                    analysisId=source["analysisId"],
                    factPath=source["path"],
                    dataPath=source["dataPath"],
                    fields=doc["columns"],
                    role=doc["role"],
                )
                columns, rows, metadata = _table_for_binding(json.loads(fact_raw), binding)
                assert columns == doc["columns"] and rows == doc["rows"]
                if metadata and metadata != doc.get("columnMeta"):
                    doc = {**doc, "columnMeta": metadata}
                    raw = (
                        json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"
                    ).encode()
                (folder / f"source-{source_index}.json").write_bytes(fact_raw)
            documents.append(doc)
            inputs.append(raw)
            provenance.append(
                {
                    "originalSha256": registered[rid]["sha256"],
                    "originalResource": rid,
                    "inputSha256": hashlib.sha256(raw).hexdigest(),
                    "metadataReprojected": doc != original,
                    "factResource": fact_rid,
                }
            )
        initial, extra, note = select(position, documents)
        if position == 1:
            # The archived original renderer explicitly multiplied this raw field by 100.
            # This check belongs to the report oracle, never to production unit inference.
            rows = [dict(zip(documents[0]["columns"], row)) for row in documents[0]["rows"]]
            for previous, row in zip(rows, rows[1:]):
                expected = (row["医疗收入总额"] - previous["医疗收入总额"]) / previous[
                    "医疗收入总额"
                ]
                assert abs(expected - row["环比变化率"]) < 1e-10
        candidates = [("strict", list(range(len(inputs))), initial)]
        candidates.extend(extra)
        outcomes = []
        for number, (mode, selected, params) in enumerate(candidates):
            work = folder / f"candidate-{number}"
            work.mkdir(exist_ok=True)
            for stale in ["standard.png", "audit.json", "render.py"]:
                (work / stale).unlink(missing_ok=True)
            (work / "parameters.json").write_text(json.dumps(params, ensure_ascii=False, indent=2))
            expected = expected_plot(params, [documents[k] for k in selected])
            (work / "expectations.json").write_text(
                json.dumps(expected, ensure_ascii=False, indent=2)
            )
            plan = plan_from_saved(params)
            files = tuple(
                ChartInputFile(f"input-{j}.json", inputs[k]) for j, k in enumerate(selected)
            )
            bound = ChartInputMaterialization(
                files=files,
                entries=tuple(
                    {"chartId": "replay", "path": file.path, "sha256": file.sha256}
                    for file in files
                ),
            )
            for file in files:
                (work / file.path).write_bytes(file.content)
            script = standard_visualization_script(plan, bound)
            result = {
                "mode": mode,
                "selectedOriginalInputs": selected,
                "status": "preflight_fallback",
                "directory": str(work.relative_to(output)),
            }
            if script:
                (work / "render.py").write_text(script)
                (work / "audit.py").write_text(AUDITOR)
                run = subprocess.run(
                    [sys.executable, "audit.py"],
                    cwd=work,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if run.returncode:
                    result.update(status="render_requires_repair", error=run.stderr[-2000:])
                else:
                    audit = json.loads((work / "audit.json").read_text())
                    issues = (
                        audit["outsideCanvas"]
                        or audit["categoryTickCollisions"]
                        or audit["semanticMismatches"]
                    )
                    result.update(
                        status="audit_issue" if issues else "rendered",
                        audit=audit,
                        image=str((work / "standard.png").relative_to(output)),
                        seriesVerified=len(expected.get("series", [])),
                    )
            for file in files:
                assert (work / file.path).read_bytes() == file.content
            outcomes.append(result)
        successful = [item for item in outcomes if item["status"] == "rendered"]
        status = successful[-1]["mode"] if successful else "uncovered"
        records.append(
            {
                "number": position,
                "chartId": trace["chartId"],
                "status": status,
                "notes": note,
                "sources": provenance,
                "candidates": outcomes,
            }
        )
        print(position, status, [item["status"] for item in outcomes], flush=True)
    counts = {
        kind: sum(record["status"] == kind for record in records)
        for kind in sorted({record["status"] for record in records})
    }
    report = {
        "mode": "offline_manual_standard_replay_not_online_route_hit",
        "archiveSha256": hashlib.sha256(Path(archive_path).read_bytes()).hexdigest(),
        "codeCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "workingTreeDirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        ),
        "registeredResourcesVerified": len(data),
        "originalCharts": len(records),
        "counts": counts,
        "originalInputValuesUnchanged": True,
        "onlineVisualGatesExecuted": False,
        "results": records,
    }
    (output / "replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    with PdfPages(output / "comparison.pdf") as pdf:
        for record in records:
            fig = plt.figure(figsize=(20, 11), dpi=150, facecolor="#f4f6f8")
            folder = output / f"chart-{record['number']:03}"
            fig.text(
                0.035,
                0.965,
                f"{record['number']:02}  原报告与标准可视化对比｜{record['status']}",
                fontsize=18,
                weight="bold",
            )
            fig.text(0.035, 0.92, "左：原报告图表", fontsize=13)
            fig.text(0.52, 0.92, "右：当前标准参数回放（具体差异见下方）", fontsize=13)
            ax = fig.add_axes([0.025, 0.2, 0.475, 0.68])
            ax.imshow(plt.imread(folder / "original.png"))
            ax.axis("off")
            images = [
                candidate["image"]
                for candidate in record["candidates"]
                if candidate["status"] == "rendered"
            ]
            if record["number"] != 15:
                images = images[-1:]
            if images:
                for j, picture in enumerate(images):
                    ax = fig.add_axes(
                        [0.52 + j * 0.475 / len(images), 0.2, 0.47 / len(images), 0.68]
                    )
                    ax.imshow(plt.imread(output / picture))
                    ax.axis("off")
            else:
                ax = fig.add_axes([0.52, 0.2, 0.47, 0.68])
                ax.axis("off")
                ax.text(
                    0.5,
                    0.5,
                    "标准路线未覆盖\n\n" + textwrap.fill(record["notes"], 27),
                    ha="center",
                    va="center",
                    fontsize=14,
                    color="#9a3412",
                    linespacing=1.7,
                )
            fig.text(
                0.035,
                0.135,
                textwrap.fill(record["notes"], 100),
                fontsize=11,
                color="#334155",
                va="top",
                linespacing=1.6,
            )
            fig.text(
                0.035,
                0.025,
                "离线人工选参｜登记来源校验size/SHA256｜保留原输入，单位仅从对应冻结事实继承｜未运行线上模型与独立视觉验收",
                fontsize=9,
                color="#64748b",
            )
            fig.savefig(output / f"comparison-{record['number']:03}.png")
            pdf.savefig(fig)
            plt.close(fig)
    text = [
        "# OS综合运营分析报告标准可视化回放",
        "",
        f"16张原图、21份图表输入；全部{len(data)}项登记资源核验size/SHA256。",
        "原输入字节保留；缺失单位只从对应登记事实重新物化，columns/rows不变。原计划未保存，人工按原图选参；不代表线上路由命中率或视觉验收通过。",
        "",
        json.dumps(counts, ensure_ascii=False),
        "",
        "| 图号 | 结果 | 差异/缺口 |",
        "|---|---|---|",
    ]
    text += [f"| {r['number']:02} | {r['status']} | {r['notes']} |" for r in records]
    (output / "README.md").write_text("\n".join(text))
    print(counts)
    if counts != {"strict": 16}:
        raise SystemExit("Not all 16 charts passed independent replay")


if __name__ == "__main__":
    main()

