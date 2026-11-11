"""正式指标来源经实际签发、修订迁移和编辑器授权读取。"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor import (
    ReportEditorContext,
    ReportEditorService,
    create_report_editor_router,
)
from smart_reporting.reporting.tests.test_http_publication_lineage import _publication_fixture
from smart_reporting.reporting.tests.test_registered_analysis_facts import analysis_inputs


@pytest.mark.anyio
@pytest.mark.parametrize('unavailable', [False, True])
async def test_registered_results_visible_in_authorized_editor_and_reject_changed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unavailable: bool,
):
    from smart_reporting.reporting.tests import test_registered_analysis_facts

    _, _, original_result = analysis_inputs()
    if unavailable:
        def unavailable_inputs():
            analysis, view, result = analysis_inputs()
            result = result.model_copy(update={'value': None, 'status': 'unavailable',
                'issue_codes': ('missing_data',), 'dataset_ids': ()})
            calculation = view.calculations[0].model_copy(update={'results': (result,)})
            return analysis, view.model_copy(update={'calculations': (calculation,)}), result

        monkeypatch.setattr(test_registered_analysis_facts, 'analysis_inputs', unavailable_inputs)
    runtime, arguments, scope, durable, _, _, _, _ = await _publication_fixture(
        tmp_path, registered_result=True,
    )
    publication = await runtime.issue_http_publication(**arguments)
    editor = ReportEditorService(
        state_repository=runtime.state_repository,
        workspace_registry=runtime.workspace_registry,
        workspace=runtime.workspace_service,
        trace_cursor_secret=b'trace-cursor-secret-32-bytes-ok!',
    )
    app = FastAPI()
    app.include_router(create_report_editor_router(runtime.editor_grants, editor=editor, cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        assert (await client.get('/reports/v1/editor/report-1/2/api/sources')).status_code == 404
        opened = await client.get(publication['editor']['openUrl'], follow_redirects=False)
        assert opened.status_code == 303
        response = await client.get('/reports/v1/editor/report-1/2/api/sources')
        assert response.status_code == 200
        payload = response.json()
        fact, = payload['facts']
        _, view, result = analysis_inputs()
        assert fact['factId'] == result.fact_id
        assert fact['name'] == view.metrics[0].name
        assert fact['displayValue'] == (None if unavailable else str(original_result.value))
        assert fact['metricVersion'] == result.metric_version.model_dump(mode='json', by_alias=True)
        assert fact['basisId'] == result.basis_id
        assert fact['calculationId'] == result.calculation_id
        assert fact['period'] == result.period.model_dump(mode='json')
        assert fact['periodBoundary'] == 'half_open'
        assert fact['periodRoles'] == []
        assert fact['status'] == ('unavailable' if unavailable else 'computed')
        assert fact['issueCodes'] == (['missing_data'] if unavailable else list(result.issue_codes))
        assert fact['datasetIds'] == ['dataset-url-abc0001']
        assert f'[{result.period.start}, {result.period.end})' in fact['label']

        detail = await client.get(f'/reports/v1/editor/report-1/2/api/facts/{fact["analysisId"]}/{fact["factId"]}')
        assert detail.status_code == 200
        assert detail.json()['entry']['metricVersion'] == fact['metricVersion']
        assert detail.json()['entry']['period'] == fact['period']
        assert detail.json()['displayValue'] == fact['displayValue']

        context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
        runtime.workspace_registry.resolve(scope)
        _, index = await editor.trace.load_manifest_and_index(context)
        file_ref = next(item for item in index.files if item.resource_id == index.fact_files[0].file_resource_id)
        await runtime.workspace_service.awrite_bytes(scope.workspace_key, file_ref.path, b'{}', overwrite=True)
        response = await client.get('/reports/v1/editor/report-1/2/api/sources')
        assert response.status_code == 200
        assert response.json()['facts'] == []
        assert response.json()['datasets']
        rejected = await client.get(f'/reports/v1/editor/report-1/2/api/facts/{fact["analysisId"]}/{fact["factId"]}')
        assert rejected.status_code == 409


@pytest.mark.anyio
async def test_editor_does_not_relabel_result_from_a_different_registered_basis(tmp_path, monkeypatch):
    from smart_reporting.reporting.tests import test_http_publication_lineage as fixtures

    original_builder = fixtures.build_csv_trace_index

    def foreign_basis_index(**values):
        return original_builder(**{**values, 'report_basis_id': 'basis-foreign'})

    monkeypatch.setattr(fixtures, 'build_csv_trace_index', foreign_basis_index)
    runtime, arguments, _, _, _, _, _, _ = await _publication_fixture(tmp_path, registered_result=True)
    publication = await runtime.issue_http_publication(**arguments)
    editor = ReportEditorService(state_repository=runtime.state_repository,
        workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
        trace_cursor_secret=b'trace-cursor-secret-32-bytes-ok!')
    app = FastAPI()
    app.include_router(create_report_editor_router(runtime.editor_grants, editor=editor, cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        await client.get(publication['editor']['openUrl'], follow_redirects=False)
        response = await client.get('/reports/v1/editor/report-1/2/api/sources')
        assert response.status_code == 200
        assert response.json()['facts'] == []
        detail = await client.get('/reports/v1/editor/report-1/2/api/facts/analysis_001/fact-budget')
        assert detail.status_code == 409
    assert publication['pdf']['downloadUrl'] and publication['word']['downloadUrl']
