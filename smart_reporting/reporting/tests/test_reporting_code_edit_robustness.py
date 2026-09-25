"""edit_script 的语法护栏与空白容错定位。"""

from __future__ import annotations

import pytest

from smart_reporting.reporting.code_agent.edit_patch import apply_edit_blocks_with_modes
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

    updated, fuzzy = apply_edit_blocks_with_modes(
        source, [("if ok:\n    run()", "if ok:\n    run()\n    log()")]
    )

    assert updated == "def main():\n    if ok:\n        run()\n        log()\n    return 1\n"
    assert fuzzy == [{"blockIndex": 1, "matchMode": "indentation"}]


def test_fuzzy_match_still_requires_unique_location():
    source = "a = 1   \nb = 2\na = 1 \nb = 2\n"

    with pytest.raises(ReportingError) as caught:
        apply_edit_blocks_with_modes(source, [("a = 1\nb = 2", "a = 3\nb = 2")])

    assert caught.value.code == "report_code_script_edit_ambiguous"


def test_exact_match_takes_precedence_over_fuzzy():
    source = "x = 1\ny = 2\n"

    updated, fuzzy = apply_edit_blocks_with_modes(source, [("x = 1", "x = 2")])

    assert updated == "x = 2\ny = 2\n"
    assert fuzzy == []
