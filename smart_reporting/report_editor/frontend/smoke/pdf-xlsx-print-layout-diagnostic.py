"""Read source/XLSX/actual host pages without changing print settings or artifacts."""
import argparse
import json
from pathlib import Path
import openpyxl
import pymupdf

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path)
parser.add_argument('xlsx', type=Path)
parser.add_argument('rendered_pdf', type=Path)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
source = pymupdf.open(args.source)
rendered = pymupdf.open(args.rendered_pdf)
workbook = openpyxl.load_workbook(args.xlsx, rich_text=True)
sheets = []
for sheet in workbook:
    columns = []
    for index in range(1, sheet.max_column + 1):
        name = openpyxl.utils.get_column_letter(index)
        explicit = sheet.column_dimensions.get(name)
        columns.append({'column': name, 'explicitWidth': explicit.width if explicit else None,
                        'builderPoints': (max(1, round(explicit.width * 7 + 5)) if explicit else 64) * .75})
    sheets.append({'name': sheet.title, 'dimension': sheet.calculate_dimension(), 'columns': columns,
                   'builderWidthPoints': sum(column['builderPoints'] for column in columns),
                   'lastExplicitRow': max(sheet.row_dimensions, default=0),
                   'pageSetup': dict(sheet.page_setup), 'merges': [str(merge) for merge in sheet.merged_cells],
                   'cells': [{'address': cell.coordinate, 'text': str(cell.value)[:120], 'wrap': cell.alignment.wrapText}
                             for row in sheet for cell in row if cell.value is not None],
                   'images': [{'fromRow': image.anchor._from.row, 'toRow': image.anchor.to.row,
                               'fromColumn': image.anchor._from.col, 'toColumn': image.anchor.to.col}
                              for image in sheet._images]})
result = {'sourcePages': [{'width': page.rect.width, 'height': page.rect.height} for page in source],
          'sheets': sheets, 'renderedPageCount': len(rendered),
          'renderedPages': [{'page': page.number + 1, 'width': page.rect.width, 'height': page.rect.height,
                             'textStart': page.get_text()[:160], 'images': len(page.get_images())}
                            for page in rendered],
          'overallFidelityPassed': False, 'manualReview': True}
text = json.dumps(result, ensure_ascii=False, indent=2)
if args.output:
    args.output.write_text(text + '\n')
print(text)
