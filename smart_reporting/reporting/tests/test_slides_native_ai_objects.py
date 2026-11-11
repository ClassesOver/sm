"""原生表格/图表候选使用真实PPTX预览和独立读取，不改来源。"""
import hashlib
from copy import deepcopy
from io import BytesIO
from uuid import uuid4

import pytest
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
from smart_reporting.reporting.tests.test_slides_native_ai import Editor


@pytest.fixture
def objects():
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(0), Inches(3), Inches(1)).text = '人工标题'
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(3), Inches(1)).table
    for r in range(2):
        for c in range(2):
            table.cell(r, c).text = f'原格{r}{c}'
    stream = BytesIO()
    deck.save(stream)
    content = patch_office('pptx', stream.getvalue(), [{'kind': 'editSlides', 'edits': [],
        'charts': [{'slideIndex': 0, 'kind': 'bar', 'categories': ['甲', '乙'],
            'series': [{'name': '原系列', 'values': [1, 2]}]}]}])
    model = inspect_office('pptx', content)
    class RealEditor(Editor):
        def __init__(self):
            super().__init__()
            self.context = self.context.model_copy(update={'source_file': self.context.source_file.model_copy(
                update={'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)})})
        async def preview(self, context, *, expected_sha256, operations):
            assert expected_sha256 == self.context.source_file.sha256
            self.previews.append(deepcopy(operations))
            changed = patch_office('pptx', content, operations)
            return {'draftSha256': hashlib.sha256(changed).hexdigest(), 'model': inspect_office('pptx', changed)}
    return RealEditor(), content, model


@pytest.mark.anyio
async def test_table_and_chart_real_preview_accept_keep_manual_fields_and_source(objects):
    editor, source, model = objects
    table = next(e for e in model['slides'][0]['elements'] if e['type'] == 'table')
    chart = next(e for e in model['slides'][0]['elements'] if e['type'] == 'chart')
    base = [{'kind': 'editSlides', 'edits': [], 'backgrounds': [{'slideIndex': 0, 'color': '#123456'}],
        'tableCells': [{'slideIndex': 0, 'elementId': table['id'], 'row': 1, 'col': 1, 'text': '人工保留格'}],
        'chartEdits': [{'slideIndex': 0, 'elementId': chart['id'], 'kind': 'line'}]}]
    async def planner(prompt, **kwargs):
        assert '人工保留格' in prompt
        assert 'line' in prompt
        return {'summary': '更新表图', 'edits': [], 'order': [0],
            'tableCells': [{'slideIndex': 0, 'elementId': table['id'], 'row': 0, 'col': 0, 'text': 'AI新格'}],
            'chartEdits': [{'slideIndex': 0, 'elementId': chart['id'], 'categories': ['一', '二'],
                'series': [{'name': '新系列', 'values': [42, 73]}]}]}
    ai = NativeSlidesAIService(editor, planner=planner, enabled=True)
    try:
        started = await ai.start_edit(None, client_request_id=uuid4().hex, instruction='更新选中的表格图表',
            expected_sha256=editor.context.source_file.sha256, operations=base,
            selection=[{'slideIndex': 0, 'elementId': e['id']} for e in (table, chart)])
        result = await ai.wait_edit_status(None, started['editId'])
        assert result['status'] == 'succeeded', result
        accepted = await ai.accept_edit(None, started['editId'], expected_sha256=editor.context.source_file.sha256,
            operations=base, snapshot_sha256=result['snapshotSha256'])
        changed = Presentation(BytesIO(patch_office('pptx', source, accepted['operations'])))
        changed_table = next(s.table for s in changed.slides[0].shapes if s.has_table)
        changed_chart = next(s.chart for s in changed.slides[0].shapes if s.has_chart)
        assert changed_table.cell(0, 0).text == 'AI新格'
        assert changed_table.cell(1, 1).text == '人工保留格'
        assert int(changed_chart.chart_type) == 65
        assert list(changed_chart.series[0].values) == [42, 73]
        assert changed_chart.series[0].name == '新系列'
        assert accepted['operations'][0]['backgrounds'] == base[0]['backgrounds']
        assert Presentation(BytesIO(source)).slides[0].shapes[1].table.cell(0, 0).text == '原格00'
        assert base[0]['chartEdits'][0] == {'slideIndex': 0, 'elementId': chart['id'], 'kind': 'line'}
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_native_object_candidate_cannot_touch_unselected_chart(objects):
    editor, _, model = objects
    table = next(e for e in model['slides'][0]['elements'] if e['type'] == 'table')
    chart = next(e for e in model['slides'][0]['elements'] if e['type'] == 'chart')
    async def planner(prompt, **kwargs):
        assert '原系列' not in prompt
        return {'summary': '越权', 'edits': [], 'order': [0],
            'chartEdits': [{'slideIndex': 0, 'elementId': chart['id'], 'categories': ['越权']}]}
    ai = NativeSlidesAIService(editor, planner=planner, enabled=True)
    try:
        job = await ai.start_edit(None, client_request_id=uuid4().hex, instruction='表格',
            expected_sha256=editor.context.source_file.sha256, operations=[],
            selection=[{'slideIndex': 0, 'elementId': table['id']}])
        result = await ai.wait_edit_status(None, job['editId'])
        assert result['status'] == 'failed', result
        assert 'proposal' not in result
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_native_object_structure_draft_is_rejected_without_guessing_ids(objects):
    editor, _, model = objects
    target = next(e for e in model['slides'][0]['elements'] if e['type'] == 'table')
    async def planner(*args, **kwargs):
        pytest.fail('结构未核验不能进入模型')
    ai = NativeSlidesAIService(editor, planner=planner, enabled=True)
    try:
        job = await ai.start_edit(None, client_request_id=uuid4().hex, instruction='表格',
            expected_sha256=editor.context.source_file.sha256,
            operations=[{'kind': 'editSlides', 'edits': [], 'elementOrders': [{'slideIndex': 0,
                'elementIds': [e['id'] for e in reversed(model['slides'][0]['elements'])]}]}],
            selection=[{'slideIndex': 0, 'elementId': target['id']}])
        result = await ai.wait_edit_status(None, job['editId'])
        assert result['status'] == 'failed', result
        assert '保存' in result['error']['message']
    finally:
        await ai.aclose()


def test_native_object_merge_replaces_only_same_cell_and_merges_chart_fields():
    base = [{'kind': 'editSlides', 'tableCells': [
        {'slideIndex': 0, 'elementId': 't', 'row': 0, 'col': 0, 'text': '人工旧格'},
        {'slideIndex': 0, 'elementId': 't', 'row': 0, 'col': 1, 'text': '人工邻格'}],
        'chartEdits': [{'slideIndex': 0, 'elementId': 'c', 'kind': 'line'}],
        'backgrounds': [{'slideIndex': 0, 'color': '#123456'}]}]
    candidate = [{'kind': 'editSlides', 'edits': [], 'tableCells': [
        {'slideIndex': 0, 'elementId': 't', 'row': 0, 'col': 0, 'text': '候选新格'}],
        'chartEdits': [{'slideIndex': 0, 'elementId': 'c', 'categories': ['甲'],
            'series': [{'name': '新值', 'values': [42]}]}]}]
    combined = NativeSlidesAIService._combined_operations(None, base, candidate)[0]
    assert [cell['text'] for cell in combined['tableCells']] == ['候选新格', '人工邻格']
    assert combined['chartEdits'][0]['kind'] == 'line'
    assert combined['chartEdits'][0]['series'][0]['values'] == [42]
    assert combined['backgrounds'] == base[0]['backgrounds']
    assert base[0]['tableCells'][0]['text'] == '人工旧格'


@pytest.mark.anyio
async def test_deck_scope_allows_native_objects_but_text_scope_does_not(objects):
    editor, _, model = objects
    table = next(e for e in model['slides'][0]['elements'] if e['type'] == 'table')
    title = next(e for e in model['slides'][0]['elements'] if e['type'] == 'text')
    async def planner(prompt, **kwargs):
        return {'summary': '改表', 'edits': [], 'order': [0], 'tableCells': [
            {'slideIndex': 0, 'elementId': table['id'], 'row': 0, 'col': 0, 'text': '全稿授权新格'}]}
    ai = NativeSlidesAIService(editor, planner=planner, enabled=True)
    try:
        for scope, selection, status in [
            ('deck', [], 'succeeded'),
            ('selection', [{'slideIndex': 0, 'elementId': title['id']}], 'failed'),
            ('selection', [{'slideIndex': True, 'elementId': table['id']}], 'failed')]:
            job = await ai.start_edit(None, client_request_id=uuid4().hex, instruction='改表',
                expected_sha256=editor.context.source_file.sha256, operations=[], selection=selection, scope=scope)
            assert (await ai.wait_edit_status(None, job['editId']))['status'] == status
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_slide_size_draft_requires_save_before_ai_to_avoid_double_scaling(objects):
    editor, _, model = objects
    target = next(e for e in model['slides'][0]['elements'] if e['type'] == 'text')
    async def planner(*args, **kwargs):
        pytest.fail('未保存尺寸修改不能交给AI再次缩放')
    ai = NativeSlidesAIService(editor, planner=planner, enabled=True)
    try:
        job = await ai.start_edit(None, client_request_id=uuid4().hex, instruction='调整对象位置',
            expected_sha256=editor.context.source_file.sha256,
            operations=[{'kind': 'editSlides', 'edits': [], 'slideSize': {
                'cx': model['size']['cx'] * 2, 'cy': model['size']['cy'] * 2}}],
            selection=[{'slideIndex': 0, 'elementId': target['id']}])
        result = await ai.wait_edit_status(None, job['editId'])
        assert result['status'] == 'failed', result
        assert '先保存页面尺寸修改' in result['error']['message']
        assert 'proposal' not in result
        assert editor.previews == [[]]
    finally:
        await ai.aclose()
