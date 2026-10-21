"""成稿质量扫描基线：合成样本中埋入的问题须被稳定识别，指标变化须显式更新基线。"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from smart_reporting.reporting.trace.numeric_text import replace_unregistered_numbers
from smart_reporting.reporting.trace.quality_scan import (
    _classify_missing,
    main,
    scan_report_quality,
)

_SAMPLE = Path(__file__).parent / "fixtures" / "report_quality"


def _sample() -> tuple[str, list[str], dict[str, str]]:
    return (
        (_SAMPLE / "report.md").read_text(encoding="utf-8"),
        [(_SAMPLE / "facts.json").read_text(encoding="utf-8")],
        json.loads((_SAMPLE / "fields.json").read_text(encoding="utf-8")),
    )


def _expected_sample() -> dict:
    # Keep the legacy fixture intact and explicitly assert the additive metric semantics.
    expected = json.loads((_SAMPLE / "expected.json").read_text(encoding="utf-8"))
    expected["binding"].update(
        derivedShareMeaning="share_of_registered_validations_accepted_by_derivation",
        derivedShareDenominator="registered",
        missingClassificationMeaning="heuristic_similarity_candidates_not_verified_root_causes",
    )
    return expected


def test_sample_report_quality_matches_baseline():
    # 埋入 6 处问题全部识别：无依据变化率、指标归属、分组归属、约数、历史新高，以及
    # “儿科收入最高”（两个指标都带分组排名、未点名指标，但对两个指标都不成立）。
    markdown, contents, fields = _sample()
    result = scan_report_quality(markdown, contents, field_definitions=fields)
    assert result == _expected_sample()
    assert result["numbers"] == {"total": 14, "unregistered": 1}


def test_quality_scan_reads_only_and_counts_existing_unverified_markers():
    markdown, contents, fields = _sample()
    marked = markdown + "\n\n成本结构待核实。\n"
    result = scan_report_quality(marked, contents, field_definitions=fields)
    assert result["unverifiedMarkers"] == 1
    assert result["numbers"]["unregistered"] == 1


def test_quality_scan_cli_prints_json(capsys):
    assert (
        main(
            [
                str(_SAMPLE / "report.md"),
                str(_SAMPLE / "facts.json"),
                "--fields",
                str(_SAMPLE / "fields.json"),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == _expected_sample()


def _table_contents() -> list[str]:
    return [
        json.dumps(
            {
                "findings": [
                    {
                        "columns": ["项目", "金额"],
                        "rows": [["甲", 100.00], ["乙", 40.00], ["丙", 20.00]],
                        "columnMeta": {"金额": {"unit": "万元"}},
                    }
                ]
            },
            ensure_ascii=False,
        )
    ]


def test_binding_scan_classifies_missing_numbers_by_heuristic_similarity():
    # 四种相似性提示各一处：邻近数值、无相近候选、金额倍率候选、无百分比登记值；不证明根因。
    # 甲乙前两项合计由服务端派生校验放行；derivedShare 不衡量锚定覆盖率。
    contents = _table_contents()
    markdown = (
        "甲项目金额100.00万元，乙项目40.00万元，丙项目20.00万元，甲乙合计140.00万元。"
        "手算末位差100.01万元，预算外的丁项目55.00万元，另一处误写成100.00元，"
        "还有占比33.00%。"
    )
    result = scan_report_quality(markdown, contents)
    binding = result["binding"]
    assert binding["verdicts"] == {"missing": 4, "registered": 4}
    assert binding["registeredReasons"] == {"derived": 1, "direct": 3}
    assert binding["derivedShare"] == 0.25
    assert binding["derivedShareMeaning"] == "share_of_registered_validations_accepted_by_derivation"
    assert binding["derivedShareDenominator"] == "registered"
    assert binding["missingClassificationMeaning"] == (
        "heuristic_similarity_candidates_not_verified_root_causes"
    )
    assert binding["missingClassification"] == {
        "formMismatch": 1,
        "noRegisteredValues": 1,
        "scaleMismatch": 1,
        "unsupported": 1,
    }
    assert {item["category"] for item in binding["missingExamples"]} == set(
        binding["missingClassification"]
    )
    # missing 结论与正文实际替换出的“待核实”同口径。
    scrubbed = replace_unregistered_numbers(markdown, contents)
    assert binding["verdicts"]["missing"] == scrubbed.count("待核实") - markdown.count("待核实")


@pytest.mark.parametrize("unit", ["%", "百分点", "个百分点", "元/人次"])
@pytest.mark.parametrize("factor", ["1e4", "1e-4", "1e8", "1e-8"])
def test_missing_classification_does_not_infer_scale_for_unrelated_units(unit, factor):
    number = Decimal("33")
    candidate = number * Decimal(factor)
    category, distance = _classify_missing(number, unit, {candidate})
    assert category == "unsupported"
    assert distance == float(abs(number - candidate) / number)


def test_quality_scan_compares_against_recorded_trace_index():

    contents = _table_contents()
    markdown = "甲项目金额100.00万元，预算外的丁项目55.00万元。"
    result = scan_report_quality(
        markdown,
        contents,
        trace_index={
            "subjectBindings": [
                {
                    "subjectKind": "text_claim",
                    "numberReference": {"token": "{{value:x:total:万元}}"},
                },
                {"subjectKind": "table_cell"},
            ],
            "reviewNotices": [
                {"kind": "numeric_unverified"},
                {"kind": "numeric_unverified"},
                {"kind": "source_review"},
            ],
        },
    )
    # 回放 1 处剩余缺失、归档记录 2 条告警；两者是不同统计对象，差值不是净修复数。
    assert result["traceIndex"] == {
        "anchoredReferences": 1,
        "recordedUnverifiedNotices": 2,
        "replayMissing": 1,
        "missingDelta": -1,
        "missingDeltaMeaning": (
            "replay_missing_count_minus_archived_numeric_unverified_notice_count"
        ),
        "missingDeltaComparable": False,
        "missingDeltaCaveat": "distinct_populations_not_net_repairs_or_regressions",
        "replayCoverage": "remaining_numbers_excludes_replaced_unverified_originals",
    }


def test_quality_scan_without_trace_index_omits_comparison():
    result = scan_report_quality("甲项目金额100.00万元。", _table_contents())
    assert "traceIndex" not in result
    assert result["binding"]["verdicts"] == {"registered": 1}
