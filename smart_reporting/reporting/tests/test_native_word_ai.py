"""Word AI 复杂操作使用明确选区和真实原生引擎。"""
from importlib import import_module, util
from io import BytesIO

import pytest
from docx import Document

from scripts.probe_native_docx_tables import fixture
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.models import ReportingError


def adapter():
    name = 'smart_reporting.report_editor.native_word_ai'
    assert util.find_spec(name) is not None, 'Word AI 缺少原生复杂操作适配器'
    return import_module(name)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'word-ai.docx'
    fixture(path)
    return path.read_bytes()


def table_of(source):
    return next(block for block in inspect_docx(source)['blocks'] if block['type'] == 'table')


def proposal(kind, block, **arguments):
    return adapter().NativeWordAIProposal(summary='调整已授权对象', operations=[{
        'kind': kind, 'arguments': {'blockId': block['blockId'], **arguments},
    }])


def test_word_ai_complex_tools_are_explicit_and_have_native_guides():
    module = adapter()
    for kind in ['reshapeTableCells', 'restructureTable', 'setTableCellAlignment',
                 'resizeTableColumns', 'setParagraphSpacing', 'formatRange']:
        assert kind in module.WORD_AI_OPERATION_FIELDS
        assert kind in module.WORD_AI_INSTRUCTIONS


def test_whole_table_selection_enables_real_multistep_structure_preview(source):
    module = adapter()
    table = table_of(source)
    selected = module.selected_word_objects({'blocks': [table]}, [], [{'blockId': table['blockId']}])
    planned = proposal('restructureTable', table, steps=[
        {'kind': 'insertTableRow', 'index': 1},
        {'kind': 'deleteTableColumn', 'index': 2},
    ], texts=[{'row': 1, 'column': 0, 'text': '新增已核验内容'}])
    candidate = module.word_candidate(planned.engine_operations(), selected)
    assert candidate[0]['expectedObjectSha256'] == table['expectedObjectSha256']
    preview = patch_docx(source, candidate)
    after = Document(BytesIO(preview)).tables[0]
    assert len(after.rows) == 4
    assert len(after.columns) == 2
    assert after.cell(1, 0).text == '新增已核验内容'
    assert Document(BytesIO(source)).tables[0].cell(1, 0).text != '新增已核验内容'


def test_word_ai_merge_split_executes_in_real_engine_and_preserves_other_cells(source):
    module = adapter()
    table = table_of(source)
    selected = module.selected_word_objects({'blocks': [table]}, [], [{'blockId': table['blockId']}])
    candidate = module.word_candidate(proposal('reshapeTableCells', table, steps=[
        {'kind': 'mergeTableCells', 'rect': {'top': 0, 'left': 0, 'bottom': 1, 'right': 2}},
        {'kind': 'splitTableCells', 'rect': {'top': 0, 'left': 0, 'bottom': 1, 'right': 2},
         'rows': 1, 'columns': 2, 'mergeFirst': True},
    ]).engine_operations(), selected)
    result = Document(BytesIO(patch_docx(source, candidate))).tables[0]
    original = Document(BytesIO(source)).tables[0]
    assert result.cell(0, 0).text == original.cell(0, 0).text + '\n' + original.cell(0, 1).text
    assert result.cell(0, 1).text == ''
    assert result.cell(2, 2).text == original.cell(2, 2).text


def test_cell_selection_cannot_authorize_whole_table_structure(source):
    module = adapter()
    table = table_of(source)
    cell = table['cells'][0][0]
    selected = module.selected_word_objects({'blocks': [table]}, [], [
        {'blockId': table['blockId'], 'cellId': cell['cellId']},
    ])
    with pytest.raises(ReportingError) as error:
        module.word_candidate(proposal('restructureTable', table, steps=[
            {'kind': 'deleteTableRow', 'index': 0},
        ]).engine_operations(), selected)
    assert error.value.code == 'native_ai_selection_mismatch'


@pytest.mark.parametrize('fault', ['foreign', 'forged_hash', 'unsupported', 'raw_xml'])
def test_word_ai_rejects_scope_identity_capability_and_schema_faults(source, fault):
    module = adapter()
    table = table_of(source)
    selected = module.selected_word_objects({'blocks': [table]}, [], [{'blockId': table['blockId']}])
    op = {'kind': 'restructureTable', 'blockId': table['blockId'],
          'steps': [{'kind': 'insertTableRow', 'index': 1}]}
    if fault == 'foreign':
        op['blockId'] = 'foreign'
    elif fault == 'forged_hash':
        op['expectedObjectSha256'] = 'forged'
    elif fault == 'unsupported':
        selected[0]['allowedOperations'].remove('restructureTable')
    else:
        op['xml'] = '<w:tbl/>'
    with pytest.raises((ReportingError, ValueError)):
        module.word_candidate([op], selected)


def test_selected_table_material_includes_manual_cell_changes_without_reanchoring(source):
    module = adapter()
    table = table_of(source)
    cell = table['cells'][0][0]
    manual = {'kind': 'replaceCellText', 'blockId': table['blockId'], 'cellId': cell['cellId'],
              'expectedObjectSha256': cell['expectedObjectSha256'], 'text': '人工未保存修改'}
    selected = module.selected_word_objects({'blocks': [table]}, [manual], [{'blockId': table['blockId']}])
    assert selected[0]['cells'][0][0]['text'] == '人工未保存修改'
    assert selected[0]['expectedObjectSha256'] == table['expectedObjectSha256']
    assert selected[0]['draftOperations'] == [manual]
    assert table['cells'][0][0]['text'] != '人工未保存修改'


def test_complex_paragraph_formatting_has_real_xml_result():
    module = adapter()
    document = Document()
    document.add_paragraph('授权格式化正文')
    document.add_paragraph('未授权正文')
    buffer = BytesIO()
    document.save(buffer)
    content = buffer.getvalue()
    model = inspect_docx(content)
    block = model['blocks'][0]
    selected = module.selected_word_objects(model, [], [{'blockId': block['blockId']}])
    candidate = module.word_candidate(proposal('setParagraphSpacing', block, spaceBefore=240,
                                             spaceAfter=120, lineSpacing=1.5).engine_operations(), selected)
    result = Document(BytesIO(patch_docx(content, candidate)))
    assert result.paragraphs[0].paragraph_format.space_before.twips == 240
    assert result.paragraphs[0].paragraph_format.space_after.twips == 120
    assert result.paragraphs[0].paragraph_format.line_spacing == 1.5
    assert result.paragraphs[1]._p.xml == document.paragraphs[1]._p.xml


def test_tools_require_complete_authorized_read_and_freeze_scope(source):
    module = adapter()
    assert hasattr(module, 'NativeWordAITools'), 'Word AI缺少真实查询与候选工具'
    table = table_of(source)
    selected = module.selected_word_objects({'blocks': [table]}, [], [{'blockId': table['blockId']}])
    tools = module.NativeWordAITools(selected)
    selected[0]['blockId'] = 'tampered_after_binding'
    operations = proposal('restructureTable', table, steps=[
        {'kind': 'insertTableRow', 'index': 1},
    ]).engine_operations()
    with pytest.raises(ReportingError, match='完整读取'):
        tools.propose_operations('插入一行', operations)
    context = tools.get_document_context()
    assert context['blocks'][0]['blockId'] == table['blockId']
    with pytest.raises(ReportingError):
        tools.read_blocks(['outside'])
    page = tools.read_blocks([table['blockId']])
    assert page['nextOffset'] is None
    receipt = tools.propose_operations('插入一行', operations)
    assert receipt['needsPreview'] is True and receipt['needsAcceptance'] is True
    assert tools.operations[0]['expectedObjectSha256'] == table['expectedObjectSha256']


def test_cell_tools_cannot_read_neighbouring_cell_content(source):
    module = adapter()
    assert hasattr(module, 'NativeWordAITools'), 'Word AI缺少真实查询与候选工具'
    table = table_of(source)
    cell = table['cells'][0][0]
    selected = module.selected_word_objects({'blocks': [table]}, [], [
        {'blockId': table['blockId'], 'cellId': cell['cellId']},
    ])
    tools = module.NativeWordAITools(selected)
    response = tools.read_blocks([table['blockId']])
    assert cell['cellId'] in response['content']
    assert table['cells'][0][1]['cellId'] not in response['content']
