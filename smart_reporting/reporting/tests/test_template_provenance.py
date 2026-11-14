"""正式模板回执只声明实际分支及本修订可核验的来源。"""

import hashlib
import io
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.delivery.templates import fill_report_template

from .test_template_runtime import TemplateRuntime


def template_bytes(format, declared=True):
    stream = io.BytesIO()
    if format == 'docx':
        from docx import Document
        from docx.shared import Pt

        native = Document()
        native.add_paragraph('{{report_title}}')
        native.add_paragraph('{{report_content}}')
        if declared:
            paragraph = native.add_paragraph('{{report_signature}}')
            paragraph.runs[0].font.name = 'Liberation Serif'
            paragraph.runs[0].font.size = Pt(17)
        native.save(stream)
    elif format == 'xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.workbook.defined_name import DefinedName

        native = Workbook()
        native.active['A1'] = '{{report_title}}'
        native.active['A2'] = '{{report_content}}'
        native.active['A3'] = '=SUM(1,2)'
        if declared:
            native.active['B5'] = 'Old sample author'
            native.active['B6'] = '2000-01-01'
            native.active.column_dimensions['B'].width = 65
            native.active['B5'].font = Font(name='Liberation Serif', size=15, bold=True)
            native.defined_names.add(DefinedName('report_signature', attr_text="'Sheet'!$B$5:$B$6"))
        native.save(stream)
    else:
        from pptx import Presentation
        from pptx.util import Inches, Pt

        native = Presentation()
        slide = native.slides.add_slide(native.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(7), Inches(1)).text = '{{report_title}}'
        slide.shapes.add_textbox(Inches(1), Inches(2), Inches(7), Inches(1)).text = '{{report_content}}'
        if declared:
            slot = slide.shapes.add_textbox(Inches(1), Inches(4), Inches(7), Inches(2))
            slot.name = 'report_signature'
            slot.text = 'Old sample author\n2000-01-01'
            slot.text_frame.paragraphs[0].runs[0].font.size = Pt(17)
        native.save(stream)
    return stream.getvalue()


def native_text(raw, format):
    if format == 'docx':
        from docx import Document

        return '\n'.join(Document(io.BytesIO(raw))._element.body.xpath('.//w:t/text()'))
    if format == 'xlsx':
        from openpyxl import load_workbook

        return '\n'.join(str(cell.value) for sheet in load_workbook(io.BytesIO(raw))
            for row in sheet for cell in row if cell.value is not None)
    from pptx import Presentation

    return '\n'.join(shape.text for slide in Presentation(io.BytesIO(raw)).slides
        for shape in slide.shapes if shape.has_text_frame)


@pytest.mark.parametrize('format, declared, placement', [
    ('docx', True, 'declared_template_slot'), ('docx', False, 'body_end'),
    ('xlsx', True, 'declared_named_range'), ('xlsx', False, 'signature_sheet'),
    ('pptx', True, 'declared_textbox'), ('pptx', False, 'ending_slide'),
])
def test_template_fill_records_actual_signature_branch_and_keeps_native_content(format, declared, placement):
    result = fill_report_template(template_bytes(format, declared), template_format=format,
        delivery_format=format, values={'report_title': 'Frozen title', 'report_content': 'Frozen body'},
        signature={'signer': 'Frozen Author', 'date': '2026-11-13'})

    assert result.signature_binding['placement'] == placement
    assert result.signature_binding['layoutSource'] == ('template' if declared else 'generated_fallback')
    assert result.signature_binding['templateSampleStatus'] == ('replaced' if declared else 'no_declared_slot')
    assert result.signature_binding['undeclaredSamples'] == 'not_assessed'
    assert result.signature_binding['issueCodes'] == []
    text = native_text(result.content, format)
    assert all(value in text for value in ['Frozen title', 'Frozen body', 'Frozen Author', '2026-11-13'])
    assert text.count('Frozen Author') == 1 and text.count('2026-11-13') == 1
    assert 'Old sample author' not in text and '2000-01-01' not in text


def frozen_runtime(format):
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
    from smart_reporting.preferences.runtime import REPORT_CONFIGURATION_SNAPSHOT_KEY

    runtime = TemplateRuntime(template_bytes(format))
    runtime.template = runtime.template.model_copy(update={'filename': f'template.{format}'})
    runtime.state['report_template_input']['identity'] = runtime.template.model_dump(mode='json', by_alias=True)
    resolved_format = 'word' if format == 'docx' else format
    preferences = FormatPreferences(common={'signer': 'Frozen Author', 'dateFormat': 'iso'})
    runtime.state[REPORT_CONFIGURATION_SNAPSHOT_KEY] = {'generatedDate': '2026-11-13',
        'contentHash': 'a' * 64, 'resolvedFormats': {resolved_format: resolve_format_preferences(preferences, resolved_format)}}
    return runtime


@pytest.mark.anyio
@pytest.mark.parametrize('format, placement', [('docx', 'declared_template_slot'),
    ('xlsx', 'declared_named_range'), ('pptx', 'declared_textbox')])
async def test_formal_template_receipt_exposes_verified_frozen_content_and_template_layout(format, placement):
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    runtime = frozen_runtime(format)
    result = await render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='Frozen title'), format)
    readback = result['validation']['readback']
    assert readback['ok'] is True
    assert readback['templateLayout'] == {'source': 'uploaded_template',
        'scope': 'outside_declared_binding_targets', 'globalDefaults': 'not_applied', 'layoutValidation': 'unverified'}
    receipt = readback['signature']
    assert receipt['source'] == 'frozen_run_preferences'
    assert receipt['configurationHash'] == 'a' * 64
    assert receipt['generatedDate'] == '2026-11-13'
    expected_hash = hashlib.sha256(json.dumps({'signer': 'Frozen Author', 'date': '2026-11-13', 'description': ''},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert receipt['contentSha256'] == expected_hash
    assert receipt['bindingStatus'] == 'recorded'
    assert receipt['placement'] == placement
    assert receipt['layoutSource'] == 'template'
    assert receipt['templateSampleStatus'] == 'replaced'
    assert receipt['undeclaredSamples'] == 'not_assessed'
    label = 'word' if format == 'docx' else format
    text = native_text(runtime.files[result[f'{label}Path']], format)
    assert 'Frozen Author' in text and '2026-11-13' in text


@pytest.mark.anyio
@pytest.mark.parametrize('source', ['service_result', 'durable_result', 'missing', 'identity',
    'templateSha256', 'sourceContentSha256', 'configurationHash', 'contentSha256', 'generatedDate', 'format'])
async def test_restored_signature_receipt_requires_exact_file_and_frozen_source_match(monkeypatch, source):
    from smart_reporting.reporting.workflow.runtime import template_delivery

    runtime = frozen_runtime('docx')
    first = await template_delivery.render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='Frozen title'), 'docx')
    saved = deepcopy(first)
    if source == 'missing':
        runtime.state.pop('report_workflow_result')
    elif source == 'durable_result':
        original_get = runtime.get

        async def get_with_saved_result(run_id):
            durable = await original_get(run_id)
            durable.payload['result'] = {'renderedTemplate': saved}
            return durable

        runtime.get = get_with_saved_result
        runtime.state.pop('report_workflow_result')
    else:
        previous = saved['validation']['readback']
        if source == 'identity':
            previous['identity']['sha256'] = 'b' * 64
        elif source in {'templateSha256', 'sourceContentSha256', 'format'}:
            previous[source] = 'foreign'
        elif source in {'configurationHash', 'contentSha256', 'generatedDate'}:
            previous['signature'][source] = 'foreign'
        runtime.state['report_workflow_result'] = saved

    def no_regeneration(*args, **kwargs):
        pytest.fail('恢复位置回执不能重新生成或猜测模板产物')

    monkeypatch.setattr(template_delivery, 'fill_report_template', no_regeneration)
    restored = await template_delivery.render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='Frozen title'), 'docx', restore_only=True)
    assert restored['wordPath'] == first['wordPath']
    assert restored['validation']['readback']['ok'] is True
    receipt = restored['validation']['readback']['signature']
    if source in {'service_result', 'durable_result'}:
        assert receipt == first['validation']['readback']['signature']
    else:
        assert receipt['bindingStatus'] == 'unavailable'
        assert receipt['placement'] == 'unverified'
        assert receipt['templateSampleStatus'] == 'not_assessed'
        assert any(issue['code'] == 'report_template_binding_receipt_unavailable'
            for issue in restored['validationIssues'])


@pytest.mark.anyio
async def test_restored_fallback_receipt_keeps_specific_unremoved_sample_warning(monkeypatch):
    from smart_reporting.reporting.workflow.runtime import template_delivery

    from .test_template_runtime import render_template_fault_case

    runtime, first = await render_template_fault_case(monkeypatch, 'xlsx_signature_measurement')

    def no_regeneration(*args, **kwargs):
        pytest.fail('已登记文件只能恢复原回执')

    monkeypatch.setattr(template_delivery, 'fill_report_template', no_regeneration)
    restored = await template_delivery.render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'xlsx', restore_only=True)
    assert restored['xlsxSha256'] == first['xlsxSha256']
    assert restored['validation']['readback']['signature'] == first['validation']['readback']['signature']
    warning = next(issue for issue in restored['validationIssues']
        if issue['code'] == 'report_template_signature_measurement_unavailable')
    assert warning == next(issue for issue in first['validationIssues']
        if issue['code'] == 'report_template_signature_measurement_unavailable')


def test_replaced_block_signature_does_not_claim_its_nested_sample_was_preserved():
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    document = Document()
    outer = OxmlElement('w:sdt')
    outer_properties = OxmlElement('w:sdtPr')
    outer_tag = OxmlElement('w:tag')
    outer_tag.set(qn('w:val'), 'report_signature')
    outer_properties.append(outer_tag)
    outer.append(outer_properties)
    content = OxmlElement('w:sdtContent')
    paragraph = document.add_paragraph()
    nested = OxmlElement('w:sdt')
    nested.append(deepcopy(outer_properties))
    nested_content = OxmlElement('w:sdtContent')
    run = OxmlElement('w:r')
    text = OxmlElement('w:t')
    text.text = 'Nested sample author'
    run.append(text)
    nested_content.append(run)
    nested.append(nested_content)
    paragraph._p.append(nested)
    content.append(paragraph._p)
    outer.append(content)
    document._element.body.insert(-1, outer)
    stream = io.BytesIO()
    document.save(stream)

    result = fill_report_template(stream.getvalue(), template_format='docx', delivery_format='docx',
        values={}, signature={'signer': 'Frozen Author', 'date': '2026-11-13'})

    assert 'Nested sample author' not in native_text(result.content, 'docx')
    assert result.signature_binding['templateSampleStatus'] == 'replaced'
    assert 'report_template_signature_slot_unusable' not in result.signature_binding['issueCodes']


def test_signature_block_inside_an_outer_control_table_keeps_sample_and_reports_unusable_declaration():
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from lxml import etree

    document = Document()
    document.add_paragraph('{{report_content}}')
    outer = OxmlElement('w:sdt')
    outer_properties = OxmlElement('w:sdtPr')
    outer_tag = OxmlElement('w:tag')
    outer_tag.set(qn('w:val'), 'report_container')
    outer_properties.append(outer_tag)
    outer.append(outer_properties)
    outer_content = OxmlElement('w:sdtContent')
    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.text = 'Retained table body'
    signature = OxmlElement('w:sdt')
    properties = OxmlElement('w:sdtPr')
    tag = OxmlElement('w:tag')
    tag.set(qn('w:val'), 'report_signature')
    properties.append(tag)
    signature.append(properties)
    content = OxmlElement('w:sdtContent')
    paragraph = OxmlElement('w:p')
    run = OxmlElement('w:r')
    text = OxmlElement('w:t')
    text.text = 'Old sample author {{report_title}} 2000-01-01'
    run.append(text)
    paragraph.append(run)
    content.append(paragraph)
    signature.append(content)
    cell._tc.append(signature)
    outer_content.append(table._tbl)
    outer.append(outer_content)
    document._element.body.insert(-1, outer)
    original = etree.tostring(signature)
    stream = io.BytesIO()
    document.save(stream)

    result = fill_report_template(stream.getvalue(), template_format='docx', delivery_format='docx',
        values={'report_content': 'Frozen business body', 'report_title': 'Not for the nested declaration'},
        signature={'signer': 'Frozen Author', 'date': '2026-11-13'})

    output = Document(io.BytesIO(result.content))
    preserved = output._element.body.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_signature"]]')
    assert len(preserved) == 1 and etree.tostring(preserved[0]) == original
    assert [paragraph.text for paragraph in output.paragraphs] == ['Frozen business body', 'Frozen Author', '2026-11-13']
    assert 'Retained table body' in native_text(result.content, 'docx')
    assert result.signature_binding['placement'] == 'body_end'
    assert result.signature_binding['layoutSource'] == 'generated_fallback'
    assert result.signature_binding['templateSampleStatus'] == 'preserved_for_review'
    assert 'report_template_signature_slot_unusable' in result.signature_binding['issueCodes']
    assert any(issue['code'] == 'report_template_signature_slot_unusable' for issue in result.issues)
