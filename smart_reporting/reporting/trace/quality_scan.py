"""成稿正文质量扫描：对已发布报告 Markdown 与冻结事实包离线计算可比较的质量指标。

用于在真实运行样本上度量改进效果（每份报告的“待核实”数、复核告警分布、无依据数值占比、
数值绑定根因分类、段落长度等），与发布链路解耦：只读输入，不改写正文、不阻断任何流程。

    python -m smart_reporting.reporting.trace.quality_scan report.md facts1.json [facts2.json ...]
        [--fields field_definitions.json] [--trace-index trace-index-v1.json]

facts 位置参数应与发布链路同源：确定性事实包、补证 evidence（supplement.json）、
图表作图数据（chart-input/v1）均可直接传入；--trace-index 读取产物自带的
trace-index-v1.json，对照本次回放与线上签发时的锚定引用数和待核实告警数。
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
# 与最近登记值的相对距离不超过 0.1% 视为“形式差异”（末位舍入/口径级），否则才视为无依据。
_FORM_TOLERANCE = Decimal("0.001")
_SCALE_FACTORS = (Decimal("1e4"), Decimal("1e-4"), Decimal("1e8"), Decimal("1e-8"))


def _category(warning: str) -> str:
    """告警类别取首个全角冒号之前的标题（如“指标数值归属需复核”）。"""
    head = warning.split("：", 1)[0].strip()
    return head if 0 < len(head) <= 24 else warning[:12]


def _classify_missing(number: Decimal, unit: str, values: set[Decimal]) -> tuple[str, float | None]:
    """按与最近登记值的距离给“待核实”数字分类，指示缺口的可修复方向。

    formMismatch：与登记值只差末位/口径（0.1% 以内），多为模型手算舍入；
    scaleMismatch：按 亿元↔万元↔元 换算后即对上，是单位错位而非无依据；
    unsupported：没有任何相近依据；noRegisteredValues：该单位在目录中无登记值。
    """

    if not values:
        return "noRegisteredValues", None
    nearest = min(abs(number - value) for value in values)
    relative = nearest / (abs(number) or Decimal(1))
    if relative <= _FORM_TOLERANCE:
        return "formMismatch", float(relative)
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
        """同单位登记值；货币单位再并入其他币值单位换算后的候选，识别“亿元写成万元”级错位。"""
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
    replace_unregistered_numbers(markdown, contents, on_verdict=on_verdict)
    unregistered = verdicts.get("missing", 0)
    checked = sum(verdicts.values())
    registered = verdicts.get("registered", 0)
    accuracy = review_content(markdown, contents, field_definitions=field_definitions)
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
            "missingRate": round(unregistered / checked, 4) if checked else 0.0,
            # derivedShare：仅靠服务端补算放行（无引用锚点）的比例，即“派生即锚定”可转化空间。
            "derivedShare": round(reasons.get("derived", 0) / registered, 4) if registered else 0.0,
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
            # 回放比线上多出的待核实即目录扩充后的新增修复；反之为回归。
            "missingDelta": unregistered - recorded,
        }
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="扫描已发布报告正文的质量指标（只读）。")
    parser.add_argument("report", type=Path, help="报告 Markdown 文件")
    parser.add_argument("facts", type=Path, nargs="+", help="冻结事实包 JSON（可多个）")
    parser.add_argument("--fields", type=Path, help="字段定义 JSON（字段名 → 业务名称）")
    parser.add_argument(
        "--trace-index", type=Path, help="产物 trace-index-v1.json（对照线上锚定与告警）"
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
