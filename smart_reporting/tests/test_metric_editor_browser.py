"""真实管理HTTP/隔离PG下的指标编辑、发布和未知响应恢复。"""

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from smart_reporting.management.api import create_management_router
from smart_reporting.management.metrics_api import create_metrics_router
from smart_reporting.management.repository import audit_events, metric_versions
from smart_reporting.management.settings import ManagementSettings
from smart_reporting.reporting.tests.test_semantic_models import metric_payload
from smart_reporting.tests.report_issue_browser_flow import run_management_browser
from smart_reporting.tests.test_management_metrics import context, draft
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_metric_editor_saves_and_publishes_once_preserving_old_and_foreign_versions(auth_context):
    service, token, scope, other = await context(auth_context)
    for organization, name in ((scope, '原预算额'), (other, '另一组织预算')):
        await service.save_draft(token, organization, draft(metric_payload(name=name)), 0)
        await service.publish(token, organization, 'budget', expected_version=1)
    old = (await service.get(token, scope, 'budget', revision=1))['published']
    foreign = await service.get(token, other, 'budget')
    await service.save_draft(token, scope, draft(metric_payload('actual', name='实际额', unit='元')), 0)
    await service.publish(token, scope, 'actual', expected_version=1)
    app = FastAPI()
    settings = ManagementSettings(public_origin='http://127.0.0.1:5198', allow_local_http=True)
    app.include_router(create_management_router(service.scopes.auth, settings))
    app.include_router(create_metrics_router(service, settings))
    output = Path('/tmp') / f'smart-reporting-metric-editor-browser-{os.getpid()}'
    output.mkdir()
    browser = await run_management_browser(app, {
        'token': token, 'database': scope.database, 'companyId': scope.company_id,
    }, output, script='smoke/management-metric-editor-postgres-smoke.mjs')
    assert browser['saves'] == browser['publications'] == 2
    current = await service.get(token, scope, 'budget')
    assert current['draft']['version'] == 2 and current['published']['revision'] == 2
    assert current['published']['document']['name'] == '修订预算额'
    assert current['published']['document']['unit'] == '元'
    assert (await service.get(token, scope, 'budget', revision=1))['published'] == old
    assert await service.get(token, other, 'budget') == foreign
    rate = await service.get(token, scope, 'rate')
    assert rate['published']['document']['numeratorVersion'] == {'metricId': 'actual', 'revision': 1}
    assert rate['published']['document']['denominatorVersion'] == {'metricId': 'budget', 'revision': 2}
    async with service.repository.transaction() as connection:
        audits = list((await connection.execute(select(audit_events.c.action).where(
            audit_events.c.action.in_(['metric_draft_saved', 'metric_published']),
        ))).scalars())
        versions = list((await connection.execute(select(metric_versions.c.revision))).scalars())
    # 初始三次保存/发布；浏览器修改预算、创建比率各一次，读回不产生写审计。
    assert audits.count('metric_draft_saved') == audits.count('metric_published') == 5
    assert sorted(versions) == [1, 1, 1, 1, 2]
    (output / 'database-evidence.json').write_text(json.dumps({
        'oldPublished': old, 'current': current, 'foreignUnchanged': foreign,
        'auditActions': audits, 'versions': sorted(versions), 'ratio': rate,
        'fixtureScope': '隔离PostgreSQL合成指标定义；未执行报告、模型或业务数据库查询',
    }, ensure_ascii=False, indent=2))
