"""可信任务冻结系统值的消费解析与历史凭据恢复，不连接共享测试库。"""

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from smart_reporting.management.configuration_catalog import configuration_inventory
from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.data_sources.secrets import CredentialVault
from smart_reporting.management.models import INSTANCE_SCOPE, INSTANCE_SCOPE_ID, ManagementError
from smart_reporting.management.runtime import ManagedConfigurationProvider
from smart_reporting.preferences.models import (
    FORMATS,
    FormatPreferences,
    resolve_format_preferences,
)
from smart_reporting.runtime.settings import AgentSettings


def startup(**changes):
    return replace(AgentSettings.from_environment({}, load_env_file=False), **changes)


def frozen(settings=None):
    settings = settings or startup()
    preferences = FormatPreferences.from_delivery(settings.report_delivery_settings).model_dump(mode='json', by_alias=True)
    return {'schemaVersion': 1, 'scopeId': INSTANCE_SCOPE_ID, 'runId': 'run-a',
        'preferenceRevision': None, 'preferenceHash': configuration_hash(preferences),
        'preferences': preferences,
        'resolvedFormats': {key: resolve_format_preferences(FormatPreferences.model_validate(preferences), key) for key in FORMATS},
        'systemRevision': settings.managed_system_revision, 'systemHash': settings.managed_system_hash,
        'systemValues': {item['key']: item['value'] for item in configuration_inventory(settings)
            if item['activation'] == 'restart' and not item['redacted']}, 'generatedDate': '2026-11-06'}


def resolve(settings, snapshot):
    from smart_reporting.management.run_system_settings import resolve_run_system_settings

    return resolve_run_system_settings(settings, snapshot)


def test_frozen_values_override_new_startup_without_replaying_current_service_policy():
    old = startup(model_standard_id='old-model', model_timeout_seconds=123, report_enable_vision=False,
        report_analysis_concurrency=1, report_phase_thinking_budget=1234,
        openai_base_url='https://old.example/v1', debug=True, report_editor_chart_ai_enabled=True)
    current = startup(model_standard_id='new-model', model_timeout_seconds=456, report_enable_vision=True,
        report_analysis_concurrency=5, report_phase_thinking_budget=9876,
        openai_base_url='https://new.example/v1', debug=False, report_editor_chart_ai_enabled=False)
    snapshot = frozen(old)
    result = resolve(current, snapshot)
    assert result.settings.model_standard_id == 'old-model'
    assert result.settings.model_timeout_seconds == 123
    assert result.settings.report_enable_vision is False
    assert result.settings.report_analysis_concurrency == 1
    assert result.settings.report_phase_thinking_budget == 1234
    assert result.settings.openai_base_url == 'https://old.example/v1'
    assert result.settings.debug is False
    assert result.settings.report_editor_chart_ai_enabled is False
    assert result.settings.database_url == current.database_url
    assert result.settings.platform_settings is current.platform_settings
    assert current.model_standard_id == 'new-model'
    assert snapshot == frozen(old)


@pytest.mark.parametrize('values', [
    {'AGENT_MODEL_TIMEOUT_SECONDS': True}, {'AGENT_REPORT_ENABLE_VISION': 1},
    {'AGENT_MODEL_TIMEOUT_SECONDS': 0}, {'AGENT_REPORT_ANALYSIS_CONCURRENCY': 6},
    {'AGENT_MODEL_STANDARD': []}, {'AGENT_REPORT_CODING_TEMPERATURE': float('nan')},
    {'OPENAI_BASE_URL': 'https://user:secret@example.test/v1'},
    {'OPENAI_API_KEY': 'polluted-private-secret'}, {'AGENT_DB_URL': 'postgresql://private-secret'},
    {'AGENT_REPORT_ORGANIZATION_NAME': 'not-a-system-execution-field'},
])
def test_polluted_saved_values_are_not_silently_replaced_with_new_startup(values):
    snapshot = frozen()
    snapshot['systemValues'].update(values)
    with pytest.raises(ManagementError, match='management_run_system_configuration_invalid') as error:
        resolve(startup(), snapshot)
    assert 'private-secret' not in error.value.message


def test_cross_field_budget_is_validated_after_frozen_values_are_applied():
    snapshot = frozen()
    snapshot['systemValues'].update(AGENT_REPORT_CONTEXT_TOKEN_BUDGET=1000, AGENT_REPORT_OUTPUT_TOKEN_RESERVE=1000)
    with pytest.raises(ManagementError, match='management_run_system_configuration_invalid'):
        resolve(startup(), snapshot)


@pytest.mark.parametrize('snapshot', [None, {'runId': 'legacy'}, {'runId': 'legacy', 'systemValues': None}])
def test_legacy_missing_system_values_has_explicit_current_startup_compatibility(snapshot):
    current = startup(model_standard_id='current')
    result = resolve(current, snapshot)
    assert result.settings is current
    assert any(issue['code'] == 'management_run_system_configuration_legacy' for issue in result.issues)
    assert result.credential_source == 'current_startup'


def test_legacy_missing_and_null_fields_are_reported_individually_without_rewriting_saved_values():
    snapshot = frozen(startup(model_standard_id='old-model'))
    del snapshot['systemValues']['AGENT_MODEL_TIMEOUT_SECONDS']
    snapshot['systemValues']['AGENT_REPORT_ENABLE_VISION'] = None
    current = startup(model_timeout_seconds=654, report_enable_vision=False)
    result = resolve(current, snapshot)
    assert result.settings.model_standard_id == 'old-model'
    assert result.settings.model_timeout_seconds == 654
    assert result.settings.report_enable_vision is False
    assert any(issue['code'] == 'management_run_system_configuration_partial' for issue in result.issues)
    assert snapshot['systemValues']['AGENT_REPORT_ENABLE_VISION'] is None
    assert 'AGENT_MODEL_TIMEOUT_SECONDS' not in snapshot['systemValues']


def test_unknown_future_fields_are_not_executed_and_have_an_explicit_diagnostic():
    snapshot = frozen()
    snapshot['systemValues']['FUTURE_UNKNOWN_FIELD'] = {'arbitrary': 'value'}
    result = resolve(startup(), snapshot)
    assert not hasattr(result.settings, 'FUTURE_UNKNOWN_FIELD')
    assert any(issue['code'] == 'management_run_system_configuration_unknown_keys' for issue in result.issues)


@pytest.mark.parametrize('revision,digest', [(True, 'a' * 64), (0, 'a' * 64), (1, None),
    (None, 'a' * 64), (1, 'not-a-digest')])
def test_saved_system_version_identity_must_be_a_complete_valid_pair(revision, digest):
    snapshot = frozen()
    snapshot.update(systemRevision=revision, systemHash=digest)
    with pytest.raises(ManagementError, match='management_run_system_configuration_invalid'):
        resolve(startup(), snapshot)


@pytest.mark.parametrize('values', [None, 'missing'])
def test_legacy_values_do_not_bypass_invalid_system_version_identity(values):
    snapshot = {'runId': 'legacy', 'systemRevision': True, 'systemHash': 'a' * 64}
    if values is None:
        snapshot['systemValues'] = None
    with pytest.raises(ManagementError, match='management_run_system_configuration_invalid'):
        resolve(startup(), snapshot)


class Result:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def first(self):
        return self.value

    def one_or_none(self):
        return self.value


class Rows:
    """提供有序数据库边界；身份、快照哈希、SQL选择及vault仍走生产实现。"""
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []

    async def execute(self, statement):
        table, value = self.rows.pop(0)
        assert table in str(statement)
        self.statements.append(statement.compile().params)
        return Result(value)


def provider_for(snapshot, *, version=None, credentials=(), current=None, owner='user-a'):
    rows = [('tenant_settings', {'id': INSTANCE_SCOPE_ID}), ('runtime_snapshots', {
        'user_id': owner, 'thread_id': 'thread-a'})]
    if owner == 'user-a':
        rows.append(('run_configuration_snapshots', None if snapshot is None else {
            'document': snapshot, 'content_hash': configuration_hash(snapshot)}))
        if snapshot and snapshot.get('systemRevision') is not None:
            rows.append(('configuration_versions', version))
            rows.extend(('system_credentials', row) for row in credentials)
    connection = Rows(rows)

    @asynccontextmanager
    async def transaction():
        yield connection

    vault = CredentialVault('test:' + CredentialVault.generate_key())
    scope_service = SimpleNamespace(repository=SimpleNamespace(transaction=transaction))
    return ManagedConfigurationProvider(scope_service, vault, startup_settings=current or startup()), connection


@pytest.mark.anyio
async def test_provider_owns_identity_and_uses_verified_database_snapshot_not_caller_state():
    snapshot = frozen(startup(model_standard_id='old-model'))
    provider, connection = provider_for(snapshot, current=startup(model_standard_id='new-model'))
    loader = getattr(provider, 'load_run_system_settings', None)
    assert callable(loader), '可信运行系统配置消费入口尚未接通'
    result = await loader('run-a', INSTANCE_SCOPE, user_id='user-a', thread_id='thread-a')
    assert result.settings.model_standard_id == 'old-model'
    assert result.snapshot['runId'] == 'run-a'
    assert result.credential_source == 'current_startup'
    assert any(issue['code'] == 'management_run_system_credentials_current' for issue in result.issues)
    assert not connection.rows


@pytest.mark.anyio
async def test_foreign_owner_is_rejected_before_reading_snapshot_or_secret():
    provider, connection = provider_for(frozen(), owner='other-user')
    loader = getattr(provider, 'load_run_system_settings', None)
    assert callable(loader), '可信运行系统配置消费入口尚未接通'
    with pytest.raises(ManagementError, match='management_run_identity_conflict'):
        await loader('run-a', INSTANCE_SCOPE, user_id='user-a', thread_id='thread-a')
    assert not connection.rows


@pytest.mark.anyio
async def test_historical_system_reference_decrypts_frozen_credential_without_persisting_secret():
    reference = str(uuid4())
    document = {'schemaVersion': 1, 'values': {'AGENT_MODEL_STANDARD': 'old-model'},
        'credentials': {'OPENAI_API_KEY': reference}}
    digest = configuration_hash(document)
    snapshot = frozen(startup(model_standard_id='old-model', managed_system_revision=3, managed_system_hash=digest))
    version = {'document': document, 'content_hash': digest}
    provider, connection = provider_for(snapshot, version=version, credentials=[{}],
        current=startup(openai_api_key='new-private-credential'))
    connection.rows[-1] = ('system_credentials', {'key': 'OPENAI_API_KEY', 'reference': reference,
        'key_id': provider.vault.active_key_id, 'ciphertext': provider.vault.encrypt('old-private-credential').decode()})
    loader = getattr(provider, 'load_run_system_settings', None)
    assert callable(loader), '可信运行系统配置消费入口尚未接通'
    result = await loader('run-a', INSTANCE_SCOPE, user_id='user-a', thread_id='thread-a')
    assert result.settings.openai_api_key == 'old-private-credential'
    assert result.settings.managed_system_revision == 3
    assert result.credential_source == 'historical_reference'
    assert 'private-credential' not in repr(result)
    assert 'private-credential' not in str(result.snapshot) + str(result.issues)
    assert any(3 in params.values() for params in connection.statements)
    assert not connection.rows


@pytest.mark.anyio
async def test_mixed_credentials_report_the_exact_unfrozen_key_without_misreporting_the_restored_key():
    reference = str(uuid4())
    document = {'schemaVersion': 1, 'values': {}, 'credentials': {'OPENAI_API_KEY': reference}}
    digest = configuration_hash(document)
    snapshot = frozen(startup(managed_system_revision=1, managed_system_hash=digest))
    provider, connection = provider_for(snapshot, version={'document': document, 'content_hash': digest},
        credentials=[{}], current=startup(openai_api_key='current-model-key', report_metadata_token='current-metadata-key'))
    connection.rows[-1] = ('system_credentials', {'key': 'OPENAI_API_KEY', 'reference': reference,
        'key_id': provider.vault.active_key_id, 'ciphertext': provider.vault.encrypt('historical-model-key').decode()})
    result = await provider.load_run_system_settings('run-a', INSTANCE_SCOPE, user_id='user-a', thread_id='thread-a')
    assert result.settings.openai_api_key == 'historical-model-key'
    assert result.settings.report_metadata_token == 'current-metadata-key'
    assert result.credential_source == 'mixed'
    issue = next(issue for issue in result.issues if issue['code'] == 'management_run_system_credentials_current')
    assert issue['keys'] == ['AGENT_REPORT_METADATA_TOKEN']
    assert '历史引用' in issue['message']


@pytest.mark.anyio
@pytest.mark.parametrize('version', [None, {'document': {'values': {}}, 'content_hash': 'b' * 64}])
async def test_missing_or_mismatched_historical_version_cannot_silently_use_current_secret(version):
    snapshot = frozen(startup(managed_system_revision=1, managed_system_hash='a' * 64))
    provider, _ = provider_for(snapshot, version=version)
    loader = getattr(provider, 'load_run_system_settings', None)
    assert callable(loader), '可信运行系统配置消费入口尚未接通'
    with pytest.raises(ManagementError, match='management_run_system_configuration_invalid'):
        await loader('run-a', INSTANCE_SCOPE, user_id='user-a', thread_id='thread-a')


@pytest.mark.anyio
async def test_missing_historical_credential_is_not_silently_replaced_with_current_secret():
    document = {'schemaVersion': 1, 'values': {}, 'credentials': {'OPENAI_API_KEY': str(uuid4())}}
    digest = configuration_hash(document)
    snapshot = frozen(startup(managed_system_revision=1, managed_system_hash=digest))
    provider, _ = provider_for(snapshot, version={'document': document, 'content_hash': digest}, credentials=[None])
    loader = getattr(provider, 'load_run_system_settings', None)
    assert callable(loader), '可信运行系统配置消费入口尚未接通'
    with pytest.raises(ManagementError, match='management_run_system_credential_unavailable'):
        await loader('run-a', INSTANCE_SCOPE, user_id='user-a', thread_id='thread-a')


@pytest.mark.anyio
async def test_historical_values_must_agree_with_the_referenced_published_version():
    document = {'schemaVersion': 1, 'values': {'AGENT_MODEL_STANDARD': 'published-model'}}
    digest = configuration_hash(document)
    snapshot = frozen(startup(model_standard_id='different-model', managed_system_revision=1, managed_system_hash=digest))
    provider, _ = provider_for(snapshot, version={'document': document, 'content_hash': digest})
    loader = getattr(provider, 'load_run_system_settings', None)
    assert callable(loader), '可信运行系统配置消费入口尚未接通'
    with pytest.raises(ManagementError, match='management_run_system_configuration_invalid'):
        await loader('run-a', INSTANCE_SCOPE, user_id='user-a', thread_id='thread-a')


@pytest.mark.anyio
async def test_missing_historical_encryption_key_fails_safely_without_falling_back_or_exposing_secret():
    reference = str(uuid4())
    document = {'schemaVersion': 1, 'values': {}, 'credentials': {'OPENAI_API_KEY': reference}}
    digest = configuration_hash(document)
    snapshot = frozen(startup(managed_system_revision=1, managed_system_hash=digest))
    provider, connection = provider_for(snapshot, version={'document': document, 'content_hash': digest}, credentials=[{}])
    other_vault = CredentialVault('retired:' + CredentialVault.generate_key())
    connection.rows[-1] = ('system_credentials', {'key': 'OPENAI_API_KEY', 'reference': reference,
        'key_id': other_vault.active_key_id, 'ciphertext': other_vault.encrypt('old-private-secret').decode()})
    loader = getattr(provider, 'load_run_system_settings', None)
    assert callable(loader), '可信运行系统配置消费入口尚未接通'
    with pytest.raises(ManagementError, match='management_run_system_credential_unavailable') as error:
        await loader('run-a', INSTANCE_SCOPE, user_id='user-a', thread_id='thread-a')
    assert 'old-private-secret' not in error.value.message


@pytest.mark.anyio
async def test_database_snapshot_hash_and_run_identity_remain_mandatory():
    snapshot = frozen()
    provider, connection = provider_for(snapshot)
    connection.rows[-1][1]['content_hash'] = '0' * 64
    loader = getattr(provider, 'load_run_system_settings', None)
    assert callable(loader), '可信运行系统配置消费入口尚未接通'
    with pytest.raises(ManagementError, match='management_configuration_snapshot_invalid'):
        await loader('run-a', INSTANCE_SCOPE, user_id='user-a', thread_id='thread-a')


@pytest.mark.anyio
async def test_legacy_registered_run_without_snapshot_preserves_existing_runtime_settings():
    current = startup()
    provider, _ = provider_for(None, current=current)
    loader = getattr(provider, 'load_run_system_settings', None)
    assert callable(loader), '可信运行系统配置消费入口尚未接通'
    result = await loader('run-a', INSTANCE_SCOPE, user_id='user-a', thread_id='thread-a')
    assert result.settings is current
    assert result.snapshot is None


@pytest.fixture
def anyio_backend():
    return 'asyncio'
