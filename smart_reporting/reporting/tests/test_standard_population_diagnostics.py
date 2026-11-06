"""证明资格诊断使用稳定代码；不依据中文 warning 文案分类。"""
import hashlib
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_standard_population_proof import _inputs
from smart_reporting.reporting.tests.test_standard_supplemental import CSV
from smart_reporting.reporting.workflow.runtime import standard_supplemental as standard


@pytest.mark.parametrize('fault,code', [
    ('member', 'invalid_member'), ('period', 'invalid_period'),
    ('numeric', 'invalid_numeric'), ('coverage', 'missing_period'),
    ('identity', 'identity_mismatch'), ('reconciliation', 'reconciliation_failed'),
    ('output', 'output_mismatch'),
])
def test_supported_proof_failure_has_machine_reason_and_location(fault, code):
    content = CSV
    if fault == 'member':
        content += b'2025-01,   ,0\n'
    elif fault == 'period':
        content += b'unknown,A,0\n'
    elif fault == 'numeric':
        content += b'2025-01,A,invalid\n'
    elif fault == 'coverage':
        content = b'period,department,amount\n2025-01,A,200\n'
    req, parent, payload = _inputs(content)
    if fault == 'identity':
        parent.dataset_sha256 = 'f' * 64
    elif fault == 'reconciliation':
        req = req.model_copy(update={'parent_total': 201})
    elif fault == 'output':
        payload['findings'][0]['rows'][0][0] = 'wrong'
    if fault == 'coverage':
        parent.period_values = [SimpleNamespace(period='2025-01', value=200),
                                SimpleNamespace(period='2025-02', value=0)]
    issues = []
    proof = standard.build_standard_population_proof(csv_content=content,
        dataset_sha256=hashlib.sha256(content).hexdigest(), request=req,
        parent_fact=parent, finding=payload['findings'][0], _issues=issues)
    assert proof is None
    assert code in {issue['code'] for issue in issues}
    assert all(issue['datasetId'] == req.dataset_id and issue['outputName'] == req.output_name
               and issue['periods'] for issue in issues)


def test_unsupported_proof_does_not_emit_failure_noise():
    req, parent, payload = _inputs()
    req = req.model_copy(update={'operation': 'group_period_series'})
    issues = []
    assert standard.build_standard_population_proof(csv_content=CSV,
        dataset_sha256=parent.dataset_sha256, request=req, parent_fact=parent,
        finding=payload['findings'][0], _issues=issues) is None
    assert issues == []


def test_ratio_invalid_operands_are_explicitly_independent_valid_sums():
    from smart_reporting.reporting.tests.test_standard_supplemental_independent import _run
    _, payload = _run('period,department,amount,budget\n2025-01,A,100,invalid\n'
                      '2025-01,A,invalid,50\n', 'group_ratio', denominatorField='budget',
                      denominatorParentTotal=50, denominatorScale=1, ratioFactId='ratio')
    table = payload['findings'][0]
    assert table['rows'][0][1:3] == [100, 50]
    assert table['operandAggregation'] == 'independent_valid_sums'
    assert {issue['code'] for issue in table['issues']} == {'invalid_numeric'}


def test_period_coverage_must_be_inside_authorized_scope():
    from smart_reporting.reporting.tests.test_standard_supplemental_independent import _run
    content = b'period,department,amount,site\n2025-01,A,100,north\n2025-02,A,0,south\n'
    req, payload = _run(content, periods=('2025-01', '2025-02'), scope={'site': 'north'})
    _, parent, _ = _inputs(content.replace(b',site', b'').replace(b',north', b'').replace(b',south', b''))
    parent.dataset_id = req.dataset_id
    parent.dataset_sha256 = hashlib.sha256(content).hexdigest()
    parent.scope = {'site': 'north'}
    parent.period_values = [SimpleNamespace(period='2025-01', value=100),
                            SimpleNamespace(period='2025-02', value=0)]
    issues = []
    assert standard.build_standard_population_proof(csv_content=content,
        dataset_sha256=parent.dataset_sha256, request=req, parent_fact=parent,
        finding=payload['findings'][0], _issues=issues) is None
    assert issues[0]['code'] == 'missing_period'


@pytest.mark.parametrize('baseline_row,baseline_code', [
    ('2024-01,A,invalid', 'invalid_numeric'),
    ('2024-01,   ,0', 'invalid_member'),
    ('unparseable,A,0', 'invalid_period'),
])
def test_comparison_issues_identify_the_actual_input_dataset_and_window(baseline_row, baseline_code):
    request = standard.StandardSupplementalRequest(
        operation='period_comparison', datasetId='current', baselineDatasetId='prior',
        outputName='comparison', measureField='amount', measureUnit='元', dimensionField='department',
        periodField='period', periodGranularity='month', currentPeriods=['2025-01'],
        baselinePeriods=['2024-01'], parentTotal=100, baselineParentTotal=50,
    )
    payload = standard.run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('current', 'prior'),
        authorized_fields=('period', 'department', 'amount'),
        csv_content=b'period,department,amount\n2025-01,A,100\n2025-01,A,invalid\n',
        baseline_csv_content=('period,department,amount\n2024-01,A,50\n' + baseline_row + '\n').encode(),
        baseline_authorized_fields=('period', 'department', 'amount'), request=request,
    )
    issues = payload['findings'][0]['issues']
    assert {(item['datasetId'], item['code'], tuple(item['periods'])) for item in issues} == {
        ('current', 'invalid_numeric', ('2025-01',)), ('prior', baseline_code, ('2024-01',)),
    }
    assert all(item['outputName'] == 'comparison' for item in issues)
    assert payload['findings'][0]['rows']
