"""新口径依据的独立执行准备；不复制旧会话、计算、画像或检查点。"""

from typing import Literal

from agno.run import RunContext
from pydantic import Field

from ...management.models import ManagementScope
from ..contract import REPORT_WORKFLOW_SCOPE_STATE_KEY, SHA256_PATTERN, StrictModel
from ..models import ReportingError
from ..semantics.models import Identity
from ..semantics.policy_adoption import PolicyAdoptionRequestId
from ..trace.contracts_v1 import canonical_sha256
from .revision_execution import _source_scope, _source_state, load_revision_materials, copy_revision_materials
from .scope import (
    REPORT_WORKFLOW_SCOPE_DEPENDENCY,
    ReportingWorkflowScope,
    resolve_reporting_workflow_scope,
)
from .state import ReportingCommand


class PolicyAdoptionExecution(StrictModel):
    request_id: PolicyAdoptionRequestId = Field(alias='requestId')
    source_scope: ReportingWorkflowScope = Field(alias='sourceScope')
    scope: ReportingWorkflowScope
    parent_basis_id: Identity = Field(alias='parentBasisId')
    basis_id: Identity = Field(alias='basisId')
    registration_sha256: str = Field(alias='registrationSha256', pattern=SHA256_PATTERN)
    output_revision: int = Field(alias='outputRevision', ge=2)
    requested_outputs: tuple[Literal['pdf', 'docx', 'pptx', 'xlsx'], ...] = Field(alias='requestedOutputs', min_length=1, max_length=4)


def _target_scope(source, target_run_id):
    return resolve_reporting_workflow_scope(run_id=target_run_id, session_id=target_run_id, user_id=source.user_id,
        dependencies={REPORT_WORKFLOW_SCOPE_DEPENDENCY: {'database': source.database, 'companyId': source.company_id,
            'threadId': source.caller_thread_id, 'userId': source.user_id}})


async def _registration(runtime, source, request_id):
    scope = ManagementScope(source.database, source.company_id)
    service = runtime.report_basis_service
    adoption = await service.read_policy_adoption(source.run_id, scope, user_id=source.user_id,
        thread_id=source.caller_thread_id, request_id=request_id)
    if adoption is None:
        raise ReportingError('report_policy_adoption_unavailable', '新口径确认尚未登记。')
    basis = await service.load_report_basis(adoption.target_run_id, scope, user_id=source.user_id,
        thread_id=source.caller_thread_id)
    return adoption, basis


async def prepare_policy_adoption_execution(runtime, run_context, *, request_id):
    from ...report_editor.revisions import apply_editor_command

    source = _source_scope(runtime, run_context)
    state, registered = await _source_state(runtime, source)
    adoption, basis = await _registration(runtime, source, request_id)
    await runtime.report_basis_service.register_adoption_selections(source.run_id,
        ManagementScope(source.database, source.company_id), user_id=source.user_id,
        thread_id=source.caller_thread_id, request_id=request_id)
    target = _target_scope(source, adoption.target_run_id)
    materials = await load_revision_materials(runtime, source, state)
    runtime.workspace_service.registry.resolve(target)
    await copy_revision_materials(runtime, source, target, materials)
    reservation = await apply_editor_command(runtime.state_repository, source.run_id, ReportingCommand(
        name='reserve_report_editor_revision', commandId=target.run_id,
        payload={'minimumRevision': state.revision, 'reservationKey': target.run_id}))
    execution = PolicyAdoptionExecution(requestId=request_id, sourceScope=source, scope=target,
        parentBasisId=adoption.parent_basis_id, basisId=basis.id,
        registrationSha256=canonical_sha256(adoption.model_dump(mode='json', by_alias=True)),
        outputRevision=reservation.state.payload['reportEditorRevisionReservations'][target.run_id],
        requestedOutputs=basis.request_summary.requested_outputs)
    from ...preferences.runtime import inherit_execution_preferences

    await inherit_execution_preferences(runtime, source, target.run_id, 'policy_adoption')
    await runtime.state_repository.register_run(report_run_id=target.run_id, external_run_id=target.external_run_id,
        entrypoint='policy_adoption', workflow_id=registered['workflow_id'], agno_session_id=target.session_id,
        agno_run_id=target.run_id, caller_session_id=source.session_id, caller_run_id=source.run_id,
        thread_id=target.caller_thread_id, owner_user_id=target.user_id, database=target.database,
        company_id=target.company_id, revision=execution.output_revision, status='pending')
    await runtime.state_repository.get_or_create(report_run_id=target.run_id, external_run_id=target.external_run_id,
        thread_id=target.caller_thread_id, owner_user_id=target.user_id, revision=execution.output_revision,
        payload={'reportPolicyAdoptionExecution': execution.model_dump(mode='json', by_alias=True), 'requestMaterials': materials})
    await require_policy_adoption_execution(runtime, run_context, execution)
    runtime.workspace_service.registry.resolve(target)
    return execution


async def require_policy_adoption_execution(runtime, run_context, execution, *, restore_only=False):
    source = _source_scope(runtime, run_context)
    parent, _ = await _source_state(runtime, source)
    adoption, basis = await _registration(runtime, source, execution.request_id)
    child = await runtime.state_repository.get(execution.scope.run_id)
    registered = await runtime.state_repository.get_run(execution.scope.run_id)
    if (execution.source_scope != source or execution.scope != _target_scope(source, adoption.target_run_id)
            or execution.parent_basis_id != adoption.parent_basis_id or execution.basis_id != basis.id
            or execution.requested_outputs != basis.request_summary.requested_outputs
            or execution.registration_sha256 != canonical_sha256(adoption.model_dump(mode='json', by_alias=True))
            or parent.payload.get('reportEditorRevisionReservations', {}).get(execution.scope.run_id) != execution.output_revision
            or child is None or registered is None
            or child.payload.get('reportPolicyAdoptionExecution') != execution.model_dump(mode='json', by_alias=True)
            or (child.external_run_id, child.thread_id, child.owner_user_id, child.revision) != (
                execution.scope.external_run_id, source.caller_thread_id, source.user_id, execution.output_revision)
            or (registered['entrypoint'], registered['caller_run_id'], registered['caller_session_id'],
                registered['agno_session_id'], registered['database'], registered['company_id'], registered['revision'],
                registered['external_run_id'], registered['agno_run_id'], registered['owner_user_id'], registered['thread_id']) != (
                    'policy_adoption', source.run_id, source.session_id, execution.scope.session_id,
                    source.database, source.company_id, execution.output_revision, execution.scope.external_run_id,
                    execution.scope.run_id, source.user_id, source.caller_thread_id)):
        raise ReportingError('report_policy_adoption_mismatch', '新口径执行与可信依据、父运行或编号不一致。')
    return child


def policy_adoption_run_context(execution):
    return RunContext(run_id=execution.scope.run_id, session_id=execution.scope.session_id,
        user_id=execution.scope.user_id, session_state={REPORT_WORKFLOW_SCOPE_STATE_KEY: execution.scope.as_state()})
