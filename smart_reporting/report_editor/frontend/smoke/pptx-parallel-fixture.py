"""Disposable authenticated-route fixture; all PPTX work uses the real application engine."""
import faulthandler
faulthandler.dump_traceback_later(30, repeat=True)
import base64
import hashlib
import json
import os
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from PIL import Image
from pptx import Presentation
from pptx.util import Inches
from pptx.util import Pt
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.dml.color import RGBColor
from pptx.oxml.xmlchemy import OxmlElement
from lxml import etree

from smart_reporting.report_editor.native_office import inspect_office, patch_office


def image(color):
    stream = BytesIO()
    Image.new("RGB", (48, 32), color).save(stream, "PNG")
    return stream.getvalue()


def chart_style(chart):
    xml = chart._chartSpace
    return {
        "title": "".join(xml.xpath("./c:chart/c:title//a:t/text()")),
        "catAxisTitle": "".join(xml.xpath(".//c:catAx/c:title//a:t/text()")),
        "valAxisTitle": "".join(xml.xpath(".//c:valAx/c:title//a:t/text()")),
        "legendPos": next(iter(xml.xpath("./c:chart/c:legend/c:legendPos/@val")), "none"),
        "dataLabels": bool(xml.xpath(".//c:dLbls/c:showVal[@val='1']")),
        "gridlines": bool(xml.xpath(".//c:valAx/c:majorGridlines")),
    }


def chart_design(chart):
    xml = chart._chartSpace
    gaps = xml.xpath('.//c:gapWidth/@val')
    return {'colors': xml.xpath('.//c:ser/c:spPr//a:srgbClr/@val'),
            'gapWidthPct': int(gaps[0]) if gaps else None}


def chart_points(chart):
    return [{point.xpath('./c:idx/@val')[0]: point.xpath('./c:spPr//a:srgbClr/@val')[0]
             for point in series.xpath('./c:dPt') if point.xpath('./c:spPr//a:srgbClr/@val')}
            for series in chart._chartSpace.xpath('.//c:ser')]


payload = json.load(sys.stdin)
mode = payload["mode"]
if mode == "create":
    presentation = Presentation()
    for text in ("Browser cat cat", "Second cat slide"):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text = text
    presentation.slides[0].shapes.add_picture(BytesIO(image("red")), Inches(1), Inches(3), Inches(2), Inches(1))
    if payload.get("shapeFormat"):
        for index, name in enumerate(("Format safe", "Format complex line", "Format complex fill", "Format empty")):
            shape = presentation.slides[0].shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1 + index * 2), Inches(5), Inches(1.5), Inches(0.75))
            shape.name = name
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor.from_string("123456")
            shape.line.color.rgb = RGBColor.from_string("345678")
            shape.line.width = Pt(2.25)
            if name == "Format complex line":
                shape.line.dash_style = MSO_LINE_DASH_STYLE.DASH
                line = shape._element.spPr.xpath("./a:ln")[0]
                line.set("algn", "in")
                arrow = OxmlElement("a:headEnd"); arrow.set("type", "triangle"); line.append(arrow)
            if name == "Format complex fill":
                shape.fill.gradient()
    stream = BytesIO()
    presentation.save(stream)
    content = patch_office("pptx", stream.getvalue(), [{"kind": "editSlides", "charts": [{"slideIndex": 0,
        "kind": "bar", "categories": ["One", "Two"], "series": [{"name": "Revenue", "values": [10, 20]}]}]}])
    preview = BytesIO()
    Image.new("RGB", (48, 32), "white").save(preview, "PDF")
    print(json.dumps({"bytes": base64.b64encode(content).decode(), "model": inspect_office("pptx", content),
        "insertImage": base64.b64encode(image("green")).decode(), "replacementImage": base64.b64encode(image("blue")).decode(),
        "previewPdf": base64.b64encode(preview.getvalue()).decode()}))
else:
    content = base64.b64decode(payload["bytes"])
    if payload.get("operations"):
        try:
            content = patch_office("pptx", content, payload["operations"])
        except Exception:
            if os.environ.get("PPTX_SMOKE_EVIDENCE_DIR"):
                output = Path(os.environ["PPTX_SMOKE_EVIDENCE_DIR"])
                output.mkdir(parents=True, exist_ok=True)
                (output / "failed-source.pptx").write_bytes(content)
                (output / "failed-payload.json").write_text(json.dumps(payload), encoding="utf-8")
            # The public adapter deliberately hides engine details; this fixture prints the underlying
            # immutable-input replay failure for diagnosis without changing application behavior.
            from smart_reporting.report_editor.native_office import _pptx_arguments
            from smart_reporting.report_editor.slides import ReportSlidesEditorService
            ReportSlidesEditorService._run_engine(content, "edit", **_pptx_arguments(payload["operations"][0]))
            raise
    if mode == "render":
        from smart_reporting.report_editor.slides_render import render_pptx_tree
        result = render_pptx_tree(content)
    elif mode == "independent":
        presentation = Presentation(BytesIO(content))
        slides = []
        for slide in presentation.slides:
            pictures = [{"sha256": hashlib.sha256(shape.image.blob).hexdigest(),
                "geometry": [shape.left, shape.top, shape.width, shape.height]} for shape in slide.shapes if shape.shape_type == 13]
            charts = [{"type": int(shape.chart.chart_type), "style": chart_style(shape.chart), "design": chart_design(shape.chart), "pointColors": chart_points(shape.chart), "categories": [category.label for category in shape.chart.plots[0].categories],
                "series": [{"name": series.name, "values": list(series.values)} for series in shape.chart.series]} for shape in slide.shapes if shape.has_chart]
            slides.append({"texts": [shape.text for shape in slide.shapes if shape.has_text_frame], "pictures": pictures, "charts": charts,
                "frames": [{"name": shape.name, "type": int(shape.shape_type), "geometry": [shape.left, shape.top, shape.width, shape.height]} for shape in slide.shapes],
                "shapeStyles": [{"name": shape.name,
                    "fillXml": [etree.tostring(node).decode() for node in shape._element.spPr if etree.QName(node).localname in {"solidFill", "noFill", "gradFill", "pattFill", "blipFill"}],
                    "lineXml": [etree.tostring(node).decode() for node in shape._element.spPr.xpath("./a:ln")],
                    "fillColors": shape._element.spPr.xpath("./a:solidFill/a:srgbClr/@val"),
                    "lineColors": shape._element.spPr.xpath("./a:ln/a:solidFill/a:srgbClr/@val"),
                    "lineWidths": shape._element.spPr.xpath("./a:ln/@w")}
                    for shape in slide.shapes if shape.name.startswith("Format ")]})
        with ZipFile(BytesIO(content)) as archive:
            result = {"slides": slides, "zip": {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()},
                "chartXml": [archive.read(name).decode() for name in archive.namelist() if name.startswith("ppt/charts/chart") and name.endswith(".xml")]}
        if os.environ.get("PPTX_SMOKE_EVIDENCE_DIR"):
            output = Path(os.environ["PPTX_SMOKE_EVIDENCE_DIR"])
            output.mkdir(parents=True, exist_ok=True)
            (output / "independent-checkpoint.pptx").write_bytes(content)
            (output / "independent-checkpoint.json").write_text(json.dumps({"completed": False,
                "stage": "independent-readback-only", "sha256": hashlib.sha256(content).hexdigest(), "readback": result}), encoding="utf-8")
    else:
        result = {"bytes": base64.b64encode(content).decode(), "model": inspect_office("pptx", content),
            "sha256": hashlib.sha256(content).hexdigest()}
    print(json.dumps(result))
