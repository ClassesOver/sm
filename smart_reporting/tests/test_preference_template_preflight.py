"""模板临时验收只走正式模板消费者，不写业务修订或套用通用布局。"""

import base64
import hashlib
from copy import deepcopy
from dataclasses import replace
from io import BytesIO

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.tests.test_preference_preflight import _inputs, _run
from smart_reporting.tests.test_preference_report_preflight import bound_case


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def template_bytes(*, declared=True, paragraph=False):
    document = Document()
    document.styles['Normal'].font.name = 'Liberation Serif'
    document.styles['Normal'].font.size = Pt(17)
    document.add_paragraph('保留业务引用：既有作者；2000-01-01')
    document.add_paragraph('{{report_title}}')
    document.add_paragraph('{{report_content}}')
    if declared:
        p = document.add_paragraph('旧署名和旧说明' if not paragraph else '{{report_signature}}')
        p.runs[0].bold = True
        if not paragraph:
            control, props, tag, content = (OxmlElement(name) for name in
                ('w:sdt', 'w:sdtPr', 'w:tag', 'w:sdtContent'))
            tag.set(qn('w:val'), 'report_signature')
            props.append(tag)
            control.append(props)
            p._p.addprevious(control)
            content.append(p._p)
            control.append(content)
    document.add_paragraph('末尾非声明业务说明保持')
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def identity(path, content):
    return {'path': path, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}


async def template_case(tmp_path):
    case = await bound_case(tmp_path)
    service, args, preferences, repository, context, root, registered = case
    raw = template_bytes()
    (root / 'frozen-template.docx').write_bytes(raw)
    file = {**identity('frozen-template.docx', raw), 'filename': '来源模板.docx'}
    repository.state.payload['requestMaterials'] = {'fileInputs': [], 'templateInput': file}
    return (*case, raw, file)


@pytest.mark.anyio
async def test_bound_template_snapshot_reads_exact_durable_file_and_declares_template_route(tmp_path, monkeypatch):
    from smart_reporting.management import preference_report_preflight as module

    service, args, _, _, _, root, _, raw, file = await template_case(tmp_path)
    async def only_snapshot(function, draft, materials, **kwargs):
        assert kwargs['formats'] == ('md', 'pdf', 'word')
        assert materials.template_source['identity'] == {**file, 'mediaType': None}
        assert materials.template_source['templateFormat'] == 'docx'
        assert (materials.workspace / file['path']).read_bytes() == raw
        assert materials.workspace != root
        return {'status': 'incomplete', 'canApply': False, 'formats': {}}
    monkeypatch.setattr(module, 'run_office_engine', only_snapshot)
    result = await service.run(**args)
    assert result['binding']['valid'] is True
    assert result['binding']['templateSource']['identity']['filename'] == '来源模板.docx'
    assert identity(file['path'], raw) in result['binding']['identities']


@pytest.mark.anyio
@pytest.mark.parametrize('change', ['filename', 'bytes'])
async def test_template_snapshot_postcheck_rejects_route_or_bytes_drift_and_preserves_output(tmp_path, monkeypatch, change):
    from smart_reporting.management import preference_report_preflight as module

    service, args, _, repository, _, root, _, _, _ = await template_case(tmp_path)
    async def generated(function, draft, materials, **kwargs):
        assert materials.template_source is not None
        if change == 'filename':
            repository.state.payload['requestMaterials']['templateInput']['filename'] = '另一模板.docx'
        else:
            (root / 'frozen-template.docx').write_bytes(b'changed')
        return {'status': 'incomplete', 'canApply': False, 'formats': {
            'word': {'artifact': {'size': 4, 'sha256': hashlib.sha256(b'test').hexdigest(), 'base64': 'dGVzdA=='}}}}
    monkeypatch.setattr(module, 'run_office_engine', generated)
    result = await service.run(**args)
    assert result['formats']['word']['artifact']['base64'] == 'dGVzdA=='
    assert result['binding']['valid'] is False and result['canApply'] is False
    assert result['issues']


def direct_case(tmp_path, *, declared=True, paragraph=False):
    draft, materials = _inputs(tmp_path)
    raw = template_bytes(declared=declared, paragraph=paragraph)
    (tmp_path / 'frozen-template.docx').write_bytes(raw)
    file = {**identity('frozen-template.docx', raw), 'filename': '来源模板.docx', 'mediaType': None}
    source = next(item for item in materials.state['sources'] if item['path'] == 'report.md')
    state = deepcopy(materials.state)
    state['sources'].append(identity(file['path'], raw))
    materials = replace(materials, state=state, sheets=(), slides=(), template_source={
        'identity': file, 'templateFormat': 'docx', 'sourceContent': source})
    return draft, materials, raw


def test_template_word_uses_actual_sdt_and_preserves_layout_without_generic_generation(tmp_path, monkeypatch):
    from smart_reporting.management import preference_preflight as module

    draft, materials, original = direct_case(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('模板不可调用通用生成器')
    monkeypatch.setattr(module, '_generate', forbidden)
    # 预览故障不应抹掉原生模板内容；真实PDF转换另一个唯一节点执行。
    monkeypatch.setattr(module, 'libreoffice_to_pdf', lambda *a, **k: (_ for _ in ()).throw(OSError('preview unavailable')))
    result = _run(draft, materials, formats=('word',))
    entry = result['formats']['word']
    content = base64.b64decode(entry['artifact']['base64'])
    document = Document(BytesIO(content))
    assert document.styles['Normal'].font.size.pt == 17  # 草稿正文12磅不能覆盖模板。
    assert document.paragraphs[0].text == '保留业务引用：既有作者；2000-01-01'
    assert document.paragraphs[-1].text == '末尾非声明业务说明保持'
    signature = document._element.body.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_signature"]]/w:sdtContent')
    assert [''.join(p.xpath('.//w:t/text()')) for p in signature[0]] == ['草稿验收编制', '2026-11-13']
    assert entry['templateReadback']['signature']['status'] == 'passed'
    assert entry['templateReadback']['outsideDeclaredTargets']['status'] == 'passed'
    assert entry['provenance']['layoutSource'] == 'uploaded_template'
    assert entry['provenance']['contentSource'] == 'frozen_report_markdown'
    assert entry['provenance']['signatureSource'] == 'current_draft'
    assert entry['templateReadback']['body']['status'] == 'passed'
    assert entry['templateReadback']['body']['coverage'] == 'complete'
    assert entry['provenance']['bodyRepresentation'] == 'native_docx_blocks'
    assert entry['provenance']['richDocumentProjection'] == 'structure_verified'
    assert entry['provenance']['template']['sha256'] == hashlib.sha256(original).hexdigest()
    assert all('evidenceKind' not in item for item in entry['readback']['checks'])
    assert any(issue['code'] == 'management_preference_preview_failed' for issue in entry['issues'])
    assert entry['artifact']['sha256'] == hashlib.sha256(content).hexdigest()
    assert result['canApply'] is False
    assert (tmp_path / 'frozen-template.docx').read_bytes() == original


@pytest.mark.parametrize(('declared', 'paragraph'), [(False, False), (True, True)])
def test_template_unmarked_or_paragraph_slot_never_claims_verified_sdt_or_example_cleanup(tmp_path, monkeypatch, declared, paragraph):
    from smart_reporting.management import preference_preflight as module

    draft, materials, _ = direct_case(tmp_path, declared=declared, paragraph=paragraph)
    monkeypatch.setattr(module, 'libreoffice_to_pdf', lambda *a, **k: (_ for _ in ()).throw(OSError('no preview')))
    result = _run(draft, materials, formats=('word',))
    entry = result['formats']['word']
    assert entry['artifact'] is not None
    assert entry['templateReadback']['signature']['status'] == 'unverified'
    assert entry['provenance']['undeclaredSamples'] == 'not_assessed'
    assert any(issue['code'] == 'management_preference_template_signature_unverified' for issue in entry['issues'])
    assert all(item.get('coverage') != 'complete' for item in entry['readback']['checks']
        if item.get('path') in {'word.common.signer', 'word.common.dateFormat', 'word.signature.description'})
    assert result['canApply'] is False


def test_template_signature_preview_uses_format_specific_draft_and_frozen_date(tmp_path, monkeypatch):
    from smart_reporting.management import preference_preflight as module
    from smart_reporting.preferences.models import FormatPreferences

    draft, materials, _ = direct_case(tmp_path)
    document = deepcopy(draft['document'])
    document['word']['common'] = {**document['word']['common'], 'signer': '文字专属署名', 'dateFormat': 'iso'}
    document['pdf']['common'] = {**document['pdf']['common'], 'signer': '版式专属署名', 'dateFormat': 'chinese'}
    document = FormatPreferences.model_validate(document).model_dump(mode='json', by_alias=True)
    draft.update(document=document, contentHash=configuration_hash(document))
    seen = {}
    from smart_reporting.reporting.delivery.templates import fill_report_template
    def no_pdf_engine(template, **kwargs):
        seen[kwargs['delivery_format']] = kwargs['signature']
        if kwargs['delivery_format'] == 'pdf':
            # PDF转换的真实唯一节点另测；此节点只隔离每格式签名决策。
            from pypdf import PdfWriter
            output = BytesIO()
            writer = PdfWriter()
            writer.add_blank_page(width=595, height=842)
            writer.write(output)
            from smart_reporting.reporting.delivery.templates import TemplateFillResult
            return TemplateFillResult(output.getvalue(), (), (), None)
        return fill_report_template(template, **kwargs)
    from smart_reporting.management import preference_template_preflight as template_module
    monkeypatch.setattr(template_module, 'fill_report_template', no_pdf_engine)
    monkeypatch.setattr(module, 'libreoffice_to_pdf', lambda *a, **k: (_ for _ in ()).throw(OSError('no preview')))
    result = _run(draft, materials, formats=('word', 'pdf'))
    assert seen['docx']['signer'] == '文字专属署名' and seen['docx']['date'] == '2026-11-13'
    assert seen['pdf']['signer'] == '版式专属署名' and seen['pdf']['date'] == '2026年11月13日'
    assert result['formats']['pdf']['artifact'] is not None
    assert result['canApply'] is False


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['missing', 'bad_identity', 'filename', 'foreign_office_bytes', 'empty_mapping', 'empty_string'])
async def test_untrusted_template_route_remains_unavailable_without_generic_substitution(tmp_path, monkeypatch, fault):
    from smart_reporting.management import preference_report_preflight as module

    service, args, _, repository, _, root, _, _, file = await template_case(tmp_path)
    if fault == 'missing':
        (root / file['path']).unlink()
    elif fault == 'bad_identity':
        repository.state.payload['requestMaterials']['templateInput']['sha256'] = 'f' * 64
    elif fault == 'filename':
        repository.state.payload['requestMaterials']['templateInput']['filename'] = 'other.pptx'
    elif fault == 'foreign_office_bytes':
        from openpyxl import Workbook
        output = BytesIO()
        Workbook().save(output)
        content = output.getvalue()
        (root / file['path']).write_bytes(content)
        repository.state.payload['requestMaterials']['templateInput'].update(identity(file['path'], content))
    else:
        repository.state.payload['requestMaterials']['templateInput'] = {} if fault == 'empty_mapping' else ''
    async def only_md(function, draft, materials, **kwargs):
        assert kwargs['formats'] == ('md',)
        assert materials.template_source is None
        return {'status': 'incomplete', 'canApply': False, 'formats': {
            'word': {'availability': 'unavailable'}, 'pdf': {'availability': 'unavailable'}}}
    monkeypatch.setattr(module, 'run_office_engine', only_md)
    result = await service.run(**args)
    assert result['formats']['word']['availability'] == 'unavailable'
    assert result['canApply'] is False
    assert result['binding']['availabilityIssues']['word']['code'] == 'management_preference_template_input_unavailable'


@pytest.mark.anyio
@pytest.mark.parametrize('registration', ['missing_key', 'none'])
async def test_absent_or_explicit_none_template_keeps_existing_generic_route(tmp_path, monkeypatch, registration):
    from smart_reporting.management import preference_report_preflight as module

    service, args, _, repository, _, _, _, _, file = await template_case(tmp_path)
    repository.state.payload['requestMaterials'] = {} if registration == 'missing_key' else {'templateInput': None}
    async def only_generic(function, draft, materials, **kwargs):
        assert kwargs['formats'] == ('md', 'pdf', 'word')
        assert materials.template_source is None
        return {'status': 'incomplete', 'canApply': False, 'formats': {}}
    monkeypatch.setattr(module, 'run_office_engine', only_generic)
    result = await service.run(**args)
    assert result['binding']['valid'] is True
    assert 'templateSource' not in result['binding']
    assert all(item['path'] != file['path'] for item in result['binding']['identities'])


@pytest.mark.parametrize('fault', ['reader', 'provenance', 'generation_receipt'])
def test_generated_template_artifact_survives_post_generation_failure_with_specific_reason(tmp_path, monkeypatch, fault):
    from smart_reporting.management import preference_preflight as module
    from smart_reporting.management import preference_template_preflight as templates
    from smart_reporting.management import preference_template_readback as reader

    draft, materials, _ = direct_case(tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError('injected template ' + fault)
    if fault == 'reader':
        monkeypatch.setattr(reader, 'read_template_document', fail)
        code = 'management_preference_readback_failed'
    elif fault == 'provenance':
        monkeypatch.setattr(templates, 'template_provenance', fail)
        code = 'management_preference_template_provenance_failed'
    else:
        actual = templates.fill_report_template
        def broken_receipt(*args, **kwargs):
            filled = actual(*args, **kwargs)
            class Receipt:
                content = filled.content
                @property
                def issues(self):
                    raise RuntimeError('injected receipt failure')
            return Receipt()
        monkeypatch.setattr(templates, 'fill_report_template', broken_receipt)
        code = 'management_preference_template_generation_failed'
    monkeypatch.setattr(module, 'libreoffice_to_pdf', lambda *a, **k: (_ for _ in ()).throw(OSError('no preview')))
    result = _run(draft, materials, formats=('word',))
    entry = result['formats']['word']
    content = base64.b64decode(entry['artifact']['base64'])
    assert Document(BytesIO(content)).paragraphs[0].text == '保留业务引用：既有作者；2000-01-01'
    assert entry['artifact']['size'] == len(content) and entry['artifact']['sha256'] == hashlib.sha256(content).hexdigest()
    assert any(issue['code'] == code for issue in entry['issues'])
    assert result['status'] == 'failed' and result['canApply'] is False


def test_template_docx_to_pdf_and_word_generate_real_independent_formats_without_generic_fallback(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from pypdf import PdfReader

    from smart_reporting.management import preference_preflight as module
    from smart_reporting.preferences.models import FormatPreferences

    draft, materials, original = direct_case(tmp_path)
    document = deepcopy(draft['document'])
    document['word']['common']['signer'] = '模板文字署名'
    document['pdf']['common'].update(signer='模板版式署名', dateFormat='slash')
    document['word']['signature']['description'] = 'Word独立说明'
    document['pdf']['signature']['description'] = 'PDF独立说明'
    document = FormatPreferences.model_validate(document).model_dump(mode='json', by_alias=True)
    draft.update(document=document, contentHash=configuration_hash(document))
    def forbidden(*args, **kwargs):
        pytest.fail('真实模板验收禁止通用生成兜底')
    monkeypatch.setattr(module, '_generate', forbidden)
    result = _run(draft, materials, formats=('word', 'pdf'))
    output = Path('output/system-config-preferences/template-preflight-continuation/implementation/actual')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'source-template.docx').write_bytes(original)
    evidence = {'scope': 'real_generator_reader_fixture_materials_not_production_approval', 'formats': {}}
    for format in ('word', 'pdf'):
        entry = result['formats'][format]
        content = base64.b64decode(entry['artifact']['base64'], validate=True)
        assert entry['artifact']['size'] == len(content)
        assert entry['artifact']['sha256'] == hashlib.sha256(content).hexdigest()
        (output / ('template-' + format + ('.docx' if format == 'word' else '.pdf'))).write_bytes(content)
        assert entry['pdf'] is not None and entry['previewPageCount'] > 0
        preview = base64.b64decode(entry['pdf']['base64'], validate=True)
        (output / (format + '-preview.pdf')).write_bytes(preview)
        assert entry['provenance']['template']['sha256'] == hashlib.sha256(original).hexdigest()
        assert entry['provenance']['generatedDate'] == '2026-11-13'
        assert all('evidenceKind' not in row for row in entry['readback']['checks'])
        evidence['formats'][format] = {**{key: entry[key] for key in ('readback', 'templateReadback', 'provenance', 'issues')},
            'artifact': {key: value for key, value in entry['artifact'].items() if key != 'base64'},
            'previewPageCount': entry['previewPageCount']}
    word = Document(BytesIO(base64.b64decode(result['formats']['word']['artifact']['base64'])))
    native = ''.join(word._element.body.xpath('.//w:t/text()'))
    assert '模板文字署名' in native and 'Word独立说明' in native and '模板版式署名' not in native
    assert word.styles['Normal'].font.size.pt == 17
    pdf = PdfReader(BytesIO(base64.b64decode(result['formats']['pdf']['artifact']['base64'])))
    visible = ''.join(''.join(page.extract_text().split()) for page in pdf.pages)
    assert '模板版式署名' in visible and 'PDF独立说明' in visible and '2026/11/13' in visible
    assert '模板文字署名' not in visible
    assert result['canApply'] is False
    assert all(row['coverage'] == 'sample' for row in result['formats']['pdf']['readback']['checks'])
    (output / 'readback.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
