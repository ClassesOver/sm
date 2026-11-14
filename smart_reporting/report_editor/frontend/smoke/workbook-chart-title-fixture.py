"""真实XLSX标题夹具：宽图保留长标题，窄图标题不得绘制到相邻网格。"""
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from PIL import Image

TITLES = ["Quarterly revenue and cost comparison across regions 2026",
          "很长的季度收入与成本比较标题，包含地区、部门与年度汇总", "WWWWWWWWWWWWWWWWWWWWWWWW"]


def create(path):
    book = Workbook()
    sheet = book.active
    for row in [["Category", "Revenue"], ["A", 3], ["B", 6]]:
        sheet.append(row)
    for index, title in enumerate(TITLES):
        chart = BarChart()
        chart.title, chart.legend = title, None
        chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=3), titles_from_data=True)
        row = 1 + index * 11
        end = AnchorMarker(col=12 if index == 0 else 5 if index == 1 else 4,
                           row=row + 8, colOff=55 * 9525 if index == 2 else 0)
        chart.anchor = TwoCellAnchor(_from=AnchorMarker(col=4, row=row), to=end)
        sheet.add_chart(chart)
    book.save(path)


def verify(directory):
    ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
          "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    with ZipFile(directory / "source.xlsx") as archive:
        for index, title in enumerate(TITLES):
            xml = etree.fromstring(archive.read(f"xl/charts/chart{index + 1}.xml"))
            assert xml.xpath("//c:title//a:t/text()", namespaces=ns) == [title]
    image = Image.open(directory / "charts.png").convert("RGB")
    pixels, edges = image.load(), []
    for y in range(200, image.height):
        start = None
        for x in range(200, image.width + 1):
            matches = x < image.width and pixels[x, y] == (154, 164, 173)
            if matches and start is None:
                start = x
            elif not matches and start is not None:
                if x - start >= 40:
                    edges.append((start, y, x - start))
                start = None
    assert len(edges) == 6, edges
    frames = []
    for top, bottom in zip(edges[::2], edges[1::2]):
        x, y, width = top
        assert bottom[0] == x and bottom[2] == width
        title_ink = sum(max(rgb) < 100 for rgb in image.crop((x + 2, y + 2, x + width - 2, y + 18)).getdata())
        outside_ink = sum(max(rgb) < 100 for rgb in image.crop((x + width + 2, y + 2, min(image.width, x + width + 220), y + 18)).getdata())
        assert title_ink > 5, (top, title_ink)
        assert outside_ink == 0, (top, outside_ink)
        frames.append({"x": x, "y": y, "width": width, "height": bottom[1] - y,
                       "titleInkPixels": title_ink, "outsideTitleInkPixels": outside_ink})
    return {"ok": True, "frames": frames, "sourceTitles": TITLES}


if __name__ == "__main__":
    if sys.argv[1] == "create":
        create(Path(sys.argv[2]))
    else:
        print(json.dumps(verify(Path(sys.argv[2])), ensure_ascii=False))
