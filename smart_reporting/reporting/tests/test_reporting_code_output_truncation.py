from __future__ import annotations

import json

import pytest

from smart_reporting.reporting.code_agent.toolkit import (
    MAX_DIAGNOSTIC_BYTES,
    _safe_diagnostic_details,
)


@pytest.mark.parametrize("field", ["stdout", "result"])
@pytest.mark.parametrize("body", ["row\n", '中文\\"\n\t\x00'])
def test_ordinary_output_preserves_header_and_final_rows(field, body):
    original = "表头：金额、日期\n" + body * 5000 + "\n合计：123"

    details = _safe_diagnostic_details({field: original})

    assert details[field].startswith("表头：金额、日期\n")
    assert details[field].endswith("\n合计：123")
    assert "truncated" in details[field]
    assert "\ufffd" not in details[field]
    assert len(json.dumps(details, ensure_ascii=False).encode("utf-8")) <= MAX_DIAGNOSTIC_BYTES


def test_short_output_remains_exact_and_unmarked():
    outputs = {"stdout": '表头\n"值"\\', "result": "结果：42", "stderr": "", "traceback": ""}

    assert _safe_diagnostic_details(outputs) == outputs


def test_exception_tails_survive_competing_large_ordinary_output():
    details = _safe_diagnostic_details({
        "stdout": "输出表头\n" + "行\n" * 5000 + "输出末行",
        "result": "结果表头\n" + "值\n" * 5000 + "结果末行",
        "stderr": "warning\n" * 5000 + "ValueError: 根因",
        "traceback": "frame\n" * 5000 + "KeyError: missing_column",
    })

    assert details["stdout"].startswith("输出表头\n")
    assert details["stdout"].endswith("输出末行")
    assert details["result"].startswith("结果表头\n")
    assert details["result"].endswith("结果末行")
    assert details["stderr"].endswith("ValueError: 根因")
    assert details["traceback"].endswith("KeyError: missing_column")
    assert len(json.dumps(details, ensure_ascii=False).encode("utf-8")) <= MAX_DIAGNOSTIC_BYTES


def test_json_escape_expansion_stays_bounded_with_metadata():
    details = _safe_diagnostic_details({
        "path": "analysis/a.py",
        "line": 10,
        "retryable": True,
        "stderr": '警告\\"\n' * 5000 + "最终根因",
        "traceback": '栈\\"\n' * 5000 + "最后异常",
        "stdout": '头\\"\n' * 5000 + "输出结束",
        "result": '值\\"\n' * 5000 + "结果结束",
    })

    assert details["path"] == "analysis/a.py"
    assert details["line"] == 10
    assert details["retryable"] is True
    assert details["stderr"].endswith("最终根因")
    assert details["traceback"].endswith("最后异常")
    assert len(json.dumps(details, ensure_ascii=False).encode("utf-8")) <= MAX_DIAGNOSTIC_BYTES


def test_large_allowed_metadata_cannot_exhaust_the_json_limit():
    details = _safe_diagnostic_details({
        "requiredNextTools": ['工具\\"\n' * 100] * 20,
        "missingPaths": ['缺失\\"\n' * 100] * 20,
        "issueSummary": "问题" * 5000,
        "stdout": "头\n" + "输出\n" * 5000 + "尾",
    })

    assert len(json.dumps(details, ensure_ascii=False).encode("utf-8")) <= MAX_DIAGNOSTIC_BYTES
