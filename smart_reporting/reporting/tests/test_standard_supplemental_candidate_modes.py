"""有界目录应兼顾同一登记比率的全窗与逐期模式。"""

import json

from smart_reporting.reporting.tests.test_standard_supplemental_period_ratio import (
    _registered_state,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import AnalysisItemWorkflow
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    standard_computation_candidates,
)


def test_bounded_catalog_keeps_both_ratio_modes_and_every_candidate_remains_authorized():
    state, *_ = _registered_state()
    state.instruction['datasets'][0]['columns'].extend(f'axis{index}' for index in range(12))
    candidates = standard_computation_candidates(
        state.facts, state.instruction['datasets'], state.instruction['currentAnalysis']['periods'],
    )
    ratios = [item['standardComputation'] for item in candidates
              if item['standardComputation']['operation'] == 'group_ratio']

    assert {spec.get('groupByPeriod', False) for spec in ratios} == {False, True}
    assert len(candidates) <= 40
    assert sum(len(json.dumps(item, ensure_ascii=False).encode()) for item in candidates) <= 24_000

    template = state.decision.coding_requirements[0]
    for candidate in candidates:
        requirement = template.model_copy(update={
            'dataset_id': candidate['datasetId'], 'fields': tuple(candidate['fields']),
            'standard_computation': None, 'standard_candidate_id': candidate['candidateId'],
            'required_columns': tuple(candidate['outputColumns']),
        })
        state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
        selected = AnalysisItemWorkflow._standard_plan(state)
        assert len(selected) == 1, candidate
        assert selected[0].model_dump(mode='json', by_alias=True, exclude_none=True) == candidate['standardComputation']
