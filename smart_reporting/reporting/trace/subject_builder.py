"""正文 claim → SubjectBindingV1 构造（B6，计划 6.1 与 B2-2 受控标记）。

subject 定位锚是装配器注入的 ``[[claim:id]]`` 协议标记（draft_v1
_marker_lines）：编辑不删除标记即可重新验证；subjectSha256 是生成时
claim 数值事实的规范化指纹，用于判定"正文仍在陈述生成时的事实"。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Sequence

from .contracts_v1 import (
    FactRefV1,
    SubjectBindingV1,
    SubjectLocatorV1,
    subject_fingerprint,
)


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
        for claim in artifact.claims:
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
                        factKind=pointer_kind,
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


def _subject_id(section_code: str, claim_id: str) -> str:
    return "sub-" + hashlib.sha256(f"{section_code}:{claim_id}".encode()).hexdigest()[:16]


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
    variants.append(f"{number:,.2f}")
    return tuple(dict.fromkeys(variants))


def claim_marker(claim_id: str) -> str:
    return f"[[claim:{claim_id}]]"


_VALUE_BOUNDARY_TAIL = r"(?![\d.,eE])"


def value_matches(cell_text: str, fact_value: Any) -> bool:
    """判定单个文本片段是否呈现该事实值（带数字边界，供 claim 窗口与表格单元格共用）。"""

    for variant in value_text_variants(fact_value):
        if re.search(
            r"(?<![\d.,+\-a-zA-Z_])" + re.escape(variant) + _VALUE_BOUNDARY_TAIL,
            cell_text,
        ):
            return True
    return False


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
_UNIT_TOKENS = ("亿元", "万元", "千元", "%", "‰", "万人次", "人次", "万人", "床", "张", "次", "人", "元")
_NUMBER_UNIT_RE = re.compile(
    r"(?<![\d.,+\-])(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?))\s*"
    r"(?P<unit>亿元|万元|千元|%|‰|万人次|人次|万人|床|张|次|人|元)(?![\w])"
)


def _period_key(token: str) -> tuple[int, ...] | None:
    digits = re.findall(r"\d+", token)
    return tuple(int(part) for part in digits) if digits else None


def unit_period_warnings(
    window: str,
    *,
    expected_unit: str | None = None,
    expected_periods: tuple[str, ...] = (),
    fact_value: Any = None,
) -> list[str]:
    """值已命中时，核对邻近单位/期间文本与生成时是否一致（软告警）。

    正文未重述单位或期间（或只写"本月/环比"这类无法比对的相对表述）
    不告警；只有明确写了与生成时不同的单位/期间才提示复核。
    """

    warnings: list[str] = []
    if expected_unit and fact_value is not None:
        unit_pattern = "|".join(re.escape(unit) for unit in _UNIT_TOKENS)
        present: list[str] = []
        for variant in value_text_variants(fact_value):
            present.extend(re.findall(
                r"(?<![\d.,+\-a-zA-Z_])" + re.escape(variant) +
                _VALUE_BOUNDARY_TAIL + r"\s*(" + unit_pattern + r")",
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
    return warnings


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
        value = float(candidates[0].group("number").replace(",", ""))
    except ValueError:
        return None
    return {
        "value": int(value) if value.is_integer() else value,
        "unit": expected_unit,
        "periods": written_periods,
    }


def claim_status(
    markdown: str,
    claim_id: str,
    fact_value: Any,
    *,
    window_chars: int = 200,
    expected_unit: str | None = None,
    expected_periods: tuple[str, ...] = (),
    expected_scope: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """标记被删除或重复 → unbound；唯一标记所在段落的有界窗口内找不到
    完整事实值形态 → stale。排除协议标记文字和数字子串；此处仍属于
    语义软校验，stale 提示复核，不拒绝保存。

    值命中（valid）后若提供了生成时单位/期间，再核对邻近文本：明确写了
    不同单位/期间 → 附带软告警，状态仍为 valid（AGENTS：软告警不阻断）。
    """

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
    window = re.sub(r"\[\[[^\]\r\n]+\]\]", "", markdown[start:end])
    statements = re.split(r"[。！？;；\n]", window)
    matched_statements = [statement for statement in statements if value_matches(statement, fact_value)]
    if matched_statements:
        warning_window = "\n".join(matched_statements)
        return {
            "status": "valid",
            "warnings": unit_period_warnings(
                warning_window,
                expected_unit=expected_unit,
                expected_periods=expected_periods,
                fact_value=fact_value,
            ),
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
        result["comparable"] = True
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
