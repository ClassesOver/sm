"""修订影响只沿可信索引中的精确依赖传播，不改变任何冻结事实。"""

from typing import Literal

from pydantic import Field, model_validator

from ..contract import StrictModel
from ..models import ReportingError
from .contracts_v1 import FactRefV1, RevisionTraceIndexV1


class RevisionChange(StrictModel):
    basis_id: str = Field(alias='basisId', min_length=1)
    parent_revision: int = Field(alias='parentRevision', ge=1)
    operation: Literal['text_edit', 'manual_override', 'verify_snapshot', 'refresh_data', 'adopt_policy']
    subject_ids: tuple[str, ...] = Field(default=(), alias='subjectIds', max_length=20000)
    fact_refs: tuple[FactRefV1, ...] = Field(default=(), alias='factRefs', max_length=20000)
    target_basis_id: str | None = Field(default=None, alias='targetBasisId', min_length=1)

    @model_validator(mode='after')
    def explicit_change(self):
        if len(set(self.subject_ids)) != len(self.subject_ids) or len(set(self.fact_refs)) != len(self.fact_refs):
            raise ValueError('修订影响对象不能重复')
        if self.operation in {'text_edit', 'manual_override'}:
            if not self.subject_ids or self.fact_refs or self.target_basis_id:
                raise ValueError('正文修改必须指定声明，不能声称改变冻结事实或依据')
        elif self.subject_ids:
            raise ValueError('复核与重算以冻结事实定位，不能只指定正文声明')
        if self.operation == 'verify_snapshot' and (self.fact_refs or self.target_basis_id):
            raise ValueError('快照复核不能宣称已改变事实或规则')
        if self.operation in {'refresh_data', 'adopt_policy'} and not self.fact_refs:
            raise ValueError('重算影响必须明确指定原事实身份')
        if self.operation == 'adopt_policy':
            if not self.target_basis_id or self.target_basis_id == self.basis_id:
                raise ValueError('采用新规则必须登记不同的新依据')
        elif self.target_basis_id:
            raise ValueError('仅采用新规则可以改变依据身份')
        return self


class SubjectRevisionImpact(StrictModel):
    subject_id: str = Field(alias='subjectId')
    status: Literal['support_review_required', 'manual_override', 'stale']
    reason: str


class ArtifactRevisionImpact(StrictModel):
    kind: Literal['markdown', 'chart', 'table']
    artifact_id: str = Field(alias='artifactId')
    status: Literal['stale'] = 'stale'
    reason: str


class RevisionImpact(StrictModel):
    basis_id: str = Field(alias='basisId')
    parent_revision: int = Field(alias='parentRevision')
    operation: str
    fact_refs: tuple[FactRefV1, ...] = Field(default=(), alias='factRefs')
    subjects: tuple[SubjectRevisionImpact, ...] = ()
    artifacts: tuple[ArtifactRevisionImpact, ...] = ()
    exports_status: Literal['unaffected', 'stale'] = Field(alias='exportsStatus')
    issue_codes: tuple[str, ...] = Field(default=(), alias='issueCodes')


def assess_revision_impact(previous_basis: RevisionTraceIndexV1, revision_change: RevisionChange) -> RevisionImpact:
    """previous_basis是上一修订的冻结依据身份及依赖索引；本函数不执行或确认重算。"""
    index, change = previous_basis, revision_change
    if change.basis_id != index.report_basis_id or change.parent_revision != index.revision:
        raise ReportingError('request_invalid', '修订影响请求与原报告依据或修订不一致。')
    subjects = {item.subject_id: item for item in index.subject_bindings}
    registered = {ref for item in index.subject_bindings for ref in item.fact_refs}
    registered.update(ref for computation in index.computations for ref in (*computation.input_fact_refs, *computation.output_fact_refs))
    registered.update(ref for chart in index.chart_traces for ref in chart.fact_refs)
    registered.update(ref for table in index.tables for cell in table.cells for ref in cell.fact_refs)
    if set(change.subject_ids) - subjects.keys() or set(change.fact_refs) - registered:
        raise ReportingError('source_missing', '修订影响对象不属于本修订登记依赖。')
    changed = set(change.fact_refs)
    computations = set()
    # 单调扩展到固定点，覆盖任意登记顺序及多层派生，不以同名fact或相同数值串联。
    while True:
        previous = len(changed), len(computations)
        for record in index.computations:
            if set(record.input_fact_refs) & changed or set(record.output_fact_refs) & changed:
                computations.add(record.computation_id)
                changed.update(record.output_fact_refs)
        if previous == (len(changed), len(computations)):
            break
    reason = {'text_edit': 'statement_changed', 'manual_override': 'manual_value_override',
        'verify_snapshot': 'snapshot_verification_pending', 'refresh_data': 'calculation_batch_changed',
        'adopt_policy': 'report_basis_changed'}[change.operation]
    affected_subjects = [SubjectRevisionImpact(subjectId=item.subject_id,
        status='manual_override' if change.operation == 'manual_override' else
            'support_review_required' if change.operation == 'text_edit' else 'stale', reason=reason)
        for item in index.subject_bindings if item.subject_id in change.subject_ids
            or set(item.fact_refs) & changed or item.computation_id in computations]
    artifacts = []
    for chart in index.chart_traces:
        if set(chart.fact_refs) & changed or chart.computation_id in computations:
            artifacts.append(ArtifactRevisionImpact(kind='chart', artifactId=chart.chart_id, reason=reason))
    for table in index.tables:
        if any(set(cell.fact_refs) & changed or cell.computation_id in computations for cell in table.cells):
            artifacts.append(ArtifactRevisionImpact(kind='table', artifactId=table.table_id, reason=reason))
    if affected_subjects or artifacts or changed:
        artifacts.append(ArtifactRevisionImpact(kind='markdown', artifactId=index.markdown_file_resource_id, reason=reason))
    return RevisionImpact(basisId=index.report_basis_id, parentRevision=index.revision, operation=change.operation,
        factRefs=tuple(sorted(changed, key=lambda ref: (ref.analysis_id, ref.file_resource_id, ref.json_pointer, ref.fact_key or ''))),
        subjects=tuple(affected_subjects), artifacts=tuple(artifacts), exportsStatus='stale' if artifacts else 'unaffected',
        issueCodes=('snapshot_verification_pending',) if change.operation == 'verify_snapshot' else ())
