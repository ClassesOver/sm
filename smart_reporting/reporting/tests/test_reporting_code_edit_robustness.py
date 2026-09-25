"""edit_script 的语法护栏与空白容错定位。"""

from __future__ import annotations

import pytest

from smart_reporting.reporting.code_agent.edit_patch import apply_edit_blocks
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_code_edit import multi_edit_patch
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    binding,  # noqa: F401
    runtime,  # noqa: F401
    workspace,  # noqa: F401
)

SCRIPT = (
    "import json\n"
    "\n"
    "def main():\n"
    "    rows = [1, 2]   \n"
    "    if rows:\n"
    "        total = sum(rows)\n"
    '    json.dump({"total": total}, open("analysis/out.json", "w"))\n'
    "\n"
    "main()\n"
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _toolkit_with_script(binding, runtime):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    written = await toolkit.write_script(SCRIPT)
    assert written["ok"] is True
    return toolkit, (await toolkit.read_script())["source"]


@pytest.mark.anyio
async def test_edit_introducing_syntax_error_is_rejected_and_file_unchanged(
    binding, runtime  # noqa: F811
):
    toolkit, source = await _toolkit_with_script(binding, runtime)

    result = await toolkit.edit_script(
        multi_edit_patch(source, [("        total = sum(rows)", "        total = sum(rows")])
    )

    assert result["ok"] is False
    assert result["code"] == "report_code_source_invalid"
    assert result["details"]["errorType"] == "SyntaxError"
    assert result["details"]["line"] > 0
    assert (await toolkit.read_script())["source"] == source


@pytest.mark.anyio
async def test_edit_matches_despite_trailing_whitespace_and_reports_mode(
    binding, runtime  # noqa: F811
):
    toolkit, _formatted = await _toolkit_with_script(binding, runtime)
    # 格式化会去掉行尾空白；直接落盘带行尾空白的源码，模拟模型复制 SEARCH 时丢了空白。
    await toolkit.workspace.awrite_text(
        toolkit.context.task_id, toolkit.context.script_path, SCRIPT, overwrite=True
    )
    source = SCRIPT
    patch = multi_edit_patch(
        source, [("    rows = [1, 2]\n    if rows:", "    rows = [1, 2, 3]\n    if rows:")]
    )

    result = await toolkit.edit_script(patch)

    assert result["ok"] is True
    assert result["fuzzyMatches"] == [{"blockIndex": 1, "matchMode": "trailing_whitespace"}]
    assert "rows = [1, 2, 3]" in (await toolkit.read_script())["source"]


def test_indentation_offset_is_reapplied_to_replacement():
    source = "def main():\n    if ok:\n        run()\n    return 1\n"

    updated, fuzzy = apply_edit_blocks(
        source, [("if ok:\n    run()", "if ok:\n    run()\n    log()")]
    )

    assert updated == "def main():\n    if ok:\n        run()\n        log()\n    return 1\n"
    assert fuzzy == [{"blockIndex": 1, "matchMode": "indentation"}]


def test_fuzzy_match_still_requires_unique_location():
    source = "a = 1   \nb = 2\na = 1 \nb = 2\n"

    with pytest.raises(ReportingError) as caught:
        apply_edit_blocks(source, [("a = 1\nb = 2", "a = 3\nb = 2")])

    assert caught.value.code == "report_code_script_edit_ambiguous"


def test_exact_match_takes_precedence_over_fuzzy():
    source = "x = 1\ny = 2\n"

    updated, fuzzy = apply_edit_blocks(source, [("x = 1", "x = 2")])

    assert updated == "x = 2\ny = 2\n"
    assert fuzzy == []


def test_fuzzy_match_supports_search_ending_with_newline():
    source = "def f():\n    x = 1   \n    y = 2\n"

    updated, fuzzy = apply_edit_blocks(source, [("    x = 1\n", "    x = 3\n")])

    assert updated == "def f():\n    x = 3\n    y = 2\n"
    assert fuzzy == [{"blockIndex": 1, "matchMode": "trailing_whitespace"}]


def test_indentation_match_with_multiline_string_reports_hint():
    source = "def f():\n    if a:\n        b = 1\n    return b\n"

    with pytest.raises(ReportingError) as caught:
        apply_edit_blocks(
            source, [("if a:\n    b = 1", 'if a:\n    b = """\nx\n"""')]
        )

    assert caught.value.code == "report_code_script_edit_not_found"
    assert "多行字符串" in caught.value.details["hint"]


def test_indentation_realignment_splits_only_on_lf():
    source = "def f():\n    x = 1\n    y = 2\n"

    updated, _fuzzy = apply_edit_blocks(source, [("x = 1\ny = 2", "x = 'a\u2028b'\ny = 3")])

    # 字符串字面量里的 \u2028 不是行分隔，重排缩进不得在其后插入空格。
    assert updated == "def f():\n    x = 'a\u2028b'\n    y = 3\n"


def test_exact_match_after_indent_realigns_multiline_replacement():
    source = "if a:\n    b = 2\nprint(b)\n"

    updated, fuzzy = apply_edit_blocks(source, [("b = 2", "b = 3\nc = 4")])

    assert updated == "if a:\n    b = 3\n    c = 4\nprint(b)\n"
    assert fuzzy == [{"blockIndex": 1, "matchMode": "indentation"}]


def test_exact_single_line_replacement_keeps_literal_semantics():
    source = "if a:\n    b = 2\nprint(b)\n"

    updated, fuzzy = apply_edit_blocks(source, [("b = 2", "b = 3")])

    assert updated == "if a:\n    b = 3\nprint(b)\n"
    assert fuzzy == []


_SHA = "a" * 64
_ENVELOPE = f"*** Begin Edit\n*** SHA256: {_SHA}\n"


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        # 工具描述承诺“删除使用空 REPLACE”；======= 后直接接 REPLACE 标记即为删除。
        (_ENVELOPE + "<<<<<<< SEARCH\nx = 1\n=======\n>>>>>>> REPLACE\n*** End Edit", ""),
        (_ENVELOPE + "<<<<<<< SEARCH\nx = 1\n=======\n\n>>>>>>> REPLACE\n*** End Edit", ""),
        (
            (_ENVELOPE + "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n*** End Edit")
            .replace("\n", "\r\n"),
            "x = 2",
        ),
        (
            _ENVELOPE.replace(_SHA, _SHA.upper())
            + "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n*** End Edit",
            "x = 2",
        ),
        (_ENVELOPE + "<<<<<<< SEARCH \nx = 1\n======= \nx = 2\n>>>>>>> REPLACE\t\n*** End Edit", "x = 2"),
        ("\n\n" + _ENVELOPE + "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n*** End Edit", "x = 2"),
    ],
)
def test_patch_tolerates_unambiguous_format_noise(patch: str, expected: str) -> None:
    from smart_reporting.reporting.code_agent.edit_patch import parse_edit_patch

    edits, sha = parse_edit_patch(patch, 10_000)

    assert edits == [("x = 1", expected)]
    assert sha == _SHA


@pytest.mark.parametrize(
    "patch",
    [
        # 缺少 End Edit 多见于输出截断，可能丢失后续块，不能只应用一部分。
        _ENVELOPE + "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n",
        "```\n" + _ENVELOPE + "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n*** End Edit\n```",
    ],
)
def test_patch_still_rejects_truncated_or_fenced_input(patch: str) -> None:
    from smart_reporting.reporting.code_agent.edit_patch import parse_edit_patch

    with pytest.raises(ReportingError) as caught:
        parse_edit_patch(patch, 10_000)
    assert caught.value.code == "report_code_script_edit_invalid"


def test_search_cutting_identifier_is_rejected_not_applied() -> None:
    with pytest.raises(ReportingError) as caught:
        apply_edit_blocks("max = 1\nprint(max)\n", [("x = 1", "x = 2")])

    assert caught.value.code == "report_code_script_edit_not_found"
    assert "标识符中间" in caught.value.details["hint"]


def test_identifier_cut_match_does_not_make_real_line_ambiguous() -> None:
    updated, _ = apply_edit_blocks("max = 1\nx = 1\n", [("x = 1", "x = 2")])

    assert updated == "max = 1\nx = 2\n"


@pytest.mark.parametrize(
    ("source", "edit", "expected"),
    [
        ("plt.figure(figsize=(8, 4))\n", ("figsize=(8, 4)", "figsize=(10, 5)"), "plt.figure(figsize=(10, 5))\n"),
        ('title = "门诊收入趋势"\n', ("收入", "营收"), 'title = "门诊营收趋势"\n'),
    ],
)
def test_inline_substring_edits_still_allowed(source, edit, expected) -> None:
    assert apply_edit_blocks(source, [edit])[0] == expected


@pytest.mark.anyio
async def test_syntax_error_receipts_report_location(binding, runtime):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    broken = "import json\nprint((1\nvalue = 2\n"
    written = await toolkit.write_script(broken)
    assert written["ok"] is True
    assert written["readyForExecution"] is False
    syntax = written["warnings"][0]["syntaxError"]
    assert syntax["line"] >= 2 and syntax["reason"]

    current = (await toolkit.read_script())["source"]
    edited = await toolkit.edit_script(
        multi_edit_patch(current, [("value = 2", "value = 3")])
    )
    assert edited["ok"] is True
    assert edited["readyForExecution"] is False
    assert edited["syntaxError"]["errorType"] == "SyntaxError"
    assert edited["nextTools"] == ["edit_script"]

    current = (await toolkit.read_script())["source"]
    fixed = await toolkit.edit_script(multi_edit_patch(current, [("print((1", "print(1)")]))
    assert fixed["ok"] is True
    assert fixed["readyForExecution"] is True
    assert "syntaxError" not in fixed
