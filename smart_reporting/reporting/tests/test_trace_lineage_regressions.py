"""跨分析来源身份、缺失分组、共同对账期间和日粒度正文引用的回归。"""

import hashlib
import json
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.contracts_v1 import FactRefV1, derive_resource_id
from smart_reporting.reporting.trace.fact_index import (
    assign_fact_ids,
    derived_fact_identity,
    fact_input_relations,
)
from smart_reporting.reporting.trace.fact_service import resolve_fact
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin

from .test_deterministic_analysis import analysis, context, semantic
from .test_deterministic_reconciliation_edges import dataset, metrics, reconcile
from .test_trace_server_tables import _Harness


def _daily_bundle(rows, *, stock=False, monthly=False):
    measure = semantic('amount', unit='元')
    if stock:
        measure['additiveAcross'] = ['department']
    ctx = context('current', semantics=(measure,)).model_copy(update={
        'period_granularities': {'month': 'month' if monthly else 'date'},
    })
    item = analysis().model_copy(update={'series_granularity': 'month' if monthly else 'day'})
    content = ('month,department,amount\n' + rows).encode()
    return build_deterministic_analysis_bundle(item, (dataset('current', content, ctx),))


@pytest.mark.parametrize('statement,selector,expected,periods', [
    ('2025年1月2日收入为', 'periodValues.1', 20, ('2025-01-02',)),
    ('2025年1月2号收入为', 'periodValues.1', 20, ('2025-01-02',)),
    ('2025年1月2日收入为', 'total', 20, ('2025-01-02',)),
    ('2025年1月1日至2日收入为', 'total', 30, ('2025-01-01', '2025-01-02')),
    ('2025年1月1—2日收入为', 'total', 30, ('2025-01-01', '2025-01-02')),
])
def test_daily_prose_keeps_or_corrects_exact_registered_period(statement, selector, expected, periods):
    bundle = _daily_bundle('2025-01-01,A,10\n2025-01-02,A,20\n')
    frozen = [bundle.model_dump_json(by_alias=True)]
    token = '{{value:' + bundle.metrics[0].fact_id + ':' + selector + ':元}}'
    text, refs, notices = render_bound_numbers(statement + token, frozen, key='day',
                                              field_definitions={'amount': '收入'})
    assert text == statement + f'{expected}元'
    assert len(refs) == 1 and not notices
    selected = resolve_number_reference(refs[0].token, frozen)
    assert selected['value'] == expected and selected['periods'] == periods


@pytest.mark.parametrize('statement', [
    '2025年1月3日收入为', '2025年2月30日收入为', '2025年13月2日收入为',
    '2025年1月2日至1日收入为', '2025年1月1日至3日收入为',
])
def test_unavailable_daily_window_never_borrows_month_or_another_day(statement):
    bundle = _daily_bundle('2025-01-01,A,10\n2025-01-02,A,20\n')
    token = '{{value:' + bundle.metrics[0].fact_id + ':periodValues.1:元}}'
    text, refs, notices = render_bound_numbers(statement + token, [bundle.model_dump_json(by_alias=True)],
                                              key='unavailable', field_definitions={'amount': '收入'})
    assert '待核实' in text and not refs and notices


def test_month_total_is_not_a_daily_bucket_even_on_month_start():
    bundle = _daily_bundle('2025-01,A,100\n2025-02,A,200\n', monthly=True)
    token = '{{value:' + bundle.metrics[0].fact_id + ':periodValues.0:元}}'
    _, refs, notices = render_bound_numbers('2025年1月1日收入为' + token,
        [bundle.model_dump_json(by_alias=True)], key='month-not-day', field_definitions={'amount': '收入'})
    assert not refs and notices


def test_cross_year_daily_stock_window_uses_its_endpoint():
    bundle = _daily_bundle('2024-12-31,A,10\n2025-01-01,A,20\n', stock=True)
    token = '{{value:' + bundle.metrics[0].fact_id + ':total:元}}'
    frozen = [bundle.model_dump_json(by_alias=True)]
    text, refs, notices = render_bound_numbers('2024年12月31日至2025年1月1日资金余额为' + token,
        frozen, key='daily-stock', field_definitions={'amount': '资金余额'})
    assert text.endswith('20元') and len(refs) == 1 and not notices
    assert resolve_number_reference(refs[0].token, frozen)['periods'] == ('2025-01-01',)


@pytest.mark.parametrize('left_a,right_a,passed', [
    ('0', '0', True), ('', '0', False), ('0', '', False), ('', '', False),
    ('invalid', '0', False), ('0', 'invalid', False),
])
def test_reconciliation_preserves_missing_numeric_groups(left_a, right_a, passed):
    content = (f'month,department,actual,ledger\n2025-01,A,{left_a},{right_a}\n'
               '2025-01,B,100,100\n').encode()
    ctx = context('current', fields=('month', 'department', 'actual', 'ledger'),
                  semantics=(semantic('actual'), semantic('ledger')))
    check = reconcile((dataset('current', content, ctx),)).reconciliations[0]
    assert check.passed is passed
    assert check.checked_group_count == 2
    assert check.failed_group_count == (0 if passed else 1)
    assert check.left_total == check.right_total == 100
    assert bool(check.warnings) is not passed


@pytest.mark.parametrize('missing_side', ['actual', 'ledger'])
def test_absent_reconciliation_group_is_unknown_instead_of_zero(missing_side):
    entries = []
    for field in ('actual', 'ledger'):
        rows = '2025-01,B,100\n' + ('' if field == missing_side else '2025-01,A,0\n')
        ctx = context(field, fields=('month', 'department', field), semantics=(semantic(field),))
        entries.append(dataset(field, (f'month,department,{field}\n' + rows).encode(), ctx))
    check = reconcile(tuple(entries)).reconciliations[0]
    assert not check.passed and check.failed_group_count == 1
    assert check.checked_group_count == 2 and check.warnings


@pytest.mark.parametrize('aggregation', ['count', 'count_distinct'])
def test_declared_count_of_null_values_is_still_a_real_zero(aggregation):
    content = b'month,department,actual,ledger\n2025-01,A,,\n2025-01,B,x,x\n'
    ctx = context('current', fields=('month', 'department', 'actual', 'ledger'),
                  semantics=(semantic('actual', aggregation), semantic('ledger', aggregation)))
    check = reconcile((dataset('current', content, ctx),)).reconciliations[0]
    assert check.passed and check.checked_group_count == 2 and not check.warnings


@pytest.mark.parametrize('right_period', ['2025-01', '2025-02', '2024-01', 'not-a-date'])
def test_reconciliation_checks_calendar_periods_instead_of_only_role(right_period):
    entries = []
    for field, period in (('actual', '2025-01'), ('ledger', right_period)):
        ctx = context(field, fields=('month', 'department', field), semantics=(semantic(field),))
        entries.append(dataset(field, f'month,department,{field}\n{period},A,100\n'.encode(), ctx))
    bundle = reconcile(tuple(entries))
    if right_period == '2025-01':
        assert bundle.reconciliations[0].passed
        assert bundle.reconciliations[0].period_start == bundle.reconciliations[0].period_end == '2025-01'
    else:
        assert bundle.reconciliations == () and bundle.warnings


def test_flow_reconciliation_groups_and_totals_share_the_common_window():
    entries = []
    for field, rows in (
        ('actual', '2025-01,A,900\n2025-02,A,100\n2025-02,B,200\n'),
        ('ledger', '2025-02,A,200\n2025-02,B,100\n2025-03,A,900\n'),
    ):
        ctx = context(field, fields=('month', 'department', field), semantics=(semantic(field),))
        entries.append(dataset(field, (f'month,department,{field}\n' + rows).encode(), ctx))
    check = reconcile(tuple(entries)).reconciliations[0]
    assert check.period_start == check.period_end == '2025-02'
    assert check.left_total == check.right_total == 300 and check.difference == 0
    assert not check.passed and check.checked_group_count == check.failed_group_count == 2
    assert any('共同连续窗口' in warning for warning in check.warnings)


def _scoped_ratio(scope, *, b_amount=100):
    content = f'month,department,amount,visits\n2025-01,A,100,10\n2025-01,B,{b_amount},10\n'.encode()
    ctx = context('current', fields=('month', 'department', 'amount', 'visits'), semantics=(
        semantic('amount', scope={'department': scope}, unit='元'),
        semantic('visits', scope={'department': scope}, unit='人次'),
    ))
    definitions = metrics('amount', 'visits') + ({'code': 'cost_per_visit', 'aggregation': 'ratio',
        'numeratorMetric': 'amount', 'denominatorMetric': 'visits'},)
    return build_deterministic_analysis_bundle(analysis(fields=('amount', 'visits')),
        (dataset('current', content, ctx),), profile_metrics=definitions)


@pytest.mark.parametrize('b_amount', [100, 200])
def test_distinct_scopes_keep_distinct_resolvable_derived_identities(b_amount):
    left, right = _scoped_ratio('A', b_amount=b_amount), _scoped_ratio('B', b_amount=b_amount)
    assert left.derived_metrics[0].fact_id != right.derived_metrics[0].fact_id
    frozen = [left.model_dump_json(by_alias=True), right.model_dump_json(by_alias=True)]
    for bundle, department in ((left, 'A'), (right, 'B')):
        fact = bundle.derived_metrics[0]
        token = '{{value:' + fact.fact_id + ':value:}}'
        text, refs, notices = render_bound_numbers(department + '科登记比值为' + token, frozen, key=department)
        assert text and len(refs) == 1 and not notices
        selected = resolve_number_reference(refs[0].token, frozen)
        assert selected['value'] == fact.value and selected['scope'] == {'department': department}
        assert fact.input_fact_ids == tuple(metric.fact_id for metric in bundle.metrics)
        assert assign_fact_ids(bundle).model_dump() == bundle.model_dump()
        loaded = DeterministicAnalysisBundle.model_validate_json(bundle.model_dump_json(by_alias=True))
        assert fact_input_relations(loaded)[fact.fact_id] == fact.input_fact_ids
        payload = resolve_fact(bundle.model_dump_json(by_alias=True).encode(), FactRefV1(
            analysisId=bundle.analysis_id, fileResourceId='trf-' + 'a' * 20,
            factKind='derived', jsonPointer='/derivedMetrics/0', factKey=fact.fact_id))
        assert tuple(ref['factId'] for ref in payload['inputFactRefs']) == fact.input_fact_ids


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('reverse', [False, True])
async def test_department_a_claim_keeps_department_a_source_after_assembly(reverse):
    left = _scoped_ratio('A').model_copy(update={'analysis_id': 'analysis_101'})
    right = _scoped_ratio('B').model_copy(update={'analysis_id': 'analysis_102'})
    bundles = (right, left) if reverse else (left, right)
    files, identities, resources = {}, {}, {}
    for bundle in bundles:
        raw = bundle.model_dump_json(by_alias=True).encode()
        path = f'facts/{bundle.analysis_id}.json'
        files[path] = raw
        identities[bundle.analysis_id] = FileIdentity(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        resources[bundle.analysis_id] = derive_resource_id(path)
    _, _, directory, _ = await RuntimeSectionsMixin._build_server_tables(
        _Harness(files), SimpleNamespace(), checkpoint=SimpleNamespace(deterministic_fact_files=identities),
        outline=SimpleNamespace(sections=()))
    token = '{{value:' + left.derived_metrics[0].fact_id + ':value:}}'
    _, refs, notices = render_bound_numbers('A科登记比值为' + token,
        [bundle.model_dump_json(by_alias=True) for bundle in bundles], key='a-source')
    assert len(refs) == 1 and not notices
    artifact = SimpleNamespace(section_code='section_101', claims=(), blocks=(SimpleNamespace(
        number_references=refs, review_notices=(), claim_ids=tuple(ref.claim_id for ref in refs)),))
    bindings = build_claim_subject_bindings((artifact,), directory, resources)
    assert len(bindings) == 1
    assert bindings[0].fact_refs[0].analysis_id == left.analysis_id
    assert bindings[0].fact_refs[0].file_resource_id == resources[left.analysis_id]


def _legacy_ratio_json(bundle):
    fact = bundle.derived_metrics[0].model_copy(update={'input_fact_ids': (), 'scope': {}})
    legacy_id = 'fact-' + hashlib.sha256(derived_fact_identity(fact).encode()).hexdigest()[:16]
    payload = bundle.model_dump(mode='json', by_alias=True)
    payload['derivedMetrics'][0].update(factId=legacy_id)
    payload['derivedMetrics'][0].pop('inputFactIds')
    payload['derivedMetrics'][0].pop('scope')
    return json.dumps(payload), '{{value:' + legacy_id + ':value:}}', legacy_id


def test_single_legacy_ratio_remains_readable_without_frozen_input_ids():
    raw, token, _ = _legacy_ratio_json(_scoped_ratio('A'))
    text, refs, notices = render_bound_numbers('登记比值为' + token, [raw], key='legacy')
    assert text.endswith('10') and len(refs) == 1 and not notices
    assert resolve_number_reference(token, [raw])['value'] == 10


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('reverse', [False, True])
async def test_legacy_scope_collision_is_unverified_instead_of_bound_to_last_analysis(reverse):
    bundles = (_scoped_ratio('A').model_copy(update={'analysis_id': 'analysis_101'}),
               _scoped_ratio('B').model_copy(update={'analysis_id': 'analysis_102'}))
    contents, token, fact_id = [], None, None
    identities, files = {}, {}
    for bundle in reversed(bundles) if reverse else bundles:
        raw, token, fact_id = _legacy_ratio_json(bundle)
        contents.append(raw)
        path = f'facts/{bundle.analysis_id}.json'
        files[path] = raw.encode()
        identities[bundle.analysis_id] = FileIdentity(
            path=path, size=len(files[path]), sha256=hashlib.sha256(files[path]).hexdigest())
    text, refs, notices = render_bound_numbers('A科登记比值为' + token, contents, key='legacy-conflict')
    assert '待核实' in text and not refs and notices
    assert resolve_number_reference(token, contents) is None
    _, _, directory, _ = await RuntimeSectionsMixin._build_server_tables(
        _Harness(files), SimpleNamespace(), checkpoint=SimpleNamespace(deterministic_fact_files=identities),
        outline=SimpleNamespace(sections=()))
    assert fact_id not in directory
