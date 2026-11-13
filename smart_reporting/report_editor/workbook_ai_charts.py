"""Bind existing-chart candidates to unique identities in the frozen draft.

This deliberately authorizes formatting/deletion only. Chart data replacement
and creation need a separate source-data contract, not arbitrary cache literals.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal

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
    owners: dict[str, list[str]] = {}
    for sheet in model.get('sheets', []):
        for chart in sheet.get('charts', []):
            path = chart.get('chartPath')
            if isinstance(path, str):
                owners.setdefault(path, []).append(sheet['name'])
    deleted: set[str] = set()
    for operation in operations:
        kind = operation['kind']
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
