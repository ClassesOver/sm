"""可信入口冻结实际默认值，新旧任务在全局更新后保持各自身份。"""

from dataclasses import replace

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from smart_reporting.management.data_sources.secrets import CredentialVault
from smart_reporting.management.format_preferences import FormatPreferenceService
from smart_reporting.management.models import INSTANCE_SCOPE, ManagementError
from smart_reporting.management.repository import runtime_snapshots
from smart_reporting.management.runtime import ManagedConfigurationProvider
from smart_reporting.management.scopes import ScopeService
from smart_reporting.preferences.models import FormatPreferences
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.tests.preference_version_fixtures import seed_preference_version
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def context(auth_context):
    auth, repository, now = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token
    startup = replace(AgentSettings.from_environment({}, load_env_file=False), openai_api_key="private-model-secret",
        workspace_hmac_secret="private-workspace-secret")
    scopes = ScopeService(auth)
    vault = CredentialVault("test:" + CredentialVault.generate_key())
    provider = ManagedConfigurationProvider(scopes, vault, startup_settings=startup)
    preferences = FormatPreferenceService(auth, FormatPreferences.from_delivery(startup.report_delivery_settings))
    return provider, preferences, token, repository, now


async def register(provider, run_id="task-a", **kwargs):
    return await provider.register_run(run_id, INSTANCE_SCOPE, user_id="user-a",
        thread_id="thread-a", entrypoint="cli", **kwargs)


async def test_tasks_freeze_distinct_preferences_and_retry_keeps_original_date_and_values(context):
    provider, preferences, token, repository, now = context
    first = await register(provider)
    assert first["preferenceRevision"] is None
    assert first["generatedDate"] == "2026-11-06"
    first_signer = first["resolvedFormats"]["word"]["common"]["signer"]
    document = (await preferences.detail(token))["draft"]["document"]
    document["common"]["signer"] = "新的落款署名"
    await preferences.save_draft(token, document, 1)
    await seed_preference_version(preferences, token, 2)
    second = await register(provider, "task-b")
    assert second["preferenceRevision"] == 1
    assert second["resolvedFormats"]["word"]["common"]["signer"] == "新的落款署名"
    from datetime import timedelta

    now[0] += timedelta(days=4)
    restarted = ManagedConfigurationProvider(provider.scope_service, provider.vault,
        startup_settings=replace(provider.startup_settings, model_timeout_seconds=123))
    restored = await register(restarted)
    assert restored == first
    assert restored["resolvedFormats"]["word"]["common"]["signer"] == first_signer
    async with repository.engine.connect() as connection:
        assert len((await connection.execute(select(runtime_snapshots))).all()) == 2


async def test_snapshot_contains_no_credentials_and_does_not_read_later_environment(context, monkeypatch):
    provider, _, _, _, _ = context
    monkeypatch.setenv("AGENT_MODEL_TIMEOUT_SECONDS", "654")
    snapshot = await register(provider)
    assert snapshot["systemValues"]["AGENT_MODEL_TIMEOUT_SECONDS"] == 900
    assert "OPENAI_API_KEY" not in snapshot["systemValues"]
    assert "AGENT_DB_URL" not in snapshot["systemValues"]
    assert "private-model-secret" not in str(snapshot)
    assert "private-workspace-secret" not in str(snapshot)


async def test_legacy_registered_run_does_not_silently_take_current_preferences(context):
    provider, _, _, _, _ = context
    legacy = ManagedConfigurationProvider(provider.scope_service, provider.vault)
    assert await register(legacy) is None
    assert await register(provider) is None


async def test_foreign_owner_cannot_read_or_replace_frozen_preferences(context):
    provider, _, _, _, _ = context
    first = await register(provider)
    with pytest.raises(ManagementError, match="management_run_identity_conflict"):
        await provider.register_run("task-a", INSTANCE_SCOPE, user_id="foreign", thread_id="thread-a", entrypoint="cli")
    with pytest.raises(ManagementError, match="management_run_identity_conflict"):
        await provider.load_run_preferences("task-a", INSTANCE_SCOPE, user_id="foreign", thread_id="thread-a")
    restored = await provider.load_run_preferences("task-a", INSTANCE_SCOPE, user_id="user-a", thread_id="thread-a")
    assert restored == first


async def test_database_prevents_frozen_snapshot_rewrite(context):
    from smart_reporting.management.repository import run_configuration_snapshots

    provider, _, _, repository, _ = context
    await register(provider)
    with pytest.raises(IntegrityError):
        async with repository.engine.begin() as connection:
            await connection.execute(update(run_configuration_snapshots).values(content_hash="0" * 64))


async def test_tampered_snapshot_is_rejected_even_when_database_guard_was_bypassed(context):
    from smart_reporting.management.repository import run_configuration_snapshots

    provider, _, _, repository, _ = context
    await register(provider)
    async with repository.engine.begin() as connection:
        await connection.execute(text("ALTER TABLE reporting_management.run_configuration_snapshots DISABLE TRIGGER USER"))
        await connection.execute(update(run_configuration_snapshots).values(content_hash="0" * 64))
        await connection.execute(text("ALTER TABLE reporting_management.run_configuration_snapshots ENABLE TRIGGER USER"))
    with pytest.raises(ManagementError, match="management_configuration_snapshot_invalid"):
        await register(provider)


async def test_unpublished_draft_and_new_published_system_values_do_not_replace_running_startup(context):
    from smart_reporting.management.system_configuration import SystemConfigurationService

    provider, preferences, token, _, _ = context
    document = (await preferences.detail(token))["draft"]["document"]
    document["common"]["signer"] = "未发布署名"
    await preferences.save_draft(token, document, 1)
    systems = SystemConfigurationService(provider.scope_service.auth, provider.startup_settings)
    system_doc = (await systems.detail(token))["draft"]["document"]
    system_doc["values"]["AGENT_MODEL_TIMEOUT_SECONDS"] = 123
    await systems.save_draft(token, system_doc, 1)
    await systems.publish(token, 2)
    snapshot = await register(provider)
    assert snapshot["resolvedFormats"]["word"]["common"]["signer"] != "未发布署名"
    assert snapshot["systemValues"]["AGENT_MODEL_TIMEOUT_SECONDS"] == 900


def test_session_binding_rejects_changed_snapshot_and_keeps_other_run_state():
    from smart_reporting.preferences.runtime import bind_run_preferences

    state = {"business": {"untouched": True}}
    first = {"runId": "a", "contentHash": "a" * 64}
    bind_run_preferences(state, first)
    assert state["report_configuration_snapshot"] == first
    first["runId"] = "mutated"
    assert state["report_configuration_snapshot"]["runId"] == "a"
    with pytest.raises(ValueError):
        bind_run_preferences(state, {"runId": "a", "contentHash": "b" * 64})
    assert state["business"] == {"untouched": True}


async def test_revision_inherits_source_preferences_after_global_default_changes(context):
    from datetime import timedelta

    provider, preferences, token, _, now = context
    parent = await register(provider)
    document = (await preferences.detail(token))['draft']['document']
    document['common']['signer'] = '后续新任务署名'
    await preferences.save_draft(token, document, 1)
    await seed_preference_version(preferences, token, 2)
    now[0] += timedelta(days=1)
    child = await provider.inherit_run_preferences('task-a', 'revision-a', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a', entrypoint='report_revision')
    assert child['runId'] == 'revision-a'
    assert child['resolvedFormats'] == parent['resolvedFormats']
    assert child['preferenceHash'] == parent['preferenceHash']
    assert child['parentConfigurationHash'] == parent['contentHash']
    assert child['generatedDate'] == '2026-11-07'
    now[0] += timedelta(days=1)
    assert child == await provider.inherit_run_preferences('task-a', 'revision-a', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a', entrypoint='report_revision')
    assert child == await provider.load_run_preferences('revision-a', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a')


async def test_restarted_tasks_and_child_revision_render_all_frozen_formats(context, tmp_path):
    """跨数据库快照与实际执行器核对，不能只比较保存的 JSON。"""
    import hashlib
    import json
    import uuid
    from datetime import timedelta
    from pathlib import Path
    from types import SimpleNamespace

    import pymupdf
    from agno.run import RunContext
    from bs4 import BeautifulSoup
    from docx import Document
    from markdown_it import MarkdownIt
    from openpyxl import load_workbook
    from PIL import Image
    from pptx import Presentation

    from smart_reporting.preferences.runtime import execution_preferences
    from smart_reporting.reporting.data_sources import thread_binding
    from smart_reporting.reporting.delivery.draft_v1 import (
        ReportChartInput,
        ReportDraft,
        ReportDraftBlock,
        ReportDraftSection,
        ReportSectionDefinition,
        assemble_report_markdown,
    )
    from smart_reporting.reporting.delivery.pptx import build_editable_pptx
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
    from smart_reporting.reporting.delivery.xlsx import build_workbook
    from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY, WorkspaceReportService

    provider, preferences, token, _, now = context
    original = (await preferences.detail(token))['draft']['document']
    original['common'].update(signer='冻结旧署名', dateFormat='iso')
    original['md'].update(sectionHeadingLevel=2, toc=True, tableStyle='html', listMarker='*', codeFence='tildes', imageCaptions=False, references=False)
    original['xlsx']['numbers']['decimalPlaces'] = 4
    original['pptx']['typography']['body']['size'] = 18
    for format, size in (('word', 12), ('pdf', 14)):
        original[format].update(cover=False, toc=False)
        original[format]['watermark']['enabled'] = False
        original[format]['typography']['body']['size'] = size
        original[format]['charts']['keepWithCaption'] = True
    await preferences.save_draft(token, original, 1)
    await seed_preference_version(preferences, token, 2)
    parent = await register(provider)

    updated = (await preferences.detail(token))['draft']['document']
    updated['common']['signer'] = '后续新署名'
    updated['md'].update(sectionHeadingLevel=4, toc=False, tableStyle='pipe', listMarker='-', codeFence='backticks', imageCaptions=True, references=True)
    updated['xlsx']['numbers']['decimalPlaces'] = 1
    updated['pptx']['typography']['body']['size'] = 24
    updated['word']['typography']['body']['size'] = 16
    updated['pdf']['typography']['body']['size'] = 18
    for format in ('word', 'pdf'):
        updated[format]['charts']['keepWithCaption'] = False
    await preferences.save_draft(token, updated, 2)
    await seed_preference_version(preferences, token, 3)
    current = await register(provider, 'task-b')
    now[0] += timedelta(days=1)
    child = await provider.inherit_run_preferences('task-a', 'revision-a', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a', entrypoint='report_revision')
    restarted = ManagedConfigurationProvider(provider.scope_service, provider.vault,
        startup_settings=replace(provider.startup_settings,
            report_delivery_settings=provider.startup_settings.report_delivery_settings.model_copy(update={
                'branding': provider.startup_settings.report_delivery_settings.branding.model_copy(update={
                    'organization_name': '重启后部署署名'})})))
    assert await register(restarted) == parent
    runtime = SimpleNamespace(configuration_provider=restarted)
    evidence = []
    for snapshot, signer, places, size in ((parent, '冻结旧署名', 4, 18),
        (current, '后续新署名', 1, 24), (child, '冻结旧署名', 4, 18)):
        execution = SimpleNamespace(execution_run_id=snapshot['runId'],
            source_scope=SimpleNamespace(database='instance', company_id='instance',
                user_id='user-a', caller_thread_id='thread-a'))
        frozen = await execution_preferences(runtime, execution)
        assert frozen == snapshot
        formats, date = frozen['resolvedFormats'], frozen['generatedDate']
        root = tmp_path / frozen['runId']
        root.mkdir()
        assembled = assemble_report_markdown(ReportDraft(sections=(ReportDraftSection(sectionCode='overview', blocks=(
            ReportDraftBlock(blockId='body', markdown='保留正文与来源。\n\n| 项目 | 金额 |\n| --- | ---: |\n| 数据 | 1234.56 |\n\n- 列表\n\n~~~text\n固定代码\n~~~',
                chartIds=('chart1',), citationIds=('source1',)),)),)),
            expected_title='冻结验证', markdown_path='report.md',
            sections=(ReportSectionDefinition(code='overview', sectionNumber='1', title='概览', protocolMarker=True),),
            charts=(ReportChartInput(chartId='chart1', fileName='chart.png', title='指标分布',
                altText='指标图片', citationIds=('source1',)),), citation_ids=('source1',),
            markdown_preferences=formats['md'], generated_date=date)
        markdown = assembled.markdown
        visible = BeautifulSoup(MarkdownIt('commonmark', {'html': True}).enable('table').render(markdown), 'html.parser')
        assert signer in visible.get_text() and date in visible.get_text()
        assert ('图表：指标分布' in visible.get_text()) == formats['md']['imageCaptions']
        assert (visible.find('abbr') is not None) == formats['md']['references']
        assert visible.find('h' + str(formats['md']['sectionHeadingLevel'])).get_text().strip() == '1. 概览'
        assert ('data-report-md-source=' in markdown) == (formats['md']['tableStyle'] == 'html')
        assert ('report-md-toc:v1' in markdown) == formats['md']['toc']
        assert ('* 列表' in markdown) == (formats['md']['listMarker'] == '*')
        assert ('~~~text' in markdown) == (formats['md']['codeFence'] == 'tildes')
        (root / 'report.md').write_text(markdown)
        build_workbook(output_path=root / 'report.xlsx', title='冻结验证', period='2026',
            sheets=({'name': '数据', 'rows': [['项目', '金额'], ['数据', 1234.56]]},),
            preferences=formats['xlsx'], generated_date=date)
        book = load_workbook(root / 'report.xlsx')
        assert book['数据']['B2'].value == 1234.56
        assert book['数据']['B2'].number_format.split(';')[0].endswith('0.' + '0' * places)
        assert book['说明']['A2'].value == signer and book['说明']['A3'].value == date
        build_editable_pptx(output_path=root / 'report.pptx', title='冻结验证', period='2026',
            theme=formats['pptx']['theme'], slides=({'title': '正文', 'bullets': ['保留原生文字']},),
            preferences=formats['pptx'], generated_date=date)
        deck = Presentation(root / 'report.pptx')
        body = next(shape for slide in deck.slides for shape in slide.shapes
            if shape.has_text_frame and shape.text == '保留原生文字')
        assert body.text_frame.paragraphs[0].runs[0].font.size.pt == size
        last = '\n'.join(shape.text for shape in deck.slides[-1].shapes if shape.has_text_frame)
        assert signer in last and date in last
        Image.new('RGB', (240, 100), '#174a66').save(root / 'chart.png')
        job_id = str(uuid.uuid4())
        job = {'jobId': job_id, '_threadBinding': thread_binding('thread-a'),
            'sources': [{'path': path.name, 'size': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in (root / 'report.md', root / 'chart.png')],
            '_citationPresentations': [{'citationId': 'source1', 'label': '冻结来源', 'coverageItems': []}]}
        context = RunContext(run_id=frozen['runId'], session_id='thread-a',
            session_state={REPORT_JOBS_STATE_KEY: {job_id: job}})
        tools = object.__new__(WorkspaceReportService)
        await tools.bind_format_preferences(job_id, formats, run_context=context)
        await tools.bind_document_context(job_id, {'title': '冻结验证', 'periodLabel': '2026',
            'organizationName': '不得沿用的部署署名', 'generatedByLabel': 'Reporting Agent', 'watermarkText': '',
            'generatedDate': date, 'sectionNumbers': ['1'],
            'sections': [{'code': 'overview', 'sectionNumber': '1', 'title': '概览'}]}, run_context=context)
        await tools.complete_document_heading_numbers(job_id,
            [item.model_dump(mode='json', by_alias=True) for item in assembled.heading_numbers], run_context=context)
        result = ReportRuntime(root).render_markdown(tools._load_job(job_id, context), 'report.md',
            'revision/report.pdf', '.reporting-tmp/workspace-report-frozen-native-render/render.pdf')
        assert result['status'] == 'rendered'
        word = Document(root / 'revision/report.docx')
        assert word.styles['Normal'].font.size.pt == formats['word']['typography']['body']['size']
        word_text = '\n'.join(paragraph.text for paragraph in word.paragraphs)
        with pymupdf.open(root / 'revision/report.pdf') as pdf:
            pdf_text = '\n'.join(page.get_text() for page in pdf)
            spans = [span for page in pdf for block in page.get_text('dict')['blocks']
                for line in block.get('lines', []) for span in line['spans']]
        body = next(span for span in spans if '保留正文与来源' in span['text'])
        assert body['size'] == pytest.approx(formats['pdf']['typography']['body']['size'], abs=.1)
        for document_text in (word_text, pdf_text):
            assert signer in document_text and date in document_text
            assert '不得沿用的部署署名' not in document_text
            assert document_text.count('图表：指标分布') == 1
        assert len(word.inline_shapes) == 1 and len(word.tables) == 1
        picture = next(paragraph for paragraph in word.paragraphs if paragraph._p.xpath('.//w:drawing'))
        caption = next(paragraph for paragraph in word.paragraphs if paragraph.text == '图表：指标分布')
        assert picture.paragraph_format.keep_with_next is formats['word']['charts']['keepWithCaption']
        assert caption.paragraph_format.keep_together is formats['word']['charts']['keepWithCaption']
        output = Path('output/system-config-preferences/frozen-native') / frozen['runId']
        output.mkdir(parents=True, exist_ok=True)
        for path in (*root.glob('report.*'), root / 'chart.png', *root.glob('revision/report.*')):
            content = path.read_bytes()
            (output / path.name).write_bytes(content)
            evidence.append({'runId': frozen['runId'], 'configurationHash': frozen['contentHash'],
                'generatedDate': date, 'filename': str(output / path.name),
                'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
    assert parent['generatedDate'] == current['generatedDate'] == '2026-11-06'
    assert child['generatedDate'] == '2026-11-07'
    assert child['resolvedFormats'] == parent['resolvedFormats'] != current['resolvedFormats']
    Path('output/system-config-preferences/frozen-native/evidence.json').write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2))


async def test_revision_cannot_inherit_foreign_source_or_replace_registered_child(context):
    provider, _, _, _, _ = context
    await register(provider)
    await register(provider, 'task-b')
    with pytest.raises(ManagementError, match='management_run_identity_conflict'):
        await provider.inherit_run_preferences('task-a', 'revision-a', INSTANCE_SCOPE,
            user_id='foreign', thread_id='thread-a', entrypoint='report_revision')
    with pytest.raises(ManagementError, match='management_run_identity_conflict'):
        await provider.inherit_run_preferences('task-a', 'task-b', INSTANCE_SCOPE,
            user_id='user-a', thread_id='thread-a', entrypoint='report_revision')


async def test_legacy_revision_does_not_take_latest_global_preferences(context):
    provider, _, _, _, _ = context
    legacy = ManagedConfigurationProvider(provider.scope_service, provider.vault)
    await register(legacy)
    child = await provider.inherit_run_preferences('task-a', 'legacy-revision', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a', entrypoint='report_revision')
    assert child is None


@pytest.mark.parametrize('entrypoint', ['report_revision', 'policy_adoption'])
async def test_execution_helpers_use_trusted_parent_identity_and_child_snapshot(context, entrypoint):
    from types import SimpleNamespace

    from smart_reporting.preferences.runtime import (
        execution_preferences,
        inherit_execution_preferences,
    )

    provider, _, _, _, _ = context
    await register(provider)
    scope = SimpleNamespace(run_id='task-a', database='instance', company_id='instance',
        user_id='user-a', caller_thread_id='thread-a')
    runtime = SimpleNamespace(configuration_provider=provider)
    inherited = await inherit_execution_preferences(runtime, scope, 'child', entrypoint)
    execution = SimpleNamespace(source_scope=scope, **({'execution_run_id': 'child'}
        if entrypoint == 'report_revision' else {'scope': SimpleNamespace(run_id='child')}))
    assert await execution_preferences(runtime, execution) == inherited


async def test_legacy_child_without_management_registration_has_no_new_defaults(context):
    from types import SimpleNamespace

    from smart_reporting.preferences.runtime import execution_preferences

    provider, _, _, _, _ = context
    await register(provider)
    execution = SimpleNamespace(execution_run_id='old-child', source_scope=SimpleNamespace(
        database='instance', company_id='instance', user_id='user-a', caller_thread_id='thread-a'))
    assert await execution_preferences(SimpleNamespace(configuration_provider=provider), execution) is None
