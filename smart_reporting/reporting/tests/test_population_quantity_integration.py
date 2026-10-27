"""服务端完整集合登记一路接到正文纠错与持久复算。"""
import json
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
from smart_reporting.reporting.model_policy import ThinkingRequest
from smart_reporting.reporting.tests.test_population_contexts import registered_population
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers
from smart_reporting.reporting.trace.table_sources import resolve_table_derivation
from smart_reporting.reporting.workflow.runtime import sections
from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview


@pytest.mark.anyio
async def test_registered_population_corrects_top_sum_and_mixed_share_with_durable_proofs(monkeypatch):
    work, sources, proof = registered_population()
    from smart_reporting.reporting.tests.test_semantic_bindings import contents
    document = json.loads(contents()[0])
    parent = document['metrics'][0]
    parent.update(total=200, field='amount', datasetId=proof['datasetId'], datasetSha256=proof['datasetSha256'],
                  periodValues=[{'period':'2025-01','value':100},{'period':'2025-02','value':100}])
    document['metrics'] = [parent]
    from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
    sources[derive_resource_id('facts.json')] = json.dumps(document).encode()
    frozen = [raw.decode() for raw in sources.values()]
    markdown, numbers, notices = render_bound_numbers(
        '2025年1—2月前1项科室收入合计{{value:fact-aaaaaaaaaaaaaaaa:monthlyAverage:元}}，'
        '内科占全院收入{{calc:ratio(fact-aaaaaaaaaaaaaaaa:periodValues.0,fact-aaaaaaaaaaaaaaaa:total):%}}。',
        frozen,key='population-integration')
    block = ReportDraftBlock(blockId='b',markdown=markdown,numberReferences=numbers,reviewNotices=notices)

    async def review(agent,schema,stage,payload,**kwargs):
        amount = next(s for s in payload['quantitySources'] if s.get('column') == 'value')
        total = next(s for s in payload['quantitySources'] if s.get('selector') == 'total')
        assert amount['completePopulation'] is True
        return SectionSemanticReview.model_validate({'interpretations':[
            {'claimId':numbers[0].claim_id,'quantity':{'operation':'top_sum','left':[amount['sourceId']],
             'limit':1,'selection':'items','evidence':['前1项科室收入合计']}},
            {'claimId':numbers[1].claim_id,'quantity':{'operation':'share','left':[amount['sourceId']],
             'right':[total['sourceId']],'rowLabel':'内科','evidence':['内科占全院收入']}},
        ]})
    monkeypatch.setattr(sections,'_run_section_stage',review)
    result = await sections._disambiguate_section_claims(object(),(block,),frozen,
        section_code='s',scope=SimpleNamespace(),run_context=SimpleNamespace(),
        thinking_request=ThinkingRequest(operation='section_generation',complexity='standard'),
        table_sources=sources,table_contexts=sections._verified_population_contexts(work,sources))
    assert '130元' in result[0].markdown and '65.00%' in result[0].markdown
    for number, expected in zip(result[0].number_references,(130,65),strict=True):
        assert number.semantic_receipt.quantity_binding_sha256
        assert resolve_table_derivation(number.token,number.table_derivation,sources)['value'] == expected
    assert result[0].number_references[0].table_derivation.population_fact
    assert result[0].number_references[1].table_derivation.denominator_fact

    from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings
    subjects = build_claim_subject_bindings((SimpleNamespace(section_code='s',blocks=result,claims=()),),{}, {})
    assert len(subjects) == 2
    assert all(subject.fact_refs and subject.fact_refs[0].fact_key == parent['factId'] for subject in subjects)
