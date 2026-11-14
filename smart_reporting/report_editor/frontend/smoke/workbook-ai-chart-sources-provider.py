"""Opt-in real-provider probe; synthetic XLSX and scoped fixture repository only."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from io import BytesIO
from pathlib import Path
from time import monotonic
from unittest.mock import patch
from zipfile import ZipFile

from lxml import etree
from openpyxl import load_workbook

from smart_reporting.report_editor.native_models import NativeArtifacts
from smart_reporting.report_editor.native_office import patch_office
from smart_reporting.report_editor.workbook_native_ai import create_native_workbook_ai_service
from smart_reporting.reporting.agent import _report_model, _reporting_phase_model
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.model_policy import (
    ReportingThinkingProfile,
    apply_reporting_thinking_profile,
)
from smart_reporting.reporting.tests.test_native_pdf_extract import extract_fixture
from smart_reporting.reporting.tests.test_workbook_ai_charts import source_with_two_charts
from smart_reporting.runtime.settings import AgentSettings


async def probe(directory: Path):
    directory.mkdir(parents=True, exist_ok=False)
    fixture = await extract_fixture(directory / 'runtime')
    ai = None
    captured = {}
    def capture_patch(format, source, operations):
        output = patch_office(format, source, operations)
        captured.update(format=format, sourceSha256=hashlib.sha256(source).hexdigest(),
                        operations=json.dumps(operations, sort_keys=True), content=output)
        return output
    writer_spy = patch('smart_reporting.report_editor.native_office.patch_office', capture_patch)
    writer_spy.start()
    evidence = {'ok': False, 'scope': 'real provider/Agno/grant/workspace/native writer/explicit accept; synthetic data; memory revision repository; no browser/save/download in this probe', 'tasks': []}
    try:
        content = await asyncio.to_thread(source_with_two_charts)
        identity = ArtifactFile(path='native/source.xlsx', size=len(content), sha256=hashlib.sha256(content).hexdigest(),
            mediaType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        await fixture.workspace.awrite_bytes(fixture.thread, identity.path, content)
        context = fixture.parent.model_copy(update={'format': 'xlsx', 'source_file': identity})
        old = fixture.repository.revisions[context.document_id]
        fixture.repository.revisions[context.document_id] = old.model_copy(update={'context': context, 'artifacts': NativeArtifacts(xlsx=identity)})
        fixture.editor.office_enabled = True
        token, _ = await fixture.editor.grants.issue(context, capabilities=fixture.editor.capabilities(context))
        _, session = await fixture.editor.grants.exchange(token)
        settings = AgentSettings.from_environment()
        model = _reporting_phase_model(_report_model(settings, enable_thinking=settings.report_phase_enable_thinking))
        profile = (ReportingThinkingProfile.on(reasoning_effort=settings.report_phase_reasoning_effort,
            thinking_budget=settings.report_phase_thinking_budget, temperature=settings.report_phase_temperature)
            if settings.report_phase_enable_thinking else ReportingThinkingProfile.off(temperature=settings.report_phase_temperature))
        apply_reporting_thinking_profile(model, profile)
        model.max_tokens = settings.report_output_token_reserve
        model.top_p = .95
        evidence['modelId'] = model.id
        ai = create_native_workbook_ai_service(model, fixture.editor, enabled=True)
        ai.timeout_seconds = 120
        operations = [{'kind': 'applyCellEdits', 'edits': [
            {'sheetName': 'Sheet', 'row': 2, 'column': 1, 'writeValue': True, 'cell': {'value': 73}},
        ]}]
        (directory / 'source.xlsx').write_bytes(content)
        for name, instruction in (
            ('added', '读取Sheet的A1:B3，然后仅新增一张折线图，数据源A1:B3，放在E20，标题“实际来源收入”。保留两张原图及全部单元格；先读取charts指南，再通过propose_operations提交add_chart源DSL候选，不要提交缓存值。'),
            ('rebound', '先读取Sheet的图表身份和A1:B3。仅修改xl/charts/chart3.xml：将系列0的值范围换为B3、分类范围换为A3，标题“第二季度收入”。通过propose_operations提交edit_chart的seriesData来源范围；保留两张原图及单元格，不提交缓存值。'),
        ):
            started = monotonic()
            job = await ai.start_edit(session, client_request_id=name, instruction=instruction,
                expected_sha256=identity.sha256, operations=operations, selection={}, scope='workbook')
            while job['status'] == 'running':
                job = await ai.wait_edit_status(session, job['editId'])
            record = {'name': name, 'seconds': round(monotonic()-started, 2), 'job': job}
            evidence['tasks'].append(record)
            if job['status'] != 'succeeded':
                raise ValueError('provider_chart_proposal_failed')
            accepted = await ai.accept_edit(session, job['editId'], expected_sha256=identity.sha256,
                operations=operations, snapshot_sha256=job['snapshotSha256'])
            operations = accepted['operations']
            record.update(accepted=accepted['accepted'], operations=operations)
            preview = await fixture.editor.preview(context, expected_sha256=identity.sha256, operations=operations)
            assert captured['format'] == 'xlsx' and captured['sourceSha256'] == identity.sha256
            assert captured['operations'] == json.dumps(operations, sort_keys=True)
            output = captured['content']
            assert hashlib.sha256(output).hexdigest() == preview['draftSha256']
            replay = await asyncio.to_thread(patch_office, 'xlsx', content, operations)
            # JSZip dates changed entries at write time. Compare actual preview bytes
            # by SHA, then compare independent replay part contents, not ZIP timestamps.
            with ZipFile(BytesIO(output)) as actual_zip, ZipFile(BytesIO(replay)) as replay_zip:
                assert sorted(actual_zip.namelist()) == sorted(replay_zip.namelist())
                assert all(actual_zip.read(path) == replay_zip.read(path) for path in actual_zip.namelist())
            (directory / (name+'.xlsx')).write_bytes(output)
            actual = load_workbook(BytesIO(output))
            assert actual.active['B3'].value == 73 and len(actual.active._charts) == 3
            with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(output)) as after:
                for path in ('xl/charts/chart1.xml', 'xl/charts/chart2.xml'):
                    assert before.read(path) == after.read(path)
                xml = etree.fromstring(after.read('xl/charts/chart3.xml'))
                ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
                expected = ['10', '73'] if name == 'added' else ['73']
                assert xml.xpath('//c:numCache/c:pt/c:v/text()', namespaces=ns) == expected
                assert xml.xpath('//c:ser/c:cat/c:strRef/c:f/text()', namespaces=ns) == [
                    "'Sheet'!$A$2:$A$3" if name == 'added' else "'Sheet'!$A$3:$A$3"]
                assert xml.xpath('//c:ser/c:val/c:numRef/c:f/text()', namespaces=ns) == [
                    "'Sheet'!$B$2:$B$3" if name == 'added' else "'Sheet'!$B$3:$B$3"]
                assert actual.active._charts[2].title is not None
                title = ''.join(xml.xpath('//c:title//a:t/text()', namespaces={**ns, 'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}))
                assert title == ('实际来源收入' if name == 'added' else '第二季度收入'), title
            record.update(accepted=True, outputSha256=hashlib.sha256(output).hexdigest(),
                previewSha256=preview['draftSha256'], replaySha256=hashlib.sha256(replay).hexdigest(),
                replayPartsEqual=True, operations=operations, independentValues=expected)
        assert await fixture.editor.read_file(context) == content
        evidence['ok'] = True
    except Exception as error:
        evidence['error'] = {'type': type(error).__name__, 'code': getattr(error, 'code', None)}
        raise
    finally:
        if ai:
            await ai.aclose()
        writer_spy.stop()
        await fixture.workspace.registry.aclose()
        (directory / 'summary.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(probe(args.directory))
