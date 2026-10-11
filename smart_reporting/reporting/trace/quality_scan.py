"""成稿正文质量扫描：对已发布报告 Markdown 与冻结事实包离线计算可比较的质量指标。

用于在真实运行样本上度量改进效果（每份报告的“待核实”数、复核告警分布、无依据数值占比、
段落长度等），与发布链路解耦：只读输入，不改写正文、不阻断任何流程。

    python -m smart_reporting.reporting.trace.quality_scan report.md facts1.json [facts2.json ...]
        [--fields field_definitions.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .content_review import review_content
from .numeric_text import replace_unregistered_numbers
from .review_common import _VALUE
from .review_readability import _prose_lines, readability_warnings

_MAX_EXAMPLES = 10


def _category(warning: str) -> str:
    """告警类别取首个全角冒号之前的标题（如“指标数值归属需复核”）。"""
    head = warning.split("：", 1)[0].strip()
    return head if 0 < len(head) <= 24 else warning[:12]


def scan_report_quality(
    markdown: str,
    contents: Sequence[str],
    *,
    field_definitions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """返回成稿质量指标；输入与发布链路使用的冻结事实包相同。"""

    contents = tuple(contents)
    paragraphs = _prose_lines(markdown)
    lengths = [len(line) for line in paragraphs]
    numbers = len(list(_VALUE.finditer("\n".join(paragraphs))))
    # 无依据数值：按发布链路同一规则核对时会被替换为“待核实”的处数。
    unregistered = (replace_unregistered_numbers(markdown, contents).count("待核实")
                    - markdown.count("待核实"))
    accuracy = review_content(markdown, contents, field_definitions=field_definitions)
    readability = readability_warnings(markdown)
    return {
        "paragraphs": len(paragraphs),
        "averageParagraphChars": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "maxParagraphChars": max(lengths, default=0),
        "headings": len(re.findall(r"^#{1,6}\s", markdown, re.MULTILINE)),
        "numbers": {"total": numbers, "unregistered": unregistered},
        "unverifiedMarkers": markdown.count("待核实"),
        "accuracyWarnings": dict(sorted(Counter(map(_category, accuracy)).items())),
        "readabilityWarnings": dict(sorted(Counter(map(_category, readability)).items())),
        "examples": [*accuracy, *readability][:_MAX_EXAMPLES],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="扫描已发布报告正文的质量指标（只读）。")
    parser.add_argument("report", type=Path, help="报告 Markdown 文件")
    parser.add_argument("facts", type=Path, nargs="+", help="冻结事实包 JSON（可多个）")
    parser.add_argument("--fields", type=Path, help="字段定义 JSON（字段名 → 业务名称）")
    arguments = parser.parse_args(argv)
    fields = json.loads(arguments.fields.read_text(encoding="utf-8")) if arguments.fields else None
    result = scan_report_quality(
        arguments.report.read_text(encoding="utf-8"),
        [path.read_text(encoding="utf-8") for path in arguments.facts],
        field_definitions=fields,
    )
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
