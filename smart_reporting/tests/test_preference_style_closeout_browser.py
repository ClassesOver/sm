"""本轮偏好入口真实浏览器保存、下载与独立原生回读；复用隔离认证数据库。"""
import hashlib
import json
import socket
from pathlib import Path

import pytest
from fastapi import FastAPI
from openpyxl import load_workbook

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


async def test_preference_style_browser_saves_native_workbook_and_locates_footer_errors(auth_context):
    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    settings = ManagementSettings(public_origin=origin, static_dir=ManagementSettings.from_environment().static_dir,
        allow_local_http=True)
    app = FastAPI()
    app.include_router(create_management_router(auth, settings,
        startup_settings=AgentSettings.from_environment({}, load_env_file=False),
        system_configuration_state=SystemConfigurationState()))
    output = Path('output/system-config-preferences/preference-style-closeout-browser').resolve()
    result = await run_management_browser(app, {'password': OLD_PASSWORD}, output,
        script='smoke/management-preference-style-closeout-smoke.mjs', listener=listener)
    assert result == {'errors': [], 'saved': True}
    identities = json.loads((output / 'download-evidence.json').read_text())
    assert len(identities) == 1
    identity = identities[0]
    path = output / identity['filename']
    content = path.read_bytes()
    assert len(content) == identity['size']
    assert hashlib.sha256(content).hexdigest() == identity['sha256']
    book = load_workbook(path)
    sheet = book['示例数据']
    assert sheet.oddHeader.left.text == '页眉样式验证'
    for section in (sheet.oddHeader.left, sheet.oddFooter.right):
        assert section.font == 'Noto Serif CJK SC,Bold'
        assert section.size == 14
        assert section.color == '345678'
    assert sheet['A2'].value == '示例收入'
    assert sheet['B2'].value == 1234.56
    assert sheet['B3'].value == -234.56
    assert sheet['B4'].value == '=SUM(B2:B3)'
    assert load_workbook(path, data_only=True)['示例数据']['B4'].value == 1000
