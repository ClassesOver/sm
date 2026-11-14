"""投影版本隔离新生成；恢复只按冻结身份寻找精确旧路径且保留原字节。"""

import hashlib
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document

from smart_reporting.reporting.delivery.templates import fill_report_template
from smart_reporting.reporting.tests.test_template_rich_material_runtime import chart_runtime
from smart_reporting.reporting.tests.test_template_runtime import identity
from smart_reporting.reporting.workflow.runtime import template_delivery


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def values(runtime):
    return {'report_title': '冻结标题', 'report_content': runtime.files['reports/frozen.md'].decode()}


def output_path(runtime, version):
    frozen = {'template': identity('inputs/template.docx', runtime.files['inputs/template.docx']).model_dump(),
        'source': runtime.manifest.markdown.model_dump(include={'path', 'size', 'sha256'}),
        'values': values(runtime), 'format': 'docx'}
    if version is not None:
        chart = runtime.manifest.charts[0]
        frozen['bodyProjection'] = {'version': version,
            'resources': {'chart.png': {'size': chart.size, 'sha256': chart.sha256}}}
    digest = hashlib.sha256(json.dumps(frozen, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return f'报表/智能分析/run/template/revision-2/{digest[:20]}/report.docx'


def literal_bytes(runtime):
    doc = Document()
    for value in values(runtime).values():
        doc.add_paragraph(value)
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


@pytest.fixture(scope='module')
def rich_bytes():
    runtime, raw = chart_runtime()
    result = fill_report_template(runtime.files['inputs/template.docx'], template_format='docx', delivery_format='docx',
        values=values(runtime), body_resources={'chart.png': raw})
    assert not result.issues and result.body_binding['status'] == 'projected'
    return result.content


def seed(runtime, path, raw, registered):
    runtime.files[path] = raw
    if registered:
        runtime.registered.append(identity(path, raw).model_dump())


def no_conversion(*args, **kwargs):
    pytest.fail('恢复精确历史文件不能重新转换或覆盖字节')


def test_projection_version_is_v4_with_exact_historical_versions():
    from smart_reporting.reporting.delivery.template_body import (
        TEMPLATE_BODY_RESTORE_VERSIONS,
        TEMPLATE_BODY_VERSION,
    )

    assert TEMPLATE_BODY_VERSION == 'template-body/4'
    assert TEMPLATE_BODY_RESTORE_VERSIONS == ('template-body/3', 'template-body/2', 'template-body/1')


@pytest.mark.anyio
async def test_new_v4_generation_never_reuses_historical_v1_v2_or_v3_cache():
    runtime, _ = chart_runtime()
    old_path = output_path(runtime, 'template-body/1')
    old_raw = literal_bytes(runtime)
    seed(runtime, old_path, old_raw, True)
    seed(runtime, output_path(runtime, 'template-body/2'), old_raw, True)
    seed(runtime, output_path(runtime, 'template-body/3'), old_raw, True)
    expected = output_path(runtime, 'template-body/4')
    result = await template_delivery.render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx')
    assert result['wordPath'] == expected and result['wordPath'] != old_path
    assert result['validation']['readback']['body']['status'] == 'passed'
    assert runtime.files[old_path] == old_raw


@pytest.mark.anyio
@pytest.mark.parametrize('version', ['template-body/1', 'template-body/2', 'template-body/3'])
@pytest.mark.parametrize('registered', [True, False])
@pytest.mark.parametrize('representation', ['rich', 'literal'])
async def test_restore_exact_historical_identity_keeps_bytes_and_rechecks_rich_body(
        monkeypatch, rich_bytes, registered, representation, version):
    runtime, _ = chart_runtime()
    raw = rich_bytes if representation == 'rich' else literal_bytes(runtime)
    path = output_path(runtime, version)
    seed(runtime, path, raw, registered)
    monkeypatch.setattr(template_delivery, 'fill_report_template', no_conversion)
    result = await template_delivery.render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx', restore_only=True)
    assert result['wordPath'] == path
    assert result['wordSha256'] == hashlib.sha256(raw).hexdigest()
    assert runtime.files[path] == raw
    body = result['validation']['readback']['body']
    assert body['status'] == ('passed' if representation == 'rich' else 'unverified')
    assert body['coverage'] == ('complete' if representation == 'rich' else 'unverified')
    assert not result['validation']['ok']
    if not registered:
        assert any(issue['code'] == 'report_template_registration_unavailable' for issue in result['validationIssues'])


@pytest.mark.anyio
@pytest.mark.parametrize('registered', [True, False])
async def test_current_v4_file_has_priority_over_registered_v3_v2_v1_and_legacy(monkeypatch, rich_bytes, registered):
    runtime, _ = chart_runtime()
    current_path = output_path(runtime, 'template-body/4')
    seed(runtime, output_path(runtime, 'template-body/3'), literal_bytes(runtime), True)
    seed(runtime, output_path(runtime, 'template-body/2'), literal_bytes(runtime), True)
    seed(runtime, output_path(runtime, 'template-body/1'), literal_bytes(runtime), True)
    seed(runtime, output_path(runtime, None), literal_bytes(runtime), True)
    seed(runtime, current_path, rich_bytes, registered)
    monkeypatch.setattr(template_delivery, 'fill_report_template', no_conversion)
    result = await template_delivery.render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx', restore_only=True)
    assert result['wordPath'] == current_path
    assert result['validation']['readback']['body']['status'] == 'passed'


@pytest.mark.anyio
@pytest.mark.parametrize('registered', [True, False])
async def test_original_legacy_path_still_restores_literal_bytes(monkeypatch, registered):
    runtime, _ = chart_runtime()
    raw = literal_bytes(runtime)
    path = output_path(runtime, None)
    seed(runtime, path, raw, registered)
    monkeypatch.setattr(template_delivery, 'fill_report_template', no_conversion)
    result = await template_delivery.render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx', restore_only=True)
    assert result['wordPath'] == path and runtime.files[path] == raw
    assert result['validation']['readback']['body']['representation'] == 'historical_literal_markdown'


@pytest.mark.anyio
async def test_v1_restore_uses_frozen_resource_identity_even_when_actual_image_has_drifted(monkeypatch, rich_bytes):
    runtime, _ = chart_runtime()
    path = output_path(runtime, 'template-body/1')
    seed(runtime, path, rich_bytes, False)
    runtime.files['reports/chart.png'] = b'drifted-bytes-must-not-change-frozen-path'
    monkeypatch.setattr(template_delivery, 'fill_report_template', no_conversion)
    result = await template_delivery.render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx', restore_only=True)
    assert result['wordPath'] == path and runtime.files[path] == rich_bytes
    assert result['validation']['readback']['body']['status'] != 'passed'
    assert any(issue['code'] == 'report_template_body_resource_unavailable' for issue in result['validationIssues'])
