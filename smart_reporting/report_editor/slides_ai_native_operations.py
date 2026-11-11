"""仅原生 PPTX 候选的已有表格/图表协议，不扩张报告幻灯片合同。"""
from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import Field, StrictFloat, StrictInt, StrictStr

from ..reporting.contract import StrictModel
from .slides_ai import SlidesAIProposal, _validate_proposal

NativeChartKind = Literal['bar', 'barStacked', 'barPercentStacked', 'barH', 'bar3D', 'line',
    'area', 'pie', 'pie3D', 'doughnut', 'scatter', 'radar', 'comboBarLine']


class NativeSlidesAITableCell(StrictModel):
    slide_index: StrictInt = Field(alias='slideIndex', ge=0)
    element_id: StrictStr = Field(alias='elementId', min_length=1)
    row: StrictInt = Field(ge=0)
    col: StrictInt = Field(ge=0)
    text: StrictStr = Field(max_length=10000)


class NativeSlidesAIChartSeries(StrictModel):
    name: StrictStr = Field(max_length=100)
    values: tuple[StrictInt | StrictFloat, ...] = Field(min_length=1, max_length=100)


class NativeSlidesAIChartEdit(StrictModel):
    slide_index: StrictInt = Field(alias='slideIndex', ge=0)
    element_id: StrictStr = Field(alias='elementId', min_length=1)
    kind: NativeChartKind | None = None
    categories: tuple[StrictStr, ...] | None = Field(default=None, min_length=1, max_length=100)
    series: tuple[NativeSlidesAIChartSeries, ...] | None = Field(default=None, min_length=1, max_length=20)


class NativeSlidesAINotesEdit(StrictModel):
    slide_index: StrictInt = Field(alias='slideIndex', ge=0)
    text: StrictStr = Field(max_length=20000)


class NativeSlidesAIProposal(SlidesAIProposal):
    notes_edits: tuple[NativeSlidesAINotesEdit, ...] = Field(default=(), alias='notesEdits', max_length=100)
    table_cells: tuple[NativeSlidesAITableCell, ...] = Field(default=(), alias='tableCells', max_length=500)
    chart_edits: tuple[NativeSlidesAIChartEdit, ...] = Field(default=(), alias='chartEdits', max_length=50)


def native_editable_elements(deck: dict) -> dict[tuple[int, str], dict]:
    """editable表示服务端本轮授权；图表另需引擎chartEditSafe能力。"""
    return {(slide['slideIndex'], element['id']): element for slide in deck['slides']
            for element in slide.get('elements', []) if element.get('editable') is True and (
                element.get('type') == 'table' and isinstance(element.get('tableCells'), list)
                and element.get('tableCellsEditable') is not False or
                element.get('type') == 'chart' and element.get('chartEditSafe') is True)}


def _label(value: str) -> bool:
    return len(value) <= 100 and not any(ord(char) < 32 or ord(char) == 127 for char in value)


def validate_native_proposal(raw: dict, editable: dict, deck: dict) -> dict:
    """先复用旧文字/页序合同，再核验原生表格格位和安全图表实际身份。"""
    # 先严格Schema验证，不能让pydantic把布尔坐标或字符串数值转换成有效候选。
    parsed = NativeSlidesAIProposal.model_validate(raw)
    native = parsed.model_dump(mode='python', by_alias=True, exclude_none=True)
    if any(isinstance(value, float) and not math.isfinite(value)
           for chart in native.get('chartEdits', ()) for series in chart.get('series', ())
           for value in series['values']):
        raise ValueError('proposal_chart_data_invalid')
    # JSON模式保留旧验证器依赖的list结构。
    data = parsed.model_dump(mode='json', by_alias=True, exclude_none=True)
    known = {(slide['slideIndex'], element['id']): element for slide in deck['slides']
             for element in slide.get('elements', [])}
    text_editable = {key: value for key, value in editable.items()
                     if known.get(key, {}).get('type') not in {'table', 'chart'}}
    clean = _validate_proposal({key: value for key, value in data.items()
                               if key not in {'tableCells', 'chartEdits', 'notesEdits'}}, text_editable, deck)
    authorized = native_editable_elements(deck)
    seen = set()
    for cell in data['tableCells']:
        key = (cell['slideIndex'], cell['elementId'])
        target = authorized.get(key)
        identity = (*key, cell['row'], cell['col'])
        rows = (target or {}).get('tableCells', [])
        if (target is None or target.get('type') != 'table' or identity in seen or
                cell['row'] >= len(rows) or not isinstance(rows[cell['row']], list) or
                cell['col'] >= len(rows[cell['row']]) or
                not isinstance(rows[cell['row']][cell['col']], str)):
            raise ValueError('proposal_table_cell_not_editable')
        if (len(cell['text'].encode('utf-16-le')) // 2 > 10000 or
                re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', cell['text'])):
            raise ValueError('proposal_table_text_invalid')
        seen.add(identity)
    seen = set()
    for chart in data['chartEdits']:
        key = (chart['slideIndex'], chart['elementId'])
        target = authorized.get(key)
        if (target is None or target.get('type') != 'chart' or key in seen or
                not any(field in chart for field in ('kind', 'categories')) or
                ('categories' in chart) != ('series' in chart)):
            raise ValueError('proposal_chart_not_editable')
        categories = chart.get('categories', target.get('chartCategories'))
        series = chart.get('series', target.get('chartSeries'))
        if (not isinstance(categories, list) or not 1 <= len(categories) <= 100 or
                any(not isinstance(label, str) or not _label(label) for label in categories) or
                not isinstance(series, list) or not 1 <= len(series) <= 20):
            raise ValueError('proposal_chart_data_invalid')
        for entry in series:
            if (not _label(entry['name']) or len(entry['values']) != len(categories) or
                    any(type(value) not in (int, float) or not -1e100 <= value <= 1e100 or
                        not math.isfinite(value) for value in entry['values'])):
                raise ValueError('proposal_chart_data_invalid')
        kind = chart.get('kind', target.get('chartKind'))
        if kind == 'comboBarLine' and len(series) < 2:
            raise ValueError('proposal_chart_data_invalid')
        if kind == 'scatter':
            try:
                valid = all(label.strip() and math.isfinite(float(label)) for label in categories)
            except ValueError:
                valid = False
            if not valid:
                raise ValueError('proposal_chart_data_invalid')
        seen.add(key)
    slides = {slide['slideIndex']: slide for slide in deck['slides']}
    seen = set()
    total = 0
    for note in data['notesEdits']:
        index, text = note['slideIndex'], note['text']
        target = slides.get(index, {})
        if index in seen or target.get('notesAuthorized') is not True or target.get('notesEditable') is not True:
            raise ValueError('proposal_notes_not_editable')
        if any(ord(char) < 32 and char not in '\t\n\r' or 0xd800 <= ord(char) <= 0xdfff
               or ord(char) in (0xfffe, 0xffff) for char in text):
            raise ValueError('proposal_notes_text_invalid')
        length = len(text.encode('utf-16-le')) // 2
        total += length
        if length > 20000 or total > 200000:
            raise ValueError('proposal_notes_text_invalid')
        note['text'] = text.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n')
        seen.add(index)
    clean.update(tableCells=data['tableCells'], chartEdits=data['chartEdits'], notesEdits=data['notesEdits'])
    return clean
