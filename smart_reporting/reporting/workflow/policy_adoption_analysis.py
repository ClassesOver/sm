"""新口径从正式计算重新规划；按登记文件恢复，不沿用原报告计划或画像。"""

import json
from datetime import timedelta

from agno.workflow.types import StepInput
from pydantic import Field, JsonValue, ValidationError

from ...management.models import ManagementScope
from ..contract import ReportPeriod, ReportRequestEnvelope, StrictModel
from ..hospital_operation.detailed_analysis import DatasetAnalysisContext, DetailedAnalysisPlan
from ..hospital_operation.outline import ReportOutline
from ..models import ReportingError
from ..trace.contracts_v1 import canonical_sha256
from .checkpoint import FileIdentity, ProfileCoverageManifest
from .policy_adoption import policy_adoption_run_context, require_policy_adoption_execution
from .query_pipeline import DatasetLineage, QueryRequirement, resolve_schema_snapshot
from .revision_execution import _source_state
from .runtime.models import AnalysisItem, DataUnderstandingPlan
from .state import ReportingCommand


class PolicyAdoptionAnalysis(StrictModel):
    execution_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    planning_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    data_understanding: DataUnderstandingPlan = Field(alias='report_data_understanding')
    analyses: tuple[AnalysisItem, ...] = Field(alias='report_analysis_plan')
    requirements: tuple[QueryRequirement, ...] = Field(alias='report_data_requirements')
    contexts: tuple[DatasetAnalysisContext, ...] = Field(alias='report_analysis_data_context')
    coverage: ProfileCoverageManifest = Field(alias='report_profile_coverage')
    detailed_plan: DetailedAnalysisPlan = Field(alias='report_detailed_analysis_plan')
    context_file: FileIdentity = Field(alias='report_analysis_context_file')


class PolicyAdoptionDocumentJob(StrictModel):
    execution_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    outline_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    # 原生WorkspaceReportService的会话job快照，不另定义文档任务协议。
    job: dict[str, JsonValue]


def _request(basis, report_type):
    summary = basis.request_summary
    formats = {'document' if item in {'pdf', 'docx'} else item for item in summary.requested_outputs}
    if len(formats) != 1:
        raise ReportingError('report_policy_adoption_unavailable', '尚不支持混合文档、演示与工作簿的新口径交付。')
    def period(value):
        return ReportPeriod(start=value.start, end=value.end - timedelta(days=1)) if value else None
    return ReportRequestEnvelope(reportGoal=summary.goal, scenario=summary.scenario,
        statisticalPolicyVersion=basis.policy_version, questions=summary.questions,
        knowledgeAsOf=basis.knowledge_as_of if any(item.field == 'knowledgeAsOf' and item.source == 'explicit'
            for item in summary.assumptions) else None,
        displayUnit=summary.display_unit, period=period(summary.period),
        comparisonPeriod=period(summary.comparison_period), comparisonRoles=(),
        sourceIds=tuple(item.source_id for item in basis.source_versions), deliveryFormat=next(iter(formats)),
        domains=summary.domains, reportType=report_type)


async def read_policy_adoption_analysis_preparation(runtime, execution, child, identity, view, handles):
    """只读核验供恢复和预检复用，不执行规划或登记。"""
    files = {item['path']: FileIdentity.model_validate(item) for item in child.payload.get('artifacts', ())}
    saved = await runtime._read_identity_model(execution.scope.workspace_key, identity, PolicyAdoptionAnalysis)
    if (saved.execution_sha256 != canonical_sha256(execution.model_dump(mode='json', by_alias=True))
            or saved.planning_sha256 != canonical_sha256(view.model_dump(mode='json', by_alias=True))
            or saved.detailed_plan.model_dump(mode='json', by_alias=True) != child.payload.get('detailedAnalysisPlan')
            or set(saved.detailed_plan.dataset_ids) != {item.dataset_id for item in handles}):
        raise ReportingError('report_policy_adoption_mismatch', '已登记分析准备与新依据或实际数据不一致。')
    for identity in (saved.context_file, *(item.profile_file for item in saved.contexts)):
        if files.get(identity.path) != FileIdentity.model_validate(identity.model_dump()):
            raise ReportingError('report_policy_adoption_mismatch', '新分析依赖未登记到当前执行。')
        await runtime._read_identity_bytes(execution.scope.workspace_key, identity)
    return saved


async def prepare_policy_adoption_analysis(runtime, source_context, execution, *,
        confirmed_preparation: FileIdentity | None = None):
    """新原生阶段仅消费新计算；完成准备后仅读取已登记计划及真实依赖文件。"""
    child = await require_policy_adoption_execution(runtime, source_context, execution)
    context = policy_adoption_run_context(execution)
    managed = await runtime._basis_execution_context(context)
    parent, _ = await _source_state(runtime, execution.source_scope)
    try:
        original_outline = ReportOutline.model_validate(parent.payload.get('approvedOutline'))
    except ValidationError as error:
        raise ReportingError('report_policy_adoption_outline_unavailable',
            '原报告缺少已登记提纲，无法确认报告类型；不从旧正文或模型猜测。') from error
    # 只沿用原报告类型；新分析及新提纲不能复制原章节或旧分析引用。
    envelope = _request(managed.basis, original_outline.report_type)
    state = context.session_state
    state['report_workflow_input'] = envelope.model_dump(mode='json', by_alias=True)
    state['report_schema_snapshots'] = [resolve_schema_snapshot(envelope, source=source,
        metadata=managed.metadata[key], catalog=managed.metadata[key].tables,
        preserve_metadata=True).model_dump(mode='json', by_alias=True)
        for key, source in managed.sources.items()]
    state['report_data_shapes'] = []
    state['report_data_shape_issues'] = []
    state['report_configuration_warnings'] = [{'code': 'report_registered_output_profile',
        'sourceId': key, 'message': '本次仅画像已登记计算输出，不表示业务明细、趋势或期间覆盖完整。'}
        for key in managed.sources]
    await runtime._apply_durable_command(context, ReportingCommand(name='freeze_delivery_format',
        commandId='adoption-delivery-format', payload={'deliveryFormat': envelope.delivery_format}))
    path = f'报表/智能分析/{execution.scope.run_id}/policy-adoption/analysis-preparation.json'
    files = {item['path']: FileIdentity.model_validate(item) for item in child.payload.get('artifacts', ())}
    registered = files.get(path)
    # 显式核对只接纳当前固定路径和精确字节身份，不自动信任遗留文件。
    if confirmed_preparation is not None:
        if confirmed_preparation.path != path or (registered is not None and registered != confirmed_preparation):
            raise ReportingError('report_policy_adoption_mismatch', '确认的准备文件与当前执行或已登记身份不一致。')
        await runtime._read_identity_bytes(execution.scope.workspace_key, confirmed_preparation)
    candidate = registered or confirmed_preparation
    step = StepInput(input='从新口径正式计算重新组织分析')
    if candidate is None:
        existing = await runtime.workspace_service.abatch_hash_files(execution.scope.workspace_key, [path])
        if any(not item.get('missing') for item in existing) or child.payload.get('detailedAnalysisPlan'):
            raise ReportingError('report_policy_adoption_preparation_unknown',
                '新分析准备尚未完整登记，请核对原执行，不能自动重新规划或覆盖。')
        await runtime.calculate_report_metrics(step, context)
    view = await runtime._metric_planning_context(context)
    handles = await runtime._registered_metric_dataset_handles(context)
    if not handles:
        raise ReportingError('report_analysis_context_unavailable',
            '新依据暂无可分析的已登记数据；问题保持未回答，不借用原报告数值。')
    await runtime.report_basis_service.restore_receipt_datasets(execution.scope.run_id,
        ManagementScope(execution.scope.database, execution.scope.company_id), user_id=execution.scope.user_id,
        thread_id=execution.scope.caller_thread_id, report_revision='initial', dataset_store=runtime.datasets,
        run_context=runtime._tool_context(context), workflow_scope=execution.scope)
    state['report_workflow_result'] = {'datasets': [item.public_dict() for item in handles],
        'revision': execution.output_revision - 1}
    state['report_dataset_lineage'] = [DatasetLineage(datasetId=item.dataset_id, sourceId=item.source_id,
        requirementId=item.requirement_id, sqlHash=item.sql_hash, rowCount=item.row_count,
        size=item.size, sha256=item.sha256, periodRoles=item.period_roles,
        queryWindowId=item.query_window_id).model_dump(mode='json', by_alias=True) for item in handles]
    execution_hash = canonical_sha256(execution.model_dump(mode='json', by_alias=True))
    planning_hash = canonical_sha256(view.model_dump(mode='json', by_alias=True))
    if candidate is not None:
        saved = await read_policy_adoption_analysis_preparation(
            runtime, execution, child, candidate, view, handles)
        state.update(saved.model_dump(mode='json', by_alias=True, exclude={'execution_sha256', 'planning_sha256'}))
        state['report_row_preserving_requirements'] = []
        state['report_request_context'] = {'originalGoal': envelope.report_goal, 'feedback': [],
            'questionSpecs': child.payload['questionSpecs']}
    else:
        await runtime.plan_data_scope(step, context)
        await runtime.generate_analysis_plan(step, context)
        await runtime.prepare_analysis_context(step, context)
        await runtime.generate_detailed_analysis_plan(step, context)
        saved = PolicyAdoptionAnalysis(execution_sha256=execution_hash, planning_sha256=planning_hash,
            **{field.alias: state[field.alias] for field in PolicyAdoptionAnalysis.model_fields.values() if field.alias})
        for identity in (saved.context_file, *(item.profile_file for item in saved.contexts)):
            await runtime._read_identity_bytes(execution.scope.workspace_key, identity)
            await runtime._apply_durable_command(context, ReportingCommand(name='record_artifact',
                commandId=f'adoption-analysis-dependency:{identity.path}:{identity.sha256}',
                payload={'artifact': identity.model_dump(mode='json', by_alias=True)}))
        identity = await runtime._write_immutable_artifact(execution.scope.workspace_key, path,
            json.dumps(saved.model_dump(mode='json', by_alias=True), ensure_ascii=False,
                sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
        await require_policy_adoption_execution(runtime, source_context, execution)
        await runtime._apply_durable_command(context, ReportingCommand(name='record_artifact',
            commandId=f'adoption-analysis-preparation:{identity.sha256}',
            payload={'artifact': identity.model_dump(mode='json', by_alias=True)}))
    runtime._assert_state_safe(state)
    if registered is None and confirmed_preparation is not None:
        # 所有持久计划、正式CSV和已登记依赖核验通过后才补登记；不执行任何模型或取数。
        await require_policy_adoption_execution(runtime, source_context, execution)
        await runtime._read_identity_bytes(execution.scope.workspace_key, confirmed_preparation)
        await runtime._apply_durable_command(context, ReportingCommand(name='record_artifact',
            commandId=f'adoption-analysis-preparation:{confirmed_preparation.sha256}',
            payload={'artifact': confirmed_preparation.model_dump(mode='json', by_alias=True)}))
    return context


async def run_policy_adoption_evidence(runtime, source_context, execution):
    """在新运行中委托原生分析Task；已完成任务按持久回执恢复。"""
    context = await prepare_policy_adoption_analysis(runtime, source_context, execution)
    await require_policy_adoption_execution(runtime, source_context, execution)
    # 初步规划中的明细需求没有物化；实际Task只使用正式计算，不能登记虚假的明细期间事实。
    context.session_state['report_data_requirements'] = []
    return await runtime.run_analysis_evidence(StepInput(input='执行新口径的已登记分析计划'), context)


async def prepare_policy_adoption_narrative(runtime, source_context, execution):
    """从已完成的新发现图谱规划章节；不重跑取数或分析Task。"""
    from .checkpoint import ReportingCheckpoint, payload_sha256

    context = await prepare_policy_adoption_analysis(runtime, source_context, execution)
    child = await require_policy_adoption_execution(runtime, source_context, execution)
    if not child.payload.get('workflowCheckpoint'):
        raise ReportingError('report_finding_graph_unavailable', '新口径分析证据尚未完成，不能规划章节。')
    checkpoint = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
    if checkpoint.revision != execution.output_revision or checkpoint.finding_graph_file is None:
        raise ReportingError('report_policy_adoption_mismatch', '章节规划必须采用当前新修订的发现图谱。')
    outline = ReportOutline.model_validate(child.payload.get('approvedOutline'))
    state = context.session_state
    state['report_outline'] = outline.model_dump(mode='json', by_alias=True)
    state['report_outline_hash'] = payload_sha256(state['report_outline'])
    state['report_data_requirements'] = []
    await runtime.generate_narrative_outline(StepInput(input='按新口径发现图谱规划章节'), context)
    return context


async def prepare_policy_adoption_document(runtime, source_context, execution, *,
        confirmed_job: FileIdentity | None = None):
    """把新CSV和最终提纲绑定到真实原生文档job；登记后只恢复原身份。"""
    if not set(execution.requested_outputs) <= {'pdf', 'docx'}:
        raise ReportingError('report_policy_adoption_mismatch', '文档准备只接受已确认的PDF/Word交付。')
    context = await prepare_policy_adoption_narrative(runtime, source_context, execution)
    child = await require_policy_adoption_execution(runtime, source_context, execution)
    state = context.session_state
    outline = ReportOutline.model_validate(state['report_outline'])
    execution_hash = canonical_sha256(execution.model_dump(mode='json', by_alias=True))
    path = f'报表/智能分析/{execution.scope.run_id}/policy-adoption/document-job.json'
    registered = next((FileIdentity.model_validate(item) for item in child.payload.get('artifacts', ())
        if item['path'] == path), None)
    if confirmed_job is not None:
        if confirmed_job.path != path or (registered is not None and registered != confirmed_job):
            raise ReportingError('report_policy_adoption_mismatch', '确认的文档job与当前执行或已登记身份不一致。')
        await runtime._read_identity_bytes(execution.scope.workspace_key, confirmed_job)
    candidate = registered or confirmed_job
    tool_context = runtime._tool_context(context)
    result = state['report_workflow_result']
    if candidate is not None:
        saved = await runtime._read_identity_model(execution.scope.workspace_key, candidate, PolicyAdoptionDocumentJob)
        if saved.execution_sha256 != execution_hash or saved.outline_sha256 != state['report_outline_hash']:
            raise ReportingError('report_policy_adoption_mismatch', '文档job与新执行或最终提纲不一致。')
        runtime.report_tools._store_job(saved.job, tool_context)
        job = runtime.report_tools._load_job(saved.job['jobId'], tool_context)
        expected = {(item['path'], item['size'], item['sha256']) for item in result['datasets']}
        actual = {(item['path'], item['size'], item['sha256']) for item in job['sources']}
        if actual != expected or len(job['sources']) != len(expected):
            raise ReportingError('report_policy_adoption_mismatch', '文档job必须仅使用当前新依据的CSV。')
        state['report_document_generated_date'] = job['_documentContext']['generatedDate']
    else:
        existing = await runtime.workspace_service.abatch_hash_files(execution.scope.workspace_key, [path])
        if any(not item.get('missing') for item in existing):
            raise ReportingError('report_policy_adoption_preparation_unknown', '文档job尚未完整登记，不能自动覆盖。')
        prepared = await runtime.report_tools.report_prepare_dataset(
            [item['datasetId'] for item in result['datasets']], run_context=tool_context)
        job_id = prepared['jobId']
        await runtime.report_tools.bind_page_layout(job_id,
            runtime.delivery_settings.page_layout.model_dump(mode='json', by_alias=True), run_context=tool_context)
        await runtime._bind_report_document_context(context, outline=outline, job_id=job_id)
        job = runtime.report_tools._load_job(job_id, tool_context)
        saved = PolicyAdoptionDocumentJob(execution_sha256=execution_hash,
            outline_sha256=state['report_outline_hash'], job=job)
        identity = await runtime._write_immutable_artifact(execution.scope.workspace_key, path,
            json.dumps(saved.model_dump(mode='json'), ensure_ascii=False, sort_keys=True,
                separators=(',', ':'), allow_nan=False).encode())
        await require_policy_adoption_execution(runtime, source_context, execution)
        await runtime._apply_durable_command(context, ReportingCommand(name='record_artifact',
            commandId=f'adoption-document-job:{identity.sha256}',
            payload={'artifact': identity.model_dump(mode='json', by_alias=True)}))
    await runtime._bind_report_document_context(context, outline=outline, job_id=job['jobId'])
    result.update({'jobId': job['jobId'], 'revision': execution.output_revision})
    runtime._assert_state_safe(state)
    if registered is None and confirmed_job is not None:
        await require_policy_adoption_execution(runtime, source_context, execution)
        await runtime._read_identity_bytes(execution.scope.workspace_key, confirmed_job)
        await runtime._apply_durable_command(context, ReportingCommand(name='record_artifact',
            commandId=f'adoption-document-job:{confirmed_job.sha256}',
            payload={'artifact': confirmed_job.model_dump(mode='json', by_alias=True)}))
    return context


async def run_policy_adoption_section(runtime, source_context, execution, *, section_code):
    """用新运行的冻结图谱构建原生章节Task；不借用父报告事实或章节。"""
    from ..delivery.acceptance import build_report_artifact_validation_context
    from ..delivery.artifacts_v1 import authoritative_citations
    from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
    from ..hospital_operation.findings import FindingGraph
    from ..hospital_operation.narrative_outline import NarrativeOutline
    from .checkpoint import ReportingCheckpoint

    context = await prepare_policy_adoption_document(runtime, source_context, execution)
    child = await require_policy_adoption_execution(runtime, source_context, execution)
    state = context.session_state
    outline = ReportOutline.model_validate(state['report_outline'])
    checkpoint = ReportingCheckpoint.model_validate(child.payload.get('workflowCheckpoint'))
    section = next((item for item in outline.sections if item.code == section_code), None)
    if section is None:
        raise ReportingError('report_policy_adoption_mismatch', '章节不属于当前新口径的最终提纲。')
    plan = DetailedAnalysisPlan.model_validate(state['report_detailed_analysis_plan'])
    view = await runtime._metric_planning_context(context)
    for identity in checkpoint.deterministic_fact_files.values():
        fact = await runtime._read_identity_model(execution.scope.workspace_key, identity, DeterministicAnalysisBundle)
        if fact.metric_context != view:
            raise ReportingError('report_policy_adoption_mismatch', '章节事实与新依据的正式计算不一致。')
    lineage = tuple(DatasetLineage.model_validate(item) for item in state['report_dataset_lineage'])
    citations = authoritative_citations(lineage)
    artifact = await runtime._build_reporting_artifact(context,
        analysis_ids=tuple(item.analysis_id for item in plan.analyses), detailed_plan=plan,
        fact_files=checkpoint.deterministic_fact_files, citation_bindings=citations, section_codes=(section_code,))
    graph = await runtime._read_identity_model(execution.scope.workspace_key, checkpoint.finding_graph_file, FindingGraph)
    narrative = await runtime._read_identity_model(execution.scope.workspace_key, checkpoint.narrative_outline_file, NarrativeOutline)
    selected = next(item for item in narrative.sections if item.code == section_code)
    work_item = runtime._build_narrative_section_work_item(selected, graph=graph, detailed_plan=plan,
        analysis_artifact=artifact, citation_bindings=citations)
    validation = build_report_artifact_validation_context(
        expected_citations=tuple((item.citation_id, item.dataset_id, item.requirement_id, item.snapshot_hash) for item in citations),
        analysis_context_file=state['report_analysis_context_file'])
    validation_file = await runtime._write_immutable_artifact(execution.scope.workspace_key,
        f'报表/智能分析/{execution.scope.run_id}/policy-adoption/section.validation-context.json',
        json.dumps(validation, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    await runtime._apply_durable_command(context, ReportingCommand(name='record_artifact',
        commandId=f'adoption-section-validation:{validation_file.sha256}',
        payload={'artifact': validation_file.model_dump(mode='json', by_alias=True)}))
    allowed = selected.narrative_role != 'appendix'
    return await runtime._run_section_phase(context, checkpoint=checkpoint, revision=execution.output_revision,
        sandbox_id=execution.scope.workspace_key, validation_context_file=validation_file, work_item=work_item,
        analysis_rework_constraints=runtime._analysis_rework_constraints(detailed_plan=plan,
            profile_coverage=checkpoint.profile_coverage, analysis_ids=work_item.analysis_ids) if allowed else {},
        analysis_rework_allowed=allowed, degraded_rework=None)


async def assemble_policy_adoption_document(runtime, source_context, execution):
    """冻结新运行的完整分析产物，复用原生正文/表格/追溯装配。"""
    from ..delivery.artifacts_v1 import ReportArtifactManifest, authoritative_citations
    from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
    from .checkpoint import ReportingCheckpoint

    context = await prepare_policy_adoption_document(runtime, source_context, execution)
    child = await require_policy_adoption_execution(runtime, source_context, execution)
    checkpoint = ReportingCheckpoint.model_validate(child.payload.get('workflowCheckpoint'))
    state = context.session_state
    outline = ReportOutline.model_validate(state['report_outline'])
    view = await runtime._metric_planning_context(context)
    for identity in checkpoint.deterministic_fact_files.values():
        fact = await runtime._read_identity_model(execution.scope.workspace_key, identity, DeterministicAnalysisBundle)
        if fact.metric_context != view:
            raise ReportingError('report_policy_adoption_mismatch', '装配事实与新依据的正式计算不一致。')
    if checkpoint.pending_sections or {item.section_code for item in checkpoint.completed_sections} != {item.code for item in outline.sections}:
        raise ReportingError('report_section_artifact_missing', '新口径报告必须完成最终提纲的全部章节才能装配。')
    for section in checkpoint.completed_sections:
        await runtime._read_identity_bytes(execution.scope.workspace_key, section.artifact_file)
    if checkpoint.phase != 'completed':
        plan = DetailedAnalysisPlan.model_validate(state['report_detailed_analysis_plan'])
        lineage = tuple(DatasetLineage.model_validate(item) for item in state['report_dataset_lineage'])
        artifact = await runtime._build_reporting_artifact(context,
            analysis_ids=tuple(item.analysis_id for item in plan.analyses), detailed_plan=plan,
            fact_files=checkpoint.deterministic_fact_files, citation_bindings=authoritative_citations(lineage))
        identity = await runtime._write_immutable_artifact(execution.scope.workspace_key,
            f'报表/智能分析/{execution.scope.run_id}/policy-adoption/analysis-artifact.json',
            json.dumps(artifact.model_dump(mode='json', by_alias=True), ensure_ascii=False,
                sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
        await runtime._apply_durable_command(context, ReportingCommand(name='record_artifact',
            commandId=f'adoption-analysis-artifact:{identity.sha256}',
            payload={'artifact': identity.model_dump(mode='json', by_alias=True)}))
        checkpoint = runtime._update_reporting_checkpoint(checkpoint, phase='finalize',
            report_brief=artifact.report_brief, evidence_manifest=artifact.evidence_manifest,
            analysis_manifest_file=identity, profile_read_receipts=artifact.profile_read_receipts,
            files=runtime._merge_checkpoint_files(checkpoint.files, identity))
        await runtime._persist_reporting_checkpoint(context, checkpoint)
    await runtime.assemble_report(StepInput(input='装配新口径完整正文与追溯'), context)
    child = await require_policy_adoption_execution(runtime, source_context, execution)
    checkpoint = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
    result = state['report_workflow_result']
    identity = next(item for item in checkpoint.files if item.path == result['artifactManifestPath'])
    manifest = await runtime._read_identity_model(execution.scope.workspace_key, identity, ReportArtifactManifest)
    if (manifest.report_id != execution.scope.run_id or manifest.revision != execution.output_revision
            or manifest.report_basis_id != execution.basis_id):
        raise ReportingError('report_policy_adoption_mismatch', '新装配清单必须精确绑定新运行、修订及依据。')
    await runtime._read_identity_bytes(execution.scope.workspace_key,
        FileIdentity(path=manifest.markdown.path, size=manifest.markdown.size, sha256=manifest.markdown.sha256))
    await runtime.report_tools.complete_document_heading_numbers(result['jobId'],
        [item.model_dump(mode='json', by_alias=True) for item in manifest.heading_numbers],
        run_context=runtime._tool_context(context))
    for identity in checkpoint.files:
        await runtime._apply_durable_command(context, ReportingCommand(name='record_artifact',
            commandId=f'adoption-document-source:{canonical_sha256(identity.model_dump(mode="json"))}',
            payload={'artifact': identity.model_dump(mode='json', by_alias=True)}))
    return context


async def assemble_policy_adoption_slides(runtime, source_context, execution):
    """将新依据的发现和已生成证据交给原生幻灯片装配；不借用旧图。"""
    from ..delivery.artifacts_v1 import ReportArtifactManifest, authoritative_citations
    from .checkpoint import ReportingCheckpoint, payload_sha256

    child = await require_policy_adoption_execution(runtime, source_context, execution)
    if execution.requested_outputs != ('pptx',) or child.payload.get('deliveryFormat') != 'pptx':
        raise ReportingError('report_policy_adoption_mismatch', '幻灯片仅接受明确确认的PPTX交付。')
    checkpoint = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
    context = policy_adoption_run_context(execution)
    completed = child.payload.get('result', {})
    if completed.get('manifest') is not None:
        # complete已提交但检查点响应丢失时，核验实际文件后恢复，不重跑上游。
        for file in checkpoint.files:
            await runtime._read_identity_bytes(execution.scope.workspace_key, file)
        manifest_file = FileIdentity.model_validate(completed['manifest'])
        manifest = await runtime._read_identity_model(execution.scope.workspace_key, manifest_file, ReportArtifactManifest)
        if (manifest.report_id, manifest.revision, manifest.report_basis_id) != (
                execution.scope.run_id, execution.output_revision, execution.basis_id):
            raise ReportingError('report_policy_adoption_mismatch', '幻灯片完成清单与新运行依据不一致。')
        if checkpoint.phase != 'completed':
            checkpoint = runtime._update_reporting_checkpoint(checkpoint, phase='completed')
            await runtime._persist_reporting_checkpoint(context, checkpoint)
    else:
        context = await prepare_policy_adoption_narrative(runtime, source_context, execution)
        if checkpoint.analysis_manifest_file is None:
            plan = DetailedAnalysisPlan.model_validate(context.session_state['report_detailed_analysis_plan'])
            lineage = tuple(DatasetLineage.model_validate(item) for item in context.session_state['report_dataset_lineage'])
            artifact = await runtime._build_reporting_artifact(context,
                analysis_ids=tuple(item.analysis_id for item in plan.analyses), detailed_plan=plan,
                fact_files=checkpoint.deterministic_fact_files, citation_bindings=authoritative_citations(lineage))
            identity = await runtime._write_immutable_artifact(execution.scope.workspace_key,
                f'报表/智能分析/{execution.scope.run_id}/policy-adoption/analysis-artifact.json',
                json.dumps(artifact.model_dump(mode='json', by_alias=True), ensure_ascii=False,
                    sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
            checkpoint = runtime._update_reporting_checkpoint(checkpoint,
                report_brief=artifact.report_brief, evidence_manifest=artifact.evidence_manifest,
                analysis_manifest_file=identity, profile_read_receipts=artifact.profile_read_receipts,
                files=runtime._merge_checkpoint_files(checkpoint.files, identity))
            for file in checkpoint.files:
                await runtime._apply_durable_command(context, ReportingCommand(name='record_artifact',
                    commandId=f'adoption-slide-input:{canonical_sha256(file.model_dump(mode="json"))}',
                    payload={'artifact': file.model_dump(mode='json', by_alias=True)}))
            await runtime._persist_reporting_checkpoint(context, checkpoint)
        await runtime.generate_slide_outline(StepInput(input='新口径幻灯片提纲'), context)
        await runtime.assemble_slides(StepInput(input='装配新口径幻灯片及追溯'), context)
        child = await require_policy_adoption_execution(runtime, source_context, execution)
        checkpoint = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
        completed = child.payload['result']
        manifest = await runtime._read_identity_model(execution.scope.workspace_key,
            FileIdentity.model_validate(completed['manifest']), ReportArtifactManifest)
        if (manifest.report_id, manifest.revision, manifest.report_basis_id) != (
                execution.scope.run_id, execution.output_revision, execution.basis_id):
            raise ReportingError('report_policy_adoption_mismatch', '新幻灯片必须精确绑定新运行、修订及依据。')
    for file in checkpoint.files:
        await runtime._apply_durable_command(context, ReportingCommand(name='record_artifact',
            commandId=f'adoption-slide-output:{canonical_sha256(file.model_dump(mode="json"))}',
            payload={'artifact': file.model_dump(mode='json', by_alias=True)}))
    context.session_state['report_outline'] = child.payload['approvedOutline']
    context.session_state['report_outline_hash'] = payload_sha256(context.session_state['report_outline'])
    await runtime.generate_narrative_outline(StepInput(input='恢复冻结的新口径最终提纲'), context)
    context.session_state['report_workflow_result'] = {
        **completed, 'revision': execution.output_revision, 'deliveryFormat': 'pptx',
        'markdownPath': completed['markdown']['path'], 'artifactManifestPath': completed['manifest']['path']}
    return context


async def continue_policy_adoption_delivery(runtime, source_context, execution):
    """从可信新依据续跑原生阶段；有已登记交付时只恢复，不重算或重生成。"""
    from agno.workflow.types import StepOutput

    from .checkpoint import ReportingCheckpoint
    from .revision_execution import assemble_revision_workbook

    child = await require_policy_adoption_execution(runtime, source_context, execution)
    runtime.workspace_service.registry.resolve(execution.scope)
    outputs = execution.requested_outputs
    delivery = 'document' if set(outputs) <= {'pdf', 'docx'} else (
        'pptx' if outputs == ('pptx',) else 'xlsx' if outputs == ('xlsx',) else None)
    if delivery is None:
        raise ReportingError('report_policy_adoption_mismatch', '新口径交付必须保留明确选择的原交付类型。')
    root = 'document-render' if delivery == 'document' else 'slides' if delivery == 'pptx' else 'workbook'
    final_paths = {f'报表/智能分析/{execution.scope.run_id}/{root}/revision-{execution.output_revision}/report.{output}'
        for output in outputs}
    step = StepInput(input='继续已确认的新口径报告交付')
    if any(item.get('path') in final_paths for item in child.payload.get('artifacts', ())):
        return await runtime.publish_report(step, source_context, execution=execution)
    raw_checkpoint = child.payload.get('workflowCheckpoint')
    checkpoint = ReportingCheckpoint.model_validate(raw_checkpoint) if raw_checkpoint is not None else None
    if checkpoint is None or checkpoint.finding_graph_file is None:
        await run_policy_adoption_evidence(runtime, source_context, execution)
    context = await prepare_policy_adoption_narrative(runtime, source_context, execution)
    child = await require_policy_adoption_execution(runtime, source_context, execution)
    checkpoint = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
    outline = ReportOutline.model_validate(context.session_state['report_outline'])
    if checkpoint.phase != 'completed':
        if delivery == 'document':
            for section in outline.sections:
                _, _, rework = await run_policy_adoption_section(runtime, source_context, execution,
                    section_code=section.code)
                if rework is not None:
                    return StepOutput(content={'status': 'supplemental_evidence_required',
                        'revision': execution.output_revision,
                        'reworkRequest': rework.model_dump(mode='json', by_alias=True)})
            await assemble_policy_adoption_document(runtime, source_context, execution)
        elif delivery == 'pptx':
            await assemble_policy_adoption_slides(runtime, source_context, execution)
        else:
            await assemble_revision_workbook(runtime, source_context, execution)
    if delivery == 'document':
        rendered = await runtime._render_and_validate(source_context, execution=execution)
    else:
        renderer = runtime._render_pptx if delivery == 'pptx' else runtime._render_xlsx
        rendered = await renderer(source_context, {'revision': execution.output_revision}, outline, execution=execution)
    published = await runtime.publish_report(step, source_context, execution=execution)
    if rendered.get('validation', {}).get('ok') is False:
        # 同次执行中的验收/登记失败不得被随后只读恢复的有效回执抹去。
        content = dict(published.content)
        issues = list(content.get('validation', {}).get('issues', ()))
        for issue in rendered['validation'].get('issues', ()):
            if issue not in issues:
                issues.append(issue)
        content.update({'status': 'validation_failed',
            'validation': {**content.get('validation', {}), 'ok': False, 'issues': issues},
            'validationIssues': issues})
        return StepOutput(content=content)
    return published
