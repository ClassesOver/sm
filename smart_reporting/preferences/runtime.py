"""把可信任务快照绑定到会话；恢复时必须与数据库记录一致。"""

from copy import deepcopy

REPORT_CONFIGURATION_SNAPSHOT_KEY = "report_configuration_snapshot"


def bind_run_preferences(state: dict, snapshot: dict | None) -> None:
    current = state.get(REPORT_CONFIGURATION_SNAPSHOT_KEY)
    if current is not None and current != snapshot:
        raise ValueError("报告配置快照与可信运行不一致")
    if snapshot is not None:
        state[REPORT_CONFIGURATION_SNAPSHOT_KEY] = deepcopy(snapshot)


async def inherit_execution_preferences(runtime, source_scope, run_id, entrypoint):
    from ..management.models import ManagementScope

    provider = getattr(runtime, 'configuration_provider', None)
    if provider is None or not hasattr(provider, 'inherit_run_preferences'):
        return None
    return await provider.inherit_run_preferences(source_scope.run_id, run_id,
        ManagementScope(source_scope.database, source_scope.company_id), user_id=source_scope.user_id,
        thread_id=source_scope.caller_thread_id, entrypoint=entrypoint)


async def execution_preferences(runtime, execution):
    from ..management.models import ManagementError, ManagementScope

    provider = getattr(runtime, 'configuration_provider', None)
    if provider is None or not hasattr(provider, 'load_run_preferences'):
        return None
    scope = execution.source_scope
    run_id = getattr(execution, 'execution_run_id', None) or execution.scope.run_id
    try:
        return await provider.load_run_preferences(run_id, ManagementScope(scope.database, scope.company_id),
            user_id=scope.user_id, thread_id=scope.caller_thread_id)
    except ManagementError as error:
        if error.code != 'management_run_identity_missing':
            raise
        # 升级前的派生运行没有格式快照，沿用原交付机制，不补取新默认。
        return None
