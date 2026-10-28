"""正文 claim → SubjectBindingV1 构造（B6，计划 6.1 与 B2-2 受控标记）。

subject 定位锚是装配器注入的 ``[[claim:id]]`` 协议标记（draft_v1
_marker_lines）：编辑不删除标记即可重新验证；subjectSha256 是生成时
claim 数值事实的规范化指纹，用于判定"正文仍在陈述生成时的事实"。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any, Literal, cast

from ..delivery.report_runtime.markdown import _subject_id
from ..hospital_operation.deterministic_analysis import (
    _next_period,
    _parse_fact_period,
    _parse_period,
    _ParsedPeriod,
)
from ..units import REPORT_VALUE_UNIT_PATTERN, unit_scales
from .comparison_proofs import period_list_text
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
            if locator in locators or not (cell.fact_refs or cell.source_cell):
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
                computationId=cell.computation_id, sourceCell=cell.source_cell,
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
                table_derived = number.table_derivation is not None
                ids = () if table_derived else reference_fact_ids(number.token)
                if (not ids and not table_derived) or any(
                    fact_id not in fact_directory
                    or fact_directory[fact_id][0] not in fact_file_resources
                    for fact_id in ids
                ):
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
                if table_derived:
                    for ref in (number.table_derivation.denominator_fact, number.table_derivation.population_fact):
                        if ref is not None and ref not in refs:
                            refs.append(ref)
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

    # 与 registered_decline_magnitude 同口径：“较预算短少/少1.09亿元”同样是负值的幅度写法。
    return rf"(?:{'|'.join(FALLING_WORDS)}|短少|(?<![至最不多短])少)(?:\s*(?:了|约|为|达|幅度为))*\s*"


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
    # 旧版把零值写成“0.00万元”；已发布正文仍按登记零值核对。
    if Decimal(str(value)) == 0:
        patterns.extend(r"(?<![\d.,+\-])0\.00" + re.escape(target) + r"(?![\d.])"
                        for target in units if target in {"万元", "亿元", "万人次"})
    # 旧版把舍入后为整数的原始元值写成“20,921,671,265.00元”，已发布正文仍可核对。
    patterns.extend(r"(?<![\d.,+\-])" + re.escape(text.removesuffix(target) + ".00" + target) + r"(?![\d.])"
                    for target in units
                    if (text := format_fact_value(value, unit, target)) and target in {"元", "人次", "床日"}
                    and Decimal(str(value)) != Decimal(str(value)).to_integral_value()
                    and abs(Decimal(str(value))) >= 1_000_000 and "." not in text)
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
    # “1月17,088人次”的 17 是数值，不是日：年月写法的日须带“日/号”。
    r"\d{4}\s*[-/年.]\s*\d{1,2}(?:\s*[-/.]\s*\d{1,2}(?![\d,])\s*日?|\s*月\s*\d{1,2}\s*[日号])?"
    r"|\d{4}\s*年|本月|上月|本季度|上季度|本年|上年|去年同期|环比|同比"
)
_UNIT_TOKENS = ("亿元", "万元", "千元", "个百分点", "%", "‰", "万人次", "人次", "万人", "床日", "床", "张", "次", "人", "元")
_UNIT_PATTERN = REPORT_VALUE_UNIT_PATTERN + "|" + "|".join(re.escape(unit) for unit in _UNIT_TOKENS)
_NUMBER_UNIT_RE = re.compile(
    r"(?<![\dA-Za-z_.,+−－-])(?P<number>[+−－-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
    rf"(?P<unit>{_UNIT_PATTERN})(?![\dA-Za-z_])"
)


def _period_key(token: str) -> tuple[int, ...] | None:
    digits = re.findall(r"\d+", token)
    return tuple(int(part) for part in digits) if digits else None


_MONTH_RANGE_WORDING = re.compile(
    r'(?P<year>\d{4})年\s*(?P<start>\d{1,2})月?\s*(?:至|到|[-~～–—])\s*'
    r'(?:(?P<end_year>\d{4})年\s*)?(?P<end>\d{1,2})月'
)


def _expanded_period_wording(window: str) -> str:
    """补齐月份范围终点的年份，再继承正文明确给出的年份；不从来源猜年份。"""
    # Bare years are dates only in an explicit role window, never ordinary
    # four-digit amounts. Normalize both endpoints before the common tokenizer.
    window = re.sub(
        r'(?P<role>(?:本期|当前期|报告期|基期)(?:为)?)\s*(?P<start>\d{4})(?:\s*年)?'
        r'(?:(?P<link>\s*(?:至|到|[-~～–—])\s*)(?P<end>\d{4})(?:\s*年)?)?'
        r'(?!\d|[-/]\d)(?=\s*(?:[、，,。；;]|$|同比|环比|较前|较上一))',
        lambda match: f"{match['role']}{match['start']}年" + (
            f"{match['link']}{match['end']}年" if match['end'] else ""),
        window,
    )
    window = _MONTH_RANGE_WORDING.sub(
        lambda match: f"{match['year']}年{match['start']}月至{match['end_year'] or match['year']}年{match['end']}月",
        window,
    )
    # “2025年1—9月…较2024年同期”：同期即前文月份范围换成该年，年份仍须与基期一致。
    def relative_same_period(match):
        # 只继承同一句明确给出的本期窗口，不从冻结事实反推正文年份。
        sentence = re.split(r'[。！？；;\n]', window[:match.start()])[-1]
        calendars = _inheritable_calendars(sentence)
        prior = list(re.finditer(
            r'(\d{4})年(\d{1,2})月(?:至(\d{4})年(\d{1,2})月)?', calendars[-1] if calendars else ''
        ))
        if not prior:
            return match[0]
        anchor = prior[-1]
        if (anchor[3] and anchor[3] != anchor[1]) or int(anchor[1]) <= 1:
            return match[0]
        year = int(anchor[1]) - 1
        return f'{year}年{anchor[2]}月' + (
            f'至{year}年{anchor[4]}月' if anchor[4] else ''
        ) + '同期'

    window = re.sub(r'(?:上年|去年)同期', relative_same_period, window)
    ranges = list(re.finditer(r'(\d{4})年(\d{1,2})月至(\d{4})年(\d{1,2})月', window))

    def same_period(match):
        prior = [item for item in ranges if item.end() <= match.start() and item[1] == item[3]]
        if not prior:
            return match[0]
        return f"{match['year']}年{prior[-1][2]}月至{match['year']}年{prior[-1][4]}月"

    window = re.sub(r'(?P<year>\d{4})\s*年(?=\s*(?:同期|同月))', same_period, window)
    year = None

    def expand(match):
        nonlocal year
        key = _period_key(match[0])
        if key and len(key) == 1 and re.match(r'\s*(?:同期|同月)', window[match.end():]):
            # “2024年同期/同月”指与本期相同的月份，不是2024全年；只为其后的月份提供年份。
            year = key[0]
            return '该年'
        if key and (len(key) >= 2 or re.fullmatch(r'\d{4}\s*年', match[0])):
            year = key[0]
        elif key and year is not None and not re.search(r'去年|上年|次年|翌年|上月|下月', window[max(0, match.start() - 3):match.start()]):
            return f'{year}年{match[0]}'
        return match[0]

    return re.sub(_PERIOD_TOKEN.pattern + r'|(?<!\d)\d{1,2}月', expand, window)


def fact_periods(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """按已声明粒度解释日期桶；月初标签不是日粒度统计窗口。"""
    periods = []
    declared_grain = entry.get("periodGranularity")
    if declared_grain not in {None, "day", "month", "year"}:
        return ()
    grain = cast(Literal["day", "month", "year"] | None, declared_grain)
    for item in entry.get("periodValues") or ():
        if not isinstance(item, dict) or not isinstance(item.get("period"), str):
            return ()
        period = item["period"]
        parsed = _parse_period(period)
        # Validate the original calendar before normalizing a monthly/yearly
        # bucket. Never drop a bad bucket and borrow an enclosing range.
        if (parsed is None or _parse_fact_period(period, grain) is None
                or (grain == "month" and parsed.granularity == "year")):
            return ()
        if grain == "month":
            period = parsed.value.isoformat()[:7]
        elif grain == "year":
            period = str(parsed.value.year)
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
        grain = grain or start.granularity
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
        count = (last.year - first.year + 1 if grain == "year"
                 else (last.year - first.year) * 12 + last.month - first.month + 1 if grain == "month"
                 else (last - first).days + 1)
        if count > 1200:
            return ()  # Match frozen periodValues capacity; never return a truncated proof.
        while first <= last:
            periods.append(first.isoformat()[:width])
            if first == last:
                break
            first = _next_period(_ParsedPeriod("", first, grain))
    return tuple(dict.fromkeys(periods))


def _period_role_warnings(window: str, roles: Mapping[str, tuple[str, ...]]) -> list[str]:
    """Explicit range labels apply to every endpoint; bare changes retain start/end roles."""
    window = _expanded_period_wording(_point_plain_text(window))
    written = [match for match in _PERIOD_TOKEN.finditer(window) if _period_key(match[0])]
    labels = {'endpoint': '累计终点', 'current': '当前期', 'baseline': '基期'}
    connected = [bool(re.fullmatch(r'\s*[月日]?\s*(?:至|到|[-~～–—]|、|和|及)\s*',
                                  window[left.end():right.start()]))
                 for left, right in zip(written, written[1:])]
    # Compute connected range ends once, so a long list never needs repeated scans.
    group_ends = list(range(len(written)))
    for index in range(len(written) - 2, -1, -1):
        if connected[index]:
            group_ends[index] = group_ends[index + 1]
    role_keys = {name: {_period_key(period) for period in roles.get(name, ())} for name in ('current', 'baseline')}
    written_keys = {_period_key(match[0]) for match in written}
    both_roles_written = bool(written_keys & role_keys['current']) and bool(written_keys & role_keys['baseline'])
    previous_role, previous_explicit = None, False
    for index, match in enumerate(written):
        prefix = window[:match.start()]
        suffix = re.sub(r'^\s*[月日]?', '', window[written[group_ends[index]].end():])
        cutoff = re.search(r'(?:截至|截止|截止到|截至到)\s*$', prefix)
        context = re.search(r'(?:包含|包括|含|其中|例如|覆盖)\s*$', prefix)
        baseline = re.search(r'(?:较于|相较于|相较|较|相比于|对比|比|基期(?:为)?)\s*$', prefix)
        baseline = baseline or re.match(r'(?:作为|为)(?:环比)?(?:基期|基准)', suffix)
        baseline = baseline or (re.search(r'与\s*$', prefix) and re.match(r'相?比', suffix))
        baseline = baseline or (re.search(r'以\s*$', prefix)
                                and re.match(r'(?:月)?末累计快照为基线', suffix))
        current = re.search(r'(?:本期|当前期|报告期)(?:为)?\s*$', prefix)
        current = current or re.match(r'(?:作为|为)(?:本期|当前期|报告期)', suffix)
        inherited = index > 0 and connected[index - 1] and previous_explicit
        explicit = bool(cutoff or context or baseline or current or inherited)
        if cutoff:
            role = 'endpoint'
        elif context:
            role = 'context'
        elif baseline:
            role = 'baseline'
        elif current:
            role = 'current'
        elif inherited:
            role = previous_role
        elif index < len(connected) and connected[index]:
            # An unlabeled two-date change is from baseline to current. A
            # cumulative range start does not redefine its endpoint. A range whose
            # ends equal a registered multi-period window is that window itself
            # (“2025年1月至9月累计…”), not a change from January to September.
            ends = (_period_key(match[0]), _period_key(written[group_ends[index]][0]))
            window_role = next((
                name for name in ('current', 'baseline')
                if len(roles.get(name, ())) > 1
                and ends == (_period_key(roles[name][0]), _period_key(roles[name][-1]))
            ), None)
            if window_role is not None:
                role, explicit = window_role, True
            else:
                role = 'baseline' if roles.get('baseline') else 'context'
        else:
            # 句中同时写出本期与基期日期时（“2025年9月…，2024年9月为…，变化额…”），未标注
            # 角色的日期按所属登记窗口归属；只写一个日期时它是本期（“2025年2月增长”须核对）。
            key = _period_key(match[0])
            role = next((
                name for name in ('current', 'baseline')
                if both_roles_written and key in role_keys[name]
            ), 'current' if roles.get('current') else 'endpoint')
        previous_role, previous_explicit = role, explicit
        expected = roles.get(role, ())
        if expected and _period_key(match[0]) not in {_period_key(period) for period in expected}:
            return [f"期间角色与生成时不一致（{labels[role]} {period_list_text(expected)}）"]
        if expected and role in {'current', 'baseline'} and (current or baseline) and not inherited:
            end = group_ends[index]
            keys = tuple(_period_key(item[0]) for item in written[index:end + 1])
            expected_keys = tuple(_period_key(period) for period in expected)
            connectors = [window[left.end():right.start()] for left, right in zip(
                written[index:end], written[index + 1:end + 1])]
            is_range = any(re.fullmatch(r'\s*[月日]?\s*(?:至|到|[-~～–—])\s*', link) for link in connectors)
            complete = ((keys[0], keys[-1]) == (expected_keys[0], expected_keys[-1]) if is_range
                        else set(keys) == set(expected_keys))
            if not complete:
                return [f"期间角色与生成时不一致（{labels[role]}完整窗口 {period_list_text(expected)}）"]
    return []


_PERIOD_TEXT_MISMATCH = "期间文本与生成时不一致"


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
        period_window = _expanded_period_wording(window)
        # 月份范围可以是背景；当它后面明确点出当前数值所属月份时，范围不替代该月份。
        # 未点出单期、或“截至…，含…”的说明仍按完整期间集合和角色复核。
        if fact_value is not None:
            values = [match for match in _NUMBER_UNIT_RE.finditer(period_window)
                      if value_matches(match[0], fact_value)
                      or formatted_value_matches(match[0], fact_value, expected_unit)]
            if len(values) == 1:
                before_value = period_window[:values[0].start()]
                ranges = list(_MONTH_RANGE_WORDING.finditer(before_value))
                if ranges:
                    last_range = ranges[-1]
                    later = before_value[last_range.end():]
                    # “同比/环比/本月”没有具体日期，不能据此抹去已写明的累计窗口。
                    if (any(_period_key(match[0]) for match in _PERIOD_TOKEN.finditer(later))
                            and not re.search(r'(?:包含|包括|含|例如|覆盖)\s*\d{4}', later)):
                        period_window = (period_window[:last_range.start()] + ' ' * len(last_range[0])
                                         + period_window[last_range.end():])
        expected_keys = {
            key
            for period in expected_periods
            if (key := _period_key(str(period))) is not None
        }
        written = [
            token
            for token in _PERIOD_TOKEN.findall(period_window)
            if _period_key(token) is not None
        ]
        if expected_keys and any(_period_key(token) not in expected_keys for token in written):
            warnings.append(
                f"{_PERIOD_TEXT_MISMATCH}（生成时 {period_list_text(expected_periods)}）"
            )
        elif expected_period_roles:
            warnings.extend(_period_role_warnings(period_window, expected_period_roles))
    return warnings


def _period_key_label(key: tuple[int, ...]) -> str:
    if len(key) == 1:
        return str(key[0])
    if len(key) == 2:
        return f"{key[0]:04d}-{key[1]:02d}"
    return f"{key[0]:04d}-{key[1]:02d}-{key[2]:02d}"


def _continuous_period_keys(
    first: tuple[int, ...], last: tuple[int, ...],
) -> tuple[tuple[int, ...], ...] | None:
    """展开一个明确的连续期间范围；非法、倒序或超长范围不参与替代事实猜测。"""
    if len(first) != len(last) or len(first) not in {1, 2, 3}:
        return None
    start = _parse_period(_period_key_label(first))
    end = _parse_period(_period_key_label(last))
    if start is None or end is None or start.granularity != end.granularity or start.value > end.value:
        return None
    result: list[tuple[int, ...]] = []
    current = start
    while current.value <= end.value:
        result.append(
            (current.value.year,)
            if current.granularity == "year"
            else (current.value.year, current.value.month)
            if current.granularity == "month"
            else (current.value.year, current.value.month, current.value.day)
        )
        if len(result) > 1200:
            return None
        current = _ParsedPeriod(current.label, _next_period(current), current.granularity)
    return tuple(result)


def written_period_mentions(statement: str) -> tuple[tuple[int, ...], ...]:
    """提取明确日期及连续范围，不把并列窗口合并成一个范围。"""
    window = _expanded_period_wording(statement.replace("−", "-").replace("－", "-"))
    matches = [match for match in _PERIOD_TOKEN.finditer(window) if _period_key(match[0]) is not None]
    keys = [cast(tuple[int, ...], _period_key(match[0])) for match in matches]
    for left, right in zip(matches, matches[1:]):
        keys.extend(written_period_keys(window[left.start():right.end()]) or ())
    return tuple(dict.fromkeys(keys))


def written_period_keys(statement: str) -> tuple[tuple[int, ...], ...] | None:
    """返回语句唯一明确期间的完整桶集合。

    单个日期返回一个桶；一个用“至/—”连接的范围展开成完整连续桶。并列日期、两个独立范围、
    粒度混杂或无效日历均返回 ``None``，避免把多个语义窗口压成全局最小—最大跨度。
    """
    window = _expanded_period_wording(statement.replace("−", "-").replace("－", "-"))
    matches = [match for match in _PERIOD_TOKEN.finditer(window) if _period_key(match[0]) is not None]
    if not matches:
        return None
    keys = tuple(cast(tuple[int, ...], _period_key(match[0])) for match in matches)
    if len({len(key) for key in keys}) != 1:
        return None
    if len(keys) == 1:
        return _continuous_period_keys(keys[0], keys[0])
    if len(keys) != 2 or not re.fullmatch(
        r"\s*[月日]?\s*(?:至|到|[-~～–—])\s*", window[matches[0].end():matches[1].start()]
    ):
        return None
    return _continuous_period_keys(keys[0], keys[1])


def written_period_span(statement: str) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    """兼容调用方的首末表示；只接受 ``written_period_keys`` 可唯一确定的连续期间。"""
    keys = written_period_keys(statement)
    return (keys[0], keys[-1]) if keys else None


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
    compatible_units = unit_scales(expected_unit) or {expected_unit: Decimal(1)}
    candidates = [match for match in _NUMBER_UNIT_RE.finditer(statement) if match.group("unit") in compatible_units]
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
        "unit": candidates[0].group("unit"),
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
    expected_reference: Mapping[str, Any] | None = None,
    semantic_receipt: Any = None,
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
        expected_reference=expected_reference,
        semantic_receipt=semantic_receipt,
        section_id=section_id,
    )


def prepare_claim_status(markdown: str) -> Callable[..., dict[str, Any]]:
    """供同一草稿的全部引用复用正文解析。"""
    return ClaimStatusChecker(markdown).check


def _reference_notes_end(text: str) -> int:
    """返回前置括注的末端，嵌套的中英文括号均属于同一值。"""
    pairs = {'（': '）', '(': ')'}
    position = 0
    end = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        if text[position] not in pairs:
            break
        stack = []
        while position < len(text):
            character = text[position]
            if character in pairs:
                stack.append(pairs[character])
            elif character in pairs.values():
                if not stack or stack.pop() != character:
                    return end
                if not stack:
                    position += 1
                    end = position
                    break
            position += 1
        else:
            break
    return end


_BASELINE_PREFIX = re.compile(r'(?:较于|相较于|相较|较|相比于|对比|比|基期(?:为)?)\s*$')


def _inheritable_calendars(text: str, *, include_baseline: bool = False) -> list[str]:
    """可供并列引用继承的日期：“较2024年1—9月的…”“与2024年同期相比”这类基期日期组
    不是后项的所属期间。"""
    groups: list[list[re.Match[str]]] = []
    for match in _PERIOD_TOKEN.finditer(text):
        if not _period_key(match[0]):
            continue
        if groups and re.fullmatch(
            r'\s*[月日]?\s*(?:至|到|[-~～–—]|、|和|及)\s*', text[groups[-1][-1].end():match.start()]
        ):
            groups[-1].append(match)
        else:
            groups.append([match])
    calendars: list[str] = []
    for group in groups:
        prefix, suffix = text[:group[0].start()], text[group[-1].end():]
        baseline = _BASELINE_PREFIX.search(prefix) or (
            re.search(r'与\s*$', prefix) and re.match(r'\s*[月日]?\s*(?:同期|同月)?\s*相?比', suffix)
        )
        baseline = baseline or re.match(r'\s*[月日]?\s*(?:同期|同月)', suffix)
        if not baseline or include_baseline:
            # 继承整个日期组及末尾单位，不能把“1月至2月”截成不带“月”的终点。
            ending = re.match(r'\s*[月日号]', suffix)
            end = group[-1].end() + (ending.end() if ending else 0)
            calendars.append(text[group[0].start():end])
    return calendars


_CALENDAR_WINDOW = r'\d{4}年\d{1,2}月(?:至\d{4}年\d{1,2}月)?'
_COMPARISON_WINDOW = re.compile(
    rf'(?:(?:较于|相较于|相较|较|相比于|对比|比|与|基期(?:为)?)\s*'
    rf'(?P<period>{_CALENDAR_WINDOW})(?:同期|同月)?|(?P<relative>{_CALENDAR_WINDOW})(?:同期|同月))'
)


@dataclass(frozen=True)
class ReferencePeriodContext:
    current_window: str | None
    baseline_window: str | None
    reference_role: Literal['current', 'baseline']


def _reference_period_context(before: str, local_before: str) -> ReferencePeriodContext:
    """解析已展开日期的引用归属：显式角色优先，再区分基期定语与比较后的断言。"""
    calendars = _inheritable_calendars(before)
    baselines = list(_COMPARISON_WINDOW.finditer(before))
    local_baselines = list(_COMPARISON_WINDOW.finditer(local_before))
    tail = local_before[local_baselines[-1].end():] if local_baselines else local_before
    explicit = list(re.finditer(r'本期|当前期|报告期|基期|去年|上年', tail))
    role: Literal['current', 'baseline'] = 'current'
    if explicit:
        role = 'baseline' if explicit[-1][0] in {'基期', '去年', '上年'} else 'current'
    elif local_baselines:
        # “同期的/同期为”直接修饰基期值；“后为/至/到/相比”已经进入比较结果。
        wording = _NUMBER_UNIT_RE.sub('', tail).strip()
        attached = re.fullmatch(r'(?:的|为|是)?', wording) or (
            wording.startswith('的') and not re.search(r'后|至|到|相比', wording)
        )
        role = 'baseline' if attached else 'current'
    return ReferencePeriodContext(
        current_window=calendars[-1] if calendars else None,
        baseline_window=(baselines[-1]['period'] or baselines[-1]['relative']) if baselines else None,
        reference_role=role,
    )


def _reference_local_window(before: str, after: str, *, comparison: bool = False) -> str | None:
    """并列引用先继承已写年份，再隔离当前锚点的期间与值。

    comparison：变化额、变化率涉及本期与基期两个期间，继承句中全部日期，而不是最后一个。
    """
    claim = re.compile(r'\[\[claim:[^\]\r\n]+\]\]')
    # 单金额句也要区分相对同期的比较背景与当前值归属。
    if not claim.search(before + after) and not re.search(r'(?:上年|去年)同期', before):
        return None
    # 继承须先于截断：“一月…[[claim]]及二月…”的年份仍属于当前正文。
    before, after = _expanded_period_wording(before + '\0' + after).split('\0', 1)
    previous = list(claim.finditer(before))
    local_before = before[previous[-1].end():] if previous else before
    local_before = re.sub(r'\[\[[^\]\r\n]+\]\]', '', local_before)
    # 前一锚点后的日期括注属于前值；当前前缀从括注之后开始。
    if previous:
        local_before = local_before[_reference_notes_end(local_before):]
    if not comparison:
        restatement = bool(previous and re.match(r'\s*[（(]', local_before))
        explicit_parenthetical_period = restatement and any(
            _period_key(match[0]) for match in _PERIOD_TOKEN.finditer(local_before)
        )
        context_before, context_local = before, local_before
        if restatement:
            # 未闭合括注是紧邻前值的同值重述，沿用前一引用自身的本期/基期归属。
            context_before = before[:previous[-1].start()]
            context_local = context_before[previous[-2].end():] if len(previous) > 1 else context_before
        context = _reference_period_context(context_before, context_local)
        period = context.baseline_window if context.reference_role == 'baseline' else context.current_window
        if period and (context.baseline_window or restatement) and not explicit_parenthetical_period:
            local_before = period + ' ' + re.sub(_CALENDAR_WINDOW + r'(?:同期|同月)?', '', local_before)
    after = re.sub(r'^(?:\s*\[\[citation:[^\]\r\n]+\]\])*', '', after)
    after = re.split(claim, after, maxsplit=1)[0]
    # 当前值紧邻的括注保留；连接词之后已是下一个值的说明。
    notes_end = _reference_notes_end(after)
    local_after = after[:notes_end] if notes_end else re.split(r'[及和与、，,]', after, maxsplit=1)[0]
    local_after = re.sub(r'\[\[[^\]\r\n]+\]\]', '', local_after)
    local = local_before + local_after
    # “较2024年同期…”已写明所属期间（展开为“该年同期”），不能再继承前项的本期月份。
    if previous and not re.search(r'该年(?:同期|同月)', local) and not any(
        _period_key(match[0]) for match in _PERIOD_TOKEN.finditer(local)
    ):
        # “2025年二月…[[claim]]及收入…”仍继承正文前项明确的月份。
        calendars = _inheritable_calendars(before[:previous[-1].start()], include_baseline=comparison)
        if calendars:
            local = ' '.join(dict.fromkeys(calendars) if comparison else calendars[-1:]) + ' ' + local
    return local


def _scope_presence_warnings(
    window: str, scope: Mapping[str, str], reference: Mapping[str, Any] | None,
) -> list[str]:
    """登记范围须在引用句中可辨认；只核对能区分对象的范围。

    回放 artifacts3：73 条范围告警几乎都是正确句子。编码字段（RJ402.03）、分组中处处相同的
    属性（单院 company）、带区分后缀的名称（“心血管内科（一级）”）和日期范围（data_date=
    2025-07-01 写作“7月”）都不是误归属的证据。
    """
    entry = (reference or {}).get("entry") or {}
    groups = [
        item.get("groupValues") or {}
        for key in ("topGroups", "bottomGroups", "groupPopulation")
        for item in entry.get(key) or ()
        if isinstance(item, Mapping)
    ]
    constant = {
        key for key in scope
        if len(groups) > 1 and all(key in group for group in groups)
        and len({str(group[key]) for group in groups}) == 1
    }
    months = {int(month) for month in re.findall(r"(?<!\d)(\d{1,2})\s*月", window)}
    warnings = []
    for key, value in scope.items():
        if not value or value in window or key in constant or key.endswith("_code"):
            continue
        period = _period_key(value)
        if period is not None:
            if len(period) >= 2 and period[1] in months:
                continue
        elif (name := re.sub(r"[（(][^）)]*[）)]$", "", value)) and name in window:
            continue
        warnings.append(f"业务范围需复核：当前引用句未体现登记范围 {key}={value}。")
    return warnings


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
    expected_reference: Mapping[str, Any] | None = None,
    semantic_receipt: Any = None,
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
    lower = block_start + 2 if block_start >= 0 else 0
    # 来源与锚点标记不是可见正文：列举句里每个数值后跟约 60 字符的标记，按原始字符截窗会把
    # 句首的科室、院区截掉。窗口按去掉标记后的可见长度计算。
    marker_chars = sum(len(item) for item in re.findall(
        r"\[\[[^\]\r\n]+\]\]", markdown[max(lower, position - 4 * window_chars):position]
    ))
    start = max(0, position - window_chars - marker_chars, lower)
    end = min(len(markdown), position + window_chars, block_end if block_end >= 0 else len(markdown))
    before = markdown[start:position]
    after = markdown[position + len(marker):end]
    # 旧格式允许锚点位于句号后；此时只归属前一句，不能借用下一句。
    if re.search(r"[。！？;；\n]\s*$", before):
        before = re.sub(r"[。！？;；\n]+\s*$", "", before)
        after = ""
    statement = re.split(r"[。！？;；\n]", before)[-1] + re.split(r"[。！？;；\n]", after)[0]
    window = re.sub(r"\[\[[^\]\r\n]+\]\]", "", statement)
    reference_window = None
    if expected_reference:
        selector = str(expected_reference.get("selector") or "")
        reference_window = _reference_local_window(
            re.split(r'[。！？;；\n]', before)[-1], re.split(r'[。！？;；\n]', after)[0],
            comparison=selector in {"change", "changeRate"}
            or selector.startswith(("periodChanges.", "periodChangeRates.", "cumulativeChanges.")),
        )
    if expected_unit == "个百分点":
        window = _point_plain_text(window)
        if reference_window is not None:
            reference_window = _point_plain_text(reference_window)
    statements = re.split(r"[。！？;；\n]", window)
    matched_statements = [
        statement for statement in statements
        if (value_matches(statement, fact_value) or formatted_value_matches(statement, fact_value, expected_unit))
        and not (expected_unit == "个百分点" and _point_direction_conflicts(statement, fact_value))
        and (reference_window is None or value_matches(reference_window, fact_value)
             or formatted_value_matches(reference_window, fact_value, expected_unit))
    ]
    if matched_statements:
        warning_window = "\n".join(matched_statements)
        warnings = unit_period_warnings(
            reference_window if reference_window is not None else warning_window,
            expected_unit=expected_unit,
            expected_periods=expected_periods,
            expected_period_roles=expected_period_roles,
            fact_value=fact_value,
        )
        warnings.extend(_scope_presence_warnings(warning_window, expected_scope or {}, expected_reference))
        if not expected_reference:
            from .reference_semantics import scope_exclusion_warnings

            warnings.extend(scope_exclusion_warnings(warning_window, expected_scope or {}))
        if expected_reference:
            from .reference_semantics import WINDOW_MISMATCH_PREFIX, number_reference_warnings

            prefix = re.split(r'[。！？;；\n]', before)[-1]
            suffix = re.split(r'[。！？;；\n]', after)[0]
            # 同一引用的来源入口可以紧邻 claim；它本身不截断后置括注。
            suffix = re.sub(r'^(?:\s*\[\[citation:[^\]\r\n]+\]\])*', '', suffix)
            warnings.extend(number_reference_warnings(prefix, expected_reference, suffix=suffix))
            if any(warning.startswith(_PERIOD_TEXT_MISMATCH) for warning in warnings):
                # 写出的期间已与登记期间不符时，统计窗口的提醒说的是同一件事，只保留一条。
                warnings = [warning for warning in warnings if not warning.startswith(WINDOW_MISMATCH_PREFIX)]
        from .claim_semantics import semantic_warnings

        warnings = semantic_warnings(
            markdown, claim_id, semantic_receipt, expected_scope or {}, expected_periods, warnings,
            reference=expected_reference,
        )
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
    "written_period_keys",
    "written_period_span",
]
