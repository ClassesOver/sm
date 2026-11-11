"""发布预览必须保留同名多版本，并按依赖图规模处理共享子图。"""

from smart_reporting.management.statistical_policies import StatisticalPolicyService
from smart_reporting.reporting.semantics.models import MetricDefinition, StatisticalPolicy
from smart_reporting.reporting.tests.test_metric_compilation import policy
from smart_reporting.reporting.tests.test_semantic_models import (
    metric_payload,
    policy_payload,
    ratio_payload,
)


def test_first_of_two_same_id_versions_cannot_be_hidden_by_second_version():
    first = MetricDefinition.model_validate(metric_payload())
    second = MetricDefinition.model_validate(metric_payload(revision=2))
    changed = MetricDefinition.model_validate(metric_payload(revision=3, fieldRef="warehouse.test.actual.amount"))
    old_policy = StatisticalPolicy.model_validate(policy_payload(metricVersions=[{"metricId": "budget", "revision": value} for value in (1, 2)]))
    new_policy = StatisticalPolicy.model_validate(policy_payload(metricVersions=[{"metricId": "budget", "revision": value} for value in (3, 2)]))
    old = StatisticalPolicyService._calculation_signature(old_policy, {item.version_ref(): item for item in (first, second)})
    new = StatisticalPolicyService._calculation_signature(new_policy, {item.version_ref(): item for item in (changed, second)})
    assert old != new


def test_shared_metric_dependency_is_resolved_once_for_signature(monkeypatch):
    metrics = [MetricDefinition.model_validate(metric_payload("leaf"))]
    for index in range(11):
        previous = metrics[-1].id
        metrics.append(MetricDefinition.model_validate(ratio_payload(f"ratio-{index}", numerator=previous, denominator=previous)))
    selected = policy(metrics[-1].id)
    calls = 0
    original = MetricDefinition.model_dump
    def tracked(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)
    monkeypatch.setattr(MetricDefinition, "model_dump", tracked)
    assert StatisticalPolicyService._calculation_signature(selected, {item.version_ref(): item for item in metrics})
    assert calls <= len(metrics)
