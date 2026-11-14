"""隔离 PostgreSQL + 真实构建页面核验配置入口，不替换 HTTP 响应。"""
import socket
from pathlib import Path

import pytest
from fastapi import FastAPI

from smart_reporting.management.api import create_management_router
from smart_reporting.management.settings import ManagementSettings
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.runtime.system_configuration import SystemConfigurationState
from smart_reporting.tests.report_issue_browser_flow import run_management_browser
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_configuration_defaults_do_not_expand_redundant_parameters_or_page_width(auth_context):
    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    settings = ManagementSettings(public_origin=origin,
        static_dir=ManagementSettings.from_environment().static_dir, allow_local_http=True)
    app = FastAPI()
    app.include_router(create_management_router(auth, settings,
        startup_settings=AgentSettings.from_environment({}, load_env_file=False),
        system_configuration_state=SystemConfigurationState()))
    evidence = await run_management_browser(app, {'password': OLD_PASSWORD},
        Path('output/system-config-preferences/compact-settings').resolve(),
        script='smoke/management-settings-compact-smoke.mjs', listener=listener)
    assert evidence['errors'] == []
    assert evidence['compact']


async def test_preference_preview_after_each_saved_draft_uses_current_version(auth_context):
    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    settings = ManagementSettings(public_origin=origin,
        static_dir=ManagementSettings.from_environment().static_dir, allow_local_http=True)
    app = FastAPI()
    app.include_router(create_management_router(auth, settings,
        startup_settings=AgentSettings.from_environment({}, load_env_file=False),
        system_configuration_state=SystemConfigurationState()))
    evidence = await run_management_browser(app, {'password': OLD_PASSWORD},
        Path('output/system-config-preferences/heading-level-browser').resolve(),
        script='smoke/management-preference-save-preview-smoke.mjs', listener=listener)
    assert evidence['errors'] == []
    assert evidence['saved'] == 9


async def test_document_output_controls_save_independently_and_download_actual_native_files(auth_context):
    from docx import Document
    from pypdf import PdfReader

    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    settings = ManagementSettings(public_origin=origin,
        static_dir=ManagementSettings.from_environment().static_dir, allow_local_http=True)
    app = FastAPI()
    app.include_router(create_management_router(auth, settings,
        startup_settings=AgentSettings.from_environment({}, load_env_file=False),
        system_configuration_state=SystemConfigurationState()))
    output = Path('output/system-config-preferences/document-output-browser').resolve()
    evidence = await run_management_browser(app, {'password': OLD_PASSWORD}, output,
        script='smoke/management-document-output-smoke.mjs', listener=listener)
    assert evidence['errors'] == []
    assert evidence['saved'] == 3 and evidence['independentFormats']
    for name, with_sources, with_cover in [('word-v2', True, False), ('pdf-v3', False, True), ('word-v4', False, False)]:
        pdf = PdfReader(output / (name + '.pdf'))
        text = '\n'.join(page.extract_text() for page in pdf.pages)
        assert ('实际引用附录' in text) == with_sources
        assert ('固定排版样例，非业务数据' in text) == with_sources
        assert ('[来源 001]' in text) == with_sources
        assert '目录' not in text and '[[citation:' not in text
        assert '1234.56' in text and '-234.56' in text
        assert ('样例概览' not in pdf.pages[0].extract_text()) == with_cover
        if name.startswith('word'):
            document = Document(output / (name + '.docx'))
            assert len(document.tables) == 1
            assert not any('TOC ' in (field.text or '') for field in document.element.xpath('//w:instrText'))


async def test_chart_pagination_controls_save_preview_and_freeze_each_format(auth_context):
    from docx import Document
    from pypdf import PdfReader

    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    settings = ManagementSettings(public_origin=origin,
        static_dir=ManagementSettings.from_environment().static_dir, allow_local_http=True)
    app = FastAPI()
    app.include_router(create_management_router(auth, settings,
        startup_settings=AgentSettings.from_environment({}, load_env_file=False),
        system_configuration_state=SystemConfigurationState()))
    output = Path('output/system-config-preferences/chart-pagination-browser').resolve()
    evidence = await run_management_browser(app, {'password': OLD_PASSWORD}, output,
        script='smoke/management-chart-pagination-smoke.mjs', listener=listener)
    assert evidence['errors'] == [] and evidence['saved'] == 3
    for version, keep in ((2, False), (4, True)):
        document = Document(output / f'word-v{version}.docx')
        assert len(document.inline_shapes) == 1 and len(document.tables) == 1
        picture = next(paragraph for paragraph in document.paragraphs if paragraph._p.xpath('.//w:drawing'))
        caption = next(paragraph for paragraph in document.paragraphs if paragraph.text == '图表：固定排版示例')
        assert picture.paragraph_format.keep_with_next is keep
        assert caption.paragraph_format.keep_together is keep
    for filename in ('word-v2.pdf', 'pdf-v3.pdf', 'word-v4.pdf'):
        text = '\n'.join(page.extract_text() for page in PdfReader(output / filename).pages)
        assert '固定排版示例' in text and '1234.56' in text and '-234.56' in text


async def test_real_configuration_pages_save_publish_and_keep_forms_compact(auth_context, monkeypatch):
    from smart_reporting.management.data_sources.secrets import CredentialVault

    monkeypatch.setenv('AGENT_MANAGEMENT_CREDENTIAL_KEYS', 'browser:' + CredentialVault.generate_key())
    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    settings = ManagementSettings(public_origin=origin, static_dir=ManagementSettings.from_environment().static_dir,
        allow_local_http=True)
    startup = AgentSettings.from_environment({}, load_env_file=False)
    app = FastAPI()
    app.include_router(create_management_router(auth, settings, startup_settings=startup,
        system_configuration_state=SystemConfigurationState()))
    evidence = await run_management_browser(app, {'password': OLD_PASSWORD},
        Path('output/system-config-preferences/browser').resolve(),
        script='smoke/management-configuration-smoke.mjs', listener=listener)
    from docx import Document

    actual = Document('output/system-config-preferences/browser/preferences-edited-preview.docx')
    assert abs(actual.sections[-1].page_width.mm - 297) < 0.02
    assert abs(actual.sections[-1].left_margin.mm - 30) < 0.02
    assert abs(actual.sections[-1].right_margin.mm - 12.7) < 0.02
    assert '工程页眉 格式偏好预览' in actual.sections[-1].header.paragraphs[0].text
    signature = next(paragraph for paragraph in actual.paragraphs if paragraph.text == '工程验证署名')
    assert signature.style.font.size.pt == 14
    assert str(signature.style.font.color.rgb) == '123456'
    assert signature.style.font.bold
    styled = Document('output/system-config-preferences/browser/preferences-common-style.docx')
    assert styled.styles['Normal'].font.name == 'Noto Serif CJK SC'
    assert str(styled.styles['Heading 1'].font.color.rgb) == '765432'
    assert styled.styles['Heading 1'].font.name == 'Noto Serif CJK SC'
    from openpyxl import load_workbook

    workbook = load_workbook('output/system-config-preferences/browser/preferences-numeric-preview.xlsx')
    assert workbook['示例数据']['B2'].value == 1234.56
    assert workbook['示例数据']['B2'].number_format == '0.0000;(0.0000)'
    assert workbook['示例数据']['B3'].value == -234.56
    assert workbook['示例数据']['B4'].value == '=SUM(B2:B3)'
    from datetime import datetime

    assert workbook['示例数据']['B5'].value == 12.5
    assert workbook['示例数据']['B5'].number_format == '0.000"%";(0.000"%")'
    assert workbook['示例数据']['B6'].value == datetime(2026, 11, 12)
    assert workbook['示例数据']['B6'].number_format == 'yyyy/mm/dd'
    printed = load_workbook('output/system-config-preferences/browser/preferences-print-preview.xlsx')
    assert printed['示例数据'].page_setup.scale == 75
    assert not printed['示例数据'].sheet_properties.pageSetUpPr.fitToPage
    assert printed['示例数据'].print_title_rows is None
    assert printed['说明'].print_area
    assert evidence['errors'] == []
    assert evidence['saved'] and evidence['restartRequired'] and evidence['preferenceDraftSaved'] and evidence['applicationUnavailable']
    assert evidence['pptxLayoutSaved']
    assert evidence['pageAndHeaderSaved'] and evidence['realPreviewRendered']
    assert evidence['invalidFieldLocated'] and evidence['unsavedLeaveProtected']
    assert evidence['conflictRetained'] and evidence['responseLossRecovered']
    assert evidence['tableDraftSaved'] and evidence['noOrganizationInputs'] and evidence['formatTabs'] == 5
    assert evidence['credentialReplaced'] and evidence['credentialReferencePreserved']
    navigation = Path('output/system-config-preferences/browser/preferences-navigation-preview.md').read_text()
    assert navigation.count('<!-- report-md-toc:v1 -->') == 1
    assert '[1\\. 样例概览](#report-md-heading-1)' in navigation
    assert navigation.count('1234.56') == 1 and navigation.count('-234.56') == 1
    assert navigation.count('<!-- report-signature:v1 -->') == 1
    from pypdf import PdfReader

    output_pdf = PdfReader('output/system-config-preferences/browser/preferences-output-preview.pdf')
    assert output_pdf.outline == []
    assert '1234.56' in ''.join(page.extract_text() for page in output_pdf.pages)
