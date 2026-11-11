"""定义级检查不执行SQL；业务不可计算逐指标返回，身份失配拒绝使用。"""

from .models import MetricDefinition, MetricVersionRef, SemanticIssue, StatisticalPolicy


def validate_policy(
    policy: StatisticalPolicy, metrics: tuple[MetricDefinition, ...],
) -> tuple[SemanticIssue, ...]:
    return validate_metric_graph(policy.scope_id, policy.metric_versions, metrics)


def validate_metric_graph(
    scope_id: str, roots: tuple[MetricVersionRef, ...], metrics: tuple[MetricDefinition, ...],
) -> tuple[SemanticIssue, ...]:
    if any(metric.scope_id != scope_id for metric in metrics):
        raise ValueError("metric scope不匹配")
    versions = {metric.version_ref(): metric for metric in metrics}
    if len(versions) != len(metrics):
        raise ValueError("同一指标版本不能重复登记")
    issues: list[SemanticIssue] = []
    visited: set[MetricVersionRef] = set()
    visiting: set[MetricVersionRef] = set()

    def issue(code: str, ref: MetricVersionRef, message: str) -> None:
        value = SemanticIssue(code=code, object_id=f"{ref.metric_id}:{ref.revision}", message=message, impact="unavailable")
        if value not in issues:
            issues.append(value)

    def visit(ref: MetricVersionRef) -> None:
        if ref in visiting:
            issue("metric_dependency_cycle", ref, "比率依赖存在循环")
            return
        if ref in visited:
            return
        metric = versions.get(ref)
        if metric is None:
            issue("metric_version_missing", ref, "所引用的精确指标版本不存在")
            return
        visiting.add(ref)
        if metric.kind == "ratio":
            numerator, denominator = metric.numerator_version, metric.denominator_version
            assert numerator is not None and denominator is not None
            visit(numerator)
            visit(denominator)
            left, right = versions.get(numerator), versions.get(denominator)
            if left and right:
                if left.unit != right.unit:
                    issue("ratio_unit_mismatch", ref, "分子与分母单位不一致，首期未声明换算")
                if set(left.grain) != set(right.grain) or set(metric.grain) != set(left.grain):
                    issue("grain_not_supported", ref, "分子、分母与输出粒度不一致")
        visiting.remove(ref)
        visited.add(ref)

    for reference in roots:
        visit(reference)
    return tuple(issues)
