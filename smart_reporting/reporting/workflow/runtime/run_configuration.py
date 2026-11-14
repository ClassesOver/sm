"""只在执行模型前加载可信系统快照；不向产物恢复/签发增加配置门禁。"""
from ....management.models import ManagementError, ManagementScope
from ...models import ReportingError


async def execution_runtime(runtime, run_context, *, execution=None):
    factory = getattr(runtime, '_execution_runtime_factory', None)
    startup = getattr(runtime, '_execution_startup_settings', None)
    provider = getattr(runtime, 'configuration_provider', None)
    if factory is None or startup is None or provider is None:
        return runtime
    if execution is None:
        scope = runtime._scope(run_context)
        run_id = str(run_context.run_id)
        database, company_id = scope['database'], scope['companyId']
        user_id, thread_id = scope['userId'], scope['callerThreadId']
    else:
        source = execution.source_scope
        run_id = getattr(execution, 'execution_run_id', None) or execution.scope.run_id
        database, company_id = source.database, source.company_id
        user_id, thread_id = source.user_id, source.caller_thread_id
    identity = (run_id, database, company_id, user_id, thread_id)
    if getattr(runtime, '_execution_identity', None) == identity:
        return runtime
    try:
        resolved = await provider.load_run_system_settings(run_id, ManagementScope(database, company_id),
            user_id=user_id, thread_id=thread_id, startup_settings=startup)
    except ManagementError as error:
        if error.code == 'management_run_identity_missing' and execution is not None:
            return runtime
        raise ReportingError(error.code, error.message) from error
    if resolved.snapshot is None:
        return runtime
    scoped = factory(runtime, resolved.settings)
    scoped._execution_run_id = run_id
    scoped._execution_identity = identity
    # 只保留可公开回读的来源诊断，活settings/SDK client不会进入Agno持久状态。
    receipt = {
        'runId': run_id, 'systemRevision': resolved.snapshot.get('systemRevision'),
        'systemHash': resolved.snapshot.get('systemHash'), 'credentialSource': resolved.credential_source,
        'issues': list(resolved.issues)}
    scoped._execution_configuration_receipt = receipt
    if str(run_context.run_id) == run_id:
        runtime._state(run_context)['report_execution_configuration'] = receipt
    return scoped
