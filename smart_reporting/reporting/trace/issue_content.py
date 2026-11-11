"""核对纠错计算在当前正文的机械呈现，不签认业务解释。"""

import hashlib

from ..models import ReportingError
from ..semantics.planning_contracts import MetricPlanningContext
from .fact_index import fact_entry_from_pointer
from .fact_service import read_fact_document
from .semantic_bindings import (
    NumberReferenceResolver,
    reference_fact_ids,
    statement_fingerprint,
)
from .subject_builder import prepare_claim_status
from .table_quality import evaluate_table_quality


def evaluate_calculation_content(index, markdown, sources, calculation, *, report_revision):
    expected = {item.fact_id: item for item in calculation.results
        if item.metric_version == calculation.request.metric_version}
    matched, documents = set(), {}
    files = {file.resource_id: file for file in index.files}
    for entry in index.fact_files:
        file = files[entry.file_resource_id]
        raw = sources.get(file.resource_id)
        if raw is None or len(raw) != file.size or hashlib.sha256(raw).hexdigest() != file.sha256:
            continue
        try:
            document = read_fact_document(raw)
            context = MetricPlanningContext.model_validate(document['metricContext'])
        except (ValueError, KeyError, ReportingError):
            continue
        if (context.basis_id != index.report_basis_id or context.basis_id != calculation.request.basis_id
                or context.report_revision != report_revision):
            continue
        candidates = [item for item in context.calculations if item.receipt_id == calculation.receipt_id]
        if len(candidates) != 1 or (candidates[0].request, candidates[0].results) != (calculation.request, calculation.results):
            continue
        documents[file.resource_id] = document

    def fact(ref):
        document = documents.get(ref.file_resource_id)
        if document is None or document['analysisId'] != ref.analysis_id:
            return None
        try:
            kind, value = fact_entry_from_pointer(document, ref.json_pointer)
        except KeyError:
            return None
        target = expected.get(ref.fact_key)
        if target is None or kind != ref.fact_kind or value != target.model_dump(mode='json', by_alias=True):
            return None
        return ref.fact_key

    tables = evaluate_table_quality(index, markdown, documents)
    for table in index.tables:
        if tables[table.table_id].status == 'verified':
            for cell in table.cells:
                if cell.value_selector == 'value':
                    matched.update(value for ref in cell.fact_refs if (value := fact(ref)) is not None)
    resolver = NumberReferenceResolver(raw.decode() for key, raw in sources.items() if key in documents)
    check = prepare_claim_status(markdown)
    for subject in index.subject_bindings:
        number = subject.number_reference
        if number is None or number.table_derivation is not None or statement_fingerprint(markdown, number.claim_id) != number.statement_sha256:
            continue
        if set(reference_fact_ids(number.token)) != {ref.fact_key for ref in subject.fact_refs}:
            continue
        selected = resolver.resolve(number.token)
        if selected is None:
            continue
        detail = check(number.claim_id, selected['value'], expected_unit=selected['unit'],
            expected_scope=selected['scope'], expected_reference=selected,
            semantic_receipt=number.semantic_receipt, section_id=subject.locator.section_id)
        if detail['status'] == 'valid' and not detail['warnings']:
            matched.update(value for ref in subject.fact_refs if (value := fact(ref)) is not None)
    missing = set(expected) - matched
    return {'factPresentationVerified': bool(expected) and not missing,
        'coveredFactIds': sorted(matched), 'missingFactIds': sorted(missing),
        'businessApproval': 'not_performed'}
