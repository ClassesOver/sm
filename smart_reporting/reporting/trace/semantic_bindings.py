"""把冻结数值选择器及提示类型保留到编辑器；不根据业务名称猜事实。"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from typing import Any, NamedTuple

from loguru import logger

from ..hospital_operation.deterministic_analysis import (
    DeterministicMetricFact,
    _aligned_comparison_values,
)
from .calc_references import CALC_TOKEN, CalcEvaluator
from .contracts_v1 import NumberReferenceV1, ReviewNoticeV1, TableDerivationV1
from .fact_index import fact_binding_records, merge_binding_records, merge_frozen_fact
from .numeric_text import (
    _NUMBER,
    _canonical_month_label,
    _frozen_number_entries,
    align_placeholder_direction,
    correct_constant_monthly_totals,
    correct_period_extrema,
    derived_number_values,
    derived_reference_resolution,
    derived_reference_token,
    frozen_fact_bundles,
    frozen_number_catalog,
    group_large_amounts,
    normalize_signed_wording,
    plain_period_wording,
    render_frozen_numbers,
    replace_unregistered_numbers,
)
from .table_sources import resolve_table_derivation
from .value_references import UNREGISTERED_NUMBER_REASON, value_reference_failure


def reference_fact_ids(token: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"fact-[0-9a-f]{16}", token)))


def _dataset_ids(entries: Iterable[Mapping[str, Any]]) -> list[str]:
    """计算引用全部操作数的数据集身份：来源卡片与导出附录据此列出源文件。"""
    return list(dict.fromkeys(
        value for entry in entries
        for value in (*(entry.get(key) for key in ("datasetId", "currentDatasetId", "baselineDatasetId")),
                      *(entry.get("datasetIds") or ()))
        if isinstance(value, str) and value
    ))


def statement_fingerprint(markdown: str, claim_id: str) -> str | None:
    return statement_fingerprints(markdown, (claim_id,))[claim_id]


def statement_fingerprints(markdown: str, claim_ids: Iterable[str]) -> dict[str, str | None]:
    """同一草稿只做一次显示规范化，不跨请求缓存可编辑正文。"""
    from ..delivery.report_runtime.markdown import normalize_cjk_punctuation, normalize_cjk_wording

    markdown = normalize_cjk_punctuation(normalize_cjk_wording(markdown))
    return {claim_id: _statement_fingerprint(markdown, claim_id) for claim_id in claim_ids}


def _statement_fingerprint(markdown: str, claim_id: str) -> str | None:
    marker = f"[[claim:{claim_id}]]"
    if markdown.count(marker) != 1:
        return None
    before, after = markdown.split(marker)
    statement = re.split(r"[。！？；;\n]", before)[-1] + re.split(r"[。！？；;\n]", after)[0]
    statement = re.sub(r"\[\[[^\]\n]+\]\]", "", statement)
    return hashlib.sha256(re.sub(r"[\s*]", "", statement).encode()).hexdigest()


class BoundNumberDisplay(NamedTuple):
    text: str
    start: int
    verified: bool


ASSERTION_PLACEHOLDER = re.compile(r"\{\{assert:(assert-[0-9a-f]{64})\}\}")
UNAVAILABLE_ASSERTION_TEXT = "证据不足，需补充来源或指标口径。"


def assertion_unavailable_reason(assertion: Any) -> str | None:
    """受控结论不能展开为事实片段的原因（面向读者）；可以展开时返回 None。"""
    if assertion is None:
        return "受控结论编号不存在"
    if assertion.status != "supported":
        return "受控结论证据不足"
    if not assertion.reference_token and assertion.request.operation != "value":
        return "受控结论没有可展开的登记数值"
    return None


def expand_assertion_placeholders(
    markdown: str,
    assertions: Mapping[str, Any] | None,
    *,
    unavailable: Callable[[str], str] | None = None,
) -> str:
    """Use the same server fragment before scoring, retry selection and binding."""

    def expand(match: re.Match[str]) -> str:
        assertion = (assertions or {}).get(match[1])
        if (reason := assertion_unavailable_reason(assertion)) is not None:
            return unavailable(reason) if unavailable is not None else UNAVAILABLE_ASSERTION_TEXT
        reference = assertion.reference_token or assertion.request.operands[0]
        return assertion.factual_fragment(value_placeholder=reference)

    return ASSERTION_PLACEHOLDER.sub(expand, markdown)


def bound_number_display(
    markdown: str, claim_id: str, selected: dict[str, Any] | None
) -> BoundNumberDisplay | None:
    """读取唯一锚点紧邻显示，并按冻结选择器核值；不从同句其他数值借依据。"""
    from .subject_builder import (
        _DECLINE_PREFIX,
        _UNIT_PATTERN,
        formatted_value_matches,
        value_matches,
    )

    marker = f"[[claim:{claim_id}]]"
    if markdown.count(marker) != 1:
        return None
    position = markdown.index(marker)
    before = re.sub(r"(?:\s*\[\[citation:[^\]\r\n]+\]\]\s*)+$", "", markdown[:position])
    unit = re.escape(selected["unit"]) if selected and selected["unit"] else ""
    units = (unit + "|" if unit else "") + _UNIT_PATTERN
    shown = re.search(
        r"(?<![\d.,+\-a-zA-Z_])(?P<display>" + _NUMBER + rf"\s*(?:{units})?)\s*$", before
    )
    if shown is None:
        return None
    prefix = re.sub(r"\[\[[^\]\n]+\]\]", "", markdown[: shown.start("display")])
    direction = re.search(_DECLINE_PREFIX + "$", prefix)
    comparable = (direction[0] if direction else "") + shown["display"]
    verified = selected is not None and (
        value_matches(comparable, selected["value"])
        or formatted_value_matches(comparable, selected["value"], selected["unit"])
    )
    return BoundNumberDisplay(shown["display"], shown.start("display"), verified)


def render_bound_numbers(
    markdown: str, contents, *, key: str, field_definitions=None,
    table_sources: Mapping[str, bytes] | None = None,
    assertions: Mapping[str, Any] | None = None,
):
    contents = tuple(contents)
    table_sources = table_sources or {}
    table_derivations: dict[str, TableDerivationV1] = {}
    from .number_selection import align_number_selections

    markdown, _ = align_number_selections(markdown, contents, field_definitions)
    catalog = frozen_number_catalog(contents)
    calc_tokens = {match[0] for match in CALC_TOKEN.finditer(markdown)}
    evaluator = CalcEvaluator(contents) if calc_tokens else None
    if evaluator is not None:
        for token in calc_tokens:
            result = evaluator.evaluate(token)
            # 无法求值的计算引用不进目录，渲染时与未登记引用一样标注待核实。
            if result is not None:
                catalog[token] = result.text
    references: list[tuple[str, str]] = []
    notices: list[ReviewNoticeV1] = []
    counter = 0

    def identity(kind: str) -> str:
        nonlocal counter
        counter += 1
        return kind + "-" + hashlib.sha256(f"{key}:{counter}".encode()).hexdigest()[:20]

    def notice(kind: str, text: str = "待核实", *, original_text: str | None = None,
               reason: str | None = None) -> str:
        claim_id = identity("review")
        if original_text is not None and len(original_text) > 4096:
            original_text = None  # 附加展示信息超预算不能阻断报告生成。
        notices.append(ReviewNoticeV1(claimId=claim_id, kind=kind, originalText=original_text,
                                      reason=reason[:512] if reason else None))
        return text + f"[[claim:{claim_id}]]"

    def unavailable_reference(token: str) -> tuple[str, str | None]:
        if evaluator is not None and token in calc_tokens:
            return f"计算引用无法求值：{evaluator.failure(token) or '结果不可用'}", None
        if token in catalog and catalog[token] != "数值待核实":
            # 引用本身有效，但正文紧随的单位与登记值不同类：多为模型拿错引用。
            return "正文所写单位与引用数值的单位不一致", catalog[token]
        reason, shown, _suggestions = value_reference_failure(token, catalog)
        return reason, shown

    def annotate(token: str, text: str) -> str:
        if token not in catalog or text == "数值待核实":
            reason, shown = unavailable_reference(token)
            return notice("numeric_unverified", text, original_text=shown, reason=reason)
        claim_id = identity("number")
        references.append((claim_id, token))
        return text + f"[[claim:{claim_id}]]"

    # 模型不能自行签发数字锚点。原正文的复核表述独立记为来源复核，不能拿来恢复数字。
    markdown = re.sub(r"\[\[claim:[^\]\n]+\]\]", "", markdown)
    markdown = re.sub("待核实", lambda _: notice("source_review"), markdown)
    markdown = expand_assertion_placeholders(
        markdown, assertions,
        unavailable=lambda reason: notice("source_review", UNAVAILABLE_ASSERTION_TEXT, reason=reason),
    )
    markdown = render_frozen_numbers(
        align_placeholder_direction(markdown, contents), catalog, annotate=annotate
    )

    def derived_anchor(entry: Any, unit: str) -> str:
        token = derived_reference_token(entry, unit)
        if token is None:
            return ""
        if entry.table_derivation is not None:
            table_derivations[token] = entry.table_derivation
        claim_id = identity("number")
        references.append((claim_id, token))
        return f"[[claim:{claim_id}]]"

    markdown = plain_period_wording(
        group_large_amounts(
            replace_unregistered_numbers(
                normalize_signed_wording(
                    correct_period_extrema(
                        correct_constant_monthly_totals(markdown, contents), contents
                    )
                ),
                contents,
                missing=lambda: notice("numeric_unverified", reason=UNREGISTERED_NUMBER_REASON),
                on_unverified=lambda original: notice(
                    "numeric_unverified", original_text=original, reason=UNREGISTERED_NUMBER_REASON,
                ),
                references=dict(references),
                on_derived_anchor=derived_anchor,
                table_sources=table_sources,
            )
        )
    )
    resolver = NumberReferenceResolver(contents)
    signed_references = []
    for claim_id, token in references:
        marker = f"[[claim:{claim_id}]]"
        position = markdown.find(marker)
        if position < 0:
            continue
        table_derivation = table_derivations.get(token)
        selected = (
            resolve_table_derivation(token, table_derivation, table_sources)
            if table_derivation is not None else resolver.resolve(token)
        )
        shown = bound_number_display(markdown, claim_id, selected)
        if shown is None:
            # 数值可能已被下游替换为待核实，不能为占位继续签发原数值引用。
            markdown = markdown[:position] + markdown[position + len(marker) :]
            continue
        display_text = shown.text
        if not shown.verified:
            # 后置规范化不能改变已经登记的事实值；失配则保留真实待核实事件。
            markdown = (
                markdown[: shown.start]
                + notice("numeric_unverified", original_text=display_text)
                + markdown[position + len(marker) :]
            )
            continue
        signed_references.append(
            NumberReferenceV1(
                claimId=claim_id,
                token=token,
                statementSha256=statement_fingerprint(markdown, claim_id),
                displayText=display_text,
                tableDerivation=table_derivation,
            )
        )
    # 后续引用撤销会改变同句文字，指纹必须在最终正文上统一冻结。
    references = tuple(
        reference.model_copy(
            update={
                "statement_sha256": statement_fingerprint(markdown, reference.claim_id),
            }
        )
        for reference in signed_references
    )
    return strip_bound_anchors(markdown, references, notices)


def strip_bound_anchors(markdown: str, references, notices):
    """把服务端临时锚点收为装配偏移，正文仍遵守禁止协议注入的原有契约。"""
    offsets = {}
    removed = 0
    for match in re.finditer(r"\[\[claim:([^\]\n]+)\]\]", markdown):
        offsets[match[1]] = match.start() - removed
        removed += len(match[0])
    plain = re.sub(r"\[\[claim:[^\]\n]+\]\]", "", markdown)
    return (
        plain,
        tuple(
            item.model_copy(update={"offset": offsets[item.claim_id]})
            for item in references
            if item.claim_id in offsets
        ),
        tuple(
            item.model_copy(update={"offset": offsets[item.claim_id]})
            for item in notices
            if item.claim_id in offsets
        ),
    )


def anchor_bound_numbers(markdown: str, references, notices=()) -> str:
    """只在首次装配中按服务端记录的偏移插入锚点，此后编辑仅使用锚点定位。"""
    for item in sorted((*references, *(notices or ())), key=lambda item: item.offset, reverse=True):
        if item.offset <= len(markdown):
            markdown = (
                markdown[: item.offset] + f"[[claim:{item.claim_id}]]" + markdown[item.offset :]
            )
    return markdown


class NumberReferenceResolver:
    """仅在一次校验请求内复用同组已核验文件的数值目录。"""

    def __init__(self, contents):
        contents = tuple(contents)
        self.numbers = {}
        for token, value, unit, target in _frozen_number_entries(contents):
            self.numbers.setdefault(token, []).append((value, unit, target))
        self.entries = {}
        self.conflicts = set()
        records = {}
        for bundle in frozen_fact_bundles(contents):
            for key, record in fact_binding_records(bundle).items():
                if key in records:
                    merged = merge_binding_records(records[key], record)
                    if merged is None:
                        self.conflicts.add(key)
                    record = merged or record
                records[key] = record
            document = bundle.model_dump(mode="json", by_alias=True)
            for array in (
                "metrics",
                "comparisons",
                "derivedMetrics",
                "reconciliations",
                "correlationDetails",
            ):
                for fact in document.get(array, ()):
                    key = fact.get("factId")
                    if key in self.entries:
                        merged = merge_frozen_fact(self.entries[key], fact)
                        if merged is None:
                            self.conflicts.add(key)
                        else:
                            fact = merged
                    self.entries[key] = fact
        self._contents = contents
        self._derived: dict[str, tuple[Any, str]] | None = None
        self._legacy_derived: dict[str, tuple[Any, str]] | None = None
        self._top_sets: dict[str, dict] = {}
        self._registered_ratios: dict[str, dict | None] = {}
        self._cumulative_changes: dict[str, dict] = {}
        self._group_contributions: dict[str, dict | None] = {}

    def _derived_entries(self, *, legacy: bool = False) -> dict[str, tuple[Any, str]]:
        if self._derived is None:
            derived: dict[str, tuple[Any, str]] = {}
            legacy_derived: dict[str, tuple[Any, str]] = {}
            views: dict[str, dict[str, Any] | None] = {}
            conflicts = set()
            try:
                # 两种格式共享一次枚举和冲突检查，不能按格式优先级隐藏同 token 的不同语义。
                for unit, entry in derived_number_values(self._contents).derived_entries():
                    for is_legacy, catalog in ((False, derived), (True, legacy_derived)):
                        token = derived_reference_token(entry, unit, legacy=is_legacy)
                        if token is None:
                            continue
                        view = derived_reference_resolution(entry, unit, self.entries)
                        if token in views and views[token] != view:
                            conflicts.add(token)
                        else:
                            views[token] = view
                            catalog[token] = (entry, unit)
                derived = {token: value for token, value in derived.items() if token not in conflicts}
                legacy_derived = {
                    token: value for token, value in legacy_derived.items() if token not in conflicts
                }
            except Exception as error:
                # 枚举中途失败也不能使用部分目录；空结果在本次请求内缓存，避免逐 token 重试。
                derived = {}
                legacy_derived = {}
                logger.warning("number_reference_derived_catalog_failed error={}", error)
            self._derived = derived
            self._legacy_derived = legacy_derived
        return self._legacy_derived if legacy else self._derived

    def resolve(self, token: str) -> dict[str, Any] | None:
        try:
            return self._resolve(token)
        except Exception:
            # 派生目录重建只服务软校验；来源损坏时按无法解析降级，不阻断整次校验。
            logger.warning("number_reference_resolve_failed token={}", token)
            return None

    def _resolve(self, token: str) -> dict[str, Any] | None:
        if token.startswith("{{calc:"):
            return self._resolve_calc(token)
        if token.startswith("{{derived:"):
            ids = reference_fact_ids(token)
            # 兼容按操作数身份排序的旧格式，再匹配保留操作数顺序的现格式。
            matched = self._derived_entries(legacy=True).get(token)
            legacy = matched is not None
            if matched is None:
                matched = self._derived_entries().get(token)
            if matched is None:
                return None
            entry, unit = matched
            if (
                len(ids) != 2
                or any(key in self.conflicts or key not in self.entries for key in ids)
                or set(ids) != set(entry.fact_ids)
                or (legacy and ids != tuple(sorted(entry.fact_ids)))
            ):
                return None
            return derived_reference_resolution(entry, unit, self.entries)
        matches = self.numbers.get(token, ())
        if not matches or len({(str(value), unit, target) for value, unit, target in matches}) != 1:
            return None
        ids = reference_fact_ids(token)
        if not ids or any(key not in self.entries or key in self.conflicts for key in ids):
            return None
        resolved = _resolved_number_reference(token, ids, self.entries, matches[0], self.conflicts)
        if resolved["selector"].startswith("cumulativeChanges."):
            from .cumulative_changes import registered_cumulative_changes

            if ids[0] not in self._cumulative_changes:
                self._cumulative_changes[ids[0]] = registered_cumulative_changes(self.entries[ids[0]])[0]
            proof = self._cumulative_changes[ids[0]].get(resolved["selector"])
            if proof is None:
                return None
            resolved["_cumulative_change_proof"] = proof
            baseline = (proof["baseline_period"],) if proof["baseline_period"] else ()
            current = (proof["current_period"],)
            resolved["periods"] = tuple(dict.fromkeys((*current, *baseline)))
            resolved["period_roles"] = {"current": current, "baseline": baseline}
            resolved["formula"] = (f"({proof['current_value']}) - ({proof['baseline_value']})"
                                   + ("；按已确认自然年重置零基线" if proof["reset"] else "；相邻月末累计快照差额"))
        if resolved["selector"].startswith("topSet."):
            from .top_sets import registered_top_sets

            if ids[0] not in self._top_sets:
                self._top_sets[ids[0]] = registered_top_sets(self.entries[ids[0]])[0]
            resolved["_top_set_proof"] = self._top_sets[ids[0]].get(resolved["selector"])
        if resolved["selector"].startswith("groupContributions."):
            if any(key in self.conflicts for key in self.entries[ids[0]].get("inputFactIds", ())):
                return None
            from .group_contributions import registered_group_contributions

            if ids[0] not in self._group_contributions:
                self._group_contributions[ids[0]] = registered_group_contributions(
                    self.entries[ids[0]], self.entries,
                    profile_hash=self.entries.get(self.entries[ids[0]]["inputFactIds"][0], {}).get("profileHash") or "",
                    fact_warnings={key: entry.get("warnings", ()) for key, entry in self.entries.items()},
                )[0]
            resolved["_group_contribution_proof"] = self._group_contributions[ids[0]]
            proof = resolved["_group_contribution_proof"]
            if proof is not None:
                index = int(resolved["selector"].split(".")[1])
                resolved["formula"] = f"({proof['deltas'][index]}) / ({proof['netChange']}) * 100%（同单位分组差额 / 总体有符号净差额）"
        if resolved["selector"] == "registeredRatio":
            from .ratio_proofs import registered_ratio

            if any(key in self.conflicts for key in self.entries[ids[0]].get("inputFactIds", ())):
                return None
            if ids[0] not in self._registered_ratios:
                self._registered_ratios[ids[0]] = registered_ratio(self.entries[ids[0]], self.entries,
                    profile_hash=self.entries[ids[0]].get("profileHash") or "",
                    fact_warnings={key: entry.get("warnings", ()) for key, entry in self.entries.items()})[0]
            resolved["_registered_ratio_proof"] = self._registered_ratios[ids[0]]
            proof = resolved["_registered_ratio_proof"]
            if proof is not None:
                resolved["formula"] = f"({proof['numeratorValue']}) / ({proof['denominatorValue']})" + (" * 100%" if proof["unit"] == "%" else f" {proof['unit']}")
        if resolved["entry"].get("comparisonType"):
            resolved["_comparison_subjects"] = tuple(
                str(name) for key in resolved["entry"].get("inputFactIds", ())
                for name in (self.entries.get(key, {}).get("displayName"), self.entries.get(key, {}).get("field"))
                if name
            )
        return resolved


    def _resolve_calc(self, token: str) -> dict[str, Any] | None:
        """计算引用的核对视图：与派生引用同构，公式写出各操作数的指标名与冻结原值。"""
        result = CalcEvaluator(self._contents).evaluate(token)
        if result is None:
            return None
        views = []
        for operand in result.operands:
            if operand.fact_id in self.conflicts or operand.fact_id not in self.entries:
                return None
            view = self.resolve("{{value:" + f"{operand.fact_id}:{operand.field}:{operand.unit}" + "}}")
            if view is None:
                return None
            views.append(view)
        from ..delivery.report_runtime.markdown import _readable_fact_value
        from .table_builder import _period_display_label

        labels = []
        for operand, view in zip(result.operands, views, strict=True):
            entry = view["entry"]
            # 指标名缺失时用字段名，不向读者显示内部选择器；写出各操作数取值的期间。
            name = entry.get("displayName") or entry.get("field") or "登记值"
            span = "至".join(dict.fromkeys(
                _period_display_label(str(period), entry.get("periodGranularity"))
                for period in (*view["periods"][:1], *view["periods"][-1:])
            ))
            labels.append(f"{name}{f'（{span}）' if span else ''}{_readable_fact_value(float(operand.value), operand.unit)}")
        periods = tuple(dict.fromkeys(period for view in views for period in view["periods"]))
        roles: dict[str, tuple[str, ...]] = {}
        for view in views:
            for role, role_periods in (view.get("period_roles") or {}).items():
                roles[role] = tuple(dict.fromkeys((*roles.get(role, ()), *role_periods)))
        scopes = [view["scope"] for view in views]
        scope = scopes[0] if all(item == scopes[0] for item in scopes) else {}
        display = Decimal(result.text.replace(",", "").removesuffix(result.display_unit))
        return {
            "value": float(display),
            "unit": result.display_unit,
            "periods": periods,
            "period_roles": roles,
            "scope": scope,
            "formula": f"{result.expression.format(*labels)} = {result.text}",
            "entry": {
                "displayName": "、".join(dict.fromkeys(
                    str(view["entry"].get("displayName")) for view in views if view["entry"].get("displayName")
                )) or None,
                "aliases": (),
                "scope": scope,
                "datasetIds": _dataset_ids(view["entry"] for view in views),
            },
            "selector": "calc",
            # 语句核对按外层运算区分：合计与平均须写出覆盖全部操作数期间的窗口，比值、差额与增速比较两个期间。
            "operation": result.formula.split("(", 1)[0],
            "operandEntries": tuple(view["entry"] for view in views),
        }


def resolve_number_reference(token: str, contents) -> dict[str, Any] | None:
    """仅从调用者已经核验文件身份的内容重算完整 token；缺失或冲突不回退 total。"""
    return NumberReferenceResolver(contents).resolve(token)


def resolve_number_references(tokens: Iterable[str], contents) -> dict[str, dict[str, Any] | None]:
    """同一组已核验来源只展开一次，不跨文件组或请求缓存。"""
    resolver = NumberReferenceResolver(contents)
    return {token: resolver.resolve(token) for token in tokens}


def _comparison_baseline_periods(primary, entries, conflicts):
    from .subject_builder import fact_periods

    if primary.get("baselinePeriodStart") and primary.get("baselinePeriodEnd"):
        return fact_periods(
            {
                **primary,
                "periodStart": primary["baselinePeriodStart"],
                "periodEnd": primary["baselinePeriodEnd"],
            }
        )
    # 旧快照从已登记输入复核完整比较窗口；没有唯一依据时不把本期冒充基期。
    operands = []
    for prefix in ("current", "baseline"):
        candidates = [
            entry
            for entry in entries.values()
            if entry.get("factId") not in conflicts
            and entry.get("datasetId") == primary.get(prefix + "DatasetId")
            and entry.get("datasetSha256") == primary.get(prefix + "DatasetSha256")
            and entry.get("fieldRef") == primary.get("fieldRef")
        ]
        if len(candidates) != 1:
            return ()
        operands.append(DeterministicMetricFact.model_validate(candidates[0]))
    try:
        aligned = _aligned_comparison_values(*operands, primary["comparisonType"])
    except ValueError:
        return ()
    if aligned is None or fact_periods(
        {**primary, "periodStart": aligned[2], "periodEnd": aligned[3]}
    ) != fact_periods(primary):
        return ()
    return fact_periods({**primary, "periodStart": aligned[4], "periodEnd": aligned[5]})


def _resolved_number_reference(token, ids, entries, selected_value, conflicts):
    primary = entries[ids[0]]
    value, unit, target = selected_value
    selector = token[2:-2].split(":")[2]
    from .subject_builder import fact_periods

    periods = fact_periods(primary)
    period_roles = {}
    selected_periods = None
    if primary.get("comparisonType") and (
        selector in {"currentTotal", "baselineTotal", "change", "changeRate"}
        or selector.startswith("groupContributions.")
    ):
        current_periods = periods
        baseline_periods = _comparison_baseline_periods(primary, entries, conflicts)
        if selector == "baselineTotal":
            periods = baseline_periods
            period_roles["baseline"] = baseline_periods
        elif selector == "currentTotal":
            period_roles["current"] = current_periods
        else:
            periods = tuple(dict.fromkeys((*current_periods, *baseline_periods)))
            period_roles.update(current=current_periods, baseline=baseline_periods)
    elif selector.startswith("periodValues."):
        selected_periods = [primary["periodValues"][int(selector.split(".")[1])]]
    elif selector.startswith(("periodTotals.", "periodAverages.")):
        start, end = (int(index) for index in selector.split(".")[1].split("-"))
        selected_periods = primary["periodValues"][start : end + 1]
    elif selector.startswith(("periodChanges.", "periodChangeRates.")):
        index = int(selector.split(".")[1])
        selected_periods = primary["periodValues"][index - 1 : index + 1]
    elif selector.startswith("budgetComparison."):
        period = selector[len("budgetComparison." + ids[1] + ".") :].rsplit(".", 1)[0]
        window = period.split("..")
        periods = fact_periods(
            {"periodStart": window[0], "periodEnd": window[-1], "periodGranularity": "month"}
        )
        period_roles["endpoint"] = (periods[-1],)
    elif primary.get("periodAggregation") == "last" and (
        selector in {"total", "average", "minimum", "maximum"}
        or selector.startswith(("topGroups.", "bottomGroups.", "groupShares.", "groupGaps.", "topSet."))
    ):
        selected_periods = primary.get("periodValues", ())[-1:]
    if selected_periods is not None:
        # 复用事实粒度规范化，保留累计窗口的所有桶及环比的基期与本期。
        periods = fact_periods({**primary, "periodValues": selected_periods})
        if selector.startswith(("periodTotals.", "periodAverages.")):
            period_roles["endpoint"] = fact_periods(
                {**primary, "periodValues": selected_periods[-1:]}
            )
        elif selector.startswith(("periodChanges.", "periodChangeRates.")):
            period_roles["baseline"] = fact_periods(
                {**primary, "periodValues": selected_periods[:1]}
            )
            period_roles["current"] = fact_periods(
                {**primary, "periodValues": selected_periods[-1:]}
            )
    scope = dict(primary.get("scope") or {})
    if selector.startswith(("topGroups.", "bottomGroups.")):
        group, index = selector.split(".")
        selected_group = primary[group][int(index)]
        if selected_group.get("groupValues"):
            scope.update(selected_group["groupValues"])
        else:
            scope["group"] = selected_group["group"]

    def operand(value) -> str:
        return format(Decimal(str(value)).normalize(), "f")

    formula = primary.get("formula")
    if selector.startswith("groupContributions."):
        formula = "同一结构化分组本期值减去已换算基期值，再除以完整总体有符号净差额乘百分之百"
    elif selector.startswith("topSet."):
        formula = f"完整冻结分组总体按 {selector} 选择成员后求和"
    elif selector == "monthlyTrend":
        formula = "月值序列：" + " → ".join(operand(item["value"]) for item in primary["periodValues"])
    elif selector in {"monthlyAverage", "monthlyMinimum", "monthlyMaximum"}:
        amounts = [operand(item["value"]) for item in primary["periodValues"]]
        if selector == "monthlyAverage":
            formula = "(" + " + ".join(f"({amount})" for amount in amounts) + f") / {len(amounts)}"
        else:
            operation = "min" if selector == "monthlyMinimum" else "max"
            formula = operation + "(" + ", ".join(amounts) + ")"
    elif selector.startswith(("periodTotals.", "periodAverages.")):
        formula = " + ".join(f"({operand(item['value'])})" for item in selected_periods)
        if selector.startswith("periodAverages."):
            formula = f"({formula}) / {len(selected_periods)}"
    elif selector.startswith(("periodChanges.", "periodChangeRates.")):
        baseline, current = (operand(item["value"]) for item in selected_periods)
        formula = f"({current}) - ({baseline})"
        if selector.startswith("periodChangeRates."):
            formula = f"({formula}) / abs({baseline}) * 100"
    elif selector.startswith("groupShares."):
        _, group, index = selector.split(".")
        numerator = primary[group][int(index)]
        # Structured dimensions identify the group even when its display label
        # contains a delimiter or is serialized JSON for collision handling.
        if numerator.get("groupValues"):
            scope.update(numerator["groupValues"])
        else:
            scope["group"] = numerator["group"]
        formula = f"({operand(numerator['value'])}) / ({operand(primary['total'])}) * 100"
    elif selector.startswith("groupGaps."):
        left, right = (int(index) for index in selector.split(".")[1].split("-"))
        left_group, right_group = primary["topGroups"][left], primary["topGroups"][right]
        scope.update(leftGroup=left_group["group"], rightGroup=right_group["group"])
        for prefix, selected_group in (("leftGroup", left_group), ("rightGroup", right_group)):
            scope.update(
                {
                    f"{prefix}.{key}": value
                    for key, value in (selected_group.get("groupValues") or {}).items()
                }
            )
        formula = f"abs(({operand(left_group['value'])}) - ({operand(right_group['value'])}))"
    elif selector.startswith("budgetComparison."):
        operands = [
            sum(
                (
                    Decimal(str(item["value"]))
                    for item in entry["periodValues"]
                    if window[0] <= _canonical_month_label(item["period"]) <= window[-1]
                ),
                Decimal(0),
            )
            for entry in (primary, entries[ids[1]])
        ]
        operation = "/" if selector.endswith(".percentage") else "-"
        formula = f"({operand(operands[0])}) {operation} ({operand(operands[1])})"
        if operation == "/":
            formula += " * 100"
    elif selector.startswith("projectRatio."):
        operation = "/" if selector.endswith(".percentage") else "-"
        formula = f"({primary.get('formula')}) {operation} ({entries[ids[1]].get('formula')})"
        if operation == "/":
            formula += " * 100"
    elif selector.startswith("metricShare."):
        window = (
            selector[len("metricShare." + ids[1] + ".") :]
            if "." in selector[len("metricShare.") :]
            else None
        )
        if window:
            span = window.split("..")
            periods = fact_periods(
                {"periodStart": span[0], "periodEnd": span[-1], "periodGranularity": "month"}
            )
            period_roles["endpoint"] = (periods[-1],)
            operands = [
                sum(
                    (
                        Decimal(str(item["value"]))
                        for item in entry["periodValues"]
                        if span[0] <= _canonical_month_label(item["period"]) <= span[-1]
                    ),
                    Decimal(0),
                )
                for entry in (primary, entries[ids[1]])
            ]
            formula = f"({operand(operands[0])}) / ({operand(operands[1])}) * 100"
        else:
            formula = f"({primary.get('formula')}) / ({entries[ids[1]].get('formula')}) * 100"
    return {
        "value": float(value),
        "unit": target if target == "个百分点" else unit,
        "periods": periods,
        "period_roles": period_roles,
        "scope": scope,
        "formula": formula,
        "entry": primary,
        "selector": selector,
    }
