"""成稿正文质量扫描：对已发布报告 Markdown 与冻结事实包离线回放质量观测指标。

统计现有“待核实”标记、复核告警、剩余数值的登记核对结果、缺失值相似性提示和段落长度等。
与发布链路解耦：只读输入，不改写正文、不阻断任何流程；相似性分类不是已证实的根因。

    python -m smart_reporting.reporting.trace.quality_scan report.md facts1.json [facts2.json ...]
        [--fields field_definitions.json] [--trace-index trace-index-v1.json]

facts positionals should come from the same sources as the publication chain: deterministic fact packages,
supplemental evidence (supplement.json), and chart input data (chart-input/v1) are accepted. ``--trace-index``
reads the artifact's trace-index-v1.json and reports archived anchors and numeric-unverified notices beside
remaining replay misses. Published unverified numbers have already been replaced and are absent from the replay
population. ``missingDelta`` is only a count difference between these distinct populations; it is not a net
repair or regression measure. ``derivedShare`` is the share of registered validations accepted by derivation,
not the share without trace anchors.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..units import unit_scales
from .content_review import review_content
from .markdown_body import registered_table_captions, strip_server_tables
from .numeric_text import (
    derived_number_values,
    frozen_number_catalog,
    frozen_number_values,
    replace_unregistered_numbers,
    supplemental_number_values,
)
from .review_common import _VALUE
from .review_readability import _prose_lines, readability_warnings

_MAX_EXAMPLES = 10
# 与候选值的相对距离不超过 0.1% 时提供近似提示；不证明舍入差、业务口径或依据成立。
_FORM_TOLERANCE = Decimal("0.001")
_SCALE_FACTORS = (Decimal("1e4"), Decimal("1e-4"), Decimal("1e8"), Decimal("1e-8"))


def _category(warning: str) -> str:
    """告警类别取首个全角冒号之前的标题（如“指标数值归属需复核”）。"""
    head = warning.split("：", 1)[0].strip()
    return head if 0 < len(head) <= 24 else warning[:12]


def _classify_missing(number: Decimal, unit: str, values: set[Decimal]) -> tuple[str, float | None]:
    """Return a heuristic similarity label for a missing number.

    ``formMismatch`` and ``scaleMismatch`` are candidate explanations based only on
    numeric proximity; they do not establish the actual root cause. ``scaleMismatch``
    is considered only for money or visit units, whose conversion tables are explicit.
    The ``unsupported`` and ``noRegisteredValues`` labels likewise describe the
    available comparison evidence, not why the source number is missing.
    """

    if not values:
        return "noRegisteredValues", None
    nearest = min(abs(number - value) for value in values)
    relative = nearest / (abs(number) or Decimal(1))
    if relative <= _FORM_TOLERANCE:
        return "formMismatch", float(relative)
    if unit_scales(unit) is not None:
        for factor in _SCALE_FACTORS:
            scaled = number * factor
            scaled_relative = min(abs(scaled - value) for value in values) / (abs(scaled) or Decimal(1))
            if scaled_relative <= _FORM_TOLERANCE:
                return "scaleMismatch", float(scaled_relative)
    return "unsupported", float(relative)


def scan_report_quality(
    markdown: str,
    contents: Sequence[str],
    *,
    field_definitions: Mapping[str, str] | None = None,
    trace_index: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """返回成稿质量指标；输入与发布链路使用的冻结事实包相同。"""

    contents = tuple(contents)
    paragraphs = _prose_lines(markdown)
    lengths = [len(line) for line in paragraphs]
    numbers = len(list(_VALUE.finditer("\n".join(paragraphs))))
    catalog = frozen_number_catalog(contents)
    known = supplemental_number_values(contents)
    for unit, values in frozen_number_values(contents, catalog).items():
        known.setdefault(unit, set()).update(values)
    derived = derived_number_values(contents)

    def candidate_values(unit: str) -> set[Decimal]:
        """Return registered and derived values comparable in the requested unit.

        Money and visit units may be converted using their explicit unit family;
        unrelated units are never treated as scale candidates.
        """
        values = set(known.get(unit, ())) | set(derived.registered_values(unit))
        scales = unit_scales(unit)
        if scales is not None:
            values.update(
                value * scales[source] / scales[unit]
                for source, source_values in known.items()
                if source != unit and source in scales
                for value in source_values
            )
        return values

    verdicts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    classification: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []

    def on_verdict(verdict: str, number: Decimal, unit: str, reason: str) -> None:
        verdicts[verdict] += 1
        if verdict == "registered":
            reasons[reason] += 1
            return
        if verdict != "missing":
            return
        category, relative = _classify_missing(number, unit, candidate_values(unit))
        classification[category] += 1
        if len(examples) < _MAX_EXAMPLES:
            examples.append(
                {
                    "number": format(number, "f"),
                    "unit": unit,
                    "category": category,
                    "nearestRelativeDistance": relative,
                }
            )

    # 无依据数值：按发布链路同一规则核对；missing 结论数与替换出的“待核实”同口径。
    # 服务端附表（[[table:…]] 块）由冻结事实生成、不经过正文核对，计入会把表格单元格算成无依据数值。
    # 表名按追溯索引登记的服务端表名识别；正文引导句中的数字仍需核对。
    checked_markdown = strip_server_tables(
        markdown,
        registered_captions=registered_table_captions(
            (trace_index or {}).get("tables") if isinstance(trace_index, Mapping) else None
        ),
    )
    replace_unregistered_numbers(checked_markdown, contents, on_verdict=on_verdict)
    unregistered = verdicts.get("missing", 0)
    checked = sum(verdicts.values())
    registered = verdicts.get("registered", 0)
    accuracy = review_content(checked_markdown, contents, field_definitions=field_definitions)
    readability = readability_warnings(markdown)
    result: dict[str, Any] = {
        "paragraphs": len(paragraphs),
        "averageParagraphChars": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "maxParagraphChars": max(lengths, default=0),
        "headings": len(re.findall(r"^#{1,6}\s", markdown, re.MULTILINE)),
        "numbers": {"total": numbers, "unregistered": unregistered},
        "binding": {
            "checked": checked,
            "verdicts": dict(sorted(verdicts.items())),
            "registeredReasons": dict(sorted(reasons.items())),
            "missingRate": round(unregistered / checked, 4) if checked else None,
            "evaluationStatus": "evaluated" if checked else "not_evaluated",
            "unverifiedOriginalsEvaluated": False,
            # Share of registered validations accepted by server-side derivation; this says
            # nothing about whether those validations have trace anchors.
            "derivedShare": round(reasons.get("derived", 0) / registered, 4) if registered else None,
            "derivedShareMeaning": "share_of_registered_validations_accepted_by_derivation",
            "derivedShareDenominator": "registered",
            "missingClassificationMeaning": "heuristic_similarity_candidates_not_verified_root_causes",
            "missingClassification": dict(sorted(classification.items())),
            "missingExamples": examples,
        },
        "unverifiedMarkers": markdown.count("待核实"),
        "accuracyWarnings": dict(sorted(Counter(map(_category, accuracy)).items())),
        "readabilityWarnings": dict(sorted(Counter(map(_category, readability)).items())),
        "examples": [*accuracy, *readability][:_MAX_EXAMPLES],
    }
    if trace_index is not None:
        anchored = sum(
            1 for item in trace_index.get("subjectBindings", ()) if item.get("numberReference")
        )
        recorded = sum(
            1
            for item in trace_index.get("reviewNotices", ())
            if item.get("kind") == "numeric_unverified"
        )
        result["traceIndex"] = {
            "anchoredReferences": anchored,
            "recordedUnverifiedNotices": recorded,
            "replayMissing": unregistered,
            "missingDelta": unregistered - recorded,
            "missingDeltaMeaning": "replay_missing_count_minus_archived_numeric_unverified_notice_count",
            "missingDeltaComparable": False,
            "missingDeltaCaveat": "distinct_populations_not_net_repairs_or_regressions",
            "replayCoverage": "remaining_numbers_excludes_replaced_unverified_originals",
        }
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="扫描已发布报告正文的质量指标（只读）。")
    parser.add_argument("report", type=Path, help="报告 Markdown 文件")
    parser.add_argument("facts", type=Path, nargs="+", help="冻结事实包 JSON（可多个）")
    parser.add_argument("--fields", type=Path, help="字段定义 JSON（字段名 → 业务名称）")
    parser.add_argument(
        "--trace-index", type=Path,
        help="产物 trace-index-v1.json（归档告警与剩余数字回放计数；差值不代表净修复或回归）",
    )
    arguments = parser.parse_args(argv)
    fields = json.loads(arguments.fields.read_text(encoding="utf-8")) if arguments.fields else None
    trace_index = (
        json.loads(arguments.trace_index.read_text(encoding="utf-8"))
        if arguments.trace_index
        else None
    )
    result = scan_report_quality(
        arguments.report.read_text(encoding="utf-8"),
        [path.read_text(encoding="utf-8") for path in arguments.facts],
        field_definitions=fields,
        trace_index=trace_index,
    )
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
