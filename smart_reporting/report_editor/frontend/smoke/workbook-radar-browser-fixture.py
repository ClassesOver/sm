import sys
from pathlib import Path
from openpyxl import Workbook
from openpyxl.chart import RadarChart, Reference, Series
from openpyxl.chart.series import SeriesLabel
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor

output=Path(sys.argv[1]);workbook=Workbook();sheet=workbook.active;sheet.title='Sheet'
headers=['Category']+[f'Series {index}' for index in range(1,3)];sheet.append(headers)
for index in range(13): sheet.append([f'Axis {index+1}',index+1,(index+1)*2 if index<15 else None])
sheet['C15']=30;sheet['C16']=32
radar=RadarChart();radar.title='Radar browser';radar.series.append(Series(Reference(sheet,min_col=2,min_row=2,max_row=14),title_from_data=False));radar.series[0].tx=SeriesLabel(v='Series 1');radar.series.append(Series(Reference(sheet,min_col=3,min_row=2,max_row=16),title_from_data=False));radar.series[1].tx=SeriesLabel(v='Series 2');radar.set_categories(Reference(sheet,min_col=1,min_row=2,max_row=14));radar.anchor=TwoCellAnchor(_from=AnchorMarker(col=1,row=1),to=AnchorMarker(col=11,row=15));sheet.add_chart(radar)
workbook.save(output)
