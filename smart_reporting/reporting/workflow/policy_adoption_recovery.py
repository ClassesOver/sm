"""新口径准备阶段的只读核对；读取不会补登记或启动任何计算。"""

from loguru import logger

from ..hospital_operation.findings import FindingGraph
from ..hospital_operation.narrative_outline import NarrativeOutline
from ..hospital_operation.narrative_planner import build_compatible_report_outline
from ..hospital_operation.outline import ReportOutline
from ..models import ReportingError
from ..trace.contracts_v1 import canonical_sha256
from .checkpoint import FileIdentity, ReportingCheckpoint, payload_sha256
from .policy_adoption import policy_adoption_run_context, require_policy_adoption_execution
from .policy_adoption_analysis import (
    PolicyAdoptionDocumentJob,
    read_policy_adoption_analysis_preparation,
)


async def inspect_policy_adoption_preparation(runtime, source_context, execution):
    child = await require_policy_adoption_execution(runtime, source_context, execution)
    context = policy_adoption_run_context(execution)
    files = {item['path']: FileIdentity.model_validate(item) for item in child.payload.get('artifacts', ())}
    result = {}
    handles = None
    for kind, filename in (('analysis', 'analysis-preparation.json'), ('document', 'document-job.json')):
        if kind == 'document' and not set(execution.requested_outputs) <= {'pdf', 'docx'}:
            result[kind] = {'status': 'not_applicable', 'issueCodes': []}
            continue
        path = f'报表/智能分析/{execution.scope.run_id}/policy-adoption/{filename}'
        try:
            hashes = await runtime.workspace_service.abatch_hash_files(execution.scope.workspace_key, [path])
            if len(hashes) != 1 or hashes[0].get('path') != path:
                raise ReportingError('report_policy_adoption_preparation_unavailable', '准备文件身份读取结果不完整。')
            if hashes[0].get('missing'):
                partial = kind == 'analysis' and child.payload.get('detailedAnalysisPlan')
                result[kind] = {'status': 'unverifiable' if partial or path in files else 'not_generated',
                    'issueCodes': ['report_policy_adoption_preparation_unknown'] if partial or path in files else []}
                continue
            identity = FileIdentity.model_validate({key: hashes[0][key] for key in ('path', 'size', 'sha256')})
            if path in files and files[path] != identity:
                raise ReportingError('report_policy_adoption_mismatch', '已登记准备文件身份变化。')
            if handles is None:
                handles = await runtime._registered_metric_dataset_handles(context)
            if not handles:
                raise ReportingError('report_analysis_context_unavailable', '没有可核验的新计算数据。')
            if kind == 'analysis':
                view = await runtime._metric_planning_context(context)
                await read_policy_adoption_analysis_preparation(runtime, execution, child, identity, view, handles)
            else:
                # 文档依赖已登记的分析准备；不借此检查补登记上游文件。
                if result['analysis']['status'] != 'registered':
                    raise ReportingError('report_policy_adoption_preparation_unknown', '请先核对分析准备。')
                checkpoint = ReportingCheckpoint.model_validate(child.payload.get('workflowCheckpoint'))
                saved = await runtime._read_identity_model(execution.scope.workspace_key, identity, PolicyAdoptionDocumentJob)
                if (checkpoint.revision != execution.output_revision or checkpoint.narrative_outline_file is None
                        or saved.execution_sha256 != canonical_sha256(execution.model_dump(mode='json', by_alias=True))
                        or saved.outline_sha256 != checkpoint.outline_hash):
                    raise ReportingError('report_policy_adoption_mismatch', '文档job与新执行或最终提纲不一致。')
                # 图谱身份由持久checkpoint登记；章节文件另有artifact登记，不要求双重登记图谱。
                narrative_file = checkpoint.narrative_outline_file
                if (files.get(narrative_file.path) != narrative_file
                        or checkpoint.narrative_outline_hash != narrative_file.sha256
                        or checkpoint.finding_graph_file is None):
                    raise ReportingError('report_policy_adoption_mismatch', '文档提纲依赖未登记。')
                narrative = await runtime._read_identity_model(execution.scope.workspace_key, narrative_file, NarrativeOutline)
                graph = await runtime._read_identity_model(execution.scope.workspace_key, checkpoint.finding_graph_file, FindingGraph)
                initial = ReportOutline.model_validate(child.payload.get('approvedOutline'))
                outline = build_compatible_report_outline(graph, report_type=initial.report_type,
                    title=narrative.title, narrative_outline=narrative)
                if (graph.snapshot_hash != narrative.snapshot_hash or graph.snapshot_hash != checkpoint.finding_graph_hash
                        or payload_sha256(outline.model_dump(mode='json', by_alias=True)) != saved.outline_sha256):
                    raise ReportingError('report_policy_adoption_mismatch', '最终提纲与实际图谱或文档job不同。')
                tool_context = runtime._tool_context(context)
                runtime.report_tools._store_job(saved.job, tool_context)
                job = runtime.report_tools._load_job(saved.job['jobId'], tool_context)
                expected = {(item.path, item.size, item.sha256) for item in handles}
                actual = {(item['path'], item['size'], item['sha256']) for item in job['sources']}
                if actual != expected or len(job['sources']) != len(expected):
                    raise ReportingError('report_policy_adoption_mismatch', '文档job包含其他CSV来源。')
            result[kind] = {'status': 'registered' if path in files else 'awaiting_confirmation',
                'identity': identity.model_dump(mode='json', by_alias=True), 'issueCodes': []}
        except Exception as error:
            logger.warning('policy_adoption_preparation_inspection_failed kind={} error_type={}', kind, type(error).__name__)
            result[kind] = {'status': 'unverifiable', 'issueCodes': [
                error.code if isinstance(error, ReportingError) else 'report_policy_adoption_preparation_unavailable'],
                'message': error.message if isinstance(error, ReportingError) else '准备文件无法核验，请保留原任务供核对。'}
    current = await require_policy_adoption_execution(runtime, source_context, execution)
    if current.state_version != child.state_version:
        raise ReportingError('report_editor_conflict', '核对期间执行状态已变化，请重新读取。')
    return {**result, 'stateVersion': current.state_version}


async def confirm_policy_adoption_preparation(runtime, source_context, execution, *,
        kind, identity, expected_state_version):
    """只补登记明确确认的原文件；单次CAS失败不自动重试，不负责启动执行。"""
    from .state import ReportingCommand, ReportingStateConflict

    child = await require_policy_adoption_execution(runtime, source_context, execution)
    inspected = await inspect_policy_adoption_preparation(runtime, source_context, execution)
    candidate = inspected.get(kind)
    if (candidate is None or candidate.get('status') not in {'registered', 'awaiting_confirmation'}
            or candidate.get('identity') != identity.model_dump(mode='json', by_alias=True)):
        raise ReportingError('report_editor_conflict', '准备文件或依赖已变化，请重新核对，不自动采用新身份。')
    if candidate['status'] != 'registered':
        current = await require_policy_adoption_execution(runtime, source_context, execution)
        if child.state_version != expected_state_version or current.state_version != expected_state_version:
            raise ReportingError('report_editor_conflict', '执行状态已变化，请重新核对后确认。')
        await runtime._read_identity_bytes(execution.scope.workspace_key, identity)
        prefix = 'adoption-analysis-preparation' if kind == 'analysis' else 'adoption-document-job'
        try:
            await runtime.state_repository.apply(execution.scope.run_id,
                ReportingCommand(name='record_artifact', commandId=f'{prefix}:{identity.sha256}',
                    payload={'artifact': identity.model_dump(mode='json', by_alias=True)}),
                expected_version=expected_state_version)
        except ReportingStateConflict as error:
            raise ReportingError('report_editor_conflict', '确认期间执行状态已变化，请先读取原结果。') from error
    result = await inspect_policy_adoption_preparation(runtime, source_context, execution)
    return {**result, 'executionResumed': False}
