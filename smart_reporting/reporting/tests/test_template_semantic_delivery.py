"""实际模板消费者使用耐久判断；历史恢复不因模型变化重新解释。"""

from io import BytesIO
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from docx import Document

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.preferences.runtime import REPORT_CONFIGURATION_SNAPSHOT_KEY
from smart_reporting.reporting.template_semantic_review import TemplateSignatureReviewer
from smart_reporting.reporting.tests.test_template_runtime import TemplateRuntime
from smart_reporting.reporting.tests.test_template_semantic_review import (
    Executor,
    opinion,
    template_bytes,
)


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def runtime_case(raw=None):
    raw = template_bytes() if raw is None else raw
    runtime = TemplateRuntime(raw)
    runtime.template_signature_reviewer = TemplateSignatureReviewer(Executor([opinion(raw), opinion(raw)]))
    runtime.state[REPORT_CONFIGURATION_SNAPSHOT_KEY] = {'generatedDate': '2026-09-16', 'contentHash': 'a' * 64,
        'resolvedFormats': {format: resolve_format_preferences(FormatPreferences(common={'signer': '冻结编制人'}), format)
            for format in ('word', 'pdf')}}
    run = RunContext(run_id='run', user_id='owner', session_id='session', session_state=runtime.state)
    return runtime, run, raw


@pytest.mark.anyio
async def test_workflow_semantic_binding_is_frozen_and_restored_with_truthful_source():
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    runtime, run, raw = runtime_case()
    result = await render_template_delivery(runtime, run, runtime.result, SimpleNamespace(title='冻结标题'), 'docx')
    doc = Document(BytesIO(runtime.files[result['wordPath']]))
    text = '\n'.join(doc._element.body.xpath('.//w:t/text()'))
    assert text.count('清川分析室') == 1 and text.count('2001-02-03') == 1
    assert '数据库收入100' in text and '冻结编制人' in text and '2026年9月16日' in text
    readback = result['validation']['readback']
    assert readback['signature']['placement'] == 'semantic_template_slot'
    assert readback['semanticSignature']['status'] == 'resolved'
    assert readback['semanticSignature']['preparationReadback']['status'] == 'passed'
    assert readback['semanticSignature']['review']['templateSha256'] == runtime.template.sha256
    assert result['validation']['ok'] is False
    del runtime.template_signature_reviewer
    restored = await render_template_delivery(runtime, run, runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx', restore_only=True)
    assert restored['wordPath'] == result['wordPath']
    assert restored['wordSha256'] == result['wordSha256']
    assert runtime.files['inputs/template.docx'] == raw


@pytest.mark.anyio
async def test_semantic_freeze_failure_keeps_original_sample_and_readable_output():
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    runtime, run, _ = runtime_case()
    original = runtime._apply_durable_command

    async def fail_semantic(context, command):
        if command.command_id.startswith('template-signature-semantic:'):
            raise OSError('injected semantic registration failure')
        return await original(context, command)

    runtime._apply_durable_command = fail_semantic
    result = await render_template_delivery(runtime, run, runtime.result, SimpleNamespace(title='冻结标题'), 'docx')
    text = '\n'.join(Document(BytesIO(runtime.files[result['wordPath']]))._element.body.xpath('.//w:t/text()'))
    assert text.count('清川分析室') == 2 and text.count('2001-02-03') == 2
    assert '冻结编制人' in text and '数据库收入100' in text
    assert result['validation']['readback']['signature']['placement'] == 'body_end'
    assert any(item['code'] == 'report_template_signature_semantic_unavailable' for item in result['validationIssues'])


@pytest.mark.anyio
async def test_legacy_restore_without_semantic_record_keeps_old_file_identity():
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    runtime, run, _ = runtime_case()
    del runtime.template_signature_reviewer
    first = await render_template_delivery(runtime, run, runtime.result, SimpleNamespace(title='冻结标题'), 'docx')
    runtime.template_signature_reviewer = TemplateSignatureReviewer(Executor([]))
    restored = await render_template_delivery(runtime, run, runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx', restore_only=True)
    assert restored['wordPath'] == first['wordPath'] and restored['wordSha256'] == first['wordSha256']


@pytest.mark.anyio
async def test_damaged_semantic_record_still_restores_verified_previously_generated_file():
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )
    from smart_reporting.reporting.workflow.runtime.template_semantics import semantic_review_path

    runtime, run, raw = runtime_case()
    first = await render_template_delivery(runtime, run, runtime.result, SimpleNamespace(title='冻结标题'), 'docx')
    assert first['validation']['readback']['signature']['placement'] == 'semantic_template_slot'
    runtime.files[semantic_review_path('run', raw)] = b'broken frozen review'
    restored = await render_template_delivery(runtime, run, runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx', restore_only=True)
    assert restored['wordPath'] == first['wordPath'] and restored['wordSha256'] == first['wordSha256']
    assert restored['validation']['ok'] is False
    assert any(item['code'] == 'report_template_signature_semantic_unavailable' for item in restored['validationIssues'])


@pytest.mark.anyio
@pytest.mark.parametrize('version', ['template-body/1', 'template-body/2', 'template-body/3'])
@pytest.mark.parametrize('record_fault', ['missing', 'damaged'])
async def test_old_projection_restores_exact_semantic_output_when_review_is_unavailable(
        monkeypatch, version, record_fault):
    from smart_reporting.reporting.delivery import template_body
    from smart_reporting.reporting.workflow.runtime import template_delivery
    from smart_reporting.reporting.workflow.runtime.template_semantics import semantic_review_path

    runtime, run, raw = runtime_case()
    with monkeypatch.context() as old:
        old.setattr(template_body, 'TEMPLATE_BODY_VERSION', version)
        first = await template_delivery.render_template_delivery(runtime, run, runtime.result,
            SimpleNamespace(title='冻结标题'), 'docx')
    path = first['wordPath']
    before = runtime.files[path]
    record_path = semantic_review_path('run', raw)
    if record_fault == 'missing':
        del runtime.files[record_path]
    else:
        runtime.files[record_path] = b'broken frozen review'

    def no_conversion(*args, **kwargs):
        pytest.fail('历史恢复不能重新生成或覆盖已核验文件')

    monkeypatch.setattr(template_delivery, 'fill_report_template', no_conversion)
    restored = await template_delivery.render_template_delivery(runtime, run, runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx', restore_only=True)
    assert restored['wordPath'] == path and restored['wordSha256'] == first['wordSha256']
    assert runtime.files[path] == before
    assert restored['validation']['ok'] is False
    assert any(item['code'] == 'report_template_signature_semantic_unavailable'
        for item in restored['validationIssues'])


@pytest.mark.anyio
async def test_new_generation_does_not_recover_old_semantic_projection(monkeypatch):
    from smart_reporting.reporting.delivery import template_body
    from smart_reporting.reporting.workflow.runtime import template_delivery
    from smart_reporting.reporting.workflow.runtime.template_semantics import semantic_review_path

    runtime, run, raw = runtime_case()
    with monkeypatch.context() as old:
        old.setattr(template_body, 'TEMPLATE_BODY_VERSION', 'template-body/2')
        first = await template_delivery.render_template_delivery(runtime, run, runtime.result,
            SimpleNamespace(title='冻结标题'), 'docx')
    path, before = first['wordPath'], runtime.files[first['wordPath']]
    runtime.files[semantic_review_path('run', raw)] = b'broken frozen review'
    generated = await template_delivery.render_template_delivery(runtime, run, runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx')
    assert generated['wordPath'] != path
    assert runtime.files[path] == before
    assert generated['validation']['ok'] is False


@pytest.mark.anyio
async def test_existing_current_projection_precedes_old_semantic_result_without_registration(monkeypatch):
    from smart_reporting.reporting.delivery import template_body
    from smart_reporting.reporting.workflow.runtime import template_delivery
    from smart_reporting.reporting.workflow.runtime.template_semantics import semantic_review_path

    runtime, run, raw = runtime_case()
    with monkeypatch.context() as old:
        old.setattr(template_body, 'TEMPLATE_BODY_VERSION', 'template-body/2')
        previous = await template_delivery.render_template_delivery(runtime, run, runtime.result,
            SimpleNamespace(title='冻结标题'), 'docx')
    runtime.files[semantic_review_path('run', raw)] = b'broken frozen review'
    current = await template_delivery.render_template_delivery(runtime, run, runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx')
    assert current['wordPath'] != previous['wordPath']
    runtime.registered = [item for item in runtime.registered if item['path'] != current['wordPath']]
    runtime.state['report_workflow_result'] = previous
    before = dict(runtime.files)

    def no_conversion(*args, **kwargs):
        pytest.fail('当前精确路径已有文件，恢复不能重新生成')

    monkeypatch.setattr(template_delivery, 'fill_report_template', no_conversion)
    restored = await template_delivery.render_template_delivery(runtime, run, runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx', restore_only=True)
    assert restored['wordPath'] == current['wordPath']
    assert restored['wordSha256'] == current['wordSha256'] and runtime.files == before
    assert any(item['code'] == 'report_template_registration_unavailable'
        for item in restored['validationIssues'])


@pytest.mark.anyio
async def test_retry_after_fallback_keeps_revision_output_instead_of_new_model_interpretation():
    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    runtime, run, raw = runtime_case()
    del runtime.template_signature_reviewer
    first = await render_template_delivery(runtime, run, runtime.result, SimpleNamespace(title='冻结标题'), 'docx')
    executor = Executor([opinion(raw), opinion(raw)])
    runtime.template_signature_reviewer = TemplateSignatureReviewer(executor)
    second = await render_template_delivery(runtime, run, runtime.result, SimpleNamespace(title='冻结标题'), 'docx')
    assert second['wordPath'] == first['wordPath'] and second['wordSha256'] == first['wordSha256']
    assert not executor.requests
