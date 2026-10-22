"""Finite server-side assertions over exact, caller-authorized frozen selectors.

No expression evaluator, arbitrary paths or model-issued proofs. Source bytes must
already have passed the workflow's identity and scope checks. Capabilities are
server context, never fields accepted in an assertion request from a model.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import Field

from ..contract import SHA256_PATTERN, StrictModel
from .comparison_proofs import _comparable_periods, comparison_word, period_window_label
from .contracts_v1 import canonical_sha256
from .monthly_trends import TrendDirection
from .semantic_bindings import NumberReferenceResolver, reference_fact_ids

RULE_VERSION: Literal["assertions/1"] = "assertions/1"


class MetricCapability(StrictModel):
    metric_kind: Literal["flow", "stock", "cumulative", "rate", "share", "unknown"] = Field(
        default="unknown",
        alias="metricKind",
    )
    comparison_key: str | None = Field(default=None, alias="comparisonKey")
    monthly_flow_complete: bool = Field(default=False, alias="monthlyFlowComplete")
    # A shared denominator/population must be explicitly registered, not inferred
    # from a column name containing 合计 or from two percent units.
    population_id: str | None = Field(default=None, alias="populationId")
    denominator_fact_id: str | None = Field(default=None, alias="denominatorFactId")


class AssertionRequest(StrictModel):
    operation: Literal[
        "value",
        "monthly_average",
        "difference",
        "relative_change",
        "share",
        "group_rank",
        "monthly_trend",
        "top_n_set",
        "group_contribution",
        "registered_ratio",
        "cumulative_change",
    ]
    operands: tuple[str, ...] = Field(min_length=1, max_length=2)
    comparison: Literal["same_period", "yoy", "mom"] = "same_period"


class AssertionResult(StrictModel):
    version: Literal["1"] = "1"
    assertion_id: str = Field(alias="assertionId")
    rule_version: Literal["assertions/1"] = Field(default=RULE_VERSION, alias="ruleVersion")
    profile_hash: str = Field(alias="profileHash", pattern=SHA256_PATTERN)
    authorization_scope_hash: str = Field(alias="authorizationScopeHash", pattern=SHA256_PATTERN)
    request: AssertionRequest
    source_hashes: tuple[str, ...] = Field(alias="sourceHashes")
    status: Literal["supported", "unknown", "conflicting"]
    reasons: tuple[str, ...] = ()
    value: str | None = None
    unit: str | None = None
    periods: tuple[str, ...] = ()
    scope: dict[str, str] = Field(default_factory=dict)
    subject: str = ""
    baseline_periods: tuple[str, ...] = Field(default=(), alias="baselinePeriods")
    reference_token: str | None = Field(default=None, alias="referenceToken")
    population_scope: dict[str, str] | None = Field(default=None, alias="populationScope")
    population_fact_id: str | None = Field(default=None, alias="populationFactId")
    numerator_scope: dict[str, str] | None = Field(default=None, alias="numeratorScope")
    rank: int | None = Field(default=None, ge=1)
    ranking_order: Literal["ascending", "descending"] | None = Field(
        default=None, alias="rankingOrder"
    )
    trend_direction: TrendDirection | None = Field(default=None, alias="trendDirection")
    trend_comparisons: int | None = Field(default=None, alias="trendComparisons", ge=2)
    trend_qualifiers: tuple[str, ...] = Field(default=(), alias="trendQualifiers", max_length=5)

    top_set_members: tuple[dict[str, str], ...] = Field(default=(), alias="topSetMembers")
    top_set_mode: Literal["rank", "items"] | None = Field(default=None, alias="topSetMode")
    top_set_limit: int | None = Field(default=None, alias="topSetLimit", ge=1, le=100)

    contribution_members: tuple[dict[str, str], ...] = Field(default=(), alias="contributionMembers")
    contribution_group: dict[str, str] | None = Field(default=None, alias="contributionGroup")

    ratio_numerator_label: str | None = Field(default=None, alias="ratioNumeratorLabel")
    ratio_denominator_label: str | None = Field(default=None, alias="ratioDenominatorLabel")
    ratio_policy: Literal["sum", "last"] | None = Field(default=None, alias="ratioPolicy")
    cumulative_proof: dict[str, str | bool | None] | None = Field(
        default=None, alias="cumulativeProof"
    )

    def factual_fragment(self, *, value_placeholder: str | None = None) -> str:
        """The model may select an ID, but cannot supply another result/qualifier."""
        if self.status != "supported":
            return "证据不足：" + "、".join(self.reasons) + "。"
        period = period_window_label(self.periods)
        scope = "、".join(
            f"{_label(key)}={_label(value)}" for key, value in sorted(self.scope.items())
        )
        operation = {
            "value": "登记值",
            "monthly_average": "月均值",
            "difference": "差额",
            "relative_change": "相对变化率",
            "share": "占比",
            "group_rank": "分组排名",
            "monthly_trend": "月度趋势",
            "top_n_set": "完整排名集合",
            "group_contribution": "算术贡献率",
            "registered_ratio": "同期总量比率",
            "cumulative_change": "累计快照变化",
        }[self.request.operation]
        display = value_placeholder if value_placeholder is not None else f"{self.value}{self.unit}"
        if self.request.operation == "cumulative_change":
            from .cumulative_changes import cumulative_change_template

            subject = f"{scope}，{_label(self.subject)}"
            return cumulative_change_template(self.cumulative_proof or {}, subject, display)
        if self.request.operation == "registered_ratio":
            from .ratio_proofs import ratio_fragment_prefix

            return ratio_fragment_prefix(periods=self.periods, scope=self.scope, subject=self.subject,
                numerator_label=self.ratio_numerator_label or "指标", denominator_label=self.ratio_denominator_label or "指标",
                policy=self.ratio_policy) + display + "。"
        if self.request.operation == "group_contribution":
            from .group_contributions import contribution_fragment_prefix

            return contribution_fragment_prefix(
                members=self.contribution_members, group=self.contribution_group or {},
                scope=self.scope, subject=self.subject, periods=self.periods,
                baseline_periods=self.baseline_periods, comparison=self.request.comparison,
            ) + display + "。"
        if self.request.operation == "top_n_set":
            from .top_sets import display_members

            rule = "竞赛排名，含边界全部并列" if self.top_set_mode == "rank" else "同值按结构化分组键升序打破平局"
            noun = "名" if self.top_set_mode == "rank" else "个"
            capacity_note = ("当前登记总体成员少于所请求名次上限，" if self.top_set_limit is not None
                             and len(self.top_set_members) < self.top_set_limit else "")
            return (f"{period}，总体范围（{scope}）内按{_label(self.subject)}未舍入登记分组值"
                    f"降序取前{self.top_set_limit}{noun}（{rule}），{capacity_note}完整成员清单："
                    f"{display_members(self.top_set_members)}，所列成员合计为{display}。")
        if self.request.operation == "monthly_trend":
            if self.trend_direction is None:
                return "月度趋势尚未完成核验。"
            direction = {
                "increasing": "逐月严格上升",
                "decreasing": "逐月严格下降",
                "constant": "逐月持平",
                "mixed": "属于混合变化",
            }[self.trend_direction]
            qualifiers = "，".join(self.trend_qualifiers)
            if qualifiers:
                qualifiers += "，"
            return (
                f"{period}，{scope}，{_label(self.subject)}按未舍入登记月值核对全部相邻月份后{direction}，{qualifiers}"
                f"期末登记值为{display}。"
            )
        if self.request.operation == "group_rank":
            population = "、".join(
                f"{_label(key)}={_label(value)}"
                for key, value in sorted((self.population_scope or {}).items())
            )
            group = "、".join(
                f"{_label(key)}={_label(value)}"
                for key, value in sorted((self.numerator_scope or {}).items())
            )
            direction = "降序" if self.ranking_order == "descending" else "升序"
            return (
                f"{period}，总体范围（{population}）内按{_label(self.subject)}未舍入登记分组值{direction}"
                f"采用同值同名次的竞赛排名，分组（{group}）列第{self.rank}名，对应登记值为{display}。"
            )
        if self.request.operation == "share" and self.population_scope is not None:
            group_scope = "、".join(
                f"{_label(key)}={_label(value)}"
                for key, value in sorted((self.numerator_scope or self.scope).items())
            )
            population = "、".join(
                f"{_label(key)}={_label(value)}"
                for key, value in sorted(self.population_scope.items())
            )
            return f"{period}，分组范围（{group_scope}）占总体范围（{population}）内{_label(self.subject)}登记合计的比例为{display}。"
        if self.baseline_periods:
            baseline = period_window_label(self.baseline_periods)
            comparison = comparison_word(self.request.comparison, self.periods)
            return f"{scope}，{_label(self.subject)}，本期{period}、基期{baseline}，{comparison}{operation}为{display}。"
        return f"{period}，{scope}，{_label(self.subject)}{operation}为{display}。"


class AssertionCompiler:
    def __init__(
        self,
        contents: Sequence[str],
        *,
        profile_hash: str,
        authorization_scope_hash: str,
        capabilities: Mapping[str, MetricCapability] | None = None,
    ) -> None:
        self.resolver = NumberReferenceResolver(contents)
        self.fact_sources: dict[str, set[str]] = {}
        self.fact_warnings: dict[str, set[str]] = {}
        for text in contents:
            digest = hashlib.sha256(text.encode()).hexdigest()
            for fact_id, entry in NumberReferenceResolver((text,)).entries.items():
                self.fact_sources.setdefault(fact_id, set()).add(digest)
                # Numeric binding may merge analysis-local warning variants;
                # a semantic proof must retain every dependency's warnings.
                self.fact_warnings.setdefault(fact_id, set()).update(entry.get("warnings", ()))
        self.profile_hash = profile_hash
        self.authorization_scope_hash = authorization_scope_hash
        self.capabilities = dict(capabilities or {})
        self._capability_cache: dict[str, MetricCapability] = {}
        self._ratio_cache: dict[str, tuple[dict | None, tuple[str, ...]]] = {}
        self._contribution_cache: dict[str, tuple[dict | None, tuple[str, ...]]] = {}
        self._top_set_cache: dict[str, tuple[dict, tuple[str, ...]]] = {}
        self._cumulative_cache: dict[str, tuple[dict, tuple[str, ...]]] = {}

    def compile(self, request: AssertionRequest) -> AssertionResult:
        reasons: list[str] = []
        views = [self.resolver.resolve(token) or {} for token in request.operands]
        native = (
            len(views) == 1
            and bool(views[0])
            and (
                bool(views[0].get("entry", {}).get("comparisonType"))
                or views[0]["selector"].startswith(("periodChanges.", "periodChangeRates."))
            )
            and request.operation in {"difference", "relative_change", "group_contribution"}
        )
        native_share = (
            len(views) == 1
            and bool(views[0])
            and views[0]["selector"].startswith("groupShares.")
            and request.operation == "share"
        )
        expected = (
            1
            if native
            or native_share
            or request.operation in {"value", "monthly_average", "group_rank", "monthly_trend", "top_n_set", "group_contribution", "registered_ratio", "cumulative_change"}
            else 2
        )
        if len(views) != expected:
            reasons.append("operand_count_invalid")
        if any(not view for view in views):
            reasons.append("operand_unresolvable")
        dependent_ids = {
            fact_id for token in request.operands for fact_id in reference_fact_ids(token)
        }
        if native or request.operation == "registered_ratio" and views[0]:
            dependent_ids.update(views[0]["entry"].get("inputFactIds", ()))
        conflicting = any(fact_id in self.resolver.conflicts for fact_id in dependent_ids)
        if conflicting:
            reasons.append("source_fact_conflict")
        primary = views[0] or {}
        source_hashes = tuple(
            sorted(
                {
                    digest
                    for fact_id in dependent_ids
                    for digest in self.fact_sources.get(fact_id, ())
                }
            )
        )
        caps = [self._metric_capability(token) for token in request.operands]
        status: Literal["supported", "unknown", "conflicting"] = (
            "conflicting" if conflicting else "unknown"
        )
        value = None
        unit = primary.get("unit")
        periods = tuple(primary.get("periods") or ())
        raw_scope = dict(primary.get("scope") or {})
        scope = {
            key: item for key, item in raw_scope.items()
            if isinstance(key, str) and key.strip() and isinstance(item, str) and item.strip()
        }
        if len(scope) != len(raw_scope):
            reasons.append("scope_value_unknown")
        baseline_periods: tuple[str, ...] = ()
        population_scope = None
        population_fact_id = None
        numerator_scope = None
        rank = None
        ranking_order = None
        trend_direction = None
        trend_comparisons = None
        trend_qualifiers: tuple[str, ...] = ()
        top_set = None
        contribution = None
        ratio = None
        cumulative = None
        contribution_group = None
        if not scope:
            reasons.append("scope_unknown")
        if not periods:
            reasons.append("period_unknown")
        if not unit:
            reasons.append("unit_unknown")
        if not reasons:
            with localcontext() as ctx:
                ctx.prec = 64
                amounts = [Decimal(str(view["value"])) for view in views]
                if not all(amount.is_finite() for amount in amounts):
                    reasons.append("nonfinite_operand")
                elif request.operation == "cumulative_change":
                    from .cumulative_changes import registered_cumulative_changes

                    fact_key = str(primary["entry"].get("factId") or "")
                    if fact_key not in self._cumulative_cache:
                        self._cumulative_cache[fact_key] = registered_cumulative_changes(
                            primary["entry"], profile_hash=self.profile_hash,
                            warnings=tuple(self.fact_warnings.get(fact_key, ())),
                        )
                    proofs, cumulative_reasons = self._cumulative_cache[fact_key]
                    reasons.extend(cumulative_reasons)
                    cumulative = proofs.get(primary["selector"])
                    if cumulative is None or request.comparison != "same_period":
                        reasons.append("cumulative_selection_unavailable")
                    elif not reasons:
                        expected_periods = (cumulative["current_period"],)
                        expected_baseline = ((cumulative["baseline_period"],)
                                             if cumulative["baseline_period"] else ())
                        if (
                            amounts[0] != Decimal(str(float(cumulative["value"])))
                            or unit != cumulative["unit"]
                            or tuple(primary["period_roles"].get("current", ())) != expected_periods
                            or tuple(primary["period_roles"].get("baseline", ())) != expected_baseline
                        ):
                            reasons.append("cumulative_value_or_window_mismatch")
                        else:
                            value = cumulative["value"]
                            periods = expected_periods
                            baseline_periods = expected_baseline
                elif request.operation == "registered_ratio":
                    from .ratio_proofs import registered_ratio

                    fact_key = str(primary["entry"]["factId"])
                    if fact_key not in self._ratio_cache:
                        self._ratio_cache[fact_key] = registered_ratio(primary["entry"], self.resolver.entries,
                            profile_hash=self.profile_hash, fact_warnings=self.fact_warnings)
                    ratio, ratio_reasons = self._ratio_cache[fact_key]
                    reasons.extend(ratio_reasons)
                    if ratio is None or primary["selector"] != "registeredRatio" or request.comparison != "same_period":
                        reasons.append("ratio_selection_unavailable")
                    elif not reasons:
                        if amounts[0] != Decimal(str(float(ratio["value"]))) or unit != ratio["unit"] or periods != ratio["periods"]:
                            reasons.append("ratio_value_or_window_mismatch")
                        else:
                            value = ratio["value"]
                elif request.operation == "group_contribution":
                    from .group_contributions import registered_group_contributions

                    fact_key = str(primary["entry"]["factId"])
                    if fact_key not in self._contribution_cache:
                        self._contribution_cache[fact_key] = registered_group_contributions(
                            primary["entry"], self.resolver.entries,
                            profile_hash=self.profile_hash, fact_warnings=self.fact_warnings,
                        )
                    contribution, contribution_reasons = self._contribution_cache[fact_key]
                    reasons.extend(contribution_reasons)
                    if (contribution is None or not primary["selector"].startswith("groupContributions.")
                            or request.comparison != primary["entry"].get("comparisonType")):
                        reasons.append("contribution_selection_unavailable")
                    elif not reasons:
                        index = int(primary["selector"].split(".")[1])
                        if index >= len(contribution["values"]) or amounts[0] != Decimal(str(float(contribution["values"][index]))):
                            reasons.append("contribution_value_mismatch")
                        else:
                            value = contribution["values"][index]
                            periods = contribution["currentPeriods"]
                            baseline_periods = contribution["baselinePeriods"]
                            contribution_group = contribution["members"][index]
                elif request.operation == "top_n_set":
                    from .top_sets import registered_top_sets

                    fact_key = primary["entry"]["factId"]
                    if fact_key not in self._top_set_cache:
                        self._top_set_cache[fact_key] = registered_top_sets(
                            primary["entry"], profile_hash=self.profile_hash,
                            warnings=tuple(self.fact_warnings.get(fact_key, ())),
                        )
                    proofs, top_reasons = self._top_set_cache[fact_key]
                    reasons.extend(top_reasons)
                    top_set = proofs.get(primary["selector"])
                    if request.comparison != "same_period" or top_set is None:
                        reasons.append("top_set_selection_unavailable")
                    elif tuple(periods) != top_set["periods"]:
                        reasons.append("top_set_window_mismatch")
                    elif not reasons:
                        value = top_set["value"]
                elif request.operation == "monthly_trend":
                    from .monthly_trends import registered_monthly_trend

                    if primary["selector"] != "monthlyTrend" or request.comparison != "same_period":
                        reasons.append("trend_selector_invalid")
                    trend, trend_reasons = registered_monthly_trend(
                        primary["entry"],
                        profile_hash=self.profile_hash,
                        warnings=tuple(self.fact_warnings.get(primary["entry"].get("factId"), ())),
                    )
                    reasons.extend(trend_reasons)
                    if not reasons and trend is not None:
                        if periods != trend["periods"]:
                            reasons.append("trend_window_identity_mismatch")
                        else:
                            value = amounts[0]
                            trend_direction = trend["direction"]
                            trend_comparisons = trend["comparisons"]
                            from .business_semantics import registered_trend_qualifiers

                            trend_qualifiers = registered_trend_qualifiers(primary["entry"])
                elif request.operation == "group_rank":
                    from .group_ranking import registered_group_rank

                    if request.comparison != "same_period":
                        reasons.append("ranking_period_mismatch")
                    ranking, ranking_reasons = registered_group_rank(
                        primary["entry"],
                        primary["selector"],
                        periods,
                        profile_hash=self.profile_hash,
                        warnings=tuple(self.fact_warnings.get(primary["entry"].get("factId"), ())),
                    )
                    reasons.extend(ranking_reasons)
                    if not reasons and ranking is not None:
                        value = amounts[0]
                        rank = ranking["rank"]
                        ranking_order = ranking["order"]
                        population_scope = ranking["populationScope"]
                        numerator_scope = ranking["groupScope"]
                        population_fact_id = primary["entry"]["factId"]
                elif native_share:
                    try:
                        reasons.extend(self._registered_group_share_reasons(request, primary))
                    except (ValueError, TypeError, ArithmeticError, IndexError):
                        reasons.append("population_membership_unproven")
                    if not reasons:
                        value = amounts[0]
                        population_scope = dict(primary["entry"]["scope"])
                        population_fact_id = primary["entry"]["factId"]
                        _, array, index = primary["selector"].split(".")
                        numerator_scope = dict(primary["entry"][array][int(index)]["groupValues"])
                elif native:
                    try:
                        reasons.extend(
                            self._registered_comparison_reasons(request, primary)
                            if primary["entry"].get("comparisonType")
                            else self._registered_series_change_reasons(request, primary)
                        )
                    except (ValueError, TypeError, ArithmeticError):
                        reasons.append("comparison_inputs_invalid")
                    if not reasons:
                        value = amounts[0]
                        periods = tuple(primary["period_roles"]["current"])
                        baseline_periods = tuple(primary["period_roles"]["baseline"])
                elif request.operation == "value":
                    # A derived selector cannot acquire an ordinary value proof.
                    if primary["selector"] != "total" and not primary["selector"].startswith(
                        "periodValues."
                    ):
                        reasons.append("value_selector_not_supported")
                    else:
                        value = amounts[0]
                elif request.operation == "monthly_average":
                    if (
                        primary["selector"] != "monthlyAverage"
                        or primary["entry"].get("periodAggregation") == "last"
                        or bool(self.fact_warnings.get(primary["entry"].get("factId")))
                        or primary["entry"].get("missingCount", 0) > 0
                        or (primary["entry"].get("periodMissingCount") or 0) > 0
                        or caps[0].metric_kind != "flow"
                        or not caps[0].monthly_flow_complete
                        or not _consecutive_months(periods)
                    ):
                        reasons.append("complete_monthly_flow_required")
                    else:
                        value = amounts[0]
                else:
                    second = views[1]
                    baseline_periods = tuple(second["periods"])
                    if (
                        unit != second["unit"]
                        or scope != second["scope"]
                        or not _comparable_periods(
                            periods, tuple(second["periods"]), request.comparison
                        )
                    ):
                        reasons.append("operands_not_comparable")
                    if any(
                        view["selector"] != "total"
                        and not view["selector"].startswith("periodValues.")
                        for view in views
                    ):
                        reasons.append("operand_selector_not_supported")
                    if (
                        request.operation == "relative_change"
                        and request.comparison == "same_period"
                    ):
                        reasons.append("comparison_period_roles_required")
                    if request.operation == "share" and request.comparison != "same_period":
                        reasons.append("population_period_mismatch")
                    if (
                        not caps[0].comparison_key
                        or caps[0].comparison_key != caps[1].comparison_key
                    ):
                        reasons.append("comparison_definition_required")
                    if any(view["entry"].get("cumulativePolicy") is not None for view in views):
                        reasons.append("cumulative_snapshot_policy_required")
                    if any(
                        len(view["periods"]) > 1
                        and not (
                            view["entry"].get("periodAggregation") == "sum"
                            and view["entry"].get("aggregation") in {"sum", "count"}
                        )
                        and not (cap.metric_kind == "flow" and cap.monthly_flow_complete)
                        for view, cap in zip(views, caps, strict=True)
                    ):
                        reasons.append("time_additivity_unproven")
                    if not reasons:
                        if request.operation == "difference":
                            value = amounts[0] - amounts[1]
                            if unit == "%":
                                unit = "个百分点"
                        elif request.operation == "relative_change":
                            # Negative baselines require a future explicit policy;
                            # do not silently interpret an absolute denominator.
                            if amounts[1] <= 0:
                                reasons.append("positive_baseline_required")
                            else:
                                value = (amounts[0] - amounts[1]) / amounts[1] * 100
                                unit = "%"
                        else:
                            right_ids = reference_fact_ids(request.operands[1])
                            if (
                                len(right_ids) != 1
                                or caps[0].denominator_fact_id != right_ids[0]
                                or not caps[0].population_id
                                or caps[0].population_id != caps[1].population_id
                            ):
                                reasons.append("population_membership_required")
                            elif amounts[1] <= 0 or amounts[0] < 0 or amounts[0] > amounts[1]:
                                reasons.append("share_denominator_invalid")
                            else:
                                value = amounts[0] / amounts[1] * 100
                                unit = "%"
        if value is not None and not reasons:
            status = "supported"
        else:
            value = None
        identity = {
            "ruleVersion": RULE_VERSION,
            "profileHash": self.profile_hash,
            "authorizationScopeHash": self.authorization_scope_hash,
            "sourceHashes": source_hashes,
            "capabilities": [cap.model_dump(mode="json", by_alias=True) for cap in caps],
            "request": request.model_dump(mode="json", by_alias=True),
        }
        names = [str((view or {}).get("entry", {}).get("displayName") or "指标") for view in views]
        if native and primary["entry"].get("inputFactIds"):
            current = self.resolver.entries.get(primary["entry"]["inputFactIds"][0], {})
            names = [str(current.get("displayName") or current.get("field") or "指标")]
        if request.operation == "group_contribution":
            names = [str(primary.get("entry", {}).get("displayName") or primary.get("entry", {}).get("field") or "指标")]
        if request.operation == "registered_ratio":
            names = [str(primary.get("entry", {}).get("code") or "指标")]
        return AssertionResult(
            assertionId="assert-" + canonical_sha256(identity),
            profileHash=self.profile_hash,
            authorizationScopeHash=self.authorization_scope_hash,
            request=request,
            sourceHashes=source_hashes,
            status=status,
            reasons=tuple(dict.fromkeys(reasons)),
            value=format(value, "f") if value is not None else None,
            unit=unit,
            periods=periods,
            scope=scope,
            subject="与".join(names),
            baselinePeriods=baseline_periods,
            referenceToken=request.operands[0]
            if len(request.operands) == 1 and status == "supported"
            else None,
            populationScope=population_scope,
            populationFactId=population_fact_id,
            numeratorScope=numerator_scope,
            rank=rank,
            rankingOrder=ranking_order,
            trendDirection=trend_direction,
            trendComparisons=trend_comparisons,
            trendQualifiers=trend_qualifiers,
            ratioNumeratorLabel=ratio["numeratorLabel"] if ratio is not None else None,
            ratioDenominatorLabel=ratio["denominatorLabel"] if ratio is not None else None,
            ratioPolicy=ratio["policy"] if ratio is not None else None,
            cumulativeProof={key: (format(item, "f") if isinstance(item, Decimal) else item)
                             for key, item in cumulative.items()}
            if cumulative is not None and status == "supported" else None,
            contributionMembers=contribution["members"] if contribution is not None else (),
            contributionGroup=contribution_group,
            topSetMembers=top_set["members"] if top_set is not None else (),
            topSetMode=top_set["mode"] if top_set is not None else None,
            topSetLimit=top_set["limit"] if top_set is not None else None,
        )

    def _registered_group_share_reasons(self, request: AssertionRequest, view: dict) -> list[str]:
        """A frozen row partition supplies membership; a metric name never does."""
        from ..hospital_operation.deterministic_analysis import DeterministicMetricFact

        if request.comparison != "same_period":
            return ["population_period_mismatch"]
        metric = DeterministicMetricFact.model_validate(view["entry"])
        if metric.profile_hash != self.profile_hash:
            return ["population_input_identity_mismatch"]
        if (
            metric.aggregation != "sum"
            or not metric.unit
            or metric.unit in {"%", "个百分点"}
            or "/" in metric.unit
            or "／" in metric.unit
        ):
            return ["additive_population_required"]
        if not metric.scope:
            return ["population_scope_unknown"]
        if (
            metric.missing_count != 0
            or metric.period_missing_count != 0
            or self.fact_warnings.get(metric.fact_id or "")
        ):
            return ["population_completeness_unproven"]
        if metric.negative_count or not math.isfinite(metric.total) or not metric.total > 0:
            return ["share_denominator_invalid"]
        periods = tuple(view["periods"])
        if len(periods) > 1 and (
            metric.period_aggregation != "sum" or not _consecutive_months(periods)
        ):
            return ["time_additivity_unproven"]
        _, array, raw_index = view["selector"].split(".")
        group = (metric.top_groups if array == "topGroups" else metric.bottom_groups)[
            int(raw_index)
        ]
        if not group.group_values or any(
            not isinstance(value, str) or not value for value in group.group_values.values()
        ):
            return ["group_identity_unavailable"]
        if any(
            key in metric.scope and metric.scope[key] != value
            for key, value in group.group_values.items()
        ):
            return ["group_scope_conflict"]
        if not 0 <= group.value <= metric.total:
            return ["share_denominator_invalid"]
        # top/bottom overlap is normal. A repeated dimension identity with a
        # different value or an incompatible grouping grain is not a partition.
        values: dict[tuple[tuple[str, str | None], ...], float] = {}
        for candidates in (metric.top_groups, metric.bottom_groups):
            local_ids = set()
            for candidate in candidates:
                if set(candidate.group_values) != set(group.group_values):
                    return ["group_population_grain_mismatch"]
                identity = tuple(sorted(candidate.group_values.items()))
                if (
                    identity in local_ids
                    or not math.isfinite(candidate.value)
                    or candidate.value < 0
                    or candidate.value > metric.total
                ):
                    return ["group_population_conflict"]
                if identity in values and values[identity] != candidate.value:
                    return ["group_population_conflict"]
                values[identity] = candidate.value
                local_ids.add(identity)
        return []

    def _metric_capability(self, token: str) -> MetricCapability:
        ids = reference_fact_ids(token)
        if len(ids) != 1:
            return MetricCapability()
        if ids[0] in self.capabilities:
            return self.capabilities[ids[0]]
        if ids[0] not in self._capability_cache:
            self._capability_cache[ids[0]] = self._frozen_metric_capability(ids[0])
        return self._capability_cache[ids[0]]

    def _frozen_metric_capability(self, fact_id: str) -> MetricCapability:
        entry = self.resolver.entries.get(fact_id, {})
        if entry.get("profileHash") != self.profile_hash:
            return MetricCapability()
        if entry.get("cumulativePolicy") is not None:
            return MetricCapability(metricKind="cumulative")
        if entry.get("periodAggregation") == "last":
            return MetricCapability(metricKind="stock")
        if entry.get("periodAggregation") != "sum" or entry.get("aggregation") != "sum":
            return MetricCapability()
        from .subject_builder import fact_periods

        complete = (
            entry.get("periodGranularity") == "month"
            and entry.get("missingCount") == 0
            and entry.get("periodMissingCount") == 0
            and not self.fact_warnings.get(fact_id)
            and bool(entry.get("periodValues"))
            and _consecutive_months(fact_periods(entry))
        )
        return MetricCapability(metricKind="flow", monthlyFlowComplete=complete)

    def _registered_series_change_reasons(self, request: AssertionRequest, view: dict) -> list[str]:
        """An adjacent registered monthly pair needs no arbitrary fact matching."""
        from ..hospital_operation.deterministic_analysis import DeterministicMetricFact

        expected_prefix = (
            "periodChanges." if request.operation == "difference" else "periodChangeRates."
        )
        if not view["selector"].startswith(expected_prefix) or request.comparison != "mom":
            return ["comparison_selector_mismatch"]
        metric = DeterministicMetricFact.model_validate(view["entry"])
        if metric.cumulative_policy is not None:
            return ["cumulative_snapshot_policy_required"]
        if metric.profile_hash != self.profile_hash:
            return ["comparison_input_identity_mismatch"]
        if (
            metric.missing_count != 0
            or metric.period_missing_count != 0
            or self.fact_warnings.get(metric.fact_id or "")
        ):
            return ["comparison_completeness_unproven"]
        current_periods = tuple(view["period_roles"].get("current", ()))
        baseline_periods = tuple(view["period_roles"].get("baseline", ()))
        if len(current_periods) != 1 or not _comparable_periods(
            current_periods, baseline_periods, "mom"
        ):
            return ["comparison_window_mismatch"]
        index = int(view["selector"].split(".")[1])
        baseline = metric.period_values[index - 1].value
        if request.operation == "relative_change" and baseline <= 0:
            return ["positive_baseline_required"]
        return []

    def _registered_comparison_reasons(self, request: AssertionRequest, view: dict) -> list[str]:
        from .comparison_proofs import registered_comparison_reasons

        return registered_comparison_reasons(
            request.operation, request.comparison, view, self.resolver.entries,
            profile_hash=self.profile_hash, fact_warnings=self.fact_warnings,
        )


def _consecutive_months(periods: tuple[str, ...]) -> bool:
    if any(
        len(period) != 7 or not period[:4].isdigit() or not period[5:].isdigit()
        for period in periods
    ):
        return False
    return _comparable_periods(
        periods, tuple(f"{int(period[:4]) - 1:04d}{period[4:]}" for period in periods), "yoy"
    )


def _label(value: str) -> str:
    """Source names are data, never template/protocol instructions."""
    import re

    return (
        re.sub(r"[\r\n]+", " ", value)
        .replace("{{", "｛｛")
        .replace("}}", "｝｝")
        .replace("[[", "［［")
        .replace("]]", "］］")
    )


def assertion_request_for_token(
    token: str, resolver: NumberReferenceResolver
) -> AssertionRequest | None:
    view = resolver.resolve(token)
    if view is None or not token.startswith("{{value:"):
        return None
    selector = view["selector"]
    if selector == "total" or selector.startswith("periodValues."):
        return AssertionRequest(operation="value", operands=(token,))
    if selector == "registeredRatio":
        return AssertionRequest(operation="registered_ratio", operands=(token,))
    if selector.startswith("cumulativeChanges."):
        return AssertionRequest(operation="cumulative_change", operands=(token,))
    if selector.startswith("groupContributions."):
        return AssertionRequest(operation="group_contribution", operands=(token,), comparison=view["entry"]["comparisonType"])
    if selector.startswith("topSet."):
        return AssertionRequest(operation="top_n_set", operands=(token,))
    if selector.startswith("groupShares."):
        return AssertionRequest(operation="share", operands=(token,))
    if selector.startswith(("topGroups.", "bottomGroups.")):
        return AssertionRequest(operation="group_rank", operands=(token,))
    if selector == "monthlyAverage":
        return AssertionRequest(operation="monthly_average", operands=(token,))
    if selector == "monthlyTrend":
        return AssertionRequest(operation="monthly_trend", operands=(token,))
    if selector.startswith(("periodChanges.", "periodChangeRates.")):
        return AssertionRequest(
            operation="difference" if selector.startswith("periodChanges.") else "relative_change",
            operands=(token,),
            comparison="mom",
        )
    kind = view.get("entry", {}).get("comparisonType")
    if kind in {"yoy", "mom"} and selector in {"change", "changeRate"}:
        return AssertionRequest(
            operation="difference" if selector == "change" else "relative_change",
            operands=(token,),
            comparison=kind,
        )
    return None


def assertion_catalog(
    contents: Sequence[str],
    *,
    profile_hash: str,
    authorization_scope_hash: str,
    allowed_tokens: Sequence[str],
    capabilities: Mapping[str, MetricCapability] | None = None,
    include_month_changes: bool = False,
    include_group_shares: bool = False,
    include_month_trends: bool = False,
    include_top_sets: bool = False,
    include_group_contributions: bool = False,
    include_registered_ratios: bool = False,
    include_cumulative_changes: bool = False,
    top_set_limits: Sequence[int] = (3, 5, 10),
) -> dict[str, AssertionResult]:
    compiler = AssertionCompiler(
        contents,
        profile_hash=profile_hash,
        authorization_scope_hash=authorization_scope_hash,
        capabilities=capabilities,
    )
    tokens = list(dict.fromkeys(allowed_tokens))
    if include_month_changes or include_group_shares or include_month_trends or include_top_sets or include_group_contributions or include_registered_ratios or include_cumulative_changes:
        # The model sees approved assertion IDs, never these server-only raw
        # selectors. Stay inside the facts already allocated to this block.
        allowed_ids = {fact_id for token in tokens for fact_id in reference_fact_ids(token)}
        tokens.extend(
            token
            for token in compiler.resolver.numbers
            if (
                (
                    include_month_changes
                    and token.split(":", 3)[2].startswith(("periodChanges.", "periodChangeRates."))
                )
                or (include_group_shares and token.split(":", 3)[2].startswith("groupShares."))
                or (include_group_contributions and token.split(":", 3)[2].startswith("groupContributions."))
                or (include_registered_ratios and token.split(":", 3)[2] == "registeredRatio")
                or (include_cumulative_changes and token.split(":", 3)[2].startswith("cumulativeChanges."))
                or (include_month_trends and token.split(":", 3)[2] == "monthlyTrend")
                or (include_top_sets and token.split(":", 3)[2].startswith("topSet.")
                    and token.split(":", 3)[2].rsplit(".", 1)[-1] in {str(value) for value in top_set_limits if 1 <= value <= 100})
            )
            and set(reference_fact_ids(token)) <= allowed_ids
        )
    candidates = []
    for token in dict.fromkeys(tokens):
        request = assertion_request_for_token(token, compiler.resolver)
        if request is not None:
            view = compiler.resolver.resolve(token)
            if view is None:
                continue
            # Different display-unit tokens for one selector have the same
            # factual meaning. Prefer an allowed source-unit token and compile
            # only once, rather than multiplying prompt and validation cost.
            display_unit = token.rsplit(":", 1)[-1].removesuffix("}}")
            candidates.append((display_unit != view["unit"], token, request, view))
    result = {}
    seen = set()
    explicit_tokens = set(allowed_tokens)
    for _, token, request, view in sorted(candidates, key=lambda item: item[0]):
        selector = view["selector"]
        if selector.startswith("groupShares."):
            _, array, index = selector.split(".")
            group = view["entry"][array][int(index)]
            selector = (
                "groupShare",
                tuple(sorted((group.get("groupValues") or {}).items())),
                group["value"],
            )
        key = (tuple(reference_fact_ids(token)), selector, view["unit"])
        if view["selector"].startswith("cumulativeChanges."):
            if token not in explicit_tokens and int(selector.split(".")[1]) < max(
                0, len(view["entry"].get("periodValues", ())) - 12
            ):
                continue
        if view["selector"].startswith("topSet."):
            from .top_sets import display_members

            proof = view.get("_top_set_proof")
            if proof is None or len(proof["members"]) > 100 or len(display_members(proof["members"]).encode()) > 2000:
                continue  # No incomplete member lists in the model input.
        if view["selector"].startswith("groupContributions."):
            proof = view.get("_group_contribution_proof")
            if proof is None:
                continue
            largest = sorted(range(len(proof["deltas"])), key=lambda index: (-abs(proof["deltas"][index]), index))[:5]
            if token not in explicit_tokens and int(view["selector"].split(".")[1]) not in largest:
                continue
        if key in seen:
            continue
        seen.add(key)
        assertion = compiler.compile(request)
        result[assertion.assertion_id] = assertion
    return result
