"""Translate source AI print settings into the existing XLSX writer protocol."""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from openpyxl.utils.cell import column_index_from_string
from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, with_config
from typing_extensions import TypedDict

_Text = Annotated[str, Field(max_length=255)]
_Fit = Annotated[int, Field(ge=0, le=1000)]


@with_config(ConfigDict(extra='forbid'))
class _HeaderFooter(TypedDict, total=False):
    left: _Text
    center: _Text
    right: _Text


@with_config(ConfigDict(extra='forbid'))
class _PageSetup(TypedDict, total=False):
    orientation: Literal['portrait', 'landscape']
    paperSize: Annotated[int, Field(ge=1, le=118)]
    scale: Annotated[int, Field(ge=10, le=400)]
    fitToWidth: _Fit
    fitToHeight: _Fit
    margins: Literal['normal', 'wide', 'narrow']
    printGridlines: bool
    printHeadings: bool
    printArea: str | None
    printTitles: str | None
    header: _HeaderFooter | None
    footer: _HeaderFooter | None
    rowBreaks: Annotated[list[Annotated[int, Field(ge=1, le=1048575)]], Field(max_length=1023)]
    colBreaks: Annotated[list[Annotated[int, Field(ge=1, le=16383)]], Field(max_length=1023)]


_ADAPTER = TypeAdapter(_PageSetup)


def _valid_titles(titles: str) -> bool:
    axes = set()
    for span in titles.split(','):
        row = re.fullmatch(r'\$?([1-9][0-9]{0,6}):\$?([1-9][0-9]{0,6})', span)
        column = re.fullmatch(r'\$?([A-Z]{1,3}):\$?([A-Z]{1,3})', span, re.IGNORECASE | re.ASCII)
        if row is not None and 'row' not in axes and int(row[1]) <= int(row[2]) <= 1048576:
            axes.add('row')
        elif (column is not None and 'column' not in axes
              and column_index_from_string(column[1]) <= column_index_from_string(column[2]) <= 16384):
            axes.add('column')
        else:
            return False
    return bool(axes)


def page_setup_patch(operation: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    try:
        fields = dict(_ADAPTER.validate_python(
            {key: value for key, value in operation.items() if key not in {'op', 'sheetId'}},
            strict=True,
        ))
    except ValidationError as error:
        raise ValueError('workbook_ai_page_setup_invalid') from error
    has_fit = 'fitToWidth' in fields or 'fitToHeight' in fields
    titles = fields.get('printTitles')
    if not fields or (has_fit and 'scale' in fields) or (titles is not None and not _valid_titles(titles)):
        raise ValueError('workbook_ai_page_setup_invalid')
    if 'scale' in fields:
        fields['fitToPage'] = False
    elif has_fit:
        width = fields.setdefault('fitToWidth', prior.get('fitToWidth', 0))
        height = fields.setdefault('fitToHeight', prior.get('fitToHeight', 0))
        fields['fitToPage'] = width > 0 or height > 0
    return fields
