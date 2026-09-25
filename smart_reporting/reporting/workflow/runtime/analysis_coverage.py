"""补证 evidence 的维度覆盖率与输出契约确定性软校验（只告警，不驱动修复）。

- A1 覆盖率：对 codingRequirements 中低基数字符串列读取签发 CSV 全集，按值集合
  重合定位 finding 中的维度列（与列名、主题无关），报告全集中缺失的维度值。
- A1 单侧缺失：本期/上期成对列中只有一侧有值的行，若 evidence.warnings 未提及
  对应维度值，报告该方向未披露。
- A2 输出契约：每个 codingRequirements[].outputName 应对应一个 findings[].name。
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

MAX_DIMENSION_CARDINALITY = 500
MAX_MISSING_SAMPLES = 20
# 维度列定位需要足够的值重合，避免数值或偶然相同的短字符串误配。
MIN_FINDING_OVERLAP_RATIO = 0.5
_INTENTIONAL_FILTER = re.compile(
    r"top\s*\d*|bottom\s*\d*|前\s*\d+|后\s*\d+|排名|排行|最高|最低|筛选|过滤|只保留|大于|小于|超过|不低于",
    re.IGNORECASE,
)
_PRIOR_HINTS = ("上年", "去年", "上期", "同期", "prior", "previous", "last")
_CURRENT_HINTS = ("本年", "今年", "本期", "当期", "current")


def parse_csv_columns(text: str, fields: Iterable[str]) -> dict[str, list[str]]:
    """只提取需要的列；值做 strip，空串视为缺失。"""

    wanted = set(fields)
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return {}
    header = [name.lstrip("\ufeff").strip() for name in header]
    positions = {name: index for index, name in enumerate(header) if name in wanted}
    columns: dict[str, list[str]] = {name: [] for name in positions}
    for row in reader:
        for name, index in positions.items():
            if index < len(row):
                value = row[index].strip()
                if value:
                    columns[name].append(value)
    return columns


def _is_number(value: str) -> bool:
    try:
        float(value.replace(",", ""))
    except ValueError:
        return False
    return True


def dimension_universe(values: Sequence[str]) -> frozenset[str] | None:
    """低基数字符串列返回全集；数值列或高基数列返回 None。"""

    distinct = frozenset(values)
    if not 1 < len(distinct) <= MAX_DIMENSION_CARDINALITY:
        return None
    if sum(_is_number(value) for value in distinct) > len(distinct) / 2:
        return None
    return distinct


def _finding_columns(finding: Mapping[str, Any]) -> dict[str, list[Any]]:
    columns = finding.get("columns")
    rows = finding.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return {}
    table: dict[str, list[Any]] = {str(name): [] for name in columns}
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            continue
        for name, value in zip(columns, row, strict=True):
            table[str(name)].append(value)
    return table


def _best_dimension_column(
    universe: frozenset[str], finding: Mapping[str, Any]
) -> tuple[str, frozenset[str]] | None:
    best: tuple[str, frozenset[str], int] | None = None
    for name, values in _finding_columns(finding).items():
        observed = frozenset(str(value).strip() for value in values if value is not None)
        if not observed:
            continue
        overlap = len(observed & universe)
        if overlap == 0 or overlap / len(observed) < MIN_FINDING_OVERLAP_RATIO:
            continue
        if best is None or overlap > best[2]:
            best = (name, observed, overlap)
    return (best[0], best[1]) if best is not None else None


def requirement_output_gaps(
    requirements: Sequence[Mapping[str, Any]], findings: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """A2：codingRequirements.outputName 没有同名 finding 时记软告警。"""

    names = {finding.get("name") for finding in findings if isinstance(finding, Mapping)}
    return [
        {
            "code": "report_analysis_requirement_unfulfilled",
            "outputName": requirement.get("outputName"),
        }
        for requirement in requirements
        if isinstance(requirement, Mapping) and requirement.get("outputName") not in names
    ]


def dimension_coverage_gaps(
    requirements: Sequence[Mapping[str, Any]],
    dataset_columns: Mapping[str, Mapping[str, Sequence[str]]],
    findings: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """A1：返回覆盖缺口告警；dataset_columns 为 {datasetId: {字段: 全部取值}}。"""

    gaps: list[dict[str, Any]] = []
    tabular = [item for item in findings if isinstance(item, Mapping) and _finding_columns(item)]
    for requirement in requirements:
        if not isinstance(requirement, Mapping):
            continue
        output_name = requirement.get("outputName")
        columns = dataset_columns.get(str(requirement.get("datasetId")), {})
        named = [item for item in tabular if item.get("name") == output_name]
        candidates = named or tabular
        calculation = str(requirement.get("calculation") or "")
        for field in requirement.get("fields") or ():
            universe = dimension_universe(columns.get(field, ()))
            if universe is None:
                continue
            matched: tuple[str, frozenset[str], Mapping[str, Any]] | None = None
            for finding in candidates:
                located = _best_dimension_column(universe, finding)
                if located is not None and (
                    matched is None or len(located[1] & universe) > len(matched[1] & universe)
                ):
                    matched = (located[0], located[1], finding)
            if matched is None:
                continue
            missing = sorted(universe - matched[1])
            if not missing:
                continue
            row_count = len(matched[2].get("rows") or ())
            # 只按需求文本识别有意 TopN/筛选；行数只作为附带信息供离线调参。
            intentional = bool(_INTENTIONAL_FILTER.search(calculation))
            gaps.append(
                {
                    "code": "report_analysis_dimension_coverage_gap",
                    "severity": "info" if intentional else "warning",
                    "outputName": output_name,
                    "findingName": matched[2].get("name"),
                    "datasetId": requirement.get("datasetId"),
                    "field": field,
                    "findingColumn": matched[0],
                    "universeSize": len(universe),
                    "coverageRatio": round(1 - len(missing) / len(universe), 4),
                    "missingCount": len(missing),
                    "findingRowCount": row_count,
                    "missingSamples": missing[:MAX_MISSING_SAMPLES],
                    "intentionalFilterSuspected": intentional,
                }
            )
    return gaps


def _strip_hints(name: str, hints: Sequence[str]) -> str:
    """大小写无关地去掉期间提示词，得到用于配对的指标词干。"""

    stem = name
    for hint in hints:
        stem = re.sub(re.escape(hint), "", stem, flags=re.IGNORECASE)
    return " ".join(stem.replace("_", " ").split()).lower()


def _period_pairs(names: Sequence[str]) -> list[tuple[str, str]]:
    prior = [name for name in names if any(hint in name.lower() for hint in _PRIOR_HINTS)]
    current = [
        name
        for name in names
        if name not in prior and any(hint in name.lower() for hint in _CURRENT_HINTS)
    ]
    pairs: list[tuple[str, str]] = []
    for current_name in current:
        stem = _strip_hints(current_name, _CURRENT_HINTS)
        match = next(
            (name for name in prior if _strip_hints(name, _PRIOR_HINTS) == stem),
            # 词干不匹配时只允许唯一的本期列与唯一的上期列兜底配对。
            prior[0] if len(prior) == 1 and len(current) == 1 else None,
        )
        if match is not None:
            pairs.append((current_name, match))
    return pairs


def one_sided_gap_warnings(
    findings: Sequence[Mapping[str, Any]], warnings: Sequence[str]
) -> list[dict[str, Any]]:
    """本期/上期只有一侧有值的维度，两个方向都应在 evidence.warnings 中披露。"""

    text = "\n".join(str(item) for item in warnings)
    results: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, Mapping):
            continue
        table = _finding_columns(finding)
        if not table:
            continue
        names = list(table)
        label_column = next(
            (
                name
                for name in names
                if any(isinstance(value, str) and value for value in table[name])
            ),
            None,
        )
        if label_column is None:
            continue
        for current_name, prior_name in _period_pairs(names):
            directions = {
                "currentOnly": [
                    str(label)
                    for label, current, prior in zip(
                        table[label_column], table[current_name], table[prior_name], strict=True
                    )
                    if current is not None and prior is None
                ],
                "priorOnly": [
                    str(label)
                    for label, current, prior in zip(
                        table[label_column], table[current_name], table[prior_name], strict=True
                    )
                    if current is None and prior is not None
                ],
            }
            for direction, labels in directions.items():
                if not labels or any(label in text for label in labels):
                    continue
                results.append(
                    {
                        "code": "report_analysis_one_sided_gap_unreported",
                        "findingName": finding.get("name"),
                        "direction": direction,
                        "currentColumn": current_name,
                        "priorColumn": prior_name,
                        "count": len(labels),
                        "samples": labels[:MAX_MISSING_SAMPLES],
                    }
                )
    return results


__all__ = [
    "dimension_coverage_gaps",
    "dimension_universe",
    "one_sided_gap_warnings",
    "parse_csv_columns",
    "requirement_output_gaps",
]
