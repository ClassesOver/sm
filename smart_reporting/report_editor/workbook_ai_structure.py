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
SHEET_LIFECYCLE_OPS = {'add_sheet', 'rename_sheet', 'delete_sheet'}
SHEET_SOURCE_OPS = SHEET_LIFECYCLE_OPS | {'move_sheet'}


def translate_sheet_operation(operation: dict[str, Any], order: list[str]) -> dict[str, Any]:
    op = operation['op']
    fields = {
        'add_sheet': {'name'},
        'rename_sheet': {'sheetId', 'name'},
        'delete_sheet': {'sheetId'},
        'move_sheet': {'sheetId', 'position'},
    }[op]
    if set(operation) != fields | {'op'}:
        raise ValueError('workbook_ai_sheet_order_invalid')
    source = operation.get('sheetId')
    if op != 'add_sheet' and (not isinstance(source, str) or source not in order):
        raise ValueError('workbook_ai_sheet_order_invalid')
    name = operation.get('name')
    if op in {'add_sheet', 'rename_sheet'} and (
        not isinstance(name, str) or not name.strip() or len(name) > 31
        or name.startswith("'") or name.endswith("'") or re.search(r'[\\/?*\[\]:\x00-\x1f]', name)
        or any(sheet != source and sheet.upper() == name.upper() for sheet in order)
    ):
        raise ValueError('workbook_ai_sheet_name_invalid')
    additions, renames, removals = [], [], []
    if op == 'add_sheet':
        order.append(name)
        additions.append({'name': name})
    elif op == 'rename_sheet':
        order[order.index(source)] = name
        if source != name:
            renames.append({'sheetName': source, 'newName': name})
    elif op == 'delete_sheet':
        if len(order) == 1:
            raise ValueError('workbook_ai_sheet_order_invalid')
        order.remove(source)
        removals.append(source)
    else:
        position = operation['position']
        if type(position) is not int or not 1 <= position <= min(len(order), 1000):
            raise ValueError('workbook_ai_sheet_order_invalid')
        order.remove(source)
        order.insert(position - 1, source)
    return {'kind': 'applySheetEdits', 'plan': {
        'additions': additions, 'renames': renames, 'removals': removals, 'order': list(order),
    }}


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
