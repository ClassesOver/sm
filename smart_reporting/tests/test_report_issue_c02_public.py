"""C02从实际70报告的Editor反馈到原生队列修正报告，不冒充业务签认。"""

import pytest

from smart_reporting.tests.test_report_basis_persistence import auth_context as auth_context
from smart_reporting.tests.test_report_basis_persistence import basis_context as basis_context
from smart_reporting.tests.test_report_basis_persistence import document_context as document_context
from smart_reporting.tests.test_report_basis_persistence import index_context as index_context
from smart_reporting.tests.test_report_basis_persistence import receipt_snapshot as receipt_snapshot

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('outputs', [['pdf', 'docx'], ['pptx'], ['xlsx']], ids=['document', 'pptx', 'xlsx'])
async def test_c02_editor_feedback_queues_corrected_report_and_keeps_original(basis_context, receipt_snapshot, monkeypatch, outputs):
    from smart_reporting.tests.c02_public_flow import exercise_c02_public_flow

    evidence = await exercise_c02_public_flow(basis_context, receipt_snapshot[0], monkeypatch, outputs=outputs)
    assert evidence['originalValue'] == '70' and evidence['correctedValue'] == '63.33'
    assert evidence['resolution']['deliveryReady'] and evidence['resolution']['factPresentationReady']
    assert evidence['resolution']['businessApproval'] == 'not_performed'
    assert evidence['resolution']['issueClosed'] is False


@pytest.mark.parametrize('outputs', [['pdf', 'docx'], ['pptx'], ['xlsx']], ids=['document', 'pptx', 'xlsx'])
async def test_c02_public_report_signoff_and_resolution_keep_original(basis_context, receipt_snapshot, monkeypatch, outputs):
    from smart_reporting.tests.c02_public_flow import exercise_c02_public_flow

    evidence = await exercise_c02_public_flow(basis_context, receipt_snapshot[0], monkeypatch, outputs=outputs, close_issue=True)
    assert evidence['closure']['issueClosed'] and evidence['closure']['request']['mode'] == 'recalculated'
    assert evidence['closure']['evidence']['deliveryReady'] and evidence['closure']['evidence']['factPresentationReady']
    assert evidence['closure']['evidence']['newReportRevision'] != 'initial'
    assert evidence['closure']['evidence']['businessApprovalReady']
    delivered, = evidence['closure']['evidence']['deliveries']
    assert delivered['targetRunId'] == evidence['targetRunId']
    assert sorted(item['format'] for item in delivered['artifacts']) == sorted(outputs)
    assert {(item['format'], item['sha256'], item['size']) for item in delivered['artifacts']} == {
        (item['file'].rsplit('.', 1)[1], item['sha256'], item['size']) for item in evidence['files']
    }
    assert evidence['businessQueries'] == 4 and evidence['originalValue'] == '70'


async def test_c02_native_report_is_signed_and_closed_in_real_browser(basis_context, receipt_snapshot, monkeypatch):
    from smart_reporting.tests.c02_public_flow import exercise_c02_public_flow

    evidence = await exercise_c02_public_flow(basis_context, receipt_snapshot[0], monkeypatch,
        outputs=['pptx'], close_issue=True, browser_close=True)
    assert evidence['closure']['issueClosed'] and evidence['closure']['request']['mode'] == 'recalculated'
    assert evidence['closure']['evidence']['factPresentationReady']
    assert evidence['browser']['signingPosts'] == evidence['browser']['closingPosts'] == 1
    assert evidence['browser']['closureReads'] == 2
    assert evidence['businessQueries'] == 4


@pytest.mark.parametrize('outputs', [['pdf', 'docx'], ['pptx'], ['xlsx']], ids=['document', 'pptx', 'xlsx'])
async def test_c37_retired_metric_keeps_historical_report_and_downloads_in_browser(basis_context, receipt_snapshot, monkeypatch, outputs):
    from smart_reporting.tests.c02_public_flow import exercise_c02_public_flow

    evidence = await exercise_c02_public_flow(basis_context, receipt_snapshot[0], monkeypatch,
        outputs=outputs, browser_history=True)
    history = evidence['historicalBrowser']
    assert history['oldValue'] == '70'
    assert history['metricRevision'] == 1
    assert history['basisId'] == evidence['originalBasisId']
    assert history['writes'] == 0
    assert {item['format'] for item in history['downloads']} == set(outputs)
    assert len(history['viewports']) == 4
    assert evidence['businessQueries'] == 4


async def test_c36_actual_editor_feedback_is_read_back_and_drives_corrected_report(basis_context, receipt_snapshot, monkeypatch):
    from smart_reporting.tests.c02_public_flow import exercise_c02_public_flow

    evidence = await exercise_c02_public_flow(basis_context, receipt_snapshot[0], monkeypatch,
        outputs=['pptx'], browser_feedback=True)
    feedback = evidence['feedbackBrowser']
    assert feedback['issuePosts'] == 1 and feedback['unknownResponseReadback']
    assert feedback['issueId'] == evidence['issueId']
    assert feedback['objectRefs'] and feedback['category'] == 'calculation'
    assert evidence['originalValue'] == '70' and evidence['correctedValue'] == '63.33'
    assert evidence['businessQueries'] == 4


async def test_c36_browser_confirms_adoption_and_recovers_lost_response(basis_context, receipt_snapshot, monkeypatch):
    from smart_reporting.tests.c02_public_flow import exercise_c02_public_flow

    evidence = await exercise_c02_public_flow(basis_context, receipt_snapshot[0], monkeypatch,
        outputs=['pptx'], browser_feedback=True, browser_adoption=True)
    adoption = evidence['adoptionBrowser']
    assert adoption['adoptionPosts'] == 1 and adoption['unknownResponseReadback']
    assert adoption['request']['operation'] == 'adopt_policy'
    assert adoption['request']['confirmation']['targetPolicyVersion'] == {'policyId': 'monthly-budget', 'revision': 3}
    assert adoption['submitted']['taskId'] == evidence['taskId']
    assert evidence['originalValue'] == '70' and evidence['correctedValue'] == '63.33'
    assert evidence['businessQueries'] == 4


async def test_c36_browser_repairs_and_publishes_exact_metric_and_policy(basis_context, receipt_snapshot, monkeypatch):
    from smart_reporting.tests.c02_public_flow import exercise_c02_public_flow

    evidence = await exercise_c02_public_flow(basis_context, receipt_snapshot[0], monkeypatch,
        outputs=['pptx'], browser_feedback=True, browser_adoption=True, browser_repair=True)
    repair = evidence['repairBrowser']
    assert repair['metricSaves'] == repair['metricPublications'] == 1
    assert repair['policySaves'] == repair['policyPublications'] == 1
    assert repair['metricVersion'] == {'metricId': 'rate', 'revision': 2}
    assert repair['policyVersion'] == {'policyId': 'monthly-budget', 'revision': 3}
    assert evidence['originalValue'] == '70' and evidence['correctedValue'] == '63.33'
    assert evidence['businessQueries'] == 4


async def test_c36_browser_accepts_issue_and_links_exact_published_corrections(basis_context, receipt_snapshot, monkeypatch):
    from smart_reporting.tests.c02_public_flow import exercise_c02_public_flow

    evidence = await exercise_c02_public_flow(basis_context, receipt_snapshot[0], monkeypatch,
        outputs=['pptx'], browser_feedback=True, browser_adoption=True, browser_repair=True, browser_decisions=True)
    repair = evidence['repairBrowser']
    assert repair['decisionPosts'] == 2 and repair['decisionUnknownReadbacks'] == 2
    assert repair['issueId'] == evidence['issueId']
    assert repair['linkedVersions'] == [
        {'assetType': 'metric', 'assetId': 'rate', 'revision': 2},
        {'assetType': 'statistical_policy', 'assetId': 'monthly-budget', 'revision': 3},
    ]
    assert evidence['originalValue'] == '70' and evidence['correctedValue'] == '63.33'
    assert evidence['businessQueries'] == 4


async def test_c36_browser_regressions_continue_to_signed_resolution(basis_context, receipt_snapshot, monkeypatch):
    from smart_reporting.tests.c02_public_flow import exercise_c02_public_flow

    evidence = await exercise_c02_public_flow(basis_context, receipt_snapshot[0], monkeypatch,
        outputs=['pptx'], browser_feedback=True, browser_adoption=True, browser_repair=True,
        browser_decisions=True, browser_regressions=True, close_issue=True, browser_close=True)
    regression = evidence['regressionBrowser']
    assert regression['posts'] == regression['unknownReadbacks'] == 2
    assert [item['status'] for item in regression['receipts']] == ['failed', 'passed']
    assert all(item['businessApproval'] == 'not_performed' for item in regression['receipts'])
    assert evidence['closure']['issueClosed'] and evidence['closure']['evidence']['businessApprovalReady']
    assert evidence['browser']['signingPosts'] == evidence['browser']['closingPosts'] == 1
    assert evidence['originalValue'] == '70' and evidence['correctedValue'] == '63.33'
    assert evidence['businessQueries'] == 4
