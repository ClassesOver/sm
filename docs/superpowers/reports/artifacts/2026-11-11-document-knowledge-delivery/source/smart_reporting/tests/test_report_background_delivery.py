"""C33真实知识登记/检索到原生报告；受控模型与合成数据不代表业务批准。"""

import hashlib
import json
import os
import re
import shutil
from datetime import timedelta
from pathlib import Path

import duckdb
import pytest
from agno.run import RunContext
from sqlglot import parse_one

from smart_reporting.management.report_bases import ReportBasisService
from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
from smart_reporting.reporting.data_source.materialization import CsvMaterializer
from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
from smart_reporting.reporting.workflow.scope import (
    REPORT_WORKFLOW_SCOPE_DEPENDENCY,
    resolve_reporting_workflow_scope,
)
from smart_reporting.tests.c02_native_delivery import exercise_c02_native_delivery
from smart_reporting.tests.test_business_document_ingestion import metadata, register
from smart_reporting.tests.test_report_basis_persistence import auth_context as auth_context
from smart_reporting.tests.test_report_basis_persistence import basis_context as basis_context
from smart_reporting.tests.test_report_basis_persistence import build_identity
from smart_reporting.tests.test_report_basis_persistence import document_context as document_context
from smart_reporting.tests.test_report_basis_persistence import index_context as index_context
from smart_reporting.tests.test_report_basis_persistence import receipt_snapshot as receipt_snapshot
from smart_reporting.tests.test_report_issue_c02 import publish_c02_definitions

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def exercise_background_report(
    basis_context, document_context, receipt_snapshot, monkeypatch, case, expected, *, projection_failure=False,
    delivery_format='document', after_native_report=None, initial_pipeline=False, knowledge_projection_failure=False,
):
    projection_calls = []
    if projection_failure:
        from smart_reporting.reporting.workflow import claim_presentation

        async def unavailable(*args, **kwargs):
            projection_calls.append('injected')
            raise OSError('injected claim support presentation failure')

        monkeypatch.setattr(claim_presentation, 'registered_document_presentations', unavailable)
    knowledge_calls = []
    if knowledge_projection_failure:
        from smart_reporting.reporting.business_knowledge import claims

        def knowledge_unavailable(*args):
            knowledge_calls.append('injected')
            raise OSError('injected knowledge source presentation failure')

        monkeypatch.setattr(claims, 'knowledge_source_presentations', knowledge_unavailable)
    ctx = basis_context
    await publish_c02_definitions(ctx)
    documents, token, scope = document_context[:3]
    now = ctx['scopes'].auth.clock()
    cutoff = now - timedelta(minutes=1)
    statement = ('采购付款安排延后，影响本期预算执行进度' if case == 'causal'
        else '建议核对采购付款安排，解释本期预算执行率时区分支付时点与计算公式')
    early_quote = ('本期停车管理流程调整，与采购付款安排无关。' if case == 'unrelated'
        else '采购付款安排延后，影响本期预算执行进度。' if case == 'causal'
        else '建议核对采购付款安排，解释本期预算执行率时区分支付时点与计算公式。')
    late_quote = '后来补录的说明：采购付款安排延后，影响本期预算执行进度。'
    original_clock = documents.clock
    for doc_id, quote, recorded_at in [('known-context', early_quote, now - timedelta(minutes=2)),
        ('later-context', late_quote, now)]:
        documents.clock = lambda at=recorded_at: at
        await register(document_context, doc_id, body=quote.encode(), details=metadata(
            id=doc_id, title=doc_id, kind='background', eventTime='2026-11-03',
            appliesTo=[{'kind': 'metric', 'id': 'rate'}]))
        await documents.ingest_revision(await documents.claim_next())
        detail = await documents.get_document(token, scope, doc_id)
        await documents.review_revision(token, scope, doc_id, 1, decision='approved',
            reason='合成原件独立核对', expected_version=detail['revisions'][0]['stateVersion'])
    documents.clock = original_clock
    background = await ctx['policy_service'].evidence.publish(token, scope, request_id='c33-context',
        kind='background', revision_ids=tuple(DocumentRevisionRef(document_id=id, revision=1)
            for id in ('known-context', 'later-context')))
    await ctx['policy_service'].set_default(token, scope, 'budget_execution',
        policy_version={'policyId': 'monthly-budget', 'revision': 1}, expected_version=2,
        background_release_id=background.release_id)
    bases = ReportBasisService(ctx['scopes'])
    original = await bases.register_request_basis('run-basis', scope, user_id='7', thread_id='thread-basis',
        request={'reportGoal': '按当时可知材料解释本期预算执行', 'scenario': 'budget_execution',
            'deliveryFormat': delivery_format,
            'knowledgeAsOf': cutoff.isoformat(), 'period': {'start': '2026-11-01', 'end': '2026-11-30'},
            'domains': ['budget'], 'displayUnit': '%', 'comparisonRoles': [],
            'questions': [{'id': 'q-rate', 'text': '执行率及当期背景是什么？'}]}, build_identity=build_identity())
    preview = await bases.preview_policy_adoption('run-basis', scope, user_id='7', thread_id='thread-basis',
        policy_version={'policyId': 'monthly-budget', 'revision': 2})
    adoption = await bases.register_policy_adoption('run-basis', scope, user_id='7', thread_id='thread-basis',
        confirmation={'requestId': 'c33-historical-report', 'previewHash': preview.digest(),
            'targetPolicyVersion': {'policyId': 'monthly-budget', 'revision': 2},
            'questionChoices': [{'questionId': 'q-rate', 'metricVersion': {'metricId': 'rate', 'revision': 1},
                'reason': '按已发布指标计算，解释材料保持原历史截止。'}]}, build_identity=build_identity())
    await bases.register_adoption_selections('run-basis', scope, user_id='7', thread_id='thread-basis',
        request_id=adoption.confirmation.request_id)
    target = resolve_reporting_workflow_scope(run_id=adoption.target_run_id, session_id=adoption.target_run_id,
        user_id='7', dependencies={REPORT_WORKFLOW_SCOPE_DEPENDENCY: {'database': scope.database,
            'companyId': scope.company_id, 'threadId': 'thread-basis', 'userId': '7'}})
    store = receipt_snapshot[0]['dataset_store']
    store.service.registry.resolve(target)
    queries, model_inputs = [], []
    with duckdb.connect() as connection:
        connection.execute('CREATE SCHEMA test')
        connection.execute('CREATE TABLE test.project_rates(project_id VARCHAR, fraction DECIMAL(18,8), period DATE)')
        connection.execute("INSERT INTO test.project_rates VALUES ('A',0.9,'2026-11-01'),('B',0.5,'2026-11-20')")

        async def materialize(_adapter, sql, parameters, *, max_bytes=None):
            queries.append(sql)
            cursor = connection.execute(parse_one(sql, read='mysql').sql(dialect='duckdb'), parameters)
            writer = CsvMaterializer(tuple(item[0] for item in cursor.description), max_bytes=max_bytes)
            writer.append(tuple(cursor.fetchall()))
            return writer.finish()

        monkeypatch.setattr(StarRocksDataSourceAdapter, 'materialize_bound', materialize)
        calculation, = await bases.calculate_adoption_metrics(adoption.target_run_id, scope,
            user_id='7', thread_id='thread-basis', vault=ctx['vault'], dataset_store=store,
            run_context=RunContext(run_id=target.run_id, session_id=target.workspace_key, session_state={}), workflow_scope=target)
        root = next(item for item in calculation.results if item.metric_version == calculation.request.metric_version)

        async def stage(_agent, schema, name, payload, **kwargs):
            if name == 'semantics':
                candidates = payload['knowledgeEvidence']
                assert {item['documentId'] for item in candidates} == {'known-context'}
                evidence, = candidates
                model_inputs.append({'stage': name, 'knowledgeEvidence': candidates})
                return schema.model_validate({'interpretations': [{
                    'claimId': ref['claimId'], 'claimKind': 'inference' if case == 'causal' else 'recommendation',
                    'kindEvidence': ['影响' if case == 'causal' else '建议'],
                    'metricVersion': {'metricId': 'rate', 'revision': 1},
                    'knowledgeRelations': [{'evidenceId': evidence['evidenceId'],
                        'relationship': 'irrelevant' if case == 'unrelated' else 'supports',
                        'explanationType': 'causal' if case == 'causal' else 'recommendation',
                        'sourceEvidence': [early_quote], 'claimEvidence': [statement]}],
                } for ref in payload['references'] if ref.get('referenceKind') == 'narrative']})
            knowledge = payload['businessKnowledge']
            model_inputs.append({'stage': name, 'businessKnowledge': knowledge})
            hits = [hit for receipt in knowledge['receipts'] if receipt['kind'] == 'background'
                for hit in (receipt.get('search') or {}).get('hits', [])]
            assert {hit['documentId'] for hit in hits} == {'known-context'}
            if name == 'plan':
                return schema.model_validate({'kind': 'render', 'sectionCode': payload['sectionGoal']['sectionCode'],
                    'blocks': [{'blockId': 'c33-context', 'objective': '核对执行率并区别解释支持', 'claimIds': ['c33-rate']},
                        *([{'blockId': 'analysis_001', 'objective': '保留独立说明', 'claimIds': ['c33-rate']}]
                            if initial_pipeline else [])],
                    'claims': [{'claimId': 'c33-rate', 'metricCode': 'rate', 'value': str(root.value),
                        'managementQuestionRef': 'analysis_001', 'currentPeriod': '[2026-11-01, 2026-12-01)',
                        'citationIds': ['citation_001'], 'factIds': [root.fact_id],
                        'findingIds': list(payload['sectionWorkItem']['findingIds'])}]})
            assert name == 'content'
            number = '本报告执行率为{{value:' + root.fact_id + ':value:%}}。'
            return schema.model_validate({'blocks': [{'blockId': 'c33-context',
                'markdown': number if initial_pipeline else number + '\n\n' + statement + '。'},
                *([{'blockId': 'analysis_001', 'markdown': statement + '。'}] if initial_pipeline else [])]})

        async def inspect_report(report):
            if knowledge_projection_failure:
                assert knowledge_calls == ['injected']
            variant = ('initial' if initial_pipeline else 'recalculation') + (
                '-knowledge-fault' if knowledge_projection_failure else '-support-fault' if projection_failure else '')
            output = Path('/tmp') / f'smart-reporting-c33-delivery-{os.getpid()}-{case}-{variant}'
            output.mkdir(exist_ok=True)
            document = await report.editor.read_document(report.context)
            index = await report.editor.trace.require_index(report.context)
            narrative, = [item for item in index.subject_bindings if item.narrative_reference is not None]
            knowledge_ref, = narrative.narrative_reference.semantic_receipt.knowledge_references
            assert knowledge_ref.document_id == 'known-context'
            originals = {}
            for document_id, quote in [('known-context', early_quote), ('later-context', late_quote)]:
                raw = await documents.read_original(token, scope, document_id, 1)
                assert raw == quote.encode()
                digest = hashlib.sha256(raw).hexdigest()
                if document_id == 'known-context':
                    assert digest == knowledge_ref.source_hash
                (output / (document_id + '.txt')).write_bytes(raw)
                originals[document_id] = {'sha256': digest, 'size': len(raw),
                    'registration': await documents.get_document(token, scope, document_id)}
            assert late_quote not in document.markdown
            detail = await report.editor.trace.knowledge_detail(report.context, narrative.subject_id, knowledge_ref.evidence_id)
            assert detail['available'] and detail['quote'] == early_quote
            validation = await report.editor.trace.validate(report.context, document.markdown, document.sha256)
            (output / 'server-validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2, default=str))
            support, = [item for item in validation['quality']['claimSupport'] if item['subjectId'] == narrative.subject_id]
            assert support['supportStatus'] == expected, {'support': support, 'issues': validation['quality']['issues']}
            assert support['evidenceRefs'] == [knowledge_ref.evidence_id]
            if case == 'causal':
                assert any('registered_observation_unavailable' in item.get('reasons', []) for item in validation['quality']['issues'])
            adopted = await bases.load_report_basis(target.run_id, scope, user_id='7', thread_id='thread-basis')
            assert adopted.knowledge_as_of == original.knowledge_as_of == cutoff
            assert adopted.background_release_id == original.background_release_id == background.release_id
            assert not any('later-context' in json.dumps(item, ensure_ascii=False) for item in model_inputs)
            shutil.copytree(report.evidence_dir, output / 'native', dirs_exist_ok=True)
            from docx import Document
            from pypdf import PdfReader

            explanation_label = '（推断，待核实）' if case == 'causal' else '（建议' + ('）' if expected == 'supported' else '，待核实）')
            pdf_text = '\n'.join(page.extract_text() or '' for page in PdfReader(output / 'native/c02-corrected.pdf').pages)
            word_text = '\n'.join(paragraph.text for paragraph in Document(output / 'native/c02-corrected.docx').paragraphs)
            if projection_failure:
                assert projection_calls == ['injected']
                assert report.content['validation']['ok'] is False
                assert any(item['code'] == 'claim_support_projection_unknown'
                    for item in report.content['validation']['issues'])
                assert '解释与建议的支持状态未能核验' in re.sub(r'\s+', '', pdf_text)
                assert '解释与建议的支持状态未能核验' in re.sub(r'\s+', '', word_text)
            else:
                assert statement + '。' + explanation_label in re.sub(r'\s+', '', pdf_text)
                assert statement + '。' + explanation_label in re.sub(r'\s+', '', word_text)
                for text in (() if knowledge_projection_failure else (pdf_text, word_text)):
                    compact = re.sub(r'\s+', '', text)
                    assert '业务知识来源' in compact
                    assert '登记引用：known-context（第1版）' in compact
                    assert '原文定位：原件第1–1行' in compact
                    assert early_quote in compact
                    assert late_quote not in compact
            if knowledge_projection_failure:
                assert report.content['validation']['ok'] is False
                assert any(item['code'] == 'knowledge_source_projection_unavailable'
                    for item in report.content['validation']['issues'])
                assert all('业务知识来源' not in text for text in (pdf_text, word_text))
            assert explanation_label not in document.markdown
            (output / 'pdf-text.txt').write_text(pdf_text)
            (output / 'word-text.txt').write_text(word_text)
            evidence = {'caseId': 'C33', 'case': case, 'expectedSupport': expected, 'modelInputs': model_inputs,
                'projectionFailure': projection_failure, 'knowledgeProjectionFailure': knowledge_projection_failure,
                'deliveryValidation': report.content['validation'],
                'basis': adopted.model_dump(mode='json', by_alias=True), 'knowledgeDetail': detail,
                'registeredOriginals': originals, 'initialPipeline': initial_pipeline,
                'subjectId': narrative.subject_id, 'validation': validation, 'queries': queries,
                'markdownSha256': hashlib.sha256(document.markdown.encode()).hexdigest(),
                'knowledgeRefs': [knowledge_ref.model_dump(mode='json', by_alias=True)]}
            from fastapi import FastAPI

            from smart_reporting.report_editor.api import create_report_editor_router
            from smart_reporting.reporting.delivery.publishing import (
                ReportDownloadHttpService,
                create_report_download_router,
            )
            from smart_reporting.tests.report_issue_browser_flow import run_management_browser

            app = FastAPI()
            runtime = report.runtime
            app.include_router(create_report_editor_router(runtime.editor_grants, editor=report.editor, cookie_secure=False))
            app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants,
                runtime.artifact_persistence.repository)))
            grant, _ = await runtime.editor_grants.issue(report.context)
            files = json.loads((report.evidence_dir / 'evidence.json').read_text())['files']
            browser = await run_management_browser(app, {
                'knowledge': True, 'subjectId': narrative.subject_id, 'quote': early_quote, 'excludedQuote': late_quote,
                'expectedSupport': expected, 'basisId': adopted.id, 'reportId': report.context.report_id,
                'revision': report.context.revision, 'grant': grant,
                'downloads': [{**file, 'format': file['file'].rsplit('.', 1)[1],
                    'url': report.delivery['word' if file['file'].endswith('.docx') else 'pdf']['downloadUrl']}
                    for file in files],
            }, output / 'browser', script='smoke/report-historical-retirement-postgres-smoke.mjs')
            assert browser['writes'] == 0 and browser['knowledge']['keyboardToggleVerified']
            assert browser['knowledge']['quote'] == early_quote
            assert len(browser['viewports']) == 4
            assert {item['format'] for item in browser['downloads']} == {'pdf', 'docx'}
            evidence['browser'] = browser
            (output / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
            return evidence

        await exercise_c02_native_delivery(ctx, bases, store, receipt_snapshot[0]['workflow_scope'], adoption,
            calculation, monkeypatch, expected_value='70', section_stage=stage,
            summary_text=statement + '。' if delivery_format in {'xlsx', 'pptx'} else None,
            initial_pipeline=initial_pipeline,
            after_report=after_native_report or inspect_report)


@pytest.mark.parametrize('case,expected', [('known', 'supported'), ('unrelated', 'unverified'), ('causal', 'unverified')])
async def test_c33_historical_background_reaches_report_and_editor_without_later_knowledge(
    basis_context, document_context, receipt_snapshot, monkeypatch, case, expected,
):
    await exercise_background_report(basis_context, document_context, receipt_snapshot, monkeypatch, case, expected)


@pytest.mark.parametrize('initial_pipeline', [True, False], ids=['initial', 'recalculation'])
async def test_document_knowledge_original_reaches_both_delivery_paths(
    basis_context, document_context, receipt_snapshot, monkeypatch, initial_pipeline,
):
    await exercise_background_report(basis_context, document_context, receipt_snapshot, monkeypatch,
        'known', 'supported', initial_pipeline=initial_pipeline)
