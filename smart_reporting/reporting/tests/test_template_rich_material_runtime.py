"""正式模板材料冻结与新旧产物身份保持分离。"""
import hashlib
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from .test_template_runtime import TemplateRuntime, docx_template, identity


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def chart_runtime():
    runtime = TemplateRuntime(docx_template())
    stream = io.BytesIO()
    Image.new('RGB', (80, 40), '#345678').save(stream, format='PNG')
    raw = stream.getvalue()
    runtime.files['reports/chart.png'] = raw
    runtime.files['reports/frozen.md'] = '# 标题\n\n![本期图](chart.png)\n\n原值 1234.5600'.encode()
    runtime.manifest = runtime.manifest.model_copy(update={
        'markdown': runtime.manifest.markdown.model_copy(update=identity('reports/frozen.md', runtime.files['reports/frozen.md']).model_dump()),
        'charts': ()})
    from smart_reporting.reporting.delivery.artifacts_v1 import ChartArtifact
    runtime.manifest = runtime.manifest.model_copy(update={'charts': (ChartArtifact(
        **identity('reports/chart.png', raw).model_dump(), mediaType='image/png', chartId='chart-1', datasetIds=('d1',)),)})
    runtime.files['reports/manifest.json'] = runtime.manifest.model_dump_json(by_alias=True).encode()
    runtime.result['artifactManifest'] = identity('reports/manifest.json', runtime.files['reports/manifest.json']).model_dump()
    runtime.registered = [identity(path, content).model_dump() for path, content in runtime.files.items()]
    return runtime, raw


@pytest.mark.anyio
@pytest.mark.parametrize('change', ['none', 'unregistered', 'drift'])
async def test_frozen_template_values_bind_only_actual_registered_chart_bytes(change):
    from smart_reporting.reporting.workflow.runtime.template_delivery import _template_values

    runtime, raw = chart_runtime()
    if change == 'unregistered':
        runtime.registered = [f for f in runtime.registered if f['path'] != 'reports/chart.png']
    elif change == 'drift':
        runtime.files['reports/chart.png'] = b'changed'
    result = await _template_values(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx')
    assert len(result) == 4
    values, source, resources, issues = result
    assert source == identity('reports/frozen.md', runtime.files['reports/frozen.md'])
    assert '1234.5600' in values['report_content']
    if change == 'none':
        assert resources == {'chart.png': raw} and not issues
    else:
        assert resources == {} and issues[0]['code'] == 'report_template_body_resource_unavailable'


@pytest.mark.anyio
@pytest.mark.parametrize('registration', ['registered', 'missing'])
async def test_historical_literal_template_restores_same_registered_identity_without_conversion(monkeypatch, registration):
    from smart_reporting.reporting.delivery.templates import TemplateFillResult
    from smart_reporting.reporting.workflow.runtime import template_delivery

    runtime = TemplateRuntime(docx_template())
    values = {'report_title': '冻结标题', 'report_content': runtime.files['reports/frozen.md'].decode()}
    legacy_hash = hashlib.sha256(json.dumps({'template': identity('inputs/template.docx', runtime.files['inputs/template.docx']).model_dump(),
        'source': identity('reports/frozen.md', runtime.files['reports/frozen.md']).model_dump(),
        'values': values, 'format': 'docx'}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    path = f'报表/智能分析/run/template/revision-2/{legacy_hash[:20]}/report.docx'
    # 原生段落里保留旧字面 Markdown，代表已签发历史，而非新版转换样本。
    from docx import Document
    doc = Document()
    for value in values.values():
        doc.add_paragraph(value)
    output = io.BytesIO()
    doc.save(output)
    runtime.files[path] = output.getvalue()
    if registration == 'registered':
        runtime.registered.append(identity(path, output.getvalue()).model_dump())
    def forbidden(*args, **kwargs):
        pytest.fail('历史恢复不允许转换/重写原文件')
    monkeypatch.setattr(template_delivery, 'fill_report_template', forbidden)
    restored = await template_delivery.render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx', restore_only=True)
    assert restored['wordPath'] == path
    assert restored['wordSha256'] == hashlib.sha256(output.getvalue()).hexdigest()
    # 普通新生成不能命中旧literal文件；用明确替身只核生成选择/版本身份，不冒充富文档验证。
    monkeypatch.setattr(template_delivery, 'fill_report_template', lambda *a, **k: TemplateFillResult(output.getvalue(), (), ()))
    created = await template_delivery.render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx')
    assert created['wordPath'] != path
    assert runtime.files[path] == output.getvalue()


@pytest.mark.anyio
async def test_actual_template_runtime_reads_rich_body_without_requiring_markdown_punctuation():
    from docx import Document

    from smart_reporting.reporting.workflow.runtime.template_delivery import (
        render_template_delivery,
    )

    runtime, chart = chart_runtime()
    original = dict(runtime.files)
    created = await render_template_delivery(runtime, SimpleNamespace(run_id='run'), runtime.result,
        SimpleNamespace(title='冻结标题'), 'docx')
    raw = runtime.files[created['wordPath']]
    doc = Document(io.BytesIO(raw))
    assert len(doc.inline_shapes) == 1
    assert doc._element.body.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_content"]]')
    assert created['validation']['readback']['ok'] is True
    assert created['validation']['readback']['body']['status'] == 'passed'
    assert created['validation']['readback']['body']['coverage'] == 'complete'
    assert created['validation']['ok'] is False  # 结构通过不代替模板版式验收。
    assert all(runtime.files[path] == value for path, value in original.items())


@pytest.mark.anyio
async def test_rich_template_restoration_keeps_output_when_frozen_image_drifts(monkeypatch):
    from smart_reporting.reporting.workflow.runtime import template_delivery

    runtime, _ = chart_runtime()
    context, outline = SimpleNamespace(run_id='run'), SimpleNamespace(title='冻结标题')
    created = await template_delivery.render_template_delivery(runtime, context, runtime.result, outline, 'docx')
    actual = runtime.files[created['wordPath']]
    runtime.files['reports/chart.png'] = b'drifted image'

    def forbidden(*args, **kwargs):
        pytest.fail('恢复时不得重新渲染已存在的实际产物')

    monkeypatch.setattr(template_delivery, 'fill_report_template', forbidden)
    restored = await template_delivery.render_template_delivery(runtime, context, runtime.result, outline, 'docx', restore_only=True)
    assert restored['wordPath'] == created['wordPath']
    assert restored['wordSha256'] == hashlib.sha256(actual).hexdigest()
    assert restored['validation']['ok'] is False
    assert any(issue['code'] == 'report_template_body_resource_unavailable' for issue in restored['validationIssues'])
