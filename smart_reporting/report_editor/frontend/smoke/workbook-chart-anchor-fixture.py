"""以源 OOXML marker 与截图网格标定独立核对图框，不调用产品坐标代码。"""
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.spreadsheet_drawing import (
    AbsoluteAnchor, AnchorMarker, OneCellAnchor, TwoCellAnchor,
    XDRPoint2D, XDRPositiveSize2D,
)
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image

CALIBRATION = (229, 162, 71)


def create(path, anchor_types=False):
    book = Workbook()
    sheet = book.active
    for row in [["Grid", "Revenue"], ["A", 3], ["B", 6]]:
        sheet.append(row)
    # Uniform, explicit dimensions; screenshot calibration measures their actual pixels.
    for column in range(1, 21):
        sheet.column_dimensions[get_column_letter(column)].width = 12
    for row in range(1, 46):
        sheet.row_dimensions[row].height = 18
    for cell in ("B4", "D6"):
        sheet[cell].fill = PatternFill("solid", fgColor="E5A247")
    markers = [
        (AnchorMarker(col=4, row=2), AnchorMarker(col=12, row=10)),
        (AnchorMarker(col=4, row=13, colOff=5 * 9525, rowOff=3 * 9525),
         AnchorMarker(col=4, row=13, colOff=75 * 9525, rowOff=63 * 9525)),
        (AnchorMarker(col=4, row=20, colOff=-3 * 9525, rowOff=-4 * 9525),
         AnchorMarker(col=10, row=28, colOff=-7 * 9525, rowOff=-2 * 9525)),
    ]
    anchors = [TwoCellAnchor(_from=start, to=end) for start, end in markers]
    if anchor_types:
        anchors[0] = OneCellAnchor(
            _from=AnchorMarker(col=4, row=2, colOff=5 * 9525, rowOff=3 * 9525),
            ext=XDRPositiveSize2D(cx=480 * 9525, cy=192 * 9525),
        )
        anchors[1] = AbsoluteAnchor(
            pos=XDRPoint2D(x=360 * 9525, y=350 * 9525),
            ext=XDRPositiveSize2D(cx=420 * 9525, cy=100 * 9525),
        )
    for index, anchor in enumerate(anchors):
        chart = BarChart()
        chart.title, chart.legend = f"Anchor {index + 1}", None
        chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=3), titles_from_data=True)
        chart.anchor = anchor
        sheet.add_chart(chart)
    book.save(path)


def verify(directory, anchor_types=False):
    ns = {"xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"}
    with ZipFile(directory / "source.xlsx") as archive:
        drawing = etree.fromstring(archive.read("xl/drawings/drawing1.xml"))
    image = Image.open(directory / "charts.png").convert("RGB")
    # Two unselected cells establish pitch without relying on product width conversion.
    # Restrict detection to the sheet: the ribbon also shows the selected fill color.
    pixels = image.load()
    remaining = {(x, y) for y in range(250, 500) for x in range(40, image.width)
                 if pixels[x, y] == CALIBRATION}
    boxes = []
    while remaining:
        seed = remaining.pop()
        stack, component = [seed], [seed]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
                    component.append(neighbor)
        boxes.append((min(x for x, _ in component), min(y for _, y in component),
                      max(x for x, _ in component) + 1, max(y for _, y in component) + 1))
    boxes.sort()
    assert len(boxes) == 2, boxes
    first, second = boxes
    cell_width, cell_height = (second[0] - first[0]) / 2, (second[1] - first[1]) / 2
    assert cell_width > 70 and 20 <= cell_height <= 25, boxes
    assert all((box[2] - box[0], box[3] - box[1]) == (cell_width, cell_height) for box in boxes), boxes
    left, top = first[0] - cell_width, first[1] - 3 * cell_height
    pixels, edges = image.load(), []
    for y in range(int(top), image.height):
        start = None
        for x in range(350, image.width + 1):
            matches = x < image.width and pixels[x, y] == (154, 164, 173)
            if matches and start is None:
                start = x
            elif not matches and start is not None:
                if x - start >= 40:
                    edges.append((start, y, x - start))
                start = None
    assert len(edges) == 6, edges
    frames, expected_frames = [], []
    kinds = []
    for anchor in drawing:
        kind = etree.QName(anchor).localname
        if kind not in ("twoCellAnchor", "oneCellAnchor", "absoluteAnchor"):
            continue
        kinds.append(kind)
        def position(name):
            marker = anchor.find(f"xdr:{name}", ns)
            values = {etree.QName(node).localname: int(node.text) for node in marker}
            return (left + values["col"] * cell_width + values["colOff"] / 9525,
                    top + values["row"] * cell_height + values["rowOff"] / 9525)
        if kind == "absoluteAnchor":
            pos = anchor.find("xdr:pos", ns)
            start = (left + int(pos.get("x")) / 9525, top + int(pos.get("y")) / 9525)
        else:
            start = position("from")
        if kind == "twoCellAnchor":
            end = position("to")
        else:
            extent = anchor.find("xdr:ext", ns)
            end = (start[0] + int(extent.get("cx")) / 9525,
                   start[1] + int(extent.get("cy")) / 9525)
        expected_frames.append((start, end, kind))
    assert sorted(kinds) == sorted(["oneCellAnchor", "absoluteAnchor", "twoCellAnchor"] if anchor_types else ["twoCellAnchor"] * 3), kinds
    for index, (start, end, kind) in enumerate(sorted(expected_frames, key=lambda frame: frame[0][1])):
        actual_top, actual_bottom = edges[index * 2:index * 2 + 2]
        expected = [start[0], start[1], end[0] - start[0], end[1] - start[1] - 1]
        actual = [*actual_top, actual_bottom[1] - actual_top[1]]
        assert all(abs(a - b) <= 1 for a, b in zip(actual, expected)), (index, actual, expected, boxes)
        assert actual_bottom[0] == actual_top[0] and actual_bottom[2] == actual_top[2]
        frames.append({"anchorType": kind, "actual": actual, "expected": expected})
    assert len(frames) == 3
    return {"ok": True, "calibrationCells": boxes, "cellPitch": [cell_width, cell_height], "frames": frames}


if __name__ == "__main__":
    if sys.argv[1] in ("create", "create-types"):
        create(Path(sys.argv[2]), sys.argv[1] == "create-types")
    else:
        print(json.dumps(verify(Path(sys.argv[2]), sys.argv[1] == "verify-types"), ensure_ascii=False))
