"""真实报告入口保留语义选择，依据摘要只接收服务端组织身份。"""

import pytest

from smart_reporting.reporting.contract import ReportingWorkflowInput, ReportRequestEnvelope
from smart_reporting.reporting.models import ReportingError


def request_payload(**changes):
    return {
        'reportGoal': '核对本月预算执行并解释差异',
        'period': {'start': '2024-02-01', 'end': '2024-02-29'},
        'scenario': 'budget_execution',
        'statisticalPolicyVersion': {'policyId': 'monthly-budget', 'revision': 2},
        'questions': [
            {'id': 'q-amount', 'text': '实际执行额是多少？'},
            {'id': 'q-reason', 'text': '差异有哪些已证实的原因？'},
        ],
        'displayUnit': '万元',
        'comparisonRoles': [],
        **changes,
    }


def test_public_entry_preserves_exact_policy_and_distinct_questions_through_payload():
    request = ReportingWorkflowInput.model_validate(request_payload()).request()
    payload = request.workflow_payload(default_source_ids=('warehouse',))
    restored = ReportRequestEnvelope.from_untrusted(payload)
    assert restored.statistical_policy_version.policy_id == 'monthly-budget'
    assert restored.statistical_policy_version.revision == 2
    assert [(question.id, question.text) for question in restored.questions] == [
        ('q-amount', '实际执行额是多少？'), ('q-reason', '差异有哪些已证实的原因？'),
    ]
    assert restored.scenario == 'budget_execution'
    assert restored.display_unit == '万元'


def test_basis_summary_uses_server_organization_and_converts_inclusive_leap_month():
    from smart_reporting.reporting.semantics.request import summarize_report_request

    request = ReportRequestEnvelope.from_untrusted(request_payload(
        comparisonPeriod={'start': '2023-02-01', 'end': '2023-02-28'},
    ))
    summary = summarize_report_request(request, organization='trusted-org')
    assert summary.organization == 'trusted-org'
    assert summary.period.model_dump(mode='json') == {'start': '2024-02-01', 'end': '2024-03-01'}
    assert summary.comparison_period.model_dump(mode='json') == {'start': '2023-02-01', 'end': '2023-03-01'}
    assert summary.requested_outputs == ('pdf', 'docx')
    assert [item.id for item in summary.questions] == ['q-amount', 'q-reason']
    assert summary.display_unit == '万元'


def test_request_cannot_self_register_organization_or_duplicate_question_identity():
    for changes in (
        {'organization': 'foreign-org'},
        {'questions': [{'id': 'same', 'text': '问题一'}, {'id': 'same', 'text': '问题二'}]},
        {'statisticalPolicyVersion': {'policyId': 'monthly-budget', 'revision': True}},
    ):
        with pytest.raises(ReportingError) as error:
            ReportRequestEnvelope.from_untrusted(request_payload(**changes))
        assert error.value.code == 'report_request_invalid'


def test_summary_does_not_guess_missing_scenario_and_records_actual_defaults():
    from smart_reporting.reporting.semantics.request import summarize_report_request

    request = ReportRequestEnvelope.from_untrusted({
        'reportGoal': '核对执行额', 'period': {'start': '2026-11-01', 'end': '2026-11-30'},
        'comparisonRoles': [],
    })
    with pytest.raises(ReportingError) as error:
        summarize_report_request(request, organization='trusted-org')
    assert error.value.code == 'report_scenario_missing'
    summary = summarize_report_request(
        request.model_copy(update={'scenario': 'budget_execution'}), organization='trusted-org',
    )
    assert [(item.id, item.text) for item in summary.questions] == [('goal', '核对执行额')]
    assert summary.display_unit == '指标原始单位'
    assert {(item.field, item.source) for item in summary.assumptions} >= {
        ('questions', 'default'), ('displayUnit', 'default'), ('requestedOutputs', 'default'),
    }


def test_summary_does_not_silently_drop_multiple_comparison_windows():
    from smart_reporting.reporting.semantics.request import summarize_report_request

    request = ReportRequestEnvelope.from_untrusted(request_payload(comparisonRoles=['yoy', 'mom']))
    with pytest.raises(ReportingError) as error:
        summarize_report_request(request, organization='trusted-org')
    assert error.value.code == 'report_comparison_ambiguous'


@pytest.mark.parametrize('domains', [None, ['budget'], ['funds', 'budget']])
def test_policy_adoption_preserves_frozen_request_domains(domains):
    from types import SimpleNamespace

    from smart_reporting.reporting.semantics.models import ReportRequestSummary
    from smart_reporting.reporting.semantics.request import summarize_report_request
    from smart_reporting.reporting.workflow.policy_adoption_analysis import _request

    original = ReportRequestEnvelope.from_untrusted(request_payload(domains=domains))
    summary = summarize_report_request(original, organization='trusted-org')
    restored = ReportRequestSummary.model_validate_json(summary.model_dump_json(by_alias=True))
    basis = SimpleNamespace(request_summary=restored,
        policy_version={'policyId': 'monthly-budget', 'revision': 3},
        source_versions=(SimpleNamespace(source_id='warehouse'),))
    adopted = _request(basis, 'topic')
    assert adopted.domains == original.domains
    assert adopted.period == original.period
    assumption = next(item for item in restored.assumptions if item.field == 'domains')
    assert assumption.source == ('default' if domains is None else 'explicit')


@pytest.mark.parametrize('domains', [[], ['budget', 'budget'], ['unknown'], ['预算']])
def test_frozen_request_summary_rejects_invalid_domain_scope(domains):
    from pydantic import ValidationError

    from smart_reporting.reporting.semantics.models import ReportRequestSummary
    from smart_reporting.reporting.semantics.request import summarize_report_request

    summary = summarize_report_request(
        ReportRequestEnvelope.from_untrusted(request_payload()), organization='trusted-org')
    with pytest.raises(ValidationError):
        ReportRequestSummary.model_validate({**summary.model_dump(), 'domains': domains})


def test_semantic_scope_import_does_not_require_workflow_contract_first():
    import subprocess
    import sys

    subprocess.run([sys.executable, '-c',
        'from smart_reporting.management.report_bases import ReportBasisService; '
        'from smart_reporting.reporting.semantics.models import ReportRequestSummary'],
        check=True, capture_output=True, text=True, timeout=60)


@pytest.mark.anyio
async def test_structured_normalization_records_semantic_request_without_changing_selection():
    from types import SimpleNamespace

    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    runtime = object.__new__(ReportWorkflowRuntime)
    context = SimpleNamespace(session_state={})
    output = await runtime.normalize_report_request(
        SimpleNamespace(input=request_payload(), additional_data=None), context,
    )
    recorded = context.session_state['report_request_context']
    assert recorded['scenario'] == 'budget_execution'
    assert recorded['statisticalPolicyVersion'] == {'policyId': 'monthly-budget', 'revision': 2}
    assert recorded['questions'] == request_payload()['questions']
    assert output.content['statisticalPolicyVersion'] == recorded['statisticalPolicyVersion']


@pytest.mark.anyio
async def test_explicit_questions_remain_separate_in_actual_coverage_denominator():
    from types import SimpleNamespace

    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    runtime = object.__new__(ReportWorkflowRuntime)
    context = SimpleNamespace(session_state={})
    await runtime.normalize_report_request(
        SimpleNamespace(input=request_payload(), additional_data=None), context,
    )
    questions = context.session_state['report_request_context']['questionSpecs']
    assert questions['requiredQuestionIds'] == ['q-amount', 'q-reason']
    assert [(item['questionId'], item['text']) for item in questions['questions']] == [
        ('q-amount', '实际执行额是多少？'), ('q-reason', '差异有哪些已证实的原因？'),
    ]


def test_replanning_keeps_original_explicit_questions_when_analysis_changes():
    from smart_reporting.reporting.semantics.request_types import ReportQuestion
    from smart_reporting.reporting.workflow.questions import (
        freeze_analysis_questions,
        freeze_plan_questions,
        request_questions,
    )

    original = request_questions('核对预算', questions=(
        ReportQuestion(id='q-amount', text='执行额是多少？'),
        ReportQuestion(id='q-reason', text='原因是什么？'),
    ))
    current = freeze_analysis_questions(original, [{
        'analysisId': 'analysis_001', 'managementQuestion': '执行额',
        'completionConditions': ['核对金额'],
    }])
    changed = freeze_plan_questions(current, [{
        'analysisId': 'analysis_002', 'managementQuestion': '核验原因',
        'completionConditions': ['核对事件'],
    }], goal='核对预算')
    assert changed.required_question_ids == ('q-amount', 'q-reason')
    assert [(item.question_id, item.text) for item in changed.questions if item.kind == 'request'] == [
        ('q-amount', '执行额是多少？'), ('q-reason', '原因是什么？'),
    ]


@pytest.mark.anyio
async def test_natural_language_normalization_preserves_semantic_questions_and_scenario():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    from smart_reporting.reporting.workflow.runtime.models import NormalizedReportPrompt

    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()
    runtime._run_planner = AsyncMock(return_value=NormalizedReportPrompt(
        reportType='topic', domains=['budget'], scenario='budget_execution',
        period={'start': '2026-11-01', 'end': '2026-11-30'},
        questions=[{'id': 'q-amount', 'text': '执行额是多少？'}, {'id': 'q-reason', 'text': '原因是什么？'}],
        displayUnit='万元',
    ))
    context = SimpleNamespace(session_state={})
    output = await runtime.normalize_report_request(
        SimpleNamespace(input='请核对11月执行额并解释差异，金额用万元', additional_data=None), context,
    )
    assert output.content['scenario'] == 'budget_execution'
    assert output.content['displayUnit'] == '万元'
    assert [item['id'] for item in output.content['questions']] == ['q-amount', 'q-reason']
    assert context.session_state['report_request_context']['questionSpecs']['requiredQuestionIds'] == ['q-amount', 'q-reason']
    assert 'statisticalPolicyVersion' not in output.content


def test_public_workflow_boundary_does_not_turn_default_outputs_into_user_choice():
    from smart_reporting.reporting.semantics.request import summarize_report_request

    payload = {
        'reportGoal': '核对预算', 'scenario': 'budget_execution',
        'period': {'start': '2026-11-01', 'end': '2026-11-30'},
        'comparisonRoles': [],
    }
    request = ReportingWorkflowInput.model_validate(payload).request()
    summary = summarize_report_request(request, organization='trusted-org')
    assert next(item.source for item in summary.assumptions if item.field == 'requestedOutputs') == 'default'
    explicit = ReportingWorkflowInput.model_validate({**payload, 'deliveryFormat': 'document'}).request()
    summary = summarize_report_request(explicit, organization='trusted-org')
    assert next(item.source for item in summary.assumptions if item.field == 'requestedOutputs') == 'explicit'


@pytest.mark.anyio
async def test_normalization_and_saved_payload_preserve_default_assumption_sources():
    from types import SimpleNamespace

    from smart_reporting.reporting.semantics.request import summarize_report_request
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    runtime = object.__new__(ReportWorkflowRuntime)
    payload = {
        'reportGoal': '核对预算', 'scenario': 'budget_execution',
        'period': {'start': '2026-11-01', 'end': '2026-11-30'},
    }
    for extra, expected in (({}, 'default'), ({'deliveryFormat': 'document', 'comparisonRoles': ['yoy']}, 'explicit')):
        context = SimpleNamespace(session_state={})
        output = await runtime.normalize_report_request(
            SimpleNamespace(input={**payload, **extra}, additional_data=None), context,
        )
        restored = ReportRequestEnvelope.from_untrusted(output.content)
        saved = restored.workflow_payload(default_source_ids=('warehouse',))
        summary = summarize_report_request(ReportRequestEnvelope.from_untrusted(saved), organization='trusted-org')
        sources = {item.field: item.source for item in summary.assumptions}
        assert sources['requestedOutputs'] == expected
        assert sources['comparisonPeriod'] == expected

def test_explicit_knowledge_cutoff_survives_public_envelope_and_summary():
    from smart_reporting.reporting.semantics.request import summarize_report_request

    request = ReportingWorkflowInput.model_validate(
        request_payload(knowledgeAsOf="2024-02-20T18:00:00+08:00")
    ).request()
    restored = ReportRequestEnvelope.from_untrusted(
        request.workflow_payload(default_source_ids=("warehouse",))
    )
    assert restored.knowledge_as_of.isoformat() == "2024-02-20T18:00:00+08:00"
    summary = summarize_report_request(restored, organization="trusted-org")
    assumption = next(item for item in summary.assumptions if item.field == "knowledgeAsOf")
    assert (
        assumption.source == "explicit" and assumption.value == restored.knowledge_as_of.isoformat()
    )


@pytest.mark.parametrize("cutoff", ["2024-02-20", "2024-02-20T18:00:00", 123, True])
def test_knowledge_cutoff_requires_an_explicit_timezone_aware_datetime(cutoff):
    with pytest.raises(ReportingError):
        ReportRequestEnvelope.from_untrusted(request_payload(knowledgeAsOf=cutoff))


@pytest.mark.anyio
async def test_normalization_records_explicit_knowledge_cutoff():
    from types import SimpleNamespace

    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    runtime = object.__new__(ReportWorkflowRuntime)
    context = SimpleNamespace(session_state={})
    output = await runtime.normalize_report_request(
        SimpleNamespace(
            input=request_payload(knowledgeAsOf="2024-02-20T10:00:00Z"), additional_data=None
        ),
        context,
    )
    assert (
        context.session_state["report_request_context"]["knowledgeAsOf"] == "2024-02-20T10:00:00Z"
    )
    assert output.content["knowledgeAsOf"] == "2024-02-20T10:00:00Z"


def test_policy_adoption_keeps_an_explicit_historical_knowledge_cutoff():
    from types import SimpleNamespace

    from smart_reporting.reporting.semantics.request import summarize_report_request
    from smart_reporting.reporting.workflow.policy_adoption_analysis import _request

    original = ReportRequestEnvelope.from_untrusted(
        request_payload(knowledgeAsOf="2024-02-20T10:00:00Z")
    )
    basis = SimpleNamespace(
        request_summary=summarize_report_request(original, organization="trusted-org"),
        knowledge_as_of=original.knowledge_as_of,
        policy_version={"policyId": "monthly-budget", "revision": 3},
        source_versions=(SimpleNamespace(source_id="warehouse"),),
    )
    assert _request(basis, "topic").knowledge_as_of == original.knowledge_as_of


@pytest.mark.parametrize('cutoff', [123, True, '2024-02-20T10:00:00'])
def test_top_level_workflow_rejects_implicit_knowledge_timestamp(cutoff):
    from pydantic import ValidationError

    with pytest.raises((ValidationError, ReportingError)):
        ReportingWorkflowInput.model_validate(request_payload(knowledgeAsOf=cutoff))


def test_prompt_cannot_hide_an_explicit_knowledge_cutoff():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReportingWorkflowInput.model_validate({'prompt':'生成预算报告','knowledgeAsOf':'2024-02-20T10:00:00Z'})


@pytest.mark.anyio
async def test_runtime_rejects_changed_cutoff_before_restoring_execution_catalog():
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.semantics.request import summarize_report_request
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    envelope = ReportRequestEnvelope.from_untrusted(request_payload(knowledgeAsOf='2024-02-20T10:00:00Z'))
    basis = SimpleNamespace(scope_id='trusted-org', request_summary=summarize_report_request(envelope, organization='trusted-org'),
        knowledge_as_of=datetime(2024,2,19,tzinfo=UTC), policy_version=envelope.statistical_policy_version)
    service = SimpleNamespace(load_execution_context=AsyncMock(return_value=SimpleNamespace(basis=basis,sources={})))
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = SimpleNamespace(vault=object())
    runtime.report_basis_service = service
    runtime._scope = lambda _: {'database':'warehouse','companyId':'a','userId':'7','callerThreadId':'thread'}
    runtime._envelope = lambda _: envelope
    with pytest.raises(ReportingError) as error:
        await runtime._basis_execution_context(SimpleNamespace(run_id='run',session_state={'report_schema_snapshots':[]}))
    assert error.value.code == 'management_runtime_request_mismatch'
