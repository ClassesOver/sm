"""合成输入回放当前实现；预期值由 Fraction/Decimal 独立生成。"""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from smart_reporting.reporting.workflow.runtime.chart_inputs import ChartInputFile, ChartInputMaterialization
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDraft, StandardChartDerivation, StandardChartSource, VisualizationPlanDraft,
)
from smart_reporting.reporting.workflow.runtime.standard_chart_alignment import align_chart_sources
from smart_reporting.reporting.workflow.runtime.standard_chart_pagination import expand_standard_pagination
from smart_reporting.reporting.workflow.runtime.standard_chart_transform import transform_chart_document

OUT = Path(__file__).resolve().parents[1] / 'evidence' / 'current-replay.jsonl'
records = []


def record(case, source, expected, actual):
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True).encode()
    records.append({
        'case_id': case, 'variant': 'current',
        'smart_reporting_commit': '28649e9c56b1aa7e96f0c363e8eec8accd0175b7',
        'flint_commit': 'not-run',
        'input_identity': [{'path': 'inline-synthetic', 'size': len(encoded), 'sha256': hashlib.sha256(encoded).hexdigest()}],
        'synthetic_input': source, 'expected_values': expected, 'actual_values': actual,
        'business_intent': 'Technical invariants only; no independent business approval',
        'mechanism_changed': 'none; current implementation replay or declared input fault',
        'command': 'python fixtures/replay_current.py', 'geometry': 'not_run',
        'visual_review': 'not_run', 'duration_ms': None, 'model_calls': 0, 'redraws': 0,
        'limitations': ['No Flint counterfactual', 'No production run or revision/export service'],
    })


def compare_numbers(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected, strict=True):
        assert got is None if want is None else got is not None and math.isclose(got, float(want), rel_tol=1e-12, abs_tol=1e-12)


source = {'columns': ['period', 'amount', 'base'],
          'rows': [['2025-01', 1, 8], ['2025-02', 2, 0], ['2025-03', None, 4]],
          'columnMeta': {'amount': {'unit': '元'}, 'base': {'unit': '元'}}}
original = deepcopy(source)
ratio = StandardChartDerivation(kind='ratio_percent', name='占比', numerator='amount', denominator='base')
result = transform_chart_document(source, None, [ratio])
expected = [Fraction(1, 8) * 100, None, None]
actual = [row[-1] for row in result['rows']]
compare_numbers(actual, expected)
assert source == original
assert result['columnMeta']['占比']['unit'] == '%' and result['columnMeta']['占比']['isPercent'] is True
record('ratio-zero-null', source, ['12.5', None, None], actual)

for fault in ('wrong-unit', 'missing-unit'):
    bad = deepcopy(source)
    bad['columnMeta']['base'] = {'unit': '人次'} if fault == 'wrong-unit' else {}
    try:
        transform_chart_document(bad, None, [ratio])
    except ValueError as error:
        record(fault, bad, 'ValueError', {'error_type': type(error).__name__, 'message': str(error)})
    else:
        raise AssertionError(f'Fault was not detected: {fault}')

monthly = {'columns': ['period', 'amount'],
           'rows': [['2025-01', 100], ['2025-02', 120], ['2025-03', 0], ['2025-04', 20], ['2025-05', -10], ['2025-06', -20]],
           'columnMeta': {'amount': {'unit': '元'}}}
mom = StandardChartDerivation(kind='mom_percent', name='环比', numerator='amount', labelField='period')
result = transform_chart_document(monthly, None, [mom])
# 本项目既有定义：基数 <= 0 不输出比例。oracle 独立计算，不调用生产函数。
expected = [None, (Fraction(120, 100) - 1) * 100, Decimal('-100'), None, Decimal('-150'), None]
actual = [row[-1] for row in result['rows']]
compare_numbers(actual, expected)
record('mom-positive-base-policy', monthly, [None, '20', '-100', None, '-150', None], actual)

chart = ChartDraft(chartId='synthetic', sourcePath='synthetic.png', title='合成分页金额对照',
                   altText='全部类别分页并使用共享金额轴', citationIds=['synthetic'], metricCodes=['synthetic'],
                   currentPeriod='2025-01', sourceDatasetId='synthetic', aggregationGrain='category',
                   visualForm='barh', standardLabelField='label', standardValueFields=['amount'],
                   standardPagination={'pageSize': 2}, standardDisplayUnit='万元',
                   dataBindings=[{'analysisId': 'synthetic', 'factPath': 'synthetic/facts',
                                  'dataPath': 'synthetic.json', 'fields': ['label', 'amount'],
                                  'role': '分页金额冻结输入'}])
plan = VisualizationPlanDraft(charts=(chart,))


def page_input(values):
    document = {'columns': ['label', 'amount'], 'rows': [[f'合成类别{n}', value] for n, value in enumerate(values)],
                'columnMeta': {'amount': {'unit': '元'}}}
    file = ChartInputFile(path='synthetic.json', content=json.dumps(document, ensure_ascii=False).encode())
    inputs = ChartInputMaterialization(files=(file,), entries=({'chartId': 'synthetic', 'path': file.path, 'sha256': file.sha256},))
    return document, file, inputs


before, old_file, old_input = page_input([-10000, 20000, 30000])
after, new_file, new_input = page_input([-10000, 20000, 100000])
old_pages = expand_standard_pagination(plan, old_input)
new_pages = expand_standard_pagination(plan, new_input)
assert len(old_pages.charts) == len(new_pages.charts) == 2
assert old_file.sha256 != new_file.sha256
for pages, high in ((old_pages, Decimal('3.4')), (new_pages, Decimal('11.1'))):
    assert len({page.standard_domains.model_dump_json() for page in pages.charts}) == 1
    for page in pages.charts:
        assert math.isclose(page.standard_domains.left.maximum, float(high))
assert [label for page in new_pages.charts for label in page.standard_labels] == [row[0] for row in after['rows']]
record('pagination-value-boundary', {'before': before, 'after': after},
       {'pages': 2, 'new_domain_max_wan': '11.1', 'new_input_identity': True},
       {'pages': len(new_pages.charts), 'new_domain_max_wan': new_pages.charts[0].standard_domains.left.maximum,
        'old_sha256': old_file.sha256, 'new_sha256': new_file.sha256})

selection = StandardChartSource(sourceIndex=0, labelField='label', valueField='amount', seriesName='合成金额')
diagnostics = []
forged = [{'path': new_file.path, 'sha256': old_file.sha256}]
assert align_chart_sources(forged, [new_file], [selection], diagnostics=diagnostics) is None
assert diagnostics[0]['reason'] == 'source_identity_mismatch'
record('stale-source-identity', {'old_sha256': old_file.sha256, 'new_sha256': new_file.sha256},
       'source_identity_mismatch', diagnostics)

OUT.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in records))
print(json.dumps({'cases': len(records), 'output': OUT.name}, ensure_ascii=False))
