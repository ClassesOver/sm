"""Create a compact XLSX source for line/area chart hit-testing acceptance."""
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import AreaChart, LineChart, Reference
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor

output = Path(sys.argv[1])
workbook = Workbook()
sheet = workbook.active
sheet.title = 'Sheet'
for row in [
    ('Quarter', 'Line', 'Area'),
    ('Q1', 10, 2),
    ('Q2', 30, 9),
    ('Q3', 20, 5),
    ('Q4', 40, 12),
]:
    sheet.append(row)

line = LineChart()
line.title = 'Line hit'
line.add_data(Reference(sheet, min_col=2, min_row=1, max_row=5), titles_from_data=True)
line.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=5))
line.marker = 'circle'
line.anchor = TwoCellAnchor(_from=AnchorMarker(col=4, row=1), to=AnchorMarker(col=13, row=13))
sheet.add_chart(line)

area = AreaChart()
area.title = 'Area hit'
area.add_data(Reference(sheet, min_col=3, min_row=1, max_row=5), titles_from_data=True)
area.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=5))
area.anchor = TwoCellAnchor(_from=AnchorMarker(col=4, row=15), to=AnchorMarker(col=13, row=27))
sheet.add_chart(area)

workbook.save(output)
