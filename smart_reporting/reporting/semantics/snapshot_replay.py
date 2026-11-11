"""只读登记快照并复用原生计算器；不重新查询数据库或生成数据集。"""

from ...workspace import WorkspaceError
from ..models import ReportingError
from ..workflow.query_pipeline import normalized_sql_hash
from .execution import execute_metric


class _OfflineSource:
    def __init__(self, config):
        self.config = config

    async def materialize_bound(self, *args, **kwargs):
        raise ReportingError('metric_replay_query_forbidden', '快照复算不得重新查询业务库。')


class _ReplayDatasets:
    def __init__(self, datasets, receipt):
        self.service = datasets.service
        self.snapshots = {}
        self.used = set()
        for snapshot in receipt.datasets:
            key = (snapshot.source_id, snapshot.dataset.requirement_id, snapshot.dataset.query_window_id)
            if key in self.snapshots:
                raise ReportingError('metric_replay_identity_invalid', '快照查询身份重复，不能复算。')
            self.snapshots[key] = snapshot

    async def materialize_batch(self, approved, adapters, *, run_context):
        handles = []
        for query in approved:
            key = (query.source_id, query.requirement_id, query.query_window_id)
            snapshot = self.snapshots.get(key)
            if (snapshot is None or key in self.used or snapshot.dataset.sql_hash != query.sql_hash
                    or not snapshot.dataset.query_sql
                    or normalized_sql_hash(snapshot.dataset.query_sql) != query.sql_hash
                    or snapshot.dataset.period_roles != query.period_roles):
                raise ReportingError('metric_replay_identity_invalid', '登记快照不匹配冻结查询计划。')
            self.used.add(key)
            handles.append(snapshot.to_handle())
        return tuple(handles), ()


async def replay_metric_calculation(plan, receipt, sources, *, datasets, run_context):
    identity = datasets.service.registry.get(run_context.session_id)
    binding = receipt.workspace
    if (plan.request != receipt.request or not receipt.datasets or binding is None or identity is None
            or (binding.workspace_key, binding.session_id, binding.scope_fingerprint)
            != (identity.workspace_key, identity.workflow_session_id, identity.scope_fingerprint)):
        raise ReportingError('metric_replay_scope_mismatch', '快照复算的请求或可信工作区不一致。')
    try:
        for snapshot in receipt.datasets:
            actual = await datasets.service.ahash_file(binding.workspace_key, snapshot.file.path)
            if actual.get('sha256') != snapshot.file.sha256 or actual.get('size') != snapshot.file.size:
                raise ReportingError('metric_snapshot_invalid', '回归快照身份已变化。')
    except (WorkspaceError, OSError):
        raise ReportingError('metric_snapshot_invalid', '回归快照缺失或不可读取。') from None
    replay = _ReplayDatasets(datasets, receipt)
    actual = await execute_metric(plan, {key: _OfflineSource(config) for key, config in sources.items()},
        datasets=replay, run_context=run_context, calculation_id=receipt.results[0].calculation_id)
    if (set(replay.snapshots) != replay.used
            or {item.fact_id: item for item in actual.results} != {item.fact_id: item for item in receipt.results}
            or actual.readiness != receipt.readiness):
        raise ReportingError('metric_replay_result_mismatch', '实际快照复算与登记事实或数据就绪记录不一致。')
    return actual
