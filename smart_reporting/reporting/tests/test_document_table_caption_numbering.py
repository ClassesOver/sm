"""表题仅来自当前修订登记来源；编号不改变冻结正文。"""

import json
from copy import deepcopy
from hashlib import sha256

import pytest

from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id

from .test_trace_contracts import _index


def caption_input(markdown, captions=None):
    from smart_reporting.reporting.delivery.artifacts_v1 import _markdown_table_artifacts
    captions = captions if captions is not None else {'table-a': '收支明细 1234.5600', 'table-b': '收支明细 1234.5600'}
    raw = markdown.encode()
    identity = {'path': 'report.md', 'mediaType': 'text/markdown', 'size': len(raw), 'sha256': sha256(raw).hexdigest()}
    index = _index().model_dump(mode='json', by_alias=True)
    old_id = index['markdownFileResourceId']
    index['markdownFileResourceId'] = derive_resource_id(identity['path'])
    index['files'] = [dict(resourceId=derive_resource_id(identity['path']), **identity) if item['resourceId'] == old_id else item for item in index['files']]
    index['tables'] = [{'tableId': key, 'rowKeys': ['row'], 'columnKeys': ['value'],
        'originMarkdown': title + '\n\n' + table(key), 'cells': []} for key, title in captions.items()]
    text = json.dumps(index, ensure_ascii=False)
    manifest = {'reportId': index['reportId'], 'revision': index['revision'], 'codingTaskKey': 'fixture',
        'datasetSnapshotHash': 'a' * 64, 'reportBasisId': index['reportBasisId'], 'markdown': identity,
        'citations': [{'citationId': 'citation_001', 'datasetId': 'dataset-1', 'requirementId': 'requirement-1', 'snapshotHash': 'a' * 64}],
        'tables': [item.model_dump(mode='json', by_alias=True) for item in _markdown_table_artifacts(markdown.replace('\r\n', '\n'))], 'sections': ['overview'], 'sectionNumbers': ['1'],
        'headingNumbers': [{'level': 2, 'number': '1', 'title': '经营概览', 'sectionCode': 'overview', 'anchor': 'report-section-overview'}],
        'traceIndex': {'path': 'trace-index.json', 'mediaType': 'application/json', 'size': len(text.encode()), 'sha256': sha256(text.encode()).hexdigest()}}
    return {'manifest': manifest, 'traceIndexText': text, 'markdownText': markdown, 'workflowRunId': index['workflowRunId']}


def table(id):
    return f'[[table:{id}]]\n| 项目 | value |\n| --- | ---: |\n| row | 1234.5600 |\n\n[[/table:{id}]]'


def sample_markdown():
    return '\n\n'.join(('普通表 99：不能编号', '收支明细 1234.5600', table('table-a'),
        '同名普通段', '收支明细 1234.5600', table('table-b')))


def test_table_caption_source_accepts_only_current_manifest_index_and_raw_markdown():
    from smart_reporting.reporting.delivery.report_runtime.table_captions import (
        validate_table_caption_input,
    )

    text = sample_markdown().replace('\n', '\r\n')
    input = caption_input(text)
    before = deepcopy(input)
    result = validate_table_caption_input(input, text.encode())
    assert result['status'] == 'verified'
    assert result['captions'] == {'table-a': '收支明细 1234.5600', 'table-b': '收支明细 1234.5600'}
    assert input == before


@pytest.mark.parametrize('fault', ['source', 'trace_bytes', 'revision', 'report', 'basis', 'markdown_reference'])
def test_table_caption_source_rejects_foreign_or_changed_identity_without_throwing(fault):
    from smart_reporting.reporting.delivery.report_runtime.table_captions import (
        validate_table_caption_input,
    )

    text = sample_markdown()
    input = caption_input(text)
    if fault == 'source':
        text += 'changed'
    elif fault == 'trace_bytes':
        input['traceIndexText'] += ' '
    else:
        index = json.loads(input['traceIndexText'])
        field = {'revision': 'revision', 'report': 'reportId', 'basis': 'reportBasisId', 'markdown_reference': 'markdownFileResourceId'}[fault]
        index[field] = 2 if fault == 'revision' else derive_resource_id('foreign.md') if fault == 'markdown_reference' else 'foreign'
        input['traceIndexText'] = json.dumps(index, ensure_ascii=False)
        raw = input['traceIndexText'].encode()
        input['manifest']['traceIndex'].update(size=len(raw), sha256=sha256(raw).hexdigest())
    result = validate_table_caption_input(input, text.encode())
    assert result['status'] == 'unavailable' and result['captions'] == {}
    assert result['issues'][0]['code'] == 'report_table_caption_source_unavailable'


@pytest.mark.parametrize('run', [None, 'foreign-workflow'])
def test_table_caption_source_requires_explicit_current_workflow_identity(run):
    from smart_reporting.reporting.delivery.report_runtime.table_captions import (
        validate_table_caption_input,
    )

    text = sample_markdown()
    input = caption_input(text)
    input['workflowRunId'] = run
    assert validate_table_caption_input(input, text.encode())['status'] == 'unavailable'


@pytest.mark.parametrize('fault', ['index-size', 'index-bytes', 'workflow-missing'])
def test_table_caption_loader_rechecks_actual_index_and_required_workflow(tmp_path, fault):
    from smart_reporting.reporting.delivery.report_runtime.table_captions import (
        load_table_caption_input,
    )

    text = sample_markdown()
    input = caption_input(text)
    state = {'_tableCaptionManifest': input['manifest'], '_tableCaptionWorkflowRunId': input['workflowRunId']}
    raw_index = input['traceIndexText'].encode()
    if fault == 'index-size':
        raw_index += b' '
    elif fault == 'index-bytes':
        raw_index = raw_index.replace(b'run-1', b'run-9')
    else:
        state.pop('_tableCaptionWorkflowRunId')
    (tmp_path / 'trace-index.json').write_bytes(raw_index)
    assert load_table_caption_input(state, tmp_path, 'report.md', text.encode())['status'] == 'unavailable'


def test_table_caption_identity_respects_registered_title_punctuation_and_excludes_fenced_code():
    from smart_reporting.reporting.delivery.report_runtime.table_captions import (
        prepare_table_captions,
    )

    title = '2026年：表明细。'
    text = '```text\n' + title + '\n\n' + table('table-a') + '\n```\n\n' + title + '\n\n' + table('table-a')
    prepared, plans, issues = prepare_table_captions(text, {'table-a': title})
    assert len(plans) == 1 and plans[0]['caption'] == title and not issues
    assert prepared.startswith('```text\n' + title + '\n\n' + table('table-a'))


def test_duplicate_or_untitled_or_renamed_table_titles_remain_unverified():
    from smart_reporting.reporting.delivery.report_runtime.table_captions import (
        prepare_table_captions,
    )

    text = '\n\n'.join(('原题', table('table-a'), '原题', table('table-a'), table('table-b'), '改过的表题', table('table-c')))
    prepared, plans, issues = prepare_table_captions(text, {'table-a': '原题', 'table-c': '旧题'})
    assert prepared == text and plans == [] and len(issues) == 4


@pytest.mark.parametrize('numbered', [True, False])
def test_table_caption_plan_uses_identity_and_adjacency_not_caption_text_set(numbered):
    from markdown_it import MarkdownIt

    from smart_reporting.reporting.delivery.report_runtime.pdf import _pdf_markdown
    from smart_reporting.reporting.delivery.report_runtime.table_captions import (
        prepare_table_captions,
        render_table_captions,
    )

    text = sample_markdown()
    captions = {'table-a': '收支明细 1234.5600', 'table-b': '收支明细 1234.5600'}
    source = text + '\n\n收支明细 1234.5600\n\n' + '用户改题\n\n' + table('table-c')
    prepared, plans, issues = prepare_table_captions(source, {**captions, 'table-c': '原始表题'})
    assert [item['tableId'] for item in plans] == ['table-a', 'table-b']
    assert '用户改题' in prepared and '收支明细 1234.5600' in prepared
    assert any(item['code'] == 'report_table_caption_unverified' for item in issues)
    visible, _, _ = _pdf_markdown(prepared, None, include_sources=False)
    html = MarkdownIt('commonmark', {'html': False}).enable('table').render(visible)
    result = render_table_captions(html, plans, numbered=numbered)
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(result, 'html.parser')
    assert [node.get_text() for node in soup.select('.report-table-caption')] == [
        (f'表 {n}：' if numbered else '') + '收支明细 1234.5600' for n in (1, 2)]
    assert [node['data-table-id'] for node in soup.select('.report-table-caption')] == ['table-a', 'table-b']
    assert soup.select('.report-table-caption')[0].find_next_sibling().name == 'table'
    assert source == text + '\n\n收支明细 1234.5600\n\n' + '用户改题\n\n' + table('table-c')


def test_table_caption_projection_receipt_binds_titles_and_keeps_same_plain_text():
    from bs4 import BeautifulSoup
    from markdown_it import MarkdownIt

    from smart_reporting.reporting.delivery.report_runtime.projection import (
        build_render_projection,
        verify_render_projection,
    )
    from smart_reporting.reporting.delivery.report_runtime.table_captions import (
        render_table_captions,
    )

    text = sample_markdown()
    captions = {'table-a': '收支明细 1234.5600', 'table-b': '收支明细 1234.5600'}
    projection = build_render_projection(text, [], table_captions=captions)
    assert [item['tableId'] for item in projection.table_captions] == ['table-a', 'table-b']
    body = MarkdownIt('commonmark', {'html': False}).enable('table').render(projection.markdown)
    soup = BeautifulSoup(render_table_captions(body, projection.table_captions, numbered=True), 'html.parser')
    assert [node.get_text() for node in soup.select('.report-table-caption')] == ['表 1：收支明细 1234.5600', '表 2：收支明细 1234.5600']
    assert verify_render_projection(projection.receipt, text, [], table_captions=captions)['status'] == 'verified'
    assert verify_render_projection(projection.receipt, text, [], table_captions={})['status'] == 'unknown'


@pytest.mark.parametrize('pdf_numbered', [True, False])
def test_real_table_captions_keep_opposite_format_settings_editable_identity_and_originals(tmp_path, pdf_numbered):
    import shutil
    from pathlib import Path

    from docx import Document
    from pypdf import PdfReader

    from smart_reporting.preferences.document_adapter import document_design
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
    from smart_reporting.reporting.delivery.report_runtime.table_captions import caption_bookmark

    from .test_report_runtime_full_render import _build_workspace

    root = tmp_path / 'workspace'
    state = _build_workspace(root)
    state.pop('_editorExportSettings')
    source = root / 'report.md'
    with source.open('a') as stream:
        stream.write('\n\n收支明细 1234.5600\n\n普通同名段保持原样。\n\n' + sample_markdown())
    input = caption_input(source.read_text())
    state['_tableCaptionManifest'] = input['manifest']
    state['_tableCaptionWorkflowRunId'] = 'run-1'
    (root / 'trace-index.json').write_text(input['traceIndexText'])
    preferences = FormatPreferences.model_validate({'common': {'signer': '表题工程验证'}, **{fmt: {'cover': False, 'toc': False, 'sources': False,
        'headerFooter': {'enabled': False, 'pageNumbers': False}, 'watermark': {'enabled': False},
        'tables': {'captionNumbering': enabled}} for fmt, enabled in [('pdf', pdf_numbered), ('word', not pdf_numbered)]}})
    state['_formatDesigns'] = {fmt: document_design(resolve_format_preferences(preferences, fmt)).compact() for fmt in ('pdf', 'word')}
    before = source.read_bytes(), (root / 'trace-index.json').read_bytes(), deepcopy(state)
    result = ReportRuntime(root).render_markdown(state, 'report.md', 'revision/report.pdf',
        '.reporting-tmp/workspace-report-table-captions-render/render.pdf')
    assert result['status'] == 'rendered'
    pdf_text = '\n'.join(page.extract_text() for page in PdfReader(root / 'revision/report.pdf').pages)
    document = Document(root / 'revision/report.docx')
    plain = [paragraph for paragraph in document.paragraphs if paragraph.text == '收支明细 1234.5600']
    assert plain and plain[0].style.name != 'Caption'
    for n, id in enumerate(('table-a', 'table-b'), 1):
        expected = (f'表 {n}：' if not pdf_numbered else '') + '收支明细 1234.5600'
        paragraphs = [p for p in document.paragraphs if p._p.xpath('.//w:bookmarkStart[@w:name="' + caption_bookmark(id) + '"]')]
        assert len(paragraphs) == 1
        paragraph = paragraphs[0]
        assert paragraph.text == expected and paragraph.style.name == 'Caption'
        assert paragraph._p.getnext().tag.endswith('}tbl')
        assert paragraph.paragraph_format.keep_with_next is True
        assert not paragraph._p.xpath('.//w:fldChar | .//w:instrText')
        assert (f'表 {n}：收支明细 1234.5600' in pdf_text) is pdf_numbered
    assert (source.read_bytes(), (root / 'trace-index.json').read_bytes(), state) == before
    output = Path('output/system-config-preferences/document-table-captions') / ('pdf-numbered' if pdf_numbered else 'word-numbered')
    output.mkdir(parents=True, exist_ok=True)
    for file in ['report.pdf', 'report.docx']:
        shutil.copyfile(root / 'revision' / file, output / file)
    (output / 'source.md').write_bytes(source.read_bytes())
    (output / 'trace-index.json').write_bytes((root / 'trace-index.json').read_bytes())
    (output / 'receipt.json').write_text(json.dumps({'pdfNumbered': pdf_numbered, 'wordNumbered': not pdf_numbered,
        'tableCaptionInput': input, 'render': result['render']}, ensure_ascii=False, indent=2))


def test_real_missing_caption_source_preserves_files_and_original_titles_with_failed_validation(tmp_path):
    from docx import Document
    from pypdf import PdfReader

    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime

    from .test_report_runtime_full_render import _build_workspace

    root = tmp_path / 'workspace'
    state = _build_workspace(root)
    source = root / 'report.md'
    source.write_text(source.read_text() + '\n\n' + sample_markdown())
    before = source.read_bytes(), deepcopy(state)
    runtime = ReportRuntime(root)
    result = runtime.render_markdown(state, 'report.md', 'revision/report.pdf',
        '.reporting-tmp/workspace-report-missing-caption-render/render.pdf')
    assert result['status'] == 'rendered'
    render = result['render']
    assert render['tableCaptionSource']['status'] == 'unavailable'
    assert any(issue['code'] == 'report_table_caption_source_unavailable' for issue in render['renderIssues'])
    assert sum(issue['code'] == 'report_table_caption_unverified' for issue in render['renderIssues']) == 2
    assert (source.read_bytes(), state) == before
    document = Document(root / 'revision/report.docx')
    assert sum(p.text == '收支明细 1234.5600' for p in document.paragraphs) == 2
    assert not document.element.xpath('.//w:bookmarkStart[starts-with(@w:name,"tblcap_")]')
    pdf_text = '\n'.join(page.extract_text() for page in PdfReader(root / 'revision/report.pdf').pages)
    assert pdf_text.count('收支明细 1234.5600') == 2 and '表 1：' not in pdf_text
    artifacts = [(root / 'revision' / name).read_bytes() for name in ('report.pdf', 'report.docx')]
    state['render'] = render
    validation = runtime.validate_pdf(state, 'revision/report.pdf',
        '.reporting-tmp/workspace-report-missing-caption-validate')
    assert validation['ok'] is False
    assert any(issue['code'] == 'report_table_caption_source_unavailable' for issue in validation['issues'])
    assert [(root / 'revision' / name).read_bytes() for name in ('report.pdf', 'report.docx')] == artifacts


def test_real_long_and_compacted_tables_keep_single_identity_caption_and_all_values(tmp_path):
    import shutil
    from io import BytesIO
    from pathlib import Path

    from docx import Document
    from pypdf import PdfReader

    from smart_reporting.preferences.document_adapter import document_design
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
    from smart_reporting.reporting.delivery.office_engine import libreoffice_to_pdf
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
    from smart_reporting.reporting.delivery.report_runtime.table_captions import caption_bookmark

    from .test_report_runtime_full_render import _build_workspace

    root = tmp_path / 'workspace'
    state = _build_workspace(root)
    state.pop('_editorExportSettings')
    blocks = {
        'table-a': '[[table:table-a]]\n| BusinessRow | Value |\n| --- | ---: |\n'
            + '\n'.join(f'| BusinessRow{n:03} | {n}.5600 |' for n in range(100)) + '\n\n[[/table:table-a]]',
        'table-b': '[[table:table-b]]\n| | Value |\n| --- | ---: |\n'
            + '\n'.join(f'| 2026年{n}月 | {n}.7800 |' for n in range(1, 13)) + '\n\n[[/table:table-b]]',
    }
    titles = {'table-a': 'Long registered table', 'table-b': 'Compacted registered table'}
    source = root / 'report.md'
    source.write_text(source.read_text() + '\n\n' + '\n\n'.join(titles[key] + '\n\n' + body for key, body in blocks.items()))
    input = caption_input(source.read_text(), titles)
    index = json.loads(input['traceIndexText'])
    for entry in index['tables']:
        entry['originMarkdown'] = titles[entry['tableId']] + '\n\n' + blocks[entry['tableId']]
    input['traceIndexText'] = json.dumps(index, ensure_ascii=False)
    raw_index = input['traceIndexText'].encode()
    input['manifest']['traceIndex'].update(size=len(raw_index), sha256=sha256(raw_index).hexdigest())
    state['_tableCaptionManifest'] = input['manifest']
    state['_tableCaptionWorkflowRunId'] = 'run-1'
    (root / 'trace-index.json').write_bytes(raw_index)
    preferences = FormatPreferences.model_validate({'common': {'signer': '跨页表题验证'}, **{fmt: {
        'cover': False, 'toc': False, 'sources': False,
        'headerFooter': {'enabled': False, 'pageNumbers': False}, 'watermark': {'enabled': False},
        'tables': {'captionNumbering': True}} for fmt in ('pdf', 'word')}})
    state['_formatDesigns'] = {fmt: document_design(resolve_format_preferences(preferences, fmt)).compact() for fmt in ('pdf', 'word')}
    before = source.read_bytes(), raw_index, deepcopy(state)
    result = ReportRuntime(root).render_markdown(state, 'report.md', 'revision/report.pdf',
        '.reporting-tmp/workspace-report-long-caption-render/render.pdf')
    assert result['status'] == 'rendered'
    assert result['render']['tableCaptionSource']['status'] == 'verified'
    assert not any(issue['code'].startswith('report_table_caption_') for issue in result['render']['renderIssues'])
    document = Document(root / 'revision/report.docx')
    for number, key in enumerate(titles, 1):
        paragraphs = [p for p in document.paragraphs if p._p.xpath('.//w:bookmarkStart[@w:name="' + caption_bookmark(key) + '"]')]
        assert len(paragraphs) == 1 and paragraphs[0].text == f'表 {number}：' + titles[key]
        assert paragraphs[0]._p.getnext().tag.endswith('}tbl')
    assert len(document.tables) == 4  # 原有普通表 + 长表 + 两个转置分块。
    word_text = '\n'.join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
    for n in range(100):
        assert f'BusinessRow{n:03}' in word_text and f'{n}.5600' in word_text
    for n in range(1, 13):
        assert f'{n}.7800' in word_text
    pdf_pages = [page.extract_text() for page in PdfReader(root / 'revision/report.pdf').pages]
    word_preview = libreoffice_to_pdf((root / 'revision/report.docx').read_bytes(), suffix='.docx', timeout=90)
    word_pages = [page.extract_text() for page in PdfReader(BytesIO(word_preview)).pages]
    for pages in (pdf_pages, word_pages):
        assert len([text for text in pages if 'BusinessRow' in text]) >= 2
        for number, key in enumerate(titles, 1):
            assert sum(text.count(titles[key]) for text in pages) == 1
            caption_page = next(text for text in pages if titles[key] in text)
            assert ('BusinessRow000' if number == 1 else '1.7800') in caption_page
        assert 'BusinessRow099' in '\n'.join(pages) and '12.7800' in '\n'.join(pages)
    assert (source.read_bytes(), (root / 'trace-index.json').read_bytes(), state) == before
    output = Path('output/system-config-preferences/document-table-captions/long-and-compacted')
    output.mkdir(parents=True, exist_ok=True)
    for file in ('report.pdf', 'report.docx'):
        shutil.copyfile(root / 'revision' / file, output / file)
    (output / 'word-preview.pdf').write_bytes(word_preview)
    (output / 'source.md').write_bytes(source.read_bytes())
    (output / 'trace-index.json').write_bytes(raw_index)
    (output / 'receipt.json').write_text(json.dumps({'tableCaptionInput': input, 'render': result['render']}, ensure_ascii=False, indent=2))
