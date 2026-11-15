"""Source XLSX row/column DSL -> existing native structural operations.

GenOffice f8c17004 workbook-dsl.ts uses one-based rows and column labels.
The existing engine performs package/reference changes; this module only validates
and translates inputs, and never edits a workbook itself.
"""
from __future__ import annotations

import re
from typing import Any

from openpyxl.utils.cell import column_index_from_string

ROW_COLUMN_SOURCE_OPS = {
    'insert_rows': 'insert-rows', 'delete_rows': 'remove-rows',
    'insert_cols': 'insert-cols', 'delete_cols': 'remove-cols',
}


def translate_row_column_operation(operation: dict[str, Any], sheet_name: str) -> dict[str, Any]:
    op = operation['op']
    rows = op.endswith('_rows')
    count = operation.get('count')
    if type(count) is not int or not 1 <= count <= (500 if rows else 100):
        raise ValueError('workbook_ai_structure_invalid')
    if rows:
        row = operation.get('row')
        if type(row) is not int or not 1 <= row <= 1048576:
            raise ValueError('workbook_ai_structure_invalid')
        index = row - 1
    else:
        column = operation.get('column')
        if not isinstance(column, str) or re.fullmatch(r'[A-Z]{1,3}', column) is None:
            raise ValueError('workbook_ai_structure_invalid')
        index = column_index_from_string(column) - 1
    if index + count > (1048576 if rows else 16384):
        raise ValueError('workbook_ai_structure_invalid')
    return {'kind': 'applyRowColumnOps', 'sheetName': sheet_name,
            'ops': [{'kind': ROW_COLUMN_SOURCE_OPS[op], 'index': index, 'count': count}]}
