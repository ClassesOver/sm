"""语义召回可以换措辞；服务端只按登记的精确身份消歧和授权。"""

from datetime import UTC, datetime

import pytest

from smart_reporting.reporting.semantics.basis import BasisExecutionContext
from smart_reporting.reporting.semantics.models import (
    MetricCandidate,
    MetricDefinition,
    MetricVersionRef,
    ReportBasis,
    StatisticalPolicy,
)
from smart_reporting.reporting.tests.test_metric_compilation import catalog
from smart_reporting.reporting.tests.test_semantic_models import metric_payload, policy_payload


def selection_context(*, questions=None):
    metrics = (MetricDefinition.model_validate(metric_payload()),
        MetricDefinition.model_validate(metric_payload("actual", name="实际额", fieldRef="warehouse.test.actual.amount",
            timeField="warehouse.test.actual.period")))
    policy = StatisticalPolicy.model_validate(policy_payload(metricVersions=[
        {"metricId": item.id, "revision": 1} for item in metrics]))
    now = datetime(2026, 11, 9, tzinfo=UTC)
    basis = ReportBasis(id="basis-selection", runId="run-selection", scopeId="org-a",
        policyVersion={"policyId": policy.id, "revision": 1},
        metricVersions=tuple(metric.version_ref() for metric in metrics),
        sourceVersions=[{"sourceId": "warehouse", "revision": 1, "contentHash": "a" * 64}],
        catalogRefs=[{"sourceId": "warehouse", "revision": 1, "contentHash": "b" * 64}],
        evidenceReleaseId="rules-v1", requestSummary={"goal": "核对预算", "scenario": "budget_execution",
            "organization": "org-a", "period": {"start": "2026-11-01", "end": "2026-12-01"},
            "displayUnit": "CNY", "requestedOutputs": ["pdf"],
            "questions": questions or [{"id": "q-budget", "text": "预算是多少？"}]},
        buildIdentity={"commit": "a" * 40, "sourceHash": "b" * 64,
            "dependencyHash": "c" * 64, "compilerVersion": "semantic-v1"},
        registeredAt=now, knowledgeAsOf=now)
    from smart_reporting.reporting.contract import (
        ModelTermsResponse,
        RawDdlModel,
        SourceRef,
        schema_hash,
    )
    tables = catalog()
    metadata = ModelTermsResponse(revision="catalog-1", schemaHash=schema_hash(tables),
        sourceRefs=(SourceRef(sourceId="warehouse"),), tables=tables, ddlModels=tuple(
            RawDdlModel(id=index, modelName=table.name, ddl=f"CREATE TABLE test.{table.name} (project_id VARCHAR NOT NULL, amount DECIMAL(18,2), period DATE NOT NULL)")
            for index, table in enumerate(tables, 1)))
    return BasisExecutionContext(basis, policy, metrics, {}, {"warehouse": metadata})


def candidate(identity, revision=1):
    return MetricCandidate(metricVersion={"metricId": identity, "revision": revision}, reason="语义候选，尚未经用户确认")


def test_two_candidates_remain_ambiguous_and_show_formula_differences():
    from smart_reporting.reporting.semantics.selection import select_metric_candidates
    context = selection_context()
    selection = select_metric_candidates("q-budget", context, candidates=(candidate("budget"), candidate("actual")))
    assert selection.status == "ambiguous" and selection.selected is None
    assert selection.issue_codes == ("metric_ambiguous",)
    assert "warehouse.test.budget.amount" in selection.candidates[0].reason
    assert "warehouse.test.actual.amount" in selection.candidates[1].reason


def test_explicit_and_clarified_choices_use_exact_versions_without_name_matching():
    from smart_reporting.reporting.semantics.selection import select_metric_candidates
    context = selection_context(questions=[{"id": "q-budget", "text": "这次按批准的额度算"}])
    selection = select_metric_candidates("q-budget", context, candidates=(candidate("budget"), candidate("actual")),
        clarified=MetricVersionRef(metricId="budget", revision=1))
    assert selection.status == "resolved" and selection.selected.metric_id == "budget"
    assert selection.source == "clarified" and selection.reason
    direct = select_metric_candidates("q-budget", context, explicit=MetricVersionRef(metricId="actual", revision=1))
    assert direct.status == "resolved" and direct.source == "explicit"


def test_no_candidates_does_not_choose_only_or_latest_policy_metric():
    from smart_reporting.reporting.semantics.selection import select_metric_candidates
    context = selection_context()
    selection = select_metric_candidates("q-budget", context)
    assert selection.status == "unavailable" and selection.selected is None
    assert selection.issue_codes == ("metric_no_match",)


def test_unregistered_questions_versions_or_conflicting_choices_are_rejected():
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.semantics.selection import select_metric_candidates
    context = selection_context()
    for question, kwargs in [("forged-question", {}), ("q-budget", {"candidates": (candidate("budget", 2),)}),
        ("q-budget", {"explicit": MetricVersionRef(metricId="foreign", revision=1)}),
        ("q-budget", {"explicit": MetricVersionRef(metricId="budget", revision=1),
            "clarified": MetricVersionRef(metricId="actual", revision=1)})]:
        with pytest.raises(ReportingError):
            select_metric_candidates(question, context, **kwargs)


def test_invalid_candidate_does_not_hide_other_questions_or_compute_missing_fields():
    from smart_reporting.reporting.semantics.selection import select_metric_candidates
    context = selection_context()
    missing = context.metrics[1].model_copy(update={"field_ref": "warehouse.test.hidden.amount"})
    context = BasisExecutionContext(context.basis, context.policy, (context.metrics[0], missing), {}, context.metadata)
    selection = select_metric_candidates("q-budget", context, candidates=(candidate("actual"),))
    assert selection.status == "unavailable" and selection.selected is None
    assert selection.issue_codes
    valid = select_metric_candidates("q-budget", context, explicit=context.metrics[0].version_ref())
    assert valid.status == "resolved"
