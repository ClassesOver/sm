"""Create an independent XLSX source for scatter/radar axis mouse acceptance."""
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import RadarChart, ScatterChart, Reference, Series
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor

output = Path(sys.argv[1])
workbook = Workbook()
sheet = workbook.active
sheet.title = 'Sheet'
for row in [
    ('Quarter', 'Revenue', 'Cost'),
    ('Q1', 10, 3),
    ('Q2', 20, 8),
    ('Q3', 30, 6),
    ('Q4', 40, 12),
]:
    sheet.append(row)

scatter = ScatterChart()
scatter.title = 'Axis scatter'
xvalues = Reference(sheet, min_col=2, min_row=2, max_row=5)
for column in (2, 3):
    yvalues = Reference(sheet, min_col=column, min_row=2, max_row=5)
    scatter.series.append(Series(yvalues, xvalues, title=sheet.cell(1, column).value))
scatter.anchor = TwoCellAnchor(
    _from=AnchorMarker(col=4, row=1), to=AnchorMarker(col=13, row=13)
)
sheet.add_chart(scatter)

radar = RadarChart()
radar.title = 'Axis radar'
radar.add_data(Reference(sheet, min_col=2, max_col=3, min_row=1, max_row=5), titles_from_data=True)
radar.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=5))
radar.anchor = TwoCellAnchor(
    _from=AnchorMarker(col=4, row=15), to=AnchorMarker(col=13, row=27)
)
sheet.add_chart(radar)
workbook.save(output)
