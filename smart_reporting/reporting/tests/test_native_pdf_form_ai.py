"""PDF 表单 AI 授权、分页与原生写回契约。"""
from copy import deepcopy

import pytest

from smart_reporting.report_editor.native_pdf_form_ai import (
    NativePDFFormAITools,
    selected_pdf_form_fields,
    validate_pdf_form_operations,
)
from smart_reporting.reporting.models import ReportingError


def field(kind='text', value='old', **extra):
    return {'fieldId': 'a' * 64, 'expectedFieldSha256': 'b' * 64,
            'name': 'contact', 'kind': kind, 'value': value, 'editable': True, **extra}


def select(model, base=None):
    return selected_pdf_form_fields(model, base or [], [{'fieldId': 'a' * 64}])


def test_authorization_freezes_selected_fields_and_projects_base():
    model = {'formFields': [field(), field(fieldId='c' * 64, name='secret')]}
    original = deepcopy(model)
    base = validate_pdf_form_operations([{'kind': 'setFormValue', 'fieldId': 'a' * 64,
                                         'value': 'manual'}], [field()])
    selected = select(model, base)
    assert selected[0]['value'] == 'manual'
    assert selected[0]['expectedFieldSha256'] == 'b' * 64
    assert model == original
    reader = NativePDFFormAITools(selected)
    selected[0]['name'] = 'changed'
    assert 'secret' not in reader.list_form_fields()['content']
    assert 'changed' not in reader.list_form_fields()['content']
    receipt = reader.apply_ops([{'kind': 'setFormValue', 'fieldId': 'a' * 64,
                                 'value': 'AI'}], '填表')
    assert receipt['operationCount'] == 1
    assert receipt['requiresAcceptance'] is True
    assert receipt['summary'] == '填表'
    assert reader.result('候选')['operations'][0]['name'] == 'contact'


@pytest.mark.parametrize('operation', [
    {'kind': 'setFormValue', 'fieldId': 'a' * 64, 'value': 1},
    {'kind': 'setFormValue', 'fieldId': 'a' * 64, 'value': 'x', 'checked': False},
    {'kind': 'setFormValue', 'fieldId': 'a' * 64, 'value': 'x', 'name': 'forged'},
    {'kind': 'setFormValue', 'fieldId': 'a' * 64, 'value': 'x', 'extra': 1},
    {'kind': 'setFormValue', 'fieldId': 'c' * 64, 'value': 'x'},
    {'kind': 'deletePage', 'fieldId': 'a' * 64},
    {'kind': 'setFormValue', 'fieldId': 'a' * 64, 'value': '😀' * 2001},
])
def test_strict_operation_identity_and_value(operation):
    with pytest.raises(ReportingError):
        validate_pdf_form_operations([operation], [field()])


def test_options_checkbox_and_utf16_values():
    assert validate_pdf_form_operations([{'kind': 'setFormValue', 'fieldId': 'a' * 64,
        'checked': False}], [field('checkbox', True)])[0]['checked'] is False
    for value in [0, 'false', None]:
        with pytest.raises(ReportingError):
            validate_pdf_form_operations([{'kind': 'setFormValue', 'fieldId': 'a' * 64,
                'checked': value}], [field('checkbox', True)])
    for kind in ['radio', 'choice']:
        for value in ['', 'pro']:
            validate_pdf_form_operations([{'kind': 'setFormValue', 'fieldId': 'a' * 64,
                'value': value}], [field(kind, 'basic', options=['basic', 'pro'])])
        with pytest.raises(ReportingError):
            validate_pdf_form_operations([{'kind': 'setFormValue', 'fieldId': 'a' * 64,
                'value': 'Pro'}], [field(kind, 'basic', options=['basic', 'pro'])])
    validate_pdf_form_operations([{'kind': 'setFormValue', 'fieldId': 'a' * 64,
        'value': '😀' * 2000}], [field()])


def test_read_before_edit_and_atomic_duplicate_rejection():
    reader = NativePDFFormAITools([field(value='x' * 30000)])
    op = {'kind': 'setFormValue', 'fieldId': 'a' * 64, 'value': 'new'}
    reader.list_form_fields(offset=24000)
    with pytest.raises(ReportingError):
        reader.apply_ops([op], '未读')
    reader.list_form_fields()
    assert reader.result('ok')['coverage']['scopeReadComplete']
    with pytest.raises(ReportingError):
        reader.apply_ops([op, op], '重复')
    assert reader.result('ok')['operations'] == []
    reader.apply_ops([op], '候选')
    with pytest.raises(ReportingError):
        reader.apply_ops([op], '重复')
    assert len(reader.result('ok')['operations']) == 1


def test_selection_and_unsafe_base_require_save():
    for selection in [[], [{'fieldId': 'a' * 64, 'name': 'contact'}],
                      [{'fieldId': 'a' * 64}] * 2]:
        with pytest.raises(ReportingError):
            selected_pdf_form_fields({'formFields': [field()]}, [], selection)
    for fields in [[field(editable=False)], [field(), field('signature')]]:
        with pytest.raises(ReportingError):
            select({'formFields': fields})
    for kind in ['deletePage', 'mergePages', 'splitPages', 'createFormField', 'unknown']:
        with pytest.raises(ReportingError, match='保存'):
            select({'formFields': [field()]}, [{'kind': kind}])
    assert select({'formFields': [field()]}, [{'kind': 'cropPage'}, {'kind': 'rotatePage'}])


def test_real_pdf_canonical_candidate_writes_text_checkbox_radio_without_mutating_source():
    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf
    from smart_reporting.reporting.tests.test_pdf_crop import crop_fixture

    source = crop_fixture()
    model = inspect_pdf(source)
    selected = selected_pdf_form_fields(model, [],
        [{'fieldId': item['fieldId']} for item in model['formFields']])
    reader = NativePDFFormAITools(selected)
    reader.list_form_fields()
    operations = [{'kind': 'setFormValue', 'fieldId': item['fieldId'],
        **({'checked': False} if item['kind'] == 'checkbox' else
           {'value': 'pro' if item['kind'] == 'radio' else 'Ada'})} for item in selected]
    reader.apply_ops(operations, '填入申请资料')
    result = patch_pdf(source, reader.result('候选')['operations'])
    assert {item['name']: item['value'] for item in inspect_pdf(result)['formFields']} == {
        'contact': 'Ada', 'consent': False, 'plan': 'pro'}
    assert {item['name']: item['value'] for item in inspect_pdf(source)['formFields']} == {
        'contact': 'original', 'consent': True, 'plan': 'basic'}


@pytest.mark.anyio
async def test_agno_form_planner_uses_registered_tools_and_ignores_body_operations():
    import json

    from agno.models.response import ModelResponse

    from smart_reporting.report_editor.native_pdf_form_ai import AgnoNativePDFFormPlanner
    from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel

    def call(name, arguments, identity):
        return ModelResponse(tool_calls=[{'id': identity, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments)}}])

    op = {'kind': 'setFormValue', 'fieldId': 'a' * 64, 'value': 'Ada'}
    model = ScriptedModel(id='scripted', expected_tool_text='candidate', responses=[
        call('list_form_fields', {}, 'read'),
        call('apply_ops', {'operations': [op], 'summary': '填写联系人'}, 'apply'),
        ModelResponse(content='{"answer":"已生成私有填表候选。"}'),
    ])
    result = await AgnoNativePDFFormPlanner(model)(selected=[field()], instruction='填写Ada',
        session_id='form-test', user_id='user')
    assert result['operations'][0]['name'] == 'contact'
    assert result['operations'][0]['value'] == 'Ada'
    assert [event['tool'] for event in result['toolEvents']] == ['list_form_fields', 'apply_ops']
    assert len(model.responses) == 3
    body_model = ScriptedModel(id='scripted', responses=[ModelResponse(content=json.dumps({
        'answer': json.dumps({'operations': [op]})}))])
    result = await AgnoNativePDFFormPlanner(body_model)(selected=[field()], instruction='填写Ada',
        session_id='form-body', user_id='user')
    assert result['operations'] == []
    assert not result['coverage']['scopeReadComplete']


def test_apply_rejects_non_list_operations_without_losing_previous_candidate():
    reader = NativePDFFormAITools([field()])
    reader.list_form_fields()
    with pytest.raises(ReportingError):
        reader.apply_ops({'kind': 'setFormValue'}, '无效输入')
    assert reader.result('候选')['operations'] == []


def test_apply_tool_schema_explains_exact_text_and_checkbox_payloads():
    from agno.tools.function import Function

    tool = Function.from_callable(NativePDFFormAITools([field()]).apply_ops)
    description = tool.description or ''
    assert '"operations"' in description
    assert '"kind":"setFormValue"' in description
    assert '"value":"Ada"' in description
    assert '"checked":true' in description
    assert 'fieldId' in tool.parameters['properties']['operations']['description']
    assert 'summary' in tool.parameters['required']
