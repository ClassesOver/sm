"""完整总体授权只来自服务端记录与冻结输出的一致登记。"""
import hashlib
import json
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_standard_population_proof import _inputs
from smart_reporting.reporting.trace.computation_service import (
    build_standard_supplemental_computation_record,
)
from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    build_standard_population_proof,
)


def registered_population():
    from smart_reporting.reporting.tests.test_standard_supplemental import CSV
    req, parent, payload = _inputs()
    proof = build_standard_population_proof(csv_content=CSV, dataset_sha256=parent.dataset_sha256,
        request=req, parent_fact=parent, finding=payload['findings'][0])
    payload['findings'][0]['populationProof'] = proof
    raw = json.dumps(payload, ensure_ascii=False).encode()
    identity = FileIdentity(path='evidence.json',size=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    input_file = {'path':'dataset.csv','size':len(CSV),'sha256':parent.dataset_sha256}
    execution = 'standard-' + hashlib.sha256((parent.dataset_sha256+identity.sha256).encode()).hexdigest()[:16]
    record = build_standard_supplemental_computation_record(analysis_id='analysis_001',
        dataset_ids=(req.dataset_id,),input_files=(input_file,),evidence_file=identity.model_dump(by_alias=True),
        method='supplemental_standard_group_summary',method_version='standard-supplemental-v1',
        parameters={**req.model_dump(mode='json',by_alias=True),'populationProofs':[proof]},
        execution_id=execution,finding_count=len(payload['findings'][0]['rows']))
    item = SimpleNamespace(analysis_id='analysis_001',dataset_ids=(req.dataset_id,),
                           evidence_files=(identity,),computation_record=record.model_dump(mode='json',by_alias=True))
    return SimpleNamespace(evidence=(item,)), {derive_resource_id(identity.path):raw}, proof


def test_server_registered_population_context_is_table_pointer_scoped():
    from smart_reporting.reporting.workflow.runtime.sections import _verified_population_contexts
    work,sources,proof = registered_population()
    contexts = _verified_population_contexts(work,sources)
    assert contexts[derive_resource_id('evidence.json')]['/findings/0'] == proof


def test_registered_computation_may_use_only_a_subset_of_analysis_datasets():
    from smart_reporting.reporting.workflow.runtime.sections import _verified_population_contexts

    work, sources, proof = registered_population()
    work.evidence[0].dataset_ids += ('dataset-unused',)
    contexts = _verified_population_contexts(work, sources)
    assert contexts[derive_resource_id('evidence.json')]['/findings/0'] == proof
    work.evidence[0].dataset_ids = ('dataset-unused',)
    assert not _verified_population_contexts(work, sources)


def test_evidence_without_computation_does_not_log_a_population_validation_failure(monkeypatch):
    from unittest.mock import Mock

    from smart_reporting.reporting.workflow.runtime import sections

    work, sources, _ = registered_population()
    work.evidence[0].computation_record = None
    warning = Mock()
    monkeypatch.setattr(sections.loguru_logger, 'warning', warning)
    assert not sections._verified_population_contexts(work, sources)
    warning.assert_not_called()


@pytest.mark.parametrize('fault',['missing_record','script_method','output_drift','proof_conflict','dataset_conflict','output_identity'])
def test_model_metadata_or_conflicting_identity_does_not_authorize_population(fault):
    from smart_reporting.reporting.workflow.runtime.sections import _verified_population_contexts
    work,sources,_ = registered_population()
    record = work.evidence[0].computation_record
    if fault == 'missing_record':
        work.evidence[0].computation_record = None
    elif fault == 'script_method':
        record['method']='supplemental_python'
    elif fault == 'output_drift':
        sources = {k:v+b' ' for k,v in sources.items()}
    elif fault == 'proof_conflict':
        record['parameters']['populationProofs'][0]['members']=['伪造']
    elif fault == 'dataset_conflict':
        record['parameters']['inputFiles'][0]['sha256']='f'*64
    elif fault == 'output_identity':
        record['outputFactRefs'][0]['fileResourceId']=derive_resource_id('foreign.json')
    assert not _verified_population_contexts(work,sources)


def test_registered_batch_preserves_each_table_population_proof():
    from copy import deepcopy

    from smart_reporting.reporting.workflow.runtime.sections import _verified_population_contexts

    work, sources, proof = registered_population()
    item = work.evidence[0]
    resource, raw = next(iter(sources.items()))
    document = json.loads(raw)
    other = deepcopy(document['findings'][0])
    other['name'] = 'second-group-summary'
    other['populationProof']['tablePointer'] = '/findings/1'
    document['findings'].append(other)
    raw = json.dumps(document, ensure_ascii=False).encode()
    identity = FileIdentity(path=item.evidence_files[0].path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    parameters = dict(item.computation_record['parameters'])
    inputs = parameters.pop('inputFiles')
    parameters.pop('populationProofs')
    execution = 'standard-' + hashlib.sha256((inputs[0]['sha256'] + identity.sha256).encode()).hexdigest()[:16]
    row_counts = tuple(len(table['rows']) for table in document['findings'])
    record = build_standard_supplemental_computation_record(
        analysis_id=item.analysis_id, dataset_ids=item.dataset_ids, input_files=inputs,
        evidence_file=identity.model_dump(by_alias=True), method='supplemental_standard_batch',
        method_version='standard-supplemental-v1', execution_id=execution,
        parameters={'computations': [parameters, {**parameters, 'outputName': other['name']}],
                    'populationProofs': [proof, other['populationProof']]},
        finding_count=sum(row_counts), finding_row_counts=row_counts,
    )
    item.evidence_files = (identity,)
    item.computation_record = record.model_dump(mode='json', by_alias=True)
    contexts = _verified_population_contexts(work, {resource: raw})
    assert set(contexts[resource]) == {'/findings/0', '/findings/1'}
    assert contexts[resource]['/findings/1'] == other['populationProof']
    item.computation_record['parameters']['populationProofs'][1]['members'] = ['forged']
    contexts = _verified_population_contexts(work, {resource: raw})
    assert set(contexts[resource]) == {'/findings/0'}
