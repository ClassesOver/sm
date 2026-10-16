"""正文 claim → SubjectBindingV1 构造（B6，计划 6.1 与 B2-2 受控标记）。

subject 定位锚是装配器注入的 ``[[claim:id]]`` 协议标记（draft_v1
_marker_lines）：编辑不删除标记即可重新验证；subjectSha256 是生成时
claim 数值事实的规范化指纹，用于判定"正文仍在陈述生成时的事实"。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from ..delivery.report_runtime.markdown import _subject_id
from ..hospital_operation.deterministic_analysis import _next_period, _parse_period, _ParsedPeriod
from .contracts_v1 import (
    FactRefV1,
    SubjectBindingV1,
    SubjectLocatorV1,
    canonical_sha256,
    subject_fingerprint,
)


def bind_table_subjects(index: Any) -> Any:
    """从已登记的单元格定位与事实绑定补齐来源入口，兼容既有发布索引。"""
    bindings = list(index.subject_bindings)
    locators = {
        (item.locator.table_id, item.locator.row_key, item.locator.column_key)
        for item in bindings if item.subject_kind == "table_cell"
    }
    for table in index.tables:
        for cell in table.cells:
            locator = (table.table_id, cell.row_key, cell.column_key)
            if locator in locators or not cell.fact_refs:
                continue
            fingerprint = canonical_sha256({
                "tableId": table.table_id, **cell.model_dump(mode="json", by_alias=True),
            })
            bindings.append(SubjectBindingV1(
                subjectId=f"sub-{fingerprint[:16]}", subjectKind="table_cell",
                locator=SubjectLocatorV1(
                    tableId=table.table_id, rowKey=cell.row_key, columnKey=cell.column_key,
                ),
                subjectSha256=fingerprint, factRefs=cell.fact_refs,
                computationId=cell.computation_id,
            ))
            locators.add(locator)
    return index.model_copy(update={"subject_bindings": tuple(bindings)})


def build_claim_subject_bindings(
    section_artifacts: Sequence[Any],
    fact_directory: Mapping[str, tuple[str, str]],
    fact_file_resources: Mapping[str, str],
    *,
    pointer_kind: str = "metric",
) -> tuple[SubjectBindingV1, ...]:
    """把 SectionArtifact.claims 冻结为正文 subject 绑定。

    ``fact_directory``：factId → (analysisId, jsonPointer)；
    ``fact_file_resources``：analysisId → 索引文件资源 ID。
    factId 不在目录中的 claim 跳过（软降级，不伪造绑定）。
    """

    bindings: list[SubjectBindingV1] = []
    used_ids: set[str] = set()
    for artifact in section_artifacts:
        section_code = str(artifact.section_code)
        from .semantic_bindings import reference_fact_ids

        structured_claims = set()
        for block in getattr(artifact, "blocks", ()):
            if getattr(block, "review_notices", None) is not None:
                structured_claims.update(block.claim_ids)
            for number in getattr(block, "number_references", ()):
                ids = reference_fact_ids(number.token)
                if not ids or any(fact_id not in fact_directory or
                                  fact_directory[fact_id][0] not in fact_file_resources for fact_id in ids):
                    continue
                refs = []
                for fact_id in ids:
                    analysis_id, pointer = fact_directory[fact_id]
                    refs.append(FactRefV1(
                        analysisId=analysis_id, fileResourceId=fact_file_resources[analysis_id],
                        jsonPointer=pointer, factKey=fact_id,
                        factKind={"comparisons": "comparison", "derivedMetrics": "derived",
                                  "reconciliations": "reconciliation", "correlationDetails": "correlation"}.get(pointer.split("/")[1], pointer_kind),
                    ))
                subject_id = _subject_id(section_code, number.claim_id)
                if subject_id in used_ids:
                    continue
                used_ids.add(subject_id)
                bindings.append(SubjectBindingV1(
                    subjectId=subject_id, subjectKind="text_claim",
                    locator=SubjectLocatorV1(sectionId=section_code),
                    subjectSha256=number.statement_sha256, claimId=number.claim_id,
                    factRefs=tuple(refs), numberReference=number,
                ))
        for claim in artifact.claims:
            if claim.claim_id in structured_claims:
                continue
            refs: list[FactRefV1] = []
            for fact_id in claim.fact_ids:
                located = fact_directory.get(fact_id)
                if located is None:
                    continue
                analysis_id, pointer = located
                resource_id = fact_file_resources.get(analysis_id)
                if resource_id is None:
                    continue
                refs.append(
                    FactRefV1(
                        analysisId=analysis_id,
                        fileResourceId=resource_id,
                        jsonPointer=pointer,
                        factKind={"comparisons": "comparison", "derivedMetrics": "derived", "reconciliations": "reconciliation", "correlationDetails": "correlation"}.get(pointer.split("/")[1], pointer_kind),
                        factKey=fact_id,
                    )
                )
            if not refs:
                continue
            subject_id = _subject_id(section_code, claim.claim_id)
            if subject_id in used_ids:
                continue
            used_ids.add(subject_id)
            identity_text = f"{claim.value}|{claim.metric_code}|{claim.current_period}"
            bindings.append(
                SubjectBindingV1(
                    subjectId=subject_id,
                    subjectKind="text_claim",
                    locator=SubjectLocatorV1(sectionId=section_code),
                    subjectSha256=subject_fingerprint(identity_text),
                    claimId=claim.claim_id,
                    factRefs=tuple(refs),
                    evidenceKind="computed",
                )
            )
    return tuple(bindings)


def value_text_variants(value: Any) -> tuple[str, ...]:
    """事实显示值的常见文本形态（裸数、千分位、两位小数），用于正文比对。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return (str(value),) if value is not None else ()
    if number != number or number in (float("inf"), float("-inf")):
        return ()
    variants: list[str] = []
    integer = int(number)
    if float(integer) == number:
        variants.extend((f"{integer}", f"{integer:,}"))
    variants.append(f"{number:g}")
    # 与冻结目录保持十进制 ROUND_HALF_UP；float 的 .2f 会将 1.005 写为 1.00。
    with localcontext() as context:
        context.prec = max(28, len(str(abs(integer))) + 2)
        rounded = Decimal(str(number)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        variants.append(f"{abs(rounded) if rounded == 0 else rounded:,f}")
    return tuple(dict.fromkeys(variants))


def claim_marker(claim_id: str) -> str:
    return f"[[claim:{claim_id}]]"


# 紧跟“月”的数字是日期（2025年12月），不是事实值；“8.5日”“本月35.3万人次”不受影响。
_VALUE_BOUNDARY_TAIL = r"(?![\d.,eE])(?!\s*月)"

# 只遮蔽明确日历写法，保留“8.5日”等时长和 2025.09 元这样的金额。
_DATE_VALUE = re.compile(
    r"(?<![\dA-Za-z_.,])(?:\d{4}\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?)?"
    r"|\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?|\d{1,2}\s*月\s*\d{1,2}\s*日)(?!\d)"
)


def _mask_calendar_values(text: str) -> str:
    # 等长替换保留锚点插入位置，不能因为删掉日期而移动来源标记。
    return _DATE_VALUE.sub(lambda match: ' ' * len(match[0]), text)


# 负的冻结值推荐写成“下降/减少… + 正幅度”，绑定与锚定须把该写法视为同一数值。
def _decline_prefix() -> str:
    from .numeric_text import FALLING_WORDS

    return rf"(?:{'|'.join(FALLING_WORDS)})(?:\s*(?:了|约|为|达|幅度为))*\s*"


_DECLINE_PREFIX = _decline_prefix()


def _negative_magnitude(fact_value: Any) -> float | None:
    try:
        number = float(fact_value)
    except (TypeError, ValueError):
        return None
    return -number if number < 0 else None


def _value_patterns(fact_value: Any) -> list[str]:
    patterns = [
        r"(?<![\d.,+\-a-zA-Z_])" + re.escape(variant) + _VALUE_BOUNDARY_TAIL
        for variant in value_text_variants(fact_value)
    ]
    magnitude = _negative_magnitude(fact_value)
    if magnitude is not None:
        patterns.extend(
            _DECLINE_PREFIX + re.escape(variant) + _VALUE_BOUNDARY_TAIL
            for variant in value_text_variants(magnitude)
        )
    return patterns


def value_matches(cell_text: str, fact_value: Any) -> bool:
    """判定单个文本片段是否呈现该事实值（带数字边界，供 claim 窗口与表格单元格共用）。"""

    cell_text = _mask_calendar_values(cell_text.replace("−", "-").replace("－", "-"))
    return any(re.search(pattern, cell_text) for pattern in _value_patterns(fact_value))



def _display_units(unit: str | None) -> tuple[str, ...] | None:
    """冻结值可用的显示单位：金额与人次可按固定倍率换算，百分数/千分数原样；其余不核对。"""
    from .numeric_text import PERCENT_POINT, _unit_scales

    scales = _unit_scales(unit)
    if scales is not None:
        return tuple(scales)
    return (unit,) if unit in {"%", "‰", PERCENT_POINT} else None


def formatted_value_matches(text: str, value: Any, unit: str | None) -> bool:
    """用冻结值的相同舍入规则核对带单位显示文本。"""
    units = _display_units(unit)
    if value is None or units is None:
        return False
    text = text.replace("−", "-").replace("－", "-").replace("**", "")
    return any(re.search(pattern, text) for pattern in _formatted_patterns(value, unit, units))


def _formatted_patterns(value: Any, unit: str | None, units: Sequence[str]) -> list[str]:
    from .numeric_text import _hidden_by_rounding, format_fact_value

    patterns = [
        r"(?<![\d.,+\-])" + re.escape(format_fact_value(value, unit, target)) + r"(?![\d.])"
        for target in units if not _hidden_by_rounding(value, unit, target)
    ]
    magnitude = _negative_magnitude(value)
    if magnitude is not None:
        patterns.extend(
            _DECLINE_PREFIX + re.escape(format_fact_value(magnitude, unit, target)) + r"(?![\d.])"
            for target in units if not _hidden_by_rounding(value, unit, target)
        )
    return patterns


def bind_local_claim_values(artifacts: Sequence[Any], fact_values: Mapping[str, tuple[Any, str | None]]) -> tuple[Any, ...]:
    """数值 subject 只绑定本 block 真正陈述的冻结显示值，趋势仍通过 citation 追溯。"""
    from loguru import logger

    normalized = []
    for artifact in artifacts:
        claims = []
        for claim in artifact.claims:
            local = "\n\n".join(block.markdown for block in artifact.blocks if claim.claim_id in block.claim_ids)
            paragraphs = [part for part in local.split("\n\n") if not part.startswith(("#", "|", "```"))]
            supported = tuple(fact_id for fact_id in claim.fact_ids if fact_id in fact_values
                and any(formatted_value_matches(part, *fact_values[fact_id]) or value_matches(part, fact_values[fact_id][0])
                        for part in paragraphs))
            if claim.fact_ids and not supported:
                logger.warning("report_claim_numeric_binding_omitted section={} claim={} reason=local_value_absent",
                               artifact.section_code, claim.claim_id)
            claims.append(claim.model_copy(update={"fact_ids": supported}))
        normalized.append(artifact.model_copy(update={"claims": tuple(claims)}))
    return tuple(normalized)


def anchor_claims(markdown: str, values: Mapping[str, tuple[Any, str | None] | None]) -> str:
    """只在冻结金额匹配的正文段落注入锚点，未命中仍保留待复核标记。"""
    paragraphs = markdown.split("\n\n")
    for claim_id, frozen in values.items():
        marker = claim_marker(claim_id)
        placed = False
        if frozen is not None:
            value, unit = frozen
            for index, paragraph in enumerate(paragraphs):
                if paragraph.startswith(("#", "|", "```")):
                    continue
                for statement in re.split(r"(?<=[。！？；])", paragraph):
                    if formatted_value_matches(statement, value, unit) or value_matches(statement, value):
                        # 锚点紧跟数值，避免长句把金额推到校验窗口之外。
                        targets = _display_units(unit)
                        patterns = _formatted_patterns(value, unit, targets) if targets else []
                        patterns.extend(_value_patterns(value))
                        searchable = _mask_calendar_values(statement)
                        matches = [match for pattern in patterns if (match := re.search(pattern, searchable))]
                        if not matches:
                            continue
                        match = matches[0]
                        anchored = statement[:match.end()] + marker + statement[match.end():]
                        paragraphs[index] = paragraph.replace(statement, anchored, 1)
                        placed = True
                        break
                if placed:
                    break
        if not placed:
            paragraphs[-1] += marker
    return "\n\n".join(paragraphs)

def evaluate_subject_status(
    markdown: str,
    claim_id: str,
    fact_value: Any,
    *,
    window_chars: int = 200,
) -> str:
    """按协议标记定位 claim 正文并比对事实值 → valid / stale / unbound。"""

    return claim_status(
        markdown, claim_id, fact_value, window_chars=window_chars
    )["status"]


_PERIOD_TOKEN = re.compile(
    r"\d{4}\s*[-/年.]\s*\d{1,2}(?:\s*[-/月.]\s*\d{1,2}\s*日?)?"
    r"|本月|上月|本季度|上季度|本年|上年|去年同期|环比|同比"
)
_UNIT_TOKENS = ("亿元", "万元", "千元", "个百分点", "%", "‰", "万人次", "人次", "万人", "床日", "床", "张", "次", "人", "元")
_UNIT_PATTERN = "|".join(re.escape(unit) for unit in _UNIT_TOKENS)
_NUMBER_UNIT_RE = re.compile(
    r"(?<![\dA-Za-z_.,+−－-])(?P<number>[+−－-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
    rf"(?P<unit>{_UNIT_PATTERN})(?![\dA-Za-z_])"
)


def _period_key(token: str) -> tuple[int, ...] | None:
    digits = re.findall(r"\d+", token)
    return tuple(int(part) for part in digits) if digits else None


def fact_periods(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """按已声明粒度解释日期桶；月初标签不是日粒度统计窗口。"""
    periods = []
    for item in entry.get("periodValues") or ():
        if not isinstance(item, dict) or not item.get("period"):
            continue
        period = str(item["period"])
        key = _period_key(period)
        if key and entry.get("periodGranularity") == "month" and len(key) >= 2:
            period = f"{key[0]:04d}-{key[1]:02d}"
        elif key and entry.get("periodGranularity") == "year":
            period = str(key[0])
        periods.append(period)
    if not periods:
        # 比较和派生事实只登记连续窗口，补齐中间桶以免把窗口内月份误报为错期。
        try:
            start = _parse_period(str(entry.get("periodStart") or ""))
            end = _parse_period(str(entry.get("periodEnd") or ""))
        except ValueError:
            return ()
        if start is None or end is None or start.granularity != end.granularity:
            return ()
        grain = entry.get("periodGranularity") or start.granularity
        # 比较/派生事实未重复登记粒度时，双方均为月初标签仍表示月份窗口。
        if (not entry.get("periodGranularity") and start.granularity == end.granularity == "day"
                and start.value.day == end.value.day == 1):
            grain = "month"
        width = {"year": 4, "month": 7, "day": 10}.get(grain)
        if width is None:
            return ()
        first, last = start.value, end.value
        if grain in {"month", "year"}:
            first, last = first.replace(day=1), last.replace(day=1)
        if grain == "year":
            first, last = first.replace(month=1), last.replace(month=1)
        while first <= last:
            periods.append(first.isoformat()[:width])
            if first == last:
                break
            first = _next_period(_ParsedPeriod("", first, grain))
    return tuple(dict.fromkeys(periods))


def _period_role_warnings(window: str, roles: Mapping[str, tuple[str, ...]]) -> list[str]:
    """按明确语法区分截止期、本期、基期与上下文；不要求正文补写期间。"""
    window = _point_plain_text(window)
    written = [match for match in _PERIOD_TOKEN.finditer(window) if _period_key(match[0])]
    labels = {'endpoint': '累计终点', 'current': '当前期', 'baseline': '基期'}
    for index, match in enumerate(written):
        prefix = window[:match.start()]
        suffix = re.sub(r'^\s*[月日]?', '', window[match.end():])
        cutoff = re.search(r'(?:截至|截止|截止到|截至到)\s*$', prefix)
        role = 'current' if roles.get('current') else 'endpoint'
        if not cutoff:
            # “含二月”只解释操作数范围；“一月至三月”首项是窗口起点。
            if re.search(r'(?:包含|包括|含|其中|例如|覆盖)\s*$', prefix):
                continue
            baseline = re.search(r'(?:较于|相较于|相较|较|相比于|对比|比|基期(?:为)?)\s*$', prefix)
            baseline = baseline or re.match(r'(?:作为|为)(?:环比)?(?:基期|基准)', suffix)
            baseline = baseline or (re.search(r'与\s*$', prefix) and re.match(r'相?比', suffix))
            if index + 1 < len(written):
                between = window[match.end():written[index + 1].start()]
                if re.fullmatch(r'\s*[月日]?\s*(?:至|到|[-~～–—]|、|和|及)\s*', between):
                    if not roles.get('baseline'):
                        continue
                    baseline = True
            if baseline:
                # 累计窗口中的比较背景只受完整期间集合约束。
                if not roles.get('baseline'):
                    continue
                role = 'baseline'
        expected = roles.get(role, ())
        if expected and _period_key(match[0]) not in {_period_key(period) for period in expected}:
            return [f"期间角色与生成时不一致（{labels[role]} {'、'.join(expected)}）"]
    return []


def unit_period_warnings(
    window: str,
    *,
    expected_unit: str | None = None,
    expected_periods: tuple[str, ...] = (),
    expected_period_roles: Mapping[str, tuple[str, ...]] | None = None,
    fact_value: Any = None,
) -> list[str]:
    """值已命中时，核对邻近单位/期间文本与生成时是否一致（软告警）。

    正文未重述单位或期间（或只写"本月/环比"这类无法比对的相对表述）
    不告警；只有明确写了与生成时不同的单位/期间才提示复核。
    """

    window = window.replace("−", "-").replace("－", "-")
    warnings: list[str] = []
    if expected_unit and fact_value is not None:
        present: list[str] = []
        for variant in value_text_variants(fact_value):
            present.extend(re.findall(
                r"(?<![\d.,+\-a-zA-Z_])" + re.escape(variant) +
                _VALUE_BOUNDARY_TAIL + r"\s*(" + _UNIT_PATTERN + r")",
                window,
            ))
        if present and any(unit != expected_unit for unit in present):
            warnings.append(f"单位文本与生成时不一致（生成时 {expected_unit}）")
    if expected_periods:
        expected_keys = {
            key
            for period in expected_periods
            if (key := _period_key(str(period))) is not None
        }
        written = [
            token
            for token in _PERIOD_TOKEN.findall(window)
            if _period_key(token) is not None
        ]
        if expected_keys and any(_period_key(token) not in expected_keys for token in written):
            warnings.append(
                f"期间文本与生成时不一致（生成时 {'、'.join(expected_periods)}）"
            )
        elif expected_period_roles:
            warnings.extend(_period_role_warnings(window, expected_period_roles))
    return warnings


def _point_plain_text(text: str) -> str:
    # Remove paired emphasis only; never concatenate arithmetic or identifier tokens.
    return re.sub(r"(?<![A-Za-z0-9_])(\*\*|__|\*)(?=\S)(.+?)(?<=\S)\1(?![A-Za-z0-9_])", r"\2", text)


def _point_direction(prefix: str) -> str | None:
    from .numeric_text import RISING_WORDS

    if re.search(_DECLINE_PREFIX + r"$", prefix):
        return "decrease"
    if re.search(rf"(?:{'|'.join(RISING_WORDS)})(?:\s*(?:了|约|为|达|幅度为))*\s*$", prefix):
        return "increase"
    return None


def _point_direction_conflicts(statement: str, fact_value: Any) -> bool:
    if not isinstance(fact_value, (int, float)):
        return False
    for match in _NUMBER_UNIT_RE.finditer(statement):
        if match.group("unit") != "个百分点":
            continue
        direction = _point_direction(statement[:match.start()])
        if (direction == "decrease" and fact_value > 0) or (direction == "increase" and fact_value < 0):
            return True
    return False


def extract_comparable_value(
    statement: str,
    *,
    expected_unit: str | None,
    expected_periods: tuple[str, ...],
    expected_scope: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Extract a draft value only when the local claim text is unambiguous.

    This deliberately requires an explicit matching period and all registered
    scope values. It is a soft comparison aid, not a replacement for source
    validation; ambiguous prose returns ``None``.
    """

    if expected_unit == "个百分点":
        statement = _point_plain_text(statement)
    if not expected_unit or not expected_periods:
        return None
    if expected_scope and any(not value or value not in statement for value in expected_scope.values()):
        return None
    expected_keys = {
        key for period in expected_periods
        if (key := _period_key(str(period))) is not None
    }
    written_periods = [
        token for token in _PERIOD_TOKEN.findall(statement)
        if _period_key(token) is not None
    ]
    if not written_periods or any(_period_key(token) not in expected_keys for token in written_periods):
        return None
    candidates = [match for match in _NUMBER_UNIT_RE.finditer(statement) if match.group("unit") == expected_unit]
    if len(candidates) != 1:
        return None
    try:
        value = float(candidates[0].group("number").replace(",", "").replace("−", "-").replace("－", "-"))
    except ValueError:
        return None
    direction = None
    if expected_unit == "个百分点":
        direction = _point_direction(statement[:candidates[0].start()])
        # 方向词后的数值是幅度；带负号的双重方向表述留给人工复核。
        if direction is not None:
            if value < 0:
                return None
            if direction == "decrease":
                value = -value
    return {
        "value": int(value) if value.is_integer() else value,
        "unit": expected_unit,
        "periods": written_periods,
        **({"direction": direction} if direction is not None else {}),
    }


def claim_status(
    markdown: str,
    claim_id: str,
    fact_value: Any,
    *,
    window_chars: int = 200,
    expected_unit: str | None = None,
    expected_periods: tuple[str, ...] = (),
    expected_period_roles: Mapping[str, tuple[str, ...]] | None = None,
    expected_scope: Mapping[str, str] | None = None,
    section_id: str | None = None,
) -> dict[str, Any]:
    """单个引用校验；整篇多引用校验使用 ClaimStatusChecker 复用正文解析。"""
    return ClaimStatusChecker(markdown).check(
        claim_id,
        fact_value,
        window_chars=window_chars,
        expected_unit=expected_unit,
        expected_periods=expected_periods,
        expected_period_roles=expected_period_roles,
        expected_scope=expected_scope,
        section_id=section_id,
    )


def prepare_claim_status(markdown: str) -> Callable[..., dict[str, Any]]:
    """供同一草稿的全部引用复用正文解析。"""
    return ClaimStatusChecker(markdown).check


class ClaimStatusChecker:
    """按请求解析一次 Markdown，仍逐个校验唯一锚点和所属章节。"""

    def __init__(self, markdown: str):
        from .markdown_body import trace_body

        self.markdown = trace_body(markdown)

    def check(self, claim_id: str, fact_value: Any, **kwargs) -> dict[str, Any]:
        return _claim_status_from_body(self.markdown, claim_id, fact_value, **kwargs)


def _claim_status_from_body(
    markdown: str,
    claim_id: str,
    fact_value: Any,
    *,
    window_chars: int = 200,
    expected_unit: str | None = None,
    expected_periods: tuple[str, ...] = (),
    expected_period_roles: Mapping[str, tuple[str, ...]] | None = None,
    expected_scope: Mapping[str, str] | None = None,
    section_id: str | None = None,
) -> dict[str, Any]:
    sections = list(re.finditer(r"\[\[section:([^\]\r\n]+)\]\]", markdown))
    if section_id and sections:
        matching = [index for index, section in enumerate(sections) if section[1] == section_id]
        if len(matching) != 1:
            return {"status": "unbound", "warnings": []}
        index = matching[0]
        end = sections[index + 1].start() if index + 1 < len(sections) else len(markdown)
        markdown = markdown[sections[index].end():end]
    marker = claim_marker(claim_id)
    position = markdown.find(marker)
    if position < 0:
        return {"status": "unbound", "warnings": []}
    if markdown.count(marker) != 1:
        return {"status": "unbound", "warnings": []}
    block_start = markdown.rfind("\n\n", 0, position)
    block_end = markdown.find("\n\n", position)
    start = max(0, position - window_chars, block_start + 2 if block_start >= 0 else 0)
    end = min(len(markdown), position + window_chars, block_end if block_end >= 0 else len(markdown))
    before = markdown[start:position]
    after = markdown[position + len(marker):end]
    # 旧格式允许锚点位于句号后；此时只归属前一句，不能借用下一句。
    if re.search(r"[。！？;；\n]\s*$", before):
        before = re.sub(r"[。！？;；\n]+\s*$", "", before)
        after = ""
    statement = re.split(r"[。！？;；\n]", before)[-1] + re.split(r"[。！？;；\n]", after)[0]
    window = re.sub(r"\[\[[^\]\r\n]+\]\]", "", statement)
    if expected_unit == "个百分点":
        window = _point_plain_text(window)
    statements = re.split(r"[。！？;；\n]", window)
    matched_statements = [
        statement for statement in statements
        if (value_matches(statement, fact_value) or formatted_value_matches(statement, fact_value, expected_unit))
        and not (expected_unit == "个百分点" and _point_direction_conflicts(statement, fact_value))
    ]
    if matched_statements:
        warning_window = "\n".join(matched_statements)
        warnings = unit_period_warnings(
            warning_window,
            expected_unit=expected_unit,
            expected_periods=expected_periods,
            expected_period_roles=expected_period_roles,
            fact_value=fact_value,
        )
        for key, value in (expected_scope or {}).items():
            if value and value not in warning_window:
                warnings.append(f"业务范围需复核：当前引用句未体现登记范围 {key}={value}。")
        return {
            "status": "valid",
            "warnings": warnings,
        }
    comparable = None
    comparable_statements = [statement for statement in statements if _NUMBER_UNIT_RE.search(statement)]
    if len(comparable_statements) == 1:
        comparable = extract_comparable_value(
            comparable_statements[0],
            expected_unit=expected_unit,
            expected_periods=expected_periods,
            expected_scope=expected_scope,
        )
    result: dict[str, Any] = {"status": "stale", "warnings": []}
    if comparable is not None:
        result["draftValue"] = comparable["value"]
        result["draftUnit"] = comparable["unit"]
        result["draftPeriods"] = comparable["periods"]
        if "direction" in comparable:
            result["draftDirection"] = comparable["direction"]
        result["comparable"] = True
        result["warnings"] = ["正文数值与登记事实不一致，请核对数值、单位和期间。"]
    else:
        result["warnings"] = ["当前引用附近无法提取可核对的数值，尚未完成数值校验。"]
    return result


__all__ = [
    "build_claim_subject_bindings",
    "claim_marker",
    "claim_status",
    "evaluate_subject_status",
    "unit_period_warnings",
    "value_matches",
    "value_text_variants",
]
