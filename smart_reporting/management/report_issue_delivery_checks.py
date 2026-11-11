"""只读核对原生新口径任务、成稿和最终文件，不渲染或签发下载链接。"""

from loguru import logger

from ..report_editor import ReportEditorContext
from ..report_editor.recalculation import PolicyAdoptionDeliveryResult, read_task_by_id
from ..reporting.delivery.artifacts_v1 import ReportArtifactManifest
from ..reporting.models import ReportingError
from ..reporting.trace.contracts_v1 import canonical_sha256
from ..reporting.workflow.checkpoint import FileIdentity
from ..reporting.workflow.policy_adoption import (
    PolicyAdoptionExecution,
    require_policy_adoption_execution,
)


async def check_adopted_delivery(runtime, adoption, scope, *, parent_run_id, user_id, thread_id, calculation=None):
    result = {'deliveryVerified': False, 'deliveryArtifacts': [], 'deliveryIssues': [],
        'factPresentationVerified': False, 'coveredFactIds': [], 'missingFactIds': [], 'contentIssues': []}
    if getattr(runtime, 'state_repository', None) is None or getattr(runtime, 'workspace_service', None) is None:
        result['deliveryIssues'].append({'code': 'management_issue_delivery_check_unavailable',
            'message': '尚未配置可信报告状态及文件服务，不能核对新报告交付。'})
        return result
    try:
        child = await runtime.state_repository.get(adoption.target_run_id)
        if child is None or not child.payload.get('reportPolicyAdoptionExecution'):
            raise ReportingError('management_issue_delivery_not_registered', '新依据已登记，但尚无可信的新报告执行。')
        execution = PolicyAdoptionExecution.model_validate(child.payload['reportPolicyAdoptionExecution'])
        source = execution.source_scope
        if ((source.run_id, source.user_id, source.caller_thread_id, source.database, source.company_id) != (
                parent_run_id, user_id, thread_id, scope.database, scope.company_id)
                or (execution.scope.run_id, execution.basis_id, execution.parent_basis_id, execution.registration_sha256) != (
                    adoption.target_run_id, adoption.basis_id, adoption.parent_basis_id,
                    canonical_sha256(adoption.model_dump(mode='json', by_alias=True)))):
            raise ReportingError('management_issue_delivery_identity_invalid', '新报告执行与原问题、采用登记或组织不一致。')
        from agno.run import RunContext
        context = RunContext(run_id=source.run_id, session_id=source.session_id, user_id=source.user_id,
            session_state={'report_workflow_scope': source.as_state()})
        child = await require_policy_adoption_execution(runtime, context, execution)
        runtime.workspace_service.registry.resolve(execution.scope)
        parent = await runtime.state_repository.get(source.run_id)
        raw_task = parent.payload.get('reportEditorRecalculations', {}).get(execution.request_id)
        if raw_task is None:
            raise ReportingError('management_issue_delivery_incomplete', '新报告尚未登记原修订下的完成任务。')
        editor_context = ReportEditorContext.model_validate(parent.payload['reportEditorContexts'][str(raw_task['request']['parentRevision'])])
        if (editor_context.workflow_run_id != parent_run_id or editor_context.scope != source.as_state()):
            raise ReportingError('management_issue_delivery_identity_invalid', '新报告任务的原编辑修订作用域不一致。')
        task = await read_task_by_id(runtime, editor_context, execution.request_id)
        if (task.status != 'completed' or not isinstance(task.result, PolicyAdoptionDeliveryResult)
                or task.result.execution != execution or child.payload.get('workflowCheckpoint', {}).get('phase') != 'completed'):
            raise ReportingError('management_issue_delivery_incomplete', '新报告的任务或成稿检查点尚未完成。')
        result.update(outputRevision=execution.output_revision, requestedOutputs=list(execution.requested_outputs),
            validationPassed=task.result.validation_passed, validationIssueCodes=list(task.result.issue_codes))
        registered = {item['path']: FileIdentity.model_validate(item) for item in child.payload.get('artifacts', ())}
        async def read(file):
            if registered.get(file.path) != file:
                raise ReportingError('management_issue_delivery_identity_invalid', '成稿或交付文件不在本次执行登记中。')
            return await runtime._read_identity_bytes(execution.scope.workspace_key, file, max_bytes=file.size)
        manifest_file = FileIdentity.model_validate(child.payload['result']['manifest'])
        manifest = ReportArtifactManifest.model_validate_json(await read(manifest_file))
        if (manifest.report_id, manifest.revision, manifest.report_basis_id) != (
                execution.scope.run_id, execution.output_revision, execution.basis_id):
            raise ReportingError('management_issue_delivery_identity_invalid', '成稿清单不属于本次新依据和输出修订。')
        markdown = (await read(FileIdentity(path=manifest.markdown.path, size=manifest.markdown.size, sha256=manifest.markdown.sha256))).decode()
        if calculation is not None:
            try:
                from ..reporting.trace.contracts_v1 import RevisionTraceIndexV1
                from ..reporting.trace.issue_content import evaluate_calculation_content

                trace_file = manifest.trace_index
                if trace_file is None:
                    raise ValueError('report trace index unavailable')
                trace_identity = FileIdentity(path=trace_file.path, size=trace_file.size, sha256=trace_file.sha256)
                index = RevisionTraceIndexV1.model_validate_json(await read(trace_identity))
                if (index.report_id, index.revision, index.report_basis_id) != (
                        manifest.report_id, manifest.revision, manifest.report_basis_id):
                    raise ValueError('report trace ownership mismatch')
                markdown_file = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
                if (markdown_file.path, markdown_file.sha256, markdown_file.size) != (
                        manifest.markdown.path, manifest.markdown.sha256, manifest.markdown.size):
                    raise ValueError('report trace markdown mismatch')
                sources = {}
                for entry in index.fact_files:
                    file = next(file for file in index.files if file.resource_id == entry.file_resource_id)
                    sources[file.resource_id] = await read(FileIdentity(path=file.path, size=file.size, sha256=file.sha256))
                result.update(evaluate_calculation_content(index, markdown, sources, calculation, report_revision=calculation.report_revision))
                if not result['factPresentationVerified']:
                    result['contentIssues'].append({'code': 'management_issue_report_fact_uncovered',
                        'message': '新报告正文或冻结附表尚未完整呈现本次回归的精确计算事实。'})
            except Exception as error:
                logger.warning('issue_report_content_unavailable error_type={}', type(error).__name__)
                result['contentIssues'].append({'code': 'management_issue_report_content_unavailable',
                    'message': '新报告计算事实到正文的追溯当前不可完整核对，文件下载不受影响。'})
        delivery = 'document-render' if set(execution.requested_outputs) <= {'pdf', 'docx'} else (
            'slides' if execution.requested_outputs == ('pptx',) else 'workbook')
        root = f'报表/智能分析/{execution.scope.run_id}/{delivery}/revision-{execution.output_revision}'
        by_path = {file.path: file for file in task.result.artifacts}
        for output in execution.requested_outputs:
            file = by_path.get(f'{root}/report.{output}')
            if file is None:
                result['deliveryIssues'].append({'code': 'management_issue_delivery_format_missing',
                    'message': f'请求的 {output.upper()} 尚未登记可核验交付文件。'})
                continue
            try:
                await read(file)
                result['deliveryArtifacts'].append({'format': output, **file.model_dump(mode='json', by_alias=True)})
            except Exception as error:
                logger.warning('issue_delivery_file_unavailable format={} error_type={}', output, type(error).__name__)
                result['deliveryIssues'].append({'code': 'management_issue_delivery_file_unavailable',
                    'message': f'{output.upper()} 文件当前不可读取或身份已变化。'})
        current = await require_policy_adoption_execution(runtime, context, execution)
        if current.state_version != child.state_version or (await runtime.state_repository.get(source.run_id)).state_version != parent.state_version:
            raise ReportingError('management_issue_delivery_changed', '核对期间报告状态发生变化，请重新检查。')
        result['deliveryVerified'] = not result['deliveryIssues']
    except Exception as error:
        result['factPresentationVerified'] = False
        logger.warning('issue_delivery_check_unavailable error_type={}', type(error).__name__)
        result['deliveryIssues'].append({'code': error.code if isinstance(error, ReportingError) else 'management_issue_delivery_check_unavailable',
            'message': error.message if isinstance(error, ReportingError) else '当前交付登记或文件无法完整核对，请先读取原任务状态。'})
    return result
