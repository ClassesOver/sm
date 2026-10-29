"""Replay every saved chart with changed data; no model or online visual gate calls."""
import argparse
import copy
import hashlib
import html
import json
import math
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from scripts.standard_visualization_box_summary_cases import summary_cases
from scripts.standard_visualization_break_cases import break_cases
from scripts.standard_visualization_domain_cases import domain_cases
from scripts.standard_visualization_dual_stack_cases import dual_stack_cases
from scripts.standard_visualization_geometry_cases import geometry_cases
from scripts.standard_visualization_horizontal_break_cases import horizontal_break_cases
from scripts.standard_visualization_pipeline_cases import pipeline_cases
from scripts.standard_visualization_statistics_cases import statistics_cases
from scripts.standard_visualization_stress_cases import extended_cases
from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    StandardChartAnnotation,
    StandardChartAxes,
    StandardChartAxisBreak,
    StandardChartBand,
    StandardChartBoxSummary,
    StandardChartCanvas,
    StandardChartDerivation,
    StandardChartDistribution,
    StandardChartDomains,
    StandardChartEncoding,
    StandardChartPresentation,
    StandardChartSource,
    StandardChartStep,
    StandardChartStyle,
    StandardChartView,
    StandardChartWaterfall,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_script,
)

MODELS = {'standard_canvas': StandardChartCanvas, 'standard_style': StandardChartStyle,
          'standard_presentation': StandardChartPresentation, 'standard_axes': StandardChartAxes,
          'standard_view': StandardChartView, 'standard_encoding': StandardChartEncoding,
          'standard_waterfall': StandardChartWaterfall, 'standard_distribution': StandardChartDistribution,
          'standard_domains': StandardChartDomains, 'standard_break': StandardChartAxisBreak,
          'standard_box_summary': StandardChartBoxSummary}
LIST_MODELS = {'standard_annotations': StandardChartAnnotation, 'standard_sources': StandardChartSource,
               'standard_derivations': StandardChartDerivation, 'standard_steps': StandardChartStep,
               'standard_bands': StandardChartBand}
AUDITOR = '''import json, runpy, math, re
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.text import Text, Annotation
original_save = Figure.savefig
parameters = json.loads(Path("parameters.json").read_text())
horizontal = (parameters["visual_form"] == "barh" or parameters["visual_form"] in {"boxplot", "箱线图"}
              and (parameters.get("standard_distribution") or parameters.get("standard_box_summary") or {}).get("orientation") == "horizontal")

def capture(fig, *args, **kwargs):
    drawn = set()
    original_draw = Text.draw
    def record_draw(text, *args, **kwargs):
        drawn.add(text)
        return original_draw(text, *args, **kwargs)
    Text.draw = record_draw
    try:
        fig.canvas.draw()
    finally:
        Text.draw = original_draw
    renderer = fig.canvas.get_renderer()
    outside = []
    for text in drawn:
        if not text.get_visible() or not text.get_text().strip():
            continue
        bounds = Text.get_window_extent(text, renderer)
        if bounds.x0 < -2 or bounds.y0 < -2 or bounds.x1 > fig.bbox.width + 2 or bounds.y1 > fig.bbox.height + 2:
            outside.append(text.get_text()[:100])
    rounded = []
    for ax in fig.axes:
        for text in ax.texts:
            if isinstance(text, Annotation) and re.match(r"^(?:(?:峰值|谷值|重点) |[^:]+: )?[+-]?0\\.0+(?![0-9])", text.get_text()):
                value = text.xy[0 if horizontal else 1]
                if math.isfinite(float(value)) and value != 0:
                    rounded.append(text.get_text()[:100])
    audit = {"outsideCanvas": outside, "roundedToZeroCandidates": rounded,
             "axes": len(fig.axes), "size": list(fig.get_size_inches()), "dpi": fig.dpi}
    collisions = []
    for ax in fig.axes:
        if getattr(ax, "_standard_colorbar", False):
            continue
        tick_groups = [ax.get_xticklabels(), ax.get_yticklabels()] if json.loads(Path("parameters.json").read_text())["visual_form"] == "heatmap" else [ax.get_yticklabels() if horizontal else ax.get_xticklabels()]
        for ticks in tick_groups:
            boxes = [(tick.get_text(), tick.get_window_extent(renderer)) for tick in ticks if tick in drawn and tick.get_visible()]
            for index, (left_text, left) in enumerate(boxes):
                for right_text, right in boxes[index + 1:]:
                    if left.overlaps(right):
                        collisions.append([left_text, right_text])
    audit["categoryTickCollisions"] = collisions
    mismatches = []
    expectations = json.loads(Path("expectations.json").read_text()) if Path("expectations.json").exists() else {}
    from matplotlib.colors import to_hex
    for expected in expectations.get("series", []):
        artists = [artist for ax in fig.axes if "panel" not in expected or getattr(ax,"_standard_break_panel",None)==expected["panel"]
                   for artist in (ax.lines if expected["kind"] == "line" else ax.containers)
                   if artist.get_label() == expected["name"]]
        if len(artists) != 1:
            mismatches.append("missing_or_ambiguous_series:" + expected["name"])
            continue
        artist = artists[0]
        actual = list(artist.get_ydata()) if expected["kind"] == "line" else [bar.get_width() if horizontal else bar.get_height() for bar in artist]
        wanted = expected["values"]
        if len(actual) != len(wanted) or any(not (math.isnan(a) if b is None else math.isclose(a, b, rel_tol=1e-10, abs_tol=0)) for a, b in zip(actual, wanted)):
            mismatches.append("wrong_values:" + expected["name"])
        if "colors" in expected:
            actual_colors = [to_hex(bar.get_facecolor()) for bar in artist]
            if actual_colors != expected["colors"]:
                mismatches.append("wrong_colors:" + expected["name"])
        if "bottoms" in expected and (len(artist)!=len(expected["bottoms"]) or any(not math.isclose(bar.get_y(),value,rel_tol=1e-10,abs_tol=0) for bar,value in zip(artist,expected["bottoms"]))):
            mismatches.append("wrong_bar_baselines:"+expected["name"])
        for key,values in (("starts", [bar.get_x() for bar in artist] if horizontal else [bar.get_y() for bar in artist]),
                           ("centers", [bar.get_y()+bar.get_height()/2 for bar in artist] if horizontal else [bar.get_x()+bar.get_width()/2 for bar in artist])) if expected["kind"] != "line" else []:
            if key in expected and (len(values)!=len(expected[key]) or any(not math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12) for a,b in zip(values,expected[key]))):
                mismatches.append("wrong_bar_"+key+":"+expected["name"])
    import numpy as np
    def same_value(actual, wanted):
        if wanted is None:
            return bool(np.ma.is_masked(actual) or math.isnan(float(actual)))
        return not np.ma.is_masked(actual) and math.isclose(float(actual), wanted, rel_tol=1e-10, abs_tol=0)
    def check_color(artist, expected):
        if "colorMap" in expected and artist.get_cmap().name != expected["colorMap"]:
            mismatches.append("wrong_color_map:" + expected["name"])
        for key, attribute in (("colorMin", "vmin"), ("colorMax", "vmax")):
            if key in expected and not same_value(getattr(artist.norm, attribute), expected[key]):
                mismatches.append("wrong_color_range:" + expected["name"])
        if "colorCenter" in expected and not math.isclose(float(artist.norm(expected["colorCenter"])), .5):
            mismatches.append("wrong_color_center:" + expected["name"])
    for expected in expectations.get("observations", []):
        artists = [artist for ax in fig.axes for artist in ax.collections
                   if getattr(artist, "_standard_scatter", False) and artist.get_label() == expected["name"]]
        if len(artists) != 1:
            mismatches.append("missing_observations:" + expected["name"])
            continue
        artist = artists[0]
        offsets = artist.get_offsets()
        wanted = expected["offsets"]
        if len(offsets) != len(wanted) or any(not all(same_value(a,b) for a,b in zip(pair, row))
                                              for pair,row in zip(offsets,wanted)):
            mismatches.append("wrong_observation_coordinates:" + expected["name"])
        for key, actual in (("sizes", artist.get_sizes()), ("colorValues", artist.get_array())):
            if key in expected and (actual is None or len(actual) != len(expected[key])
                                    or any(not same_value(a,b) for a,b in zip(actual,expected[key]))):
                mismatches.append("wrong_observation_" + key + ":" + expected["name"])
        if "colorValues" in expected:
            expected_colors = artist.get_cmap()(artist.norm(expected["colorValues"]))
            if not np.allclose(artist.get_facecolors(), expected_colors, rtol=1e-9, atol=1e-12):
                mismatches.append("wrong_mapped_colors:" + expected["name"])
        check_color(artist, expected)
    for expected in expectations.get("matrices", []):
        artists = [artist for ax in fig.axes for artist in ax.images if artist.get_label() == expected["name"]]
        if len(artists) != 1:
            mismatches.append("missing_matrix:" + expected["name"])
            continue
        artist = artists[0]
        actual, wanted = artist.get_array(), expected["values"]
        if actual.shape != (len(wanted),len(wanted[0])) or any(
            not same_value(actual[y,x],value) for y,row in enumerate(wanted) for x,value in enumerate(row)):
            mismatches.append("wrong_matrix_or_mask:" + expected["name"])
        check_color(artist,expected)
    for expected in expectations.get("bands", []):
        artists = [artist for ax in fig.axes if "panel" not in expected or getattr(ax,"_standard_break_panel",None)==expected["panel"] for artist in ax.collections
                   if getattr(artist, "_standard_band", False) and artist.get_label() == expected["name"]]
        if len(artists) != 1:
            mismatches.append("missing_band:" + expected["name"])
            continue
        vertices = [pair for path in artists[0].get_paths() for pair in path.vertices if np.isfinite(pair).all()]
        for index,(low,high) in enumerate(zip(expected["lower"],expected["upper"])):
            found = [y for x,y in vertices if abs(x-index)<1e-9]
            if low is None:
                if found: mismatches.append("filled_missing_band:" + expected["name"])
            elif not found or not same_value(min(found),low) or not same_value(max(found),high):
                mismatches.append("wrong_band_bounds:" + expected["name"])
    for expected in expectations.get("waterfalls", []):
        artists = [artist for ax in fig.axes for artist in ax.containers if getattr(artist,"_standard_waterfall",False)]
        if len(artists)!=1:
            mismatches.append("missing_waterfall")
            continue
        actual = [(bar.get_y(),bar.get_height()) for bar in artists[0]]
        if len(actual)!=len(expected["starts"]) or any(not same_value(start,wanted_start) or not same_value(height,wanted_height)
            for (start,height),wanted_start,wanted_height in zip(actual,expected["starts"],expected["heights"])):
            mismatches.append("wrong_waterfall_levels")
        if "colors" in expected and [to_hex(bar.get_facecolor()) for bar in artists[0]] != expected["colors"]:
            mismatches.append("wrong_waterfall_colors")
        if "positions" in expected and any(not same_value(bar.get_x()+bar.get_width()/2,position) for bar,position in zip(artists[0],expected["positions"])):
            mismatches.append("wrong_waterfall_positions")
        connectors = [line for ax in fig.axes for line in ax.lines if getattr(line,"_standard_connector",False)]
        if "connectors" in expected and (len(connectors)!=len(expected["connectors"]) or any(not same_value(line.get_ydata()[0],value) or not same_value(line.get_ydata()[1],value) for line,value in zip(connectors,expected["connectors"]))):
            mismatches.append("wrong_waterfall_connectors")
        for index,line in enumerate(connectors):
            width = artists[0][index].get_width()
            if not same_value(line.get_xdata()[0],index+width/2) or not same_value(line.get_xdata()[1],index+1-width/2):
                mismatches.append("wrong_waterfall_connector_positions")
    for expected in expectations.get("boxes", []):
        boxes = [patch for ax in fig.axes for patch in ax.patches if getattr(patch,"_standard_box_group",None)==expected["name"]]
        parts = [line for ax in fig.axes for line in ax.lines if getattr(line,"_standard_box_part",(None,None))[0]==expected["name"]]
        coordinate = 0 if expected.get("horizontal") else 1
        if len(boxes)!=1:
            mismatches.append("missing_box:"+expected["name"])
            continue
        coords = boxes[0].get_path().vertices[:,coordinate]
        medians = [line for line in parts if line._standard_box_part[1]=="medians"]
        median = (medians[0].get_xdata() if coordinate==0 else medians[0].get_ydata())[0] if len(medians)==1 else float("nan")
        whiskers = [line for line in parts if line._standard_box_part[1]=="whiskers"]
        tips = [(line.get_xdata() if coordinate==0 else line.get_ydata())[-1] for line in whiskers]
        if len(tips)!=2 or any(not same_value(a,b) for a,b in zip([min(coords),median,max(coords),*tips],expected["statistics"])):
            mismatches.append("wrong_box_statistics:"+expected["name"])
        fliers = [value for line in parts if line._standard_box_part[1]=="fliers" for value in (line.get_xdata() if coordinate==0 else line.get_ydata())]
        if sorted(fliers)!=sorted(expected["fliers"]):
            if len(fliers)!=len(expected["fliers"]) or any(not same_value(a,b) for a,b in zip(sorted(fliers),sorted(expected["fliers"]))):
                mismatches.append("wrong_box_fliers:"+expected["name"])
        if "color" in expected and to_hex(boxes[0].get_facecolor())!=expected["color"]:
            mismatches.append("wrong_box_color:"+expected["name"])
    for expected in expectations.get("domains", []):
        target=fig.axes[expected.get("index",0)]
        if expected.get("inset"):
            target=target.child_axes[0]
        domain_horizontal=expected["coordinate"]=="x"
        limits=target.get_xlim() if domain_horizontal else target.get_ylim()
        if any(not same_value(actual,wanted) for actual,wanted in zip(limits,expected["limits"])):
            mismatches.append("wrong_domain_limits:"+expected["coordinate"])
        if "ticks" in expected:
            ticks=target.get_xticks() if domain_horizontal else target.get_yticks()
            if len(ticks)!=len(expected["ticks"]) or any(not same_value(a,b) for a,b in zip(ticks,expected["ticks"])):
                mismatches.append("wrong_domain_ticks:"+expected["coordinate"])
        if "tickLabels" in expected:
            labels=target.get_xticklabels() if domain_horizontal else target.get_yticklabels()
            if [text.get_text() for text in labels]!=expected["tickLabels"]:
                mismatches.append("wrong_domain_format:"+expected["coordinate"])
        axis=target.xaxis if domain_horizontal else target.yaxis
        boxes=[text.get_window_extent(renderer) for value,text in zip(axis.get_ticklocs(),axis.get_ticklabels()) if text.get_visible() and limits[0]<=value<=limits[1]]
        if any(left.overlaps(right) for i,left in enumerate(boxes) for right in boxes[i+1:]):
            mismatches.append("overlapping_domain_ticks:"+expected["coordinate"])
    for expected in expectations.get("areas", []):
        artists=[artist for ax in fig.axes if getattr(ax,"_standard_break_panel",None)==expected["panel"] for artist in ax.collections if artist.get_label()==expected["name"]]
        if len(artists)!=1:
            mismatches.append("missing_area:"+expected["name"])
            continue
        vertices=[point for path in artists[0].get_paths() for point in path.vertices]
        for i,(low,high) in enumerate(zip(expected["lower"],expected["upper"])):
            values=[y for x,y in vertices if math.isclose(x,i,abs_tol=1e-9)]
            if not values or not same_value(min(values),low) or not same_value(max(values),high):
                mismatches.append("wrong_area_bounds:"+expected["name"])
    for expected in expectations.get("breaks", []):
        sideways=expected.get("orientation")=="horizontal"
        panels={getattr(ax,"_standard_break_panel",None):ax for ax in fig.axes if hasattr(ax,"_standard_break_panel")}
        if set(panels)!={"upper","lower"}:
            mismatches.append("missing_break_panels")
            continue
        for name in ("upper","lower"):
            ax=panels[name]
            if any(not same_value(a,b) for a,b in zip(ax.get_xlim() if sideways else ax.get_ylim(),expected[name])):
                mismatches.append("wrong_break_limits:"+name)
            marks=[line for line in ax.lines if getattr(line,"_standard_axis_break_mark",False)]
            if len(marks)!=expected.get("marksPerPanel",2):
                mismatches.append("missing_break_marks:"+name)
            for i,line in enumerate(marks):
                x,y=line.get_xdata(),line.get_ydata()
                wanted_x=(0 if name=="upper" else 1) if sideways else i
                wanted_y=i if sideways else (0 if name=="upper" else 1)
                if (not line.get_visible() or line.get_clip_on() or line.get_transform()!=ax.transAxes
                    or len(x)!=2 or len(y)!=2 or not math.isclose((x[0]+x[1])/2,wanted_x,abs_tol=1e-9)
                    or not math.isclose((y[0]+y[1])/2,wanted_y,abs_tol=1e-9) or not (x[1]>x[0] and y[1]>y[0])):
                    mismatches.append("wrong_break_marks:"+name)
        upper,lower=panels["upper"].get_position(),panels["lower"].get_position()
        overlaps=lower.x1>=upper.x0 if sideways else lower.y1>=upper.y0
        ratio=lower.width/upper.width if sideways else lower.height/upper.height
        if overlaps or not math.isclose(ratio,expected.get("lowerFraction",.5)/(1-expected.get("lowerFraction",.5)),rel_tol=1e-6):
            mismatches.append("wrong_break_layout")
        if sideways and "categoryLabels" in expected:
            left=panels["lower"]
            if not left.yaxis_inverted() or left.get_ylim()!=panels["upper"].get_ylim() or [tick.get_text() for tick in left.get_yticklabels()]!=expected["categoryLabels"] or any(tick.get_visible() for tick in panels["upper"].get_yticklabels()):
                mismatches.append("wrong_break_categories")
    visible_text = "\\n".join(text.get_text() for text in drawn if text.get_visible())
    for text in expectations.get("texts", []):
        if text not in visible_text:
            mismatches.append("missing_frozen_text:" + text)
    audit["semanticMismatches"] = mismatches
    Path("audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    return original_save(fig, *args, **kwargs)

Figure.savefig = capture
runpy.run_path("render.py", run_name="__main__")
'''


def plan_from_saved(parameters):
    parameters = copy.deepcopy(parameters)
    for key, model in MODELS.items():
        if key in parameters:
            parameters[key] = model.model_validate(parameters[key])
    for key, model in LIST_MODELS.items():
        if key in parameters:
            parameters[key] = tuple(model.model_validate(item) for item in parameters[key])
    return SimpleNamespace(charts=(SimpleNamespace(**parameters),))


def mutate(documents, variant):
    documents = copy.deepcopy(documents)
    for document in documents:
        columns, rows = document['columns'], document['rows']
        metadata = document.get('columnMeta') or {}
        if variant == 'reversed_rows':
            rows.reverse()
        if variant == 'missing_units':
            document.pop('columnMeta', None)
        if variant == 'renamed_columns':
            renames = {name: '新数据_' + name for name in columns if any(isinstance(row[columns.index(name)], (float, int)) for row in rows)}
            document['columns'] = [renames.get(name, name) for name in columns]
            document['columnMeta'] = {renames.get(name, name): meta for name, meta in metadata.items()}
        for row in rows:
            for index, value in enumerate(row):
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                meta = metadata.get(columns[index], {})
                if meta.get('unit') == '%':
                    continue
                factor = {'amounts_small': 1e-10, 'amounts_large': 1e6, 'zero_amounts': 0,
                          'negative_amounts': -1}.get(variant)
                if factor is not None:
                    row[index] = value * factor
                elif variant == 'extreme_spread':
                    label = next((cell for cell in row if isinstance(cell, str)), 'single')
                    factor = 1e-9 if hashlib.sha256(label.encode()).digest()[0] % 2 else 1e6
                    row[index] = value * factor
    return documents


def run_case(case, output, *, plan_factory=plan_from_saved):
    folder = output / case['id']
    folder.mkdir(parents=True, exist_ok=True)
    for path in [folder / name for name in ['standard.png', 'audit.json', 'render.py', 'audit.py']]:
        path.unlink(missing_ok=True)
    for path in [*folder.glob('input-*.json'), *folder.glob('verified-input-*.json')]:
        path.unlink()
    record = {'id': case['id'], 'group': case['group'], 'variant': case['variant'], 'synthetic': case['synthetic']}
    if 'expected' in case:
        record['expected'] = case['expected']
    (folder / 'parameters.json').write_text(json.dumps(case['parameters'], ensure_ascii=False, indent=2))
    (folder / 'expectations.json').write_text(json.dumps(case.get('assertions', {}), ensure_ascii=False, indent=2))
    try:
        plan = plan_factory(case['parameters'])
    except ValidationError as error:
        return {**record, 'status': 'schema_rejected', 'error': str(error)[:1500]}
    files = tuple(ChartInputFile(f'input-{index}.json', json.dumps(document, ensure_ascii=False).encode())
                  for index, document in enumerate(case['documents']))
    inputs = ChartInputMaterialization(files=files, entries=tuple(
        {'chartId': plan.charts[0].chart_id, 'path': source.path, 'sha256': source.sha256} for source in files))
    for source in files:
        (folder / source.path).write_bytes(source.content)
    try:
        script = standard_visualization_script(plan, inputs)
    except Exception as error:
        return {**record, 'status': 'preflight_exception', 'error': f'{type(error).__name__}: {error}'}
    if script is None:
        return {**record, 'status': 'coding_fallback_required'}
    (folder / 'render.py').write_text(script)
    (folder / 'audit.py').write_text(AUDITOR)
    if 'tamperSource' in case.get('assertions', {}):
        target = folder / f'input-{case["assertions"]["tamperSource"]}.json'
        (folder / ('verified-' + target.name)).write_bytes(target.read_bytes())
        target.write_text('{}')
    try:
        completed = subprocess.run([sys.executable, 'audit.py'], cwd=folder, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        return {**record, 'status': 'render_timeout'}
    if completed.returncode:
        if 'identity changed' in completed.stderr:
            return {**record, 'status': 'identity_rejected', 'error': completed.stderr[-1500:]}
        if 'standard_chart_layout_unresolved' in completed.stderr:
            return {**record, 'status': 'layout_repair_required', 'error': completed.stderr[-1500:]}
        return {**record, 'status': 'render_failure_requires_fallback', 'error': completed.stderr[-1500:]}
    audit = json.loads((folder / 'audit.json').read_text())
    rounded = audit['roundedToZeroCandidates'] if case['variant'] == 'amounts_small' else []
    status = 'needs_visual_repair' if audit['outsideCanvas'] or rounded or audit['categoryTickCollisions'] else 'rendered_geometry_checked'
    if audit['semanticMismatches']:
        status = 'semantic_mismatch'
    for source in files:
        assert (folder / source.path).read_bytes() == source.content
    return {**record, 'status': status, 'audit': audit,
            'png': f'{case["id"]}/{plan.charts[0].source_path}',
            'pngSha256': hashlib.sha256((folder / plan.charts[0].source_path).read_bytes()).hexdigest()}


def cases_from_report(baseline):
    variants = ['baseline', 'amounts_small', 'amounts_large', 'zero_amounts', 'negative_amounts',
                'extreme_spread', 'reversed_rows', 'missing_units', 'renamed_columns']
    for folder in sorted(baseline.glob('chart-*')):
        parameters = json.loads((folder / 'parameters.json').read_text())
        documents = [json.loads(file.read_text()) for file in sorted(folder.glob('input-*.json'))]
        for variant in variants:
            yield {'id': f'{folder.name}-{variant}', 'group': folder.name, 'variant': variant,
                   'synthetic': variant != 'baseline', 'parameters': parameters, 'documents': mutate(documents, variant)}


def synthetic_cases():
    for form in ['line', 'bar', 'barh', 'stacked-bar', 'stacked-area', 'stacked-total']:
        for count in [1, 12, 60, 61]:
            names = ['actual', 'budget']
            doc = {'columns': ['label', *names], 'rows': [[f'业务条线-{i:02}', 100 + i, 200 + i] for i in range(count)],
                   'columnMeta': {name: {'unit': '元'} for name in names}}
            params = {'chart_id': 'synthetic', 'renderer': 'matplotlib', 'interactive_path': None,
                      'visual_form': form, 'source_path': 'standard.png', 'title': '替换数据边界回放',
                      'standard_value_fields': names}
            yield {'id': f'synthetic-{form}-{count}', 'group': form, 'variant': f'labels_{count}',
                   'synthetic': True, 'parameters': params, 'documents': [doc]}
    for mode in ['dual', 'panels', 'zoom', 'log']:
        doc = {'columns': ['period', 'actual', 'budget'], 'rows': [['2026-01', 1e-12, 1e12], ['2026-02', 2e-12, 2e12]],
               'columnMeta': {'actual': {'unit': '元'}, 'budget': {'unit': '元'}}}
        axes = {'mode': 'single', 'scale': 'log'} if mode == 'log' else {'mode': mode}
        if mode == 'dual':
            axes['rightFields'] = ['budget']
        elif mode == 'zoom':
            axes.update(zoomStart='2026-01', zoomEnd='2026-02')
        params = {'chart_id': 'synthetic', 'renderer': 'matplotlib', 'interactive_path': None,
                  'visual_form': 'line', 'source_path': 'standard.png', 'title': '跨量级替换数据',
                  'standard_axes': axes, 'standard_annotations': [{'kind': 'values', 'series': 'actual'}]}
        yield {'id': 'synthetic-' + mode, 'group': mode, 'variant': 'amounts_small', 'synthetic': True,
               'parameters': params, 'documents': [doc]}
    for fault in ['all_null', 'nan', 'infinity', 'duplicate', 'overflow', 'long_labels',
                  'null_metadata', 'malformed_rows', 'missing_columns', 'null_document']:
        rows = [['A', 10, 20], ['B', 15, 25]]
        if fault == 'all_null':
            rows = [['A', None, None], ['B', None, None]]
        elif fault == 'nan':
            rows[0][1] = math.nan
        elif fault == 'infinity':
            rows[0][1] = math.inf
        elif fault == 'duplicate':
            rows[1][0] = 'A'
        elif fault == 'overflow':
            rows = [['A', 1e308, 1e308], ['B', 1e308, 1e308]]
        elif fault == 'long_labels':
            rows[0][0] = '需要完整显示的超长业务名称' * 8
        doc = {'columns': ['label', 'actual', 'budget'], 'rows': rows,
               'columnMeta': {'actual': {'unit': '元'}, 'budget': {'unit': '元'}}}
        if fault == 'null_metadata':
            doc['columnMeta'] = None
        elif fault == 'malformed_rows':
            doc['rows'] = [['A']]
        elif fault == 'missing_columns':
            doc.pop('columns')
        elif fault == 'null_document':
            doc = None
        params = {'chart_id': 'synthetic', 'renderer': 'matplotlib', 'interactive_path': None,
                  'visual_form': 'stacked-total', 'source_path': 'standard.png', 'title': '异常数据回放',
                  'standard_annotations': [{'kind': 'values', 'series': 'actual'}]}
        yield {'id': 'synthetic-' + fault, 'group': 'invalid_or_extreme', 'variant': fault,
               'synthetic': True, 'parameters': params, 'documents': [doc]}
    for series_count, periods in [(8, 60), (9, 60), (8, 61)]:
        names = [f'类别{i}' for i in range(series_count)]
        document = {'columns': ['period', 'category', 'value'],
                    'rows': [[f'2026-{index:02}', name, 10 + index] for index in range(periods) for name in names],
                    'columnMeta': {'value': {'unit': '元'}}}
        parameters = {'chart_id': 'synthetic', 'renderer': 'matplotlib', 'interactive_path': None,
                      'visual_form': 'stacked-bar', 'source_path': 'standard.png', 'title': '长表容量边界',
                      'standard_value_fields': ['value']}
        yield {'id': f'synthetic-long-{series_count}x{periods}', 'group': 'long_table',
               'variant': 'capacity', 'synthetic': True, 'parameters': parameters, 'documents': [document]}


def write_replay_report(result, output):
    output = Path(output)
    title = '标准可视化：完整数据替换回放'
    explanation = ('这是离线模板回放，不调用规划模型或在线独立视觉审查。当前场景范围以以下逐项记录为准；支持报告变更数据、'
                   '多来源、日期、比例尺度、双轴、分面、对数、局部放大和容量边界。合成数据仅用于测试，不是新增报告事实。'
                   '成图只代表脚本与几何检查成功，不代表业务语义或最终视觉验收通过；回退只验证预检不选标准路线，未执行完整Coding修复。')
    lines = ['# ' + title, '', explanation, '', '| 状态 | 数量 |', '|---|---:|']
    lines += [f'| {status} | {count} |' for status, count in result['counts'].items()]
    lines += ['', '换数据不能保证任意数据自动合格。字段、期间、单位或口径改变时必须重新绑定和规划；标签数/系列数/行数超出标准上限时使用其他视图或Coding。', '',
              '| 场景 | 类型 | 结果 |', '|---|---|---|']
    lines += [f'| {record["id"]} | {"合成/变更数据" if record["synthetic"] else "原报告基线"} | {record["status"]} |' for record in result['results']]
    (output / 'README.md').write_text('\n'.join(lines))
    cards = []
    for record in result['results']:
        picture = ('<a href="' + html.escape(record['png'], quote=True) + '"><img loading="lazy" src="'
                   + html.escape(record['png'], quote=True) + '"></a>') if 'png' in record else '<p>未生成标准成图；详见状态及variants.json中的诊断。</p>'
        cards.append('<article><h2>' + html.escape(record['id']) + '</h2><p>' + html.escape(record['status']) + '</p>' + picture + '</article>')
    content = ('<!doctype html><meta charset="utf-8"><title>' + title + '</title>'
               '<style>body{margin:32px;font:16px system-ui;color:#243447;background:#f4f6f8}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:18px}'
               'article{background:white;padding:16px;border-radius:12px}h2{font-size:16px}img{width:100%}input{padding:12px;width:60%;margin:16px 0}</style>'
               '<h1>' + title + '</h1><p>' + explanation + '</p><p>' + html.escape(json.dumps(result['counts'])) + '</p>'
               '<input id="search" aria-label="筛选场景" placeholder="筛选图号、图形或状态"><main>' + ''.join(cards) + '</main>'
               '<script>document.querySelector("#search").addEventListener("input",e=>document.querySelectorAll("article").forEach(a=>a.hidden=!a.textContent.includes(e.target.value)))</script>')
    (output / 'index.html').write_text(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--only', help='Rerun only case IDs containing this text')
    parser.add_argument('--suite', choices=['basic', 'extended', 'pipelines', 'geometry', 'statistics', 'domains', 'breaks', 'summaries', 'horizontal-breaks', 'dual-stack', 'all'], default='basic')
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = ([*cases_from_report(args.baseline), *synthetic_cases()] if args.suite in {'basic', 'all'} else [])
    if args.suite in {'extended', 'all'}:
        cases.extend(extended_cases())
    if args.suite in {'pipelines', 'all'}:
        cases.extend(pipeline_cases())
    if args.suite in {'geometry', 'all'}:
        cases.extend(geometry_cases())
    if args.suite in {'statistics', 'all'}:
        cases.extend(statistics_cases())
    if args.suite in {'domains', 'all'}:
        cases.extend(domain_cases())
    if args.suite in {'breaks', 'all'}:
        cases.extend(break_cases())
    if args.suite in {'summaries', 'all'}:
        cases.extend(summary_cases())
    if args.suite in {'horizontal-breaks', 'all'}:
        cases.extend(horizontal_break_cases())
    if args.suite in {'dual-stack', 'all'}:
        cases.extend(dual_stack_cases())
    if args.only:
        cases = [case for case in cases if args.only in case['id']]
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_case, case, args.output) for case in cases]
        for index, future in enumerate(as_completed(futures), 1):
            record = future.result()
            expected_statuses = {'render': {'rendered_geometry_checked'}, 'fallback': {'coding_fallback_required'},
                                 'schema': {'schema_rejected'}, 'identity': {'identity_rejected'},
                                 'repair': {'layout_repair_required'}}
            if 'expected' in record:
                record['expectationMet'] = record['status'] in expected_statuses[record['expected']]
            records.append(record)
            print(f'{index}/{len(cases)} {record["id"]}: {record["status"]}', flush=True)
    counts = {status: sum(record['status'] == status for record in records) for status in sorted({r['status'] for r in records})}
    result = {'mode': 'offline_data_replacement_no_online_visual_gate', 'cases': len(records),
              'counts': counts, 'codeCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'workingTreeDirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()),
              'results': sorted(records, key=lambda record: record['id'])}
    (args.output / 'variants.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    write_replay_report(result, args.output)
    print(json.dumps(counts))
    if any(not record.get('expectationMet', record['status'] in {'rendered_geometry_checked', 'coding_fallback_required'}) for record in records):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
