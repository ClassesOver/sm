"""XLSX 摘要使用真实登记知识；撤销支持不改写已签发的历史文件。"""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook

from smart_reporting.reporting.workflow.claim_presentation import (
    registered_native_claim_presentations,
)
from smart_reporting.reporting.workflow.policy_adoption import policy_adoption_run_context
from smart_reporting.tests.test_report_background_delivery import (
    auth_context as auth_context,
)
from smart_reporting.tests.test_report_background_delivery import (
    basis_context as basis_context,
)
from smart_reporting.tests.test_report_background_delivery import (
    document_context as document_context,
)
from smart_reporting.tests.test_report_background_delivery import (
    exercise_background_report,
)
from smart_reporting.tests.test_report_background_delivery import (
    index_context as index_context,
)
from smart_reporting.tests.test_report_background_delivery import (
    receipt_snapshot as receipt_snapshot,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.mark.parametrize('case,expected', [('known', 'supported'), ('unrelated', 'unverified'), ('causal', 'unverified')])
@pytest.mark.parametrize('initial_pipeline', [False, True], ids=['adoption', 'initial-assembly'])
async def test_registered_workbook_explanation_and_current_source_revocation(
    basis_context, document_context, receipt_snapshot, monkeypatch, case, expected, initial_pipeline,
):
    async def inspect(report):
        output = Path('/tmp') / f'smart-reporting-workbook-knowledge-{os.getpid()}-{case}-{"initial" if initial_pipeline else "adoption"}'
        output.mkdir(exist_ok=True)
        shutil.copytree(report.evidence_dir, output / 'native', dirs_exist_ok=True)
        durable = await report.runtime.state_repository.get(report.context.workflow_run_id)
        checkpoint = durable.payload['workflowCheckpoint']
        assert checkpoint['workbookSummaryFiles']
        for position, file in enumerate(checkpoint['workbookSummaryFiles']):
            from smart_reporting.reporting.workflow.checkpoint import FileIdentity

            raw = await report.runtime._read_identity_bytes(report.execution.scope.workspace_key,
                FileIdentity.model_validate(file))
            (output / f'summary-registration-{position}.json').write_bytes(raw)
        document = await report.editor.read_document(report.context)
        index = await report.editor.trace.require_index(report.context)
        subject, = [item for item in index.subject_bindings if item.narrative_reference is not None
            and item.narrative_reference.analysis_id == 'analysis_001']
        assert subject.narrative_reference.analysis_id == 'analysis_001'
        if initial_pipeline:
            frozen = json.loads((output / 'summary-registration-0.json').read_bytes())
            original_ref = frozen['blocks'][0]['narrativeReferences'][0]
            assert original_ref['claimId'] != subject.claim_id
            assert original_ref['semanticReceipt']['contextSha256'] == subject.narrative_reference.semantic_receipt.context_sha256
            assert any(item.claim_id == original_ref['claimId'] for item in index.subject_bindings)
        reference, = subject.narrative_reference.semantic_receipt.knowledge_references
        assert reference.document_id == 'known-context'
        current = await report.editor.trace.validate(report.context, document.markdown, document.sha256)
        support, = [item for item in current['quality']['claimSupport'] if item['subjectId'] == subject.subject_id]
        assert support['supportStatus'] == expected
        shown = report.content['validation']['claimSupport']
        assert shown and all(item['support']['subjectId'] == subject.subject_id for item in shown)
        assert all(item['support']['supportStatus'] == expected for item in shown)
        path = output / 'native' / 'c02-corrected.xlsx'
        book = load_workbook(path, data_only=True)
        try:
            text = '\n'.join(str(cell.value or '') for row in book['汇总'] for cell in row)
        finally:
            book.close()
        label = '（建议）' if case == 'known' else '（建议，待核实）' if case == 'unrelated' else '（推断，待核实）'
        assert label in text and label not in document.markdown
        context = policy_adoption_run_context(report.execution)
        before = await registered_native_claim_presentations(report.runtime, context, report.manifest)
        assert next(item for values in before.values() for item in values
            if item['subjectId'] == subject.subject_id)['supportStatus'] == expected
        documents, token, scope = document_context[:3]
        detail = await documents.get_document(token, scope, 'known-context')
        await documents.review_revision(token, scope, 'known-context', 1, decision='revoked',
            reason='隔离测试撤销支持材料', expected_version=detail['revisions'][0]['stateVersion'])
        after = await registered_native_claim_presentations(report.runtime, context, report.manifest)
        assert next(item for values in after.values() for item in values
            if item['subjectId'] == subject.subject_id)['supportStatus'] == 'unverified'
        withdrawn = await report.editor.trace.validate(report.context, document.markdown, document.sha256)
        result, = [item for item in withdrawn['quality']['claimSupport'] if item['subjectId'] == subject.subject_id]
        assert result['supportStatus'] == 'unverified' and not result['evidenceRefs']
        assert await report.editor.read_document(report.context) == document
        async with AsyncClient(transport=ASGITransport(report.download_app), base_url='https://reports.test') as client:
            response = await client.get(report.delivery['xlsx']['downloadUrl'])
            assert response.status_code == 200 and response.content == path.read_bytes()
        (output / 'summary.txt').write_text(text)
        (output / 'evidence.json').write_text(json.dumps({'case': case, 'initialAssembly': initial_pipeline, 'expectedSupport': expected,
            'deliveredSupport': shown, 'currentBefore': before, 'currentAfter': after,
            'validationBefore': current, 'validationAfter': withdrawn,
            'historicalFileSha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'downloadAfterRevocationVerified': True, 'frozenMarkdownSha256': document.sha256,
            'registeredSummaryFiles': checkpoint['workbookSummaryFiles'],
            'realStarRocks': False, 'realModel': False, 'businessApproval': 'not_performed'},
            ensure_ascii=False, indent=2, default=str))

    await exercise_background_report(basis_context, document_context, receipt_snapshot, monkeypatch,
        case, expected, delivery_format='xlsx', after_native_report=inspect, initial_pipeline=initial_pipeline)
