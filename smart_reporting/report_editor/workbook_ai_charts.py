"""Bind chart candidates to frozen targets and worksheet source ranges."""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Required

from openpyxl.utils.cell import range_boundaries
from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, with_config
from typing_extensions import TypedDict

_Text = Annotated[str, Field(max_length=200, pattern=r'^[^\x00-\x08\x0b\x0c\x0e-\x1f]*$')]
_Color = Annotated[str, Field(pattern=r'^#[0-9a-fA-F]{6}$')]
_Index = Annotated[str, Field(pattern=r'^(0|[1-9][0-9]{0,3})$')]
_Explosion = Annotated[int, Field(ge=0, le=400)]
_Finite = Annotated[float, Field(allow_inf_nan=False)]


@with_config(ConfigDict(extra='forbid'))
class _AxisTitles(TypedDict, total=False):
    category: _Text | None
    value: _Text | None


@with_config(ConfigDict(extra='forbid'))
class _AxisBounds(TypedDict, total=False):
    min: _Finite | None
    max: _Finite | None


@with_config(ConfigDict(extra='forbid'))
class _ChartFormat(TypedDict, total=False):
    title: _Text
    chartType: Literal['column', 'bar', 'line', 'area', 'pie', 'doughnut']
    legend: Literal['none', 'right', 'bottom', 'top', 'left']
    seriesColors: dict[_Index, _Color]
    pointColors: dict[_Index, dict[_Index, _Color]]
    dataLabels: Literal['none', 'value', 'percent', 'category-percent']
    dataLabelPosition: Literal['center', 'inside-end', 'outside-end']
    dataLabelFormat: _Text
    axisTitles: _AxisTitles
    grouping: Literal['clustered', 'stacked', 'percentStacked']
    gridlines: bool
    valueAxis: _AxisBounds
    gapWidthPct: Annotated[int, Field(ge=0, le=500)]
    holeSizePct: Annotated[int, Field(ge=10, le=90)]
    explosionPct: _Explosion
    pointExplosions: dict[_Index, _Explosion]


_FORMAT_ADAPTER = TypeAdapter(_ChartFormat)
_FORMAT_FIELDS = frozenset(_ChartFormat.__annotations__)

_Range = Annotated[str, Field(pattern=r'^[A-Z]{1,3}[1-9][0-9]{0,6}(?::[A-Z]{1,3}[1-9][0-9]{0,6})?$')]


@with_config(ConfigDict(extra='forbid'))
class _ChartSourceAdd(TypedDict, total=False):
    op: Required[Literal['add_chart']]
    sheetId: Required[str]
    chartType: Required[Literal['column', 'bar', 'line', 'area', 'pie', 'doughnut', 'scatter', 'radar', 'combo']]
    dataRange: Required[_Range]
    title: _Text
    anchorCell: _Range


@with_config(ConfigDict(extra='forbid'))
class _SeriesSource(TypedDict, total=False):
    index: Required[Annotated[int, Field(ge=0, le=9999)]]
    name: _Text
    valuesRange: _Range
    categoriesRange: _Range
    sheetId: str


@with_config(ConfigDict(extra='forbid'))
class _ChartSourceEdit(_ChartFormat, total=False):
    op: Required[Literal['edit_chart']]
    chartPath: Required[str]
    seriesData: Annotated[list[_SeriesSource], Field(min_length=1, max_length=32)]


_SOURCE_ADAPTER = TypeAdapter(_ChartSourceAdd | _ChartSourceEdit)


def _source_bounds(address: str, *, vector: bool = False) -> tuple[int, int, int, int]:
    c0, r0, c1, r1 = range_boundaries(address)
    if (not 1 <= c0 <= c1 <= 16384 or not 1 <= r0 <= r1 <= 1048576
            or (c1-c0+1)*(r1-r0+1) > 2000 or vector and c0 != c1 and r0 != r1):
        raise ValueError('workbook_ai_chart_source_invalid')
    return c0, r0, c1, r1


def _validate_source(model: dict[str, Any], operation: dict[str, Any], owners: dict[str, list[str]], deleted: set[str]) -> None:
    if set(operation) != {'kind', 'operation'}:
        raise ValueError('workbook_ai_chart_source_invalid')
    try:
        source = _SOURCE_ADAPTER.validate_python(operation.get('operation'), strict=True)
    except ValidationError as error:
        raise ValueError('workbook_ai_chart_source_invalid') from error
    sheets = {sheet['name'] for sheet in model.get('sheets', [])}
    if source['op'] == 'add_chart':
        if source['sheetId'] not in sheets:
            raise ValueError('workbook_ai_chart_source_invalid')
        c0, r0, c1, _ = _source_bounds(source['dataRange'])
        anchor = source.get('anchorCell')
        if anchor:
            c0, r0, ac1, ar1 = _source_bounds(anchor)
            if c0 != ac1 or r0 != ar1:
                raise ValueError('workbook_ai_chart_source_invalid')
        else:
            c0 = c1 + 2
        if c0 + 7 > 16384 or r0 + 15 > 1048576:
            raise ValueError('workbook_ai_chart_source_invalid')
        return
    path = source['chartPath']
    if len(owners.get(path, [])) != 1 or path in deleted:
        raise ValueError('workbook_ai_chart_target_invalid')
    formatted = {key: value for key, value in source.items() if key in _FORMAT_FIELDS}
    if formatted:
        _validate_format(formatted)
    if not formatted and not source.get('seriesData'):
        raise ValueError('workbook_ai_chart_source_invalid')
    indices = set()
    for series in source.get('seriesData', []):
        if series['index'] in indices or not set(series) & {'name', 'valuesRange', 'categoriesRange'}:
            raise ValueError('workbook_ai_chart_source_invalid')
        indices.add(series['index'])
        if series.get('sheetId', owners[path][0]) not in sheets:
            raise ValueError('workbook_ai_chart_source_invalid')
        lengths = []
        for key in ('valuesRange', 'categoriesRange'):
            if key in series:
                c0, r0, c1, r1 = _source_bounds(series[key], vector=True)
                lengths.append((r1-r0+1)*(c1-c0+1))
        if len(set(lengths)) > 1:
            raise ValueError('workbook_ai_chart_source_invalid')


def _validate_format(record: dict[str, Any]) -> None:
    fields = {key: value for key, value in record.items() if key != 'chartPath'}
    try:
        _FORMAT_ADAPTER.validate_python(fields, strict=True)
    except ValidationError as error:
        raise ValueError('workbook_ai_chart_format_invalid') from error
    if any(isinstance(value, dict) and not value for value in fields.values()):
        raise ValueError('workbook_ai_chart_format_invalid')
    bounds = fields.get('valueAxis', {})
    if bounds.get('min') is not None and bounds.get('max') is not None and bounds['min'] >= bounds['max']:
        raise ValueError('workbook_ai_chart_format_invalid')


def validate_chart_candidates(model: dict[str, Any], operations: list[dict[str, Any]]) -> None:
    """Validate before any candidate preview, including non-tool planners.

    Strict runtime types are checked here; the engine checks actual OOXML
    and chart-specific support. A
    chartPath supplied by the model alone is never sufficient authorization.
    """
    if (any(operation['kind'] == 'applyChartSource' for operation in operations)
            and any(operation['kind'] in {'applySheetEdits', 'applyRowColumnOps', 'applyCellShift'} for operation in operations)):
        raise ValueError('workbook_ai_chart_structure_batch_invalid')
    owners: dict[str, list[str]] = {}
    for sheet in model.get('sheets', []):
        for chart in sheet.get('charts', []):
            path = chart.get('chartPath')
            if isinstance(path, str):
                owners.setdefault(path, []).append(sheet['name'])
    deleted: set[str] = set()
    for operation in operations:
        kind = operation['kind']
        if kind == 'applyChartSource':
            _validate_source(model, operation, owners, deleted)
            continue
        if kind not in {'applyChartEdits', 'applyChartDeletions'}:
            continue
        key = 'edits' if kind == 'applyChartEdits' else 'deletions'
        records = operation.get(key)
        if (set(operation) != {'kind', key} or not isinstance(records, list)
                or not 1 <= len(records) <= 100):
            raise ValueError('workbook_ai_chart_operation_invalid')
        for record in records:
            if not isinstance(record, dict):
                raise ValueError('workbook_ai_chart_operation_invalid')
            path = record.get('chartPath')
            if (not isinstance(path, str) or re.fullmatch(r'xl/charts/[A-Za-z0-9._-]+\.xml', path) is None
                    or len(owners.get(path, [])) != 1 or path in deleted):
                raise ValueError('workbook_ai_chart_target_invalid')
            if kind == 'applyChartDeletions':
                if set(record) != {'chartPath', 'sheetName'} or record['sheetName'] != owners[path][0]:
                    raise ValueError('workbook_ai_chart_target_invalid')
                deleted.add(path)
            elif (not set(record) - {'chartPath'}
                    or not set(record).issubset({'chartPath'} | _FORMAT_FIELDS)):
                raise ValueError('workbook_ai_chart_format_unsupported')
            else:
                _validate_format(record)
