"""真实管理浏览器保存六项PPTX缩进并回读样例原生段落。"""

import json
import socket
from pathlib import Path

import pytest
from fastapi import FastAPI
from pptx import Presentation

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


async def test_pptx_indent_fields_persist_in_real_browser_and_native_preview_artifact(auth_context):
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
    output = Path('output/system-config-preferences/pptx-indent/browser').resolve()
    result = await run_management_browser(app, {'password': OLD_PASSWORD}, output,
        script='smoke/management-pptx-indent-smoke.mjs', listener=listener)
    assert result == {'errors': [], 'saved': True}

    from hashlib import sha256

    evidence = json.loads((output / 'download-evidence.json').read_text())
    content = (output / evidence['filename']).read_bytes()
    assert len(content) == evidence['size'] and sha256(content).hexdigest() == evidence['sha256']
    deck = Presentation(output / evidence['filename'])
    roles = {'pptx.typography.body.indent': [], 'pptx.typography.h1.indent': [],
        'pptx.typography.caption.indent': [], 'pptx.signature.indent': [], 'pptx.footerStyle.indent': []}
    table_values = []
    for slide_index, slide in enumerate(deck.slides):
        for shape in slide.shapes:
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for paragraph in cell.text_frame.paragraphs:
                            table_values.append(int(paragraph._p.get_or_add_pPr().get('indent', 0)))
                continue
            if not shape.has_text_frame or not shape.text:
                continue
            if slide_index > 0 and shape.top > deck.slide_height * .82:
                target = 'pptx.footerStyle.indent'
            elif shape.text.startswith(('浏览器验收', '2026-')):
                target = 'pptx.signature.indent'
            elif shape.text.startswith('图 1 '):
                target = 'pptx.typography.caption.indent'
            elif shape.text.startswith(('TITLE', '格式偏好预览', '演示文稿偏好预览', '报告落款')) or shape.top < 160 * 9525:
                target = 'pptx.typography.h1.indent'
            else:
                target = 'pptx.typography.body.indent'
            roles[target].extend(int(paragraph._p.get_or_add_pPr().get('indent', 0))
                for paragraph in shape.text_frame.paragraphs)
    for path, values in roles.items():
        assert values, f'样例缺少该字段的真实末端对象: {path}'
        assert set(values) == {evidence['expected'][path] * 12700}, (path, values)
    if table_values:
        assert evidence['objectCoverage']['pptx.typography.table.indent'] is True
        assert set(table_values) == {evidence['expected']['pptx.typography.table.indent'] * 12700}
    else:
        assert evidence['objectCoverage']['pptx.typography.table.indent'] is None
