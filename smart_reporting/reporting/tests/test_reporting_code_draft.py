"""被拒整稿隔离草稿（V3）的补丁、提升与逃生口。"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.bootstrap import _VISUALIZATION_CODE_INSTRUCTIONS
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import (
    ReportingCodeModeToolkit,
    _declared_output_write_example,
)
from smart_reporting.reporting.tests.test_reporting_code_edit import multi_edit_patch
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    binding,  # noqa: F401
    runtime,  # noqa: F401
    workspace,  # noqa: F401
)

REJECTED_SOURCE = 'import json\njson.dump({}, open("data/x.json", "w"))\n'


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _toolkit(binding, runtime):  # noqa: F811
    return ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())


async def _post_hook(toolkit, name, result):
    call = SimpleNamespace(
        function=SimpleNamespace(name=name),
        arguments={},
        result=result,
        error=None,
        call_id="call-1",
    )
    await toolkit._update_tool_result(call)


async def _rejected(toolkit):
    result = await toolkit.write_script(REJECTED_SOURCE)
    assert result["ok"] is False
    assert result["code"] == "report_python_source_path_invalid"
    assert result["details"]["draftSha256"] == hashlib.sha256(
        REJECTED_SOURCE.encode()
    ).hexdigest()
    assert result["details"]["violations"][0]["line"] == 2
    return result


@pytest.mark.anyio
async def test_rejected_draft_patch_promotes_to_signed_script(binding, runtime):  # noqa: F811
    toolkit = _toolkit(binding, runtime)
    await _rejected(toolkit)
    await toolkit.refresh_delivery_state()
    state = toolkit.delivery_state()
    # 首次创建时脚本尚不存在，交付状态必须显式放行 edit_script 才能修补草稿。
    assert "edit_script" in state["nextTools"]
    assert state["rejectedDraftSha256"]

    result = await toolkit.edit_script(
        multi_edit_patch(REJECTED_SOURCE, [('"data/x.json"', '"analysis/out.json"')])
    )

    assert result["ok"] is True
    assert result["status"] == "draft_promoted"
    saved = await toolkit.read_script()
    assert '"analysis/out.json"' in saved["source"]
    assert toolkit.rejected_draft_sha256 is None


@pytest.mark.anyio
async def test_draft_patch_with_syntax_error_stays_isolated(binding, runtime):  # noqa: F811
    toolkit = _toolkit(binding, runtime)
    await _rejected(toolkit)
    broken = REJECTED_SOURCE.replace('"data/x.json", "w"))', '"analysis/out.json", "w")')

    result = await toolkit.edit_script(
        multi_edit_patch(
            REJECTED_SOURCE, [('open("data/x.json", "w"))', 'open("analysis/out.json", "w")')]
        )
    )

    assert result["ok"] is False
    assert result["code"] == "report_code_source_invalid"
    assert result["details"]["errorType"] == "SyntaxError"
    new_sha256 = hashlib.sha256(broken.encode()).hexdigest()
    assert result["details"]["draftSha256"] == new_sha256
    assert toolkit.rejected_draft_sha256 == new_sha256
    assert (await toolkit.read_script())["exists"] is False

    fixed = await toolkit.edit_script(
        multi_edit_patch(broken, [('"w")\n', '"w"))\n')])
    )
    assert fixed["ok"] is True
    assert fixed["status"] == "draft_promoted"


@pytest.mark.anyio
async def test_repeated_draft_patch_failures_discard_draft(binding, runtime):  # noqa: F811
    toolkit = _toolkit(binding, runtime)
    await _rejected(toolkit)
    invalid = "*** Begin Edit\n*** SHA256: bad\n*** End Edit\ntrailing"

    first = await toolkit.edit_script(invalid)
    await _post_hook(toolkit, "edit_script", first)
    assert toolkit.rejected_draft_sha256 is not None

    second = await toolkit.edit_script(invalid)
    await _post_hook(toolkit, "edit_script", second)

    assert toolkit.rejected_draft_sha256 is None
    assert second["draftDiscarded"] is True
    await toolkit.refresh_delivery_state()
    assert toolkit.delivery_state()["nextTools"] == ["write_script"]


def test_declared_output_write_example_uses_signed_paths():
    declared = ("charts/a.png", "charts/b.png", "charts/b.plotly.json")

    matplotlib_example = _declared_output_write_example("charts/a.png", declared)
    plotly_example = _declared_output_write_example("charts/b.plotly.json", declared)

    assert "fig.savefig('charts/a.png'" in matplotlib_example
    assert plotly_example == (
        "fig.write_image('charts/b.png')\nfig.write_json('charts/b.plotly.json')"
    )


def test_candidate_instructions_do_not_route_materialized_charts_to_raw_facts():
    instructions = "\n".join(_VISUALIZATION_CODE_INSTRUCTIONS)

    assert "数据形状契约" not in instructions
    assert "逐字使用 binding.dataPath 读取数据" not in instructions
    assert "task.authorized_read_paths 或 binding.factFile.path 中的逐字字符串" not in instructions
    assert "禁止编写通用 resolve()" in instructions


def test_edit_patch_tolerates_blank_noise_between_and_after_blocks():
    from smart_reporting.reporting.code_agent.edit_patch import parse_edit_patch

    sha = "a" * 64
    block = "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n"
    second = "<<<<<<< SEARCH\ny = 1\n=======\ny = 2\n>>>>>>> REPLACE\n"
    patch = f"*** Begin Edit\n*** SHA256: {sha}\n{block}\n  \n{second}*** End Edit\n\n \n"

    edits, digest = parse_edit_patch(patch, 10_000)

    assert edits == [("x = 1", "x = 2"), ("y = 1", "y = 2")]
    assert digest == sha


def test_edit_patch_marker_failure_names_missing_line():
    from smart_reporting.reporting.code_agent.edit_patch import parse_edit_patch
    from smart_reporting.reporting.models import ReportingError

    patch = (
        f"*** Begin Edit\n*** SHA256: {'a' * 64}\n"
        "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n"
        "<<<<<<< SEARCH\ny = 1\n=======\ny = 2\n>>>>>>> REPLACE\n*** End Edit"
    )

    with pytest.raises(ReportingError) as caught:
        parse_edit_patch(patch, 10_000)

    assert caught.value.details["reason"] == "marker_in_block"
    assert ">>>>>>> REPLACE" in caught.value.details["hint"]


@pytest.mark.anyio
async def test_missing_output_diagnosis_separates_unreferenced_and_unexecuted(
    binding, runtime  # noqa: F811
):
    toolkit = _toolkit(binding, runtime)
    await toolkit.write_script(
        "import json\n"
        "def unused():\n"
        '    json.dump({}, open("analysis/out.json", "w"))\n'
    )

    diagnosis = await toolkit._missing_output_diagnosis(["analysis/out.json"])

    assert diagnosis["writeNotExecutedPaths"] == ["analysis/out.json"]
    assert "notReferencedPaths" not in diagnosis
    assert "未执行到" in diagnosis["outputHint"]
