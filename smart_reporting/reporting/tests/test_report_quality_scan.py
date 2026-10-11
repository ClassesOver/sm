"""成稿质量扫描基线：合成样本中埋入的问题须被稳定识别，指标变化须显式更新基线。"""

from __future__ import annotations

import json
from pathlib import Path

from smart_reporting.reporting.trace.quality_scan import main, scan_report_quality

_SAMPLE = Path(__file__).parent / "fixtures" / "report_quality"


def _sample() -> tuple[str, list[str], dict[str, str]]:
    return ((_SAMPLE / "report.md").read_text(encoding="utf-8"),
            [(_SAMPLE / "facts.json").read_text(encoding="utf-8")],
            json.loads((_SAMPLE / "fields.json").read_text(encoding="utf-8")))


def test_sample_report_quality_matches_baseline():
    # 埋入 6 处问题：无依据变化率、指标归属、分组归属、约数、历史新高可识别；
    # “儿科收入最高”因两个指标都带分组排名、无法确定指向，按设计不判定（已知漏报）。
    markdown, contents, fields = _sample()
    result = scan_report_quality(markdown, contents, field_definitions=fields)
    assert result == json.loads((_SAMPLE / "expected.json").read_text(encoding="utf-8"))
    assert result["numbers"] == {"total": 14, "unregistered": 1}


def test_quality_scan_reads_only_and_counts_existing_unverified_markers():
    markdown, contents, fields = _sample()
    marked = markdown + "\n\n成本结构待核实。\n"
    result = scan_report_quality(marked, contents, field_definitions=fields)
    assert result["unverifiedMarkers"] == 1
    assert result["numbers"]["unregistered"] == 1


def test_quality_scan_cli_prints_json(capsys):
    assert main([str(_SAMPLE / "report.md"), str(_SAMPLE / "facts.json"),
                 "--fields", str(_SAMPLE / "fields.json")]) == 0
    assert json.loads(capsys.readouterr().out) == json.loads((_SAMPLE / "expected.json").read_text(encoding="utf-8"))
