import ast
import json

import pytest
from pydantic import ValidationError

from scripts.replay_standard_visualization_variants import plan_from_saved, run_case
from scripts.standard_visualization_stress_cases import case, extended_cases, parameters
from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_script,
)


@pytest.mark.parametrize('sample', list(extended_cases()), ids=lambda sample: sample['id'])
def test_extended_input_contracts_have_explicit_standard_or_fallback_decisions(sample):
    if sample['expected'] == 'schema':
        with pytest.raises(ValidationError):
            plan_from_saved(sample['parameters'])
        return
    plan = plan_from_saved(sample['parameters'])
    files = tuple(ChartInputFile(f'input-{index}.json', json.dumps(document, ensure_ascii=False).encode())
                  for index, document in enumerate(sample['documents']))
    inputs = ChartInputMaterialization(files=files, entries=tuple(
        {'chartId': 'stress', 'path': source.path, 'sha256': source.sha256} for source in files))
    source = standard_visualization_script(plan, inputs)
    if sample['expected'] == 'fallback':
        assert source is None
    else:
        assert source is not None
        ast.parse(source)


def test_numeric_auditor_detects_wrong_values_in_an_existing_png(tmp_path):
    document = {'columns': ['label', 'actual'], 'rows': [['甲', 10], ['乙', 20]], 'columnMeta': {'actual': {'unit': '元'}}}
    sample = case('oracle-negative-control', [document], parameters(),
                  series=[{'name': 'actual', 'kind': 'line', 'values': [100, 200]}])
    result = run_case(sample, tmp_path)
    assert result['status'] == 'semantic_mismatch'
    assert result['audit']['semanticMismatches'] == ['wrong_values:actual']


@pytest.mark.parametrize('fault', ['color', 'text'])
def test_auditor_negative_controls_detect_wrong_color_and_missing_summary(tmp_path, fault):
    document = {'columns': ['label', 'actual'], 'rows': [['甲', 10], ['乙', 20]], 'columnMeta': {'actual': {'unit': '元'}}}
    assertions = ({'series': [{'name': 'actual', 'kind': 'bar', 'values': [10, 20], 'colors': ['#ff0000', '#ff0000']}]}
                  if fault == 'color' else {'texts': ['执行率 99.99%']})
    sample = case('oracle-' + fault, [document], parameters('barh'), **assertions)
    result = run_case(sample, tmp_path)
    assert result['status'] == 'semantic_mismatch'
    assert any(('wrong_colors' if fault == 'color' else 'missing_frozen_text') in issue for issue in result['audit']['semanticMismatches'])


@pytest.mark.parametrize('invalid', [0, 1, 'false', 'true', [], {}])
def test_invalid_percentage_scale_types_cannot_silently_change_axis_semantics(invalid):
    document = {'columns': ['label', 'actual'], 'rows': [['甲', .25]], 'columnMeta': {'actual': {'unit': '%', 'isPercent': invalid}}}
    plan = plan_from_saved(parameters())
    source = ChartInputFile('input.json', json.dumps(document).encode())
    inputs = ChartInputMaterialization(files=(source,), entries=({'chartId': 'stress', 'path': source.path, 'sha256': source.sha256},))
    assert standard_visualization_script(plan, inputs) is None
