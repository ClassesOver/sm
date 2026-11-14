"""隔离DB/真实HTTP及renderer验收；工作流状态与冻结材料为fixture，非业务DB试用。"""

import hashlib
import json
import re
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest
from docx import Document
from fastapi import FastAPI
from pypdf import PdfReader

from smart_reporting.management.api import SESSION_COOKIE, create_management_router
from smart_reporting.management.format_preferences import FormatPreferenceService
from smart_reporting.management.preference_verification import PreferenceVerificationHandoffService
from smart_reporting.management.preference_verification_api import (
    create_preference_verification_router,
)
from smart_reporting.management.settings import ManagementSettings
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.preferences.workbook_adapter import displayed_date
from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE, create_report_editor_router
from smart_reporting.report_editor.repository import SqlAlchemyReportEditorRepository
from smart_reporting.report_editor.service import ReportEditorGrantService
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.runtime.system_configuration import SystemConfigurationState
from smart_reporting.tests.report_issue_browser_flow import run_management_browser
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_report_preflight import bound_case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_real_report_verification_browser_uses_scoped_sessions_and_actual_renderer(auth_context, tmp_path):
    """只替换fixture工作流/材料；鉴权、持久化、HTTP、Cookie和正式生成器均实际执行。"""
    auth, repository, _ = auth_context
    auth.clock = lambda: datetime.now(UTC)
    await auth.bootstrap(OLD_PASSWORD)
    bound, _, _, _, context, workspace, _ = await bound_case(tmp_path)
    source_identities = {name: hashlib.sha256((workspace / name).read_bytes()).hexdigest()
        for name in ('report.md', 'chart.png')}
    editor_repository = SqlAlchemyReportEditorRepository(repository.engine)
    await editor_repository.create_schema()
    grants = ReportEditorGrantService(editor_repository, secret='browser-handoff-fixture-' * 3)
    full_grant, _ = await grants.issue(context)
    limited_grant, _ = await grants.issue(context, capabilities={'download_original': True})
    startup = AgentSettings.from_environment({}, load_env_file=False)
    initial = FormatPreferences.from_delivery(startup.report_delivery_settings)
    preferences = FormatPreferenceService(auth, initial)
    generated_date = context.job['_documentContext']['generatedDate']
    signatures = {}
    for format in ('md', 'pdf', 'word'):
        resolved = resolve_format_preferences(initial, format)
        signatures[format] = [resolved['common']['signer'],
            displayed_date(generated_date, resolved['common']['dateFormat']),
            *resolved['signature']['description'].splitlines()]
    bound.preferences, bound.grants = preferences, grants
    service = PreferenceVerificationHandoffService(preferences=preferences, bound=bound)

    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    settings = ManagementSettings(public_origin=origin,
        static_dir=ManagementSettings.from_environment().static_dir, allow_local_http=True)
    app, requests = FastAPI(), []

    @app.middleware('http')
    async def observe_cookie_names(request, call_next):
        # 只留Cookie名称，禁止将原始grant/session/token写入验收证据。
        path = request.url.path
        response = await call_next(request)
        if path.startswith(('/management/api/', f'/reports/v1/editor/{context.report_id}/')):
            requests.append({'path': path, 'method': request.method,
                'cookieNames': sorted(request.cookies), 'status': response.status_code})
        return response

    app.include_router(create_management_router(auth, settings, startup_settings=startup,
        system_configuration_state=SystemConfigurationState()))
    app.include_router(create_preference_verification_router(service, settings))
    app.include_router(create_report_editor_router(grants, editor=bound.editor,
        cookie_secure=False, allowed_origin=origin))
    output = Path('output/system-config-preferences/authorized-report-verification/browser').resolve()
    result = await run_management_browser(app, {'password': OLD_PASSWORD,
        'reportPath': f'/reports/v1/editor/{context.report_id}/{context.revision}',
        'fullOpenPath': f'/reports/v1/editor/open/{full_grant}',
        'limitedOpenPath': f'/reports/v1/editor/open/{limited_grant}',
        'expectedMarkdownSignature': signatures['md']}, output,
        script='smoke/management-report-verification-smoke.mjs', listener=listener)
    assert result == {'errors': [], 'authorized': True, 'restrictedRejected': True,
        'cookiePathsVerified': True, 'workflowMaterials': 'fixture', 'renderer': 'real'}

    receipt = json.loads((output / 'artifact-evidence.json').read_text())
    assert receipt['report'] == {'reportId': context.report_id, 'revision': context.revision}
    assert receipt['bindingValid'] is True and receipt['canApply'] is False
    assert receipt['formats']['xlsx']['availability'] == 'unavailable'
    assert receipt['formats']['pptx']['availability'] == 'unavailable'
    assert receipt['formats']['md']['readback']['status'] == 'passed'
    for format in ('md', 'pdf', 'word'):
        identity = receipt['formats'][format]['artifact']
        assert identity, receipt['formats'][format]['issues']
        content = (output / identity['filename']).read_bytes()
        assert len(content) == identity['size']
        assert hashlib.sha256(content).hexdigest() == identity['sha256']
    markdown = (output / 'report.md').read_text(encoding='utf-8')
    assert '冻结业务原值 1234.56。' in markdown
    assert '| 本期收入 | 1234.56 |' in markdown
    assert '| 本期支出 | -234.56 |' in markdown
    assert '冻结代码' in markdown and '收支趋势' in markdown
    start, end = '<!-- report-signature:v1 -->', '<!-- /report-signature:v1 -->'
    assert markdown.count(start) == markdown.count(end) == 1
    assert markdown.rstrip().endswith(end)
    signature = markdown.split(start, 1)[1].split(end, 1)[0]
    signature_lines = [re.sub(r'\\([^\w\s])', r'\1', line.strip())
        for line in signature.splitlines() if line.strip()]
    assert signature_lines == signatures['md']
    document = Document(output / 'word.docx')
    assert any('1234.56' in cell.text for table in document.tables for row in table.rows for cell in row.cells)
    assert len(document.inline_shapes) == 2
    assert [paragraph.text for paragraph in document.paragraphs
        if paragraph.style.name == 'Report Signature'] == signatures['word']
    pdf = PdfReader(output / 'pdf.pdf')
    pdf_text = ''.join(page.extract_text() for page in pdf.pages)
    assert pdf.pages and '1234.56' in pdf_text
    for line in signatures['pdf']:
        assert re.sub(r'\s+', '', line) in re.sub(r'\s+', '', pdf_text)
    assert source_identities == {name: hashlib.sha256((workspace / name).read_bytes()).hexdigest()
        for name in source_identities}

    management = [item for item in requests if item['path'].startswith('/management/api/')]
    editor = [item for item in requests if item['path'].endswith('/api/preference-verification')]
    assert management and editor
    assert any(SESSION_COOKIE in item['cookieNames'] for item in management)
    assert all(EDITOR_SESSION_COOKIE not in item['cookieNames'] for item in management)
    assert all(SESSION_COOKIE not in item['cookieNames'] for item in editor)
    assert all(EDITOR_SESSION_COOKIE in item['cookieNames'] for item in editor)
    assert any(item['status'] == 403 for item in editor)
    (output / 'http-cookie-evidence.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding='utf-8')
