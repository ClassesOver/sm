"""修订影响沿冻结事实身份传播，人工改数不覆盖原计算。"""

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_report_editor_trace import _context, _make_editor, _scope


async def dependency_index(tmp_path):
    editor, _, workspace = await _make_editor(tmp_path, with_fact_file=True, with_drilldown=True,
        with_chart_trace=True, with_computation=True)
    workspace.registry.resolve(_scope())
    index = await editor.trace.require_index(_context())
    original = index.subject_bindings[0].fact_refs[0]
    computation = index.computations[0].model_copy(update={'input_fact_refs': (original,)})
    output = computation.output_fact_refs[0]
    chart = index.chart_traces[0].model_copy(update={'fact_refs': (output,), 'computation_id': computation.computation_id})
    derived = index.subject_bindings[0].model_copy(update={'subject_id': 'sub-' + 'd' * 16,
        'claim_id': 'derived-claim', 'fact_refs': (output,)})
    return type(index).model_validate({**dict(index), 'computations': (computation,),
        'chart_traces': (chart,), 'subject_bindings': (*index.subject_bindings, derived)})


@pytest.mark.anyio
@pytest.mark.parametrize('operation', ['text_edit', 'manual_override'])
async def test_text_or_manual_change_does_not_invalidate_frozen_fact_or_unchanged_chart(tmp_path, operation):
    from smart_reporting.reporting.trace.revision_impact import (
        RevisionChange,
        assess_revision_impact,
    )

    index = await dependency_index(tmp_path)
    change = RevisionChange(basisId=index.report_basis_id, parentRevision=index.revision, operation=operation,
        subjectIds=(index.subject_bindings[0].subject_id,))
    impact = assess_revision_impact(index, change)
    assert not impact.fact_refs
    assert [item.subject_id for item in impact.subjects] == [index.subject_bindings[0].subject_id]
    assert impact.subjects[0].status == ('manual_override' if operation == 'manual_override' else 'support_review_required')
    assert not any(item.kind == 'chart' for item in impact.artifacts)
    assert impact.exports_status == 'stale'
    assert index.computations[0].verification != 'manual_override'


@pytest.mark.anyio
async def test_changed_fact_invalidates_transitive_conclusions_chart_and_exports(tmp_path):
    from smart_reporting.reporting.trace.revision_impact import (
        RevisionChange,
        assess_revision_impact,
    )

    index = await dependency_index(tmp_path)
    original = index.subject_bindings[0].fact_refs[0]
    impact = assess_revision_impact(index, RevisionChange(basisId=index.report_basis_id, parentRevision=index.revision,
        operation='refresh_data', factRefs=(original,)))
    assert set(impact.fact_refs) == {original, index.computations[0].output_fact_refs[0]}
    assert {item.subject_id for item in impact.subjects} == {item.subject_id for item in index.subject_bindings}
    assert all(item.status == 'stale' for item in impact.subjects)
    assert any(item.kind == 'chart' and item.artifact_id == index.chart_traces[0].chart_id for item in impact.artifacts)
    assert impact.exports_status == 'stale'


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['basis', 'revision', 'subject', 'fact'])
async def test_impact_cannot_reference_another_basis_revision_or_unregistered_object(tmp_path, fault):
    from smart_reporting.reporting.trace.revision_impact import (
        RevisionChange,
        assess_revision_impact,
    )

    index = await dependency_index(tmp_path)
    values = dict(basisId=index.report_basis_id, parentRevision=index.revision, operation='text_edit',
        subjectIds=(index.subject_bindings[0].subject_id,))
    if fault == 'basis':
        values['basisId'] = 'foreign'
    elif fault == 'revision':
        values['parentRevision'] += 1
    elif fault == 'subject':
        values['subjectIds'] = ('sub-' + 'f' * 16,)
    else:
        values.update(operation='refresh_data', subjectIds=(), factRefs=(index.subject_bindings[0].fact_refs[0].model_copy(
            update={'fact_key': 'foreign-fact'}),))
    with pytest.raises(ReportingError):
        assess_revision_impact(index, RevisionChange(**values))


@pytest.mark.anyio
@pytest.mark.parametrize('edit', ['text_edit', 'manual_override'])
@pytest.mark.parametrize('impact_failure', [False, True])
async def test_actual_editor_reports_native_change_impact_without_reusing_support(tmp_path, edit, impact_failure, monkeypatch):
    import hashlib

    from smart_reporting.report_editor import ReportEditorContext, ReportEditorService
    from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs
    from smart_reporting.reporting.trace.semantic_bindings import (
        NumberReferenceResolver,
        bound_number_display,
    )

    runtime, arguments, scope, durable, _, _, contents, index = await native_quality_inputs(tmp_path, publication_fixture=True)
    await runtime.issue_http_publication(**arguments)
    runtime.workspace_registry.resolve(scope)
    editor = ReportEditorService(state_repository=runtime.state_repository, workspace_registry=runtime.workspace_registry,
        workspace=runtime.workspace_service)
    context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
    file = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    markdown = contents[file.path].decode()
    if edit == 'manual_override':
        number = index.subject_bindings[0].number_reference
        fact_file = next(file for file in index.files if file.resource_id == index.fact_files[0].file_resource_id)
        selected = NumberReferenceResolver((contents[fact_file.path].decode(),)).resolve(number.token)
        shown = bound_number_display(markdown, number.claim_id, selected)
        markdown = markdown[:shown.start] + '999999999元' + markdown[shown.start + len(shown.text):]
    else:
        markdown = markdown.replace('预算合计', '预算合计（已润色）')
    if impact_failure:
        from smart_reporting.reporting.trace import revision_impact

        def unavailable(*args, **kwargs):
            raise OSError('impact unavailable')

        monkeypatch.setattr(revision_impact, 'assess_revision_impact', unavailable)
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    if impact_failure:
        assert result['revisionImpactIssues'] == ['revision_impact_unavailable']
        assert result['quality']['claimSupport'][0]['supportStatus'] == 'unverified'
        assert not result['revisionImpacts']
        return
    impact, = result['revisionImpacts']
    assert impact['operation'] == edit
    assert impact['factRefs'] == []
    assert impact['exportsStatus'] == 'stale'
    assert impact['subjects'][0]['status'] == ('manual_override' if edit == 'manual_override' else 'support_review_required')
    assert result['subjects'][0]['editStatus'] == impact['subjects'][0]['status']
    assert result['quality']['claimSupport'][0]['supportStatus'] == 'unverified'
    assert contents[file.path].decode() != markdown


@pytest.mark.anyio
async def test_snapshot_verification_does_not_pretend_to_refresh_data(tmp_path):
    from smart_reporting.reporting.trace.revision_impact import (
        RevisionChange,
        assess_revision_impact,
    )

    index = await dependency_index(tmp_path)
    impact = assess_revision_impact(index, RevisionChange(basisId=index.report_basis_id,
        parentRevision=index.revision, operation='verify_snapshot'))
    assert not impact.fact_refs and not impact.subjects and not impact.artifacts
    assert impact.exports_status == 'unaffected'
    assert impact.issue_codes == ('snapshot_verification_pending',)


@pytest.mark.anyio
async def test_multi_level_dependency_order_and_table_impact_use_exact_fact_identity(tmp_path):
    from smart_reporting.reporting.trace.contracts_v1 import TableCellBindingV1, TableTraceV1
    from smart_reporting.reporting.trace.revision_impact import (
        RevisionChange,
        assess_revision_impact,
    )

    index = await dependency_index(tmp_path)
    first = index.computations[0]
    output = first.output_fact_refs[0]
    final = output.model_copy(update={'analysis_id': 'analysis_999', 'fact_key': 'derived-final'})
    second = first.model_copy(update={'computation_id': 'comp-' + 'e' * 16,
        'input_fact_refs': (output,), 'output_fact_refs': (final,)})
    same_key = final.model_copy(update={'json_pointer': '/another-value'})
    table = TableTraceV1(tableId='impact-table', rowKeys=('r1',), columnKeys=('c1',),
        cells=(TableCellBindingV1(rowKey='r1', columnKey='c1', factRefs=(final,)),))
    other = table.model_copy(update={'table_id': 'unaffected-table',
        'cells': (table.cells[0].model_copy(update={'fact_refs': (same_key,)}),)})
    index = index.model_copy(update={'computations': (second, first), 'tables': (table, other)})
    impact = assess_revision_impact(index, RevisionChange(basisId=index.report_basis_id, parentRevision=index.revision,
        operation='refresh_data', factRefs=first.input_fact_refs))
    assert final in impact.fact_refs and same_key not in impact.fact_refs
    assert [item.artifact_id for item in impact.artifacts if item.kind == 'table'] == ['impact-table']


@pytest.mark.anyio
async def test_policy_adoption_requires_a_distinct_explicit_basis(tmp_path):
    from pydantic import ValidationError

    from smart_reporting.reporting.trace.revision_impact import RevisionChange

    index = await dependency_index(tmp_path)
    values = dict(basisId=index.report_basis_id, parentRevision=index.revision,
        operation='adopt_policy', factRefs=index.computations[0].input_fact_refs)
    for target in (None, index.report_basis_id):
        with pytest.raises(ValidationError):
            RevisionChange(**values, targetBasisId=target)
    assert RevisionChange(**values, targetBasisId='new-basis').target_basis_id == 'new-basis'
