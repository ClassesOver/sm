"""正文规划直接使用正式结果身份；不可用结果不补零，串用依据不进入模型。"""

import hashlib
import json

import pytest
from agno.run import RunContext

from smart_reporting.reporting.model_policy import ThinkingRequest
from smart_reporting.reporting.tests.test_registered_chart_projection import registered_document
from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import _revenue_work_item
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime import sections
from smart_reporting.reporting.workflow.runtime.phase_models import (
    SectionEvidenceBundle,
    SectionEvidenceFile,
)
from smart_reporting.task_execution import TaskExecutionScope


@pytest.mark.anyio
@pytest.mark.parametrize('status', ['computed', 'unavailable', 'foreign_basis'])
async def test_registered_results_are_projected_to_section_plan_with_exact_identity(monkeypatch, status):
    document = registered_document()
    result = document['metricContext']['calculations'][0]['results'][0]
    if status == 'unavailable':
        result.update(status='unavailable', value=None, issueCodes=['missing_data'])
    elif status == 'foreign_basis':
        result['basisId'] = 'foreign-basis'
    content = json.dumps(document, ensure_ascii=False)
    identity = FileIdentity(path='facts/registered.json', size=len(content.encode()),
        sha256=hashlib.sha256(content.encode()).hexdigest())
    work = _revenue_work_item()
    work = work.model_copy(update={'evidence': (work.evidence[0].model_copy(update={
        'evidence_files': (identity,)}),), 'fact_files': (identity,)})
    evidence = SectionEvidenceBundle(sectionCode=work.section_code, factSummaries=(),
        files=(SectionEvidenceFile(identity=identity, content=content),))

    class PlanInspected(Exception):
        pass

    async def inspect_plan(_agent, _schema, stage, payload, **kwargs):
        assert stage == 'plan'
        entry, = payload['factCatalog']
        for key in ('factId', 'metricVersion', 'calculationId', 'period', 'unit', 'dimensions', 'status', 'value', 'issueCodes'):
            assert entry[key] == result[key]
        assert entry['kind'] == 'registered_metric_result'
        assert entry['periodBoundary'] == 'half_open'
        assert entry['reportRevision'] == document['metricContext']['reportRevision']
        assert entry['reportBasisId'] == document['metricContext']['basisId']
        raise PlanInspected

    monkeypatch.setattr(sections, '_run_section_stage', inspect_plan)
    with pytest.raises(ValueError if status == 'foreign_basis' else PlanInspected):
        await sections._generate_section_in_blocks(object(), {}, evidence, work,
            whole_section=True, scope=TaskExecutionScope('task', 'user', 'thread', 'workspace', 'section'),
            run_context=RunContext(run_id='run', session_id='thread', session_state={}),
            thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'))
