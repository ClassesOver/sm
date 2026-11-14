"""真实数据库冻结值恢复：发布B并重建Provider后，旧A与派生执行仍消费A。"""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from smart_reporting.management.data_sources.secrets import CredentialVault
from smart_reporting.management.models import INSTANCE_SCOPE, ManagementError
from smart_reporting.management.repository import (
    configuration_versions,
    run_configuration_snapshots,
)
from smart_reporting.management.runtime import ManagedConfigurationProvider
from smart_reporting.management.scopes import ScopeService
from smart_reporting.management.system_configuration import SystemConfigurationService
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.runtime.system_configuration import load_system_configuration
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_restarted_provider_consumes_distinct_frozen_values_and_historical_credentials(auth_context, monkeypatch):
    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login('admin', OLD_PASSWORD, '127.0.0.1')).raw_token
    monkeypatch.setenv('AGENT_MANAGEMENT_CREDENTIAL_KEYS', 'test:' + CredentialVault.generate_key())
    startup = replace(AgentSettings.from_environment({}, load_env_file=False),
        database_url=repository.engine.url.render_as_string(hide_password=False), openai_api_key='deployment-private-key')
    service = SystemConfigurationService(auth, startup)
    await service.detail(token)
    await service.replace_credential(token, 'OPENAI_API_KEY', 'historical-private-key-a', 1)
    document = (await service.detail(token))['draft']['document']
    document['values'].update(AGENT_MODEL_STANDARD='frozen-model-a', AGENT_MODEL_TIMEOUT_SECONDS=123,
        OPENAI_BASE_URL='https://old.example/v1', AGENT_REPORT_ENABLE_VISION=False,
        AGENT_REPORT_ANALYSIS_CONCURRENCY=1, AGENT_REPORT_CODING_EXECUTION_MODE='sequential')
    await service.save_draft(token, document, 2)
    await service.publish(token, 3)
    loaded_a = await asyncio.to_thread(load_system_configuration, startup)
    assert loaded_a.state.issue is None
    provider_a = ManagedConfigurationProvider(ScopeService(auth), CredentialVault(), startup_settings=loaded_a.settings)
    snapshot_a = await provider_a.register_run('frozen-system-a', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a', entrypoint='cli')

    await service.replace_credential(token, 'OPENAI_API_KEY', 'current-private-key-b', 3)
    document = (await service.detail(token))['draft']['document']
    document['values'].update(AGENT_MODEL_STANDARD='current-model-b', AGENT_MODEL_TIMEOUT_SECONDS=456,
        OPENAI_BASE_URL='https://new.example/v1', AGENT_REPORT_ENABLE_VISION=True,
        AGENT_REPORT_ANALYSIS_CONCURRENCY=5, AGENT_REPORT_CODING_EXECUTION_MODE='parallel')
    await service.save_draft(token, document, 4)
    await service.publish(token, 5)
    loaded_b = await asyncio.to_thread(load_system_configuration, startup)
    assert loaded_b.state.issue is None
    provider_b = ManagedConfigurationProvider(ScopeService(auth), CredentialVault(), startup_settings=loaded_b.settings)
    restored = await provider_b.load_run_system_settings('frozen-system-a', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a')
    assert restored.settings.model_standard_id == 'frozen-model-a'
    assert restored.settings.model_timeout_seconds == 123
    assert restored.settings.openai_base_url == 'https://old.example/v1'
    assert restored.settings.openai_api_key == 'historical-private-key-a'
    assert restored.settings.report_enable_vision is False
    assert restored.settings.report_analysis_concurrency == 1
    assert restored.settings.reporting_execution_mode == 'sequential'
    assert restored.settings.managed_system_revision == 1
    assert restored.credential_source == 'historical_reference'
    assert restored.snapshot == snapshot_a
    assert not restored.issues
    assert loaded_b.settings.model_standard_id == 'current-model-b'
    assert loaded_b.settings.openai_api_key == 'current-private-key-b'

    # 配置须进入实际原生模型、规划器、代码工厂、路由和视觉对象，不能止于JSON比较。
    from agno.agent import Agent
    from agno.run import RunContext

    from smart_reporting.model_routing import ModelRouteRequest, build_model_profiles
    from smart_reporting.reporting.agent import _report_model
    from smart_reporting.reporting.bootstrap import create_run_execution_runtime
    from smart_reporting.reporting.workflow.execution import ReportingTaskCoordinator
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    from smart_reporting.reporting.workflow.runtime.run_configuration import execution_runtime
    from smart_reporting.reporting.workflow.scope import REPORT_WORKFLOW_SCOPE_DEPENDENCY

    runner = ReportingTaskCoordinator(object(), object(), model_profiles=build_model_profiles(
        fast_model_id=loaded_b.settings.model_fast_id, standard_model_id=loaded_b.settings.model_standard_id,
        strong_model_id=loaded_b.settings.model_strong_id))
    runtime = ReportWorkflowRuntime(db=None,
        reporting_agent_template=Agent(model=_report_model(loaded_b.settings, enable_thinking=False)),
        task_runner=runner, workspace_service=SimpleNamespace(), registry=None, profiles=None,
        state_repository=object(), planner_enable_thinking=False)
    runtime._execution_startup_settings = loaded_b.settings
    runtime._execution_runtime_factory = create_run_execution_runtime
    runtime.configuration_provider = provider_b
    context = RunContext(run_id='frozen-system-a', session_id='session-a', user_id='user-a',
        dependencies={REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
            'database': INSTANCE_SCOPE.database, 'companyId': INSTANCE_SCOPE.company_id, 'threadId': 'thread-a'}},
        session_state={'report_configuration_snapshot': {'systemValues': {'AGENT_MODEL_STANDARD': 'injected-model'}}})
    scoped = await execution_runtime(runtime, context)
    for name in ['reporting_agent_template', '_request_normalizer', '_analysis_agent', '_sql_agent',
        'visualization_generator', 'section_generator', 'section_recovery']:
        model = getattr(scoped, name).model
        assert model.id == 'frozen-model-a'
        assert model.base_url == 'https://old.example/v1'
        assert model.api_key == 'historical-private-key-a'
        assert model.client is None and model.async_client is None
    assert scoped.reporting_agent_template.model.timeout == 123
    assert scoped.visualization_code_agent_factory([]).model.id == 'frozen-model-a'
    assert scoped.task_runner._model_router.select(ModelRouteRequest(
        task_kind='section_generation', complexity='standard')).model_id == 'frozen-model-a'
    assert scoped.vision_reviewer is None
    assert scoped.reporting_execution_mode == 'sequential' and scoped.analysis_concurrency == 1
    assert runtime.reporting_agent_template.model.id == 'current-model-b'
    assert scoped.task_runner.repository is runtime.task_runner.repository
    assert scoped.workspace_service is runtime.workspace_service
    assert scoped.code_mode_runtime is runtime.code_mode_runtime
    assert context.session_state['report_execution_configuration']['systemRevision'] == 1
    assert context.session_state['report_execution_configuration']['credentialSource'] == 'historical_reference'
    assert 'historical-private-key-a' not in str(context.session_state)

    await provider_b.register_run('frozen-system-b', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a', entrypoint='cli')
    new_run = await provider_b.load_run_system_settings('frozen-system-b', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a')
    assert new_run.settings.model_standard_id == 'current-model-b'
    assert new_run.settings.openai_api_key == 'current-private-key-b'
    assert new_run.settings.report_analysis_concurrency == 5
    assert new_run.settings.reporting_execution_mode == 'parallel'
    assert new_run.settings.managed_system_revision == 2

    await provider_b.inherit_run_preferences('frozen-system-a', 'frozen-system-child', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a', entrypoint='report_revision')
    child = await provider_b.load_run_system_settings('frozen-system-child', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a')
    assert child.settings.model_standard_id == 'frozen-model-a'
    assert child.settings.openai_api_key == 'historical-private-key-a'
    assert child.snapshot['parentRunId'] == 'frozen-system-a'
    assert child.snapshot['parentConfigurationHash'] == snapshot_a['contentHash']
    with pytest.raises(ManagementError, match='management_run_identity_conflict'):
        await provider_b.load_run_system_settings('frozen-system-a', INSTANCE_SCOPE,
            user_id='foreign-user', thread_id='thread-a')
    async with repository.engine.connect() as connection:
        saved = (await connection.execute(select(run_configuration_snapshots))).mappings().all()
        versions = (await connection.execute(select(configuration_versions))).mappings().all()
    assert len(saved) == 3
    assert all(secret not in str(saved) + str(versions) + repr(restored)
        for secret in ['historical-private-key-a', 'current-private-key-b', 'deployment-private-key'])


async def test_legacy_run_without_system_snapshot_is_not_retroactively_frozen(auth_context):
    auth, _, _ = auth_context
    scopes = ScopeService(auth)
    legacy = ManagedConfigurationProvider(scopes, CredentialVault())
    assert await legacy.register_run('legacy-no-system-snapshot', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a', entrypoint='cli') is None
    current = AgentSettings.from_environment({}, load_env_file=False)
    provider = ManagedConfigurationProvider(scopes, CredentialVault(), startup_settings=current)
    result = await provider.load_run_system_settings('legacy-no-system-snapshot', INSTANCE_SCOPE,
        user_id='user-a', thread_id='thread-a')
    assert result.settings is current
    assert result.snapshot is None
    assert any(issue['code'] == 'management_run_system_configuration_legacy' for issue in result.issues)
