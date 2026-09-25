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
    _missing_output_diagnosis,
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
    rejected = await _rejected(toolkit)
    # 第五跑形态：补丁携带草稿 SHA，但块内混入标记（marker_in_block），无法应用。
    invalid = (
        f"*** Begin Edit\n*** SHA256: {rejected['details']['draftSha256']}\n"
        "<<<<<<< SEARCH\nimport json\n=======\nimport os\n"
        "<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\n*** End Edit"
    )

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

    diagnosis = _missing_output_diagnosis(
        await toolkit._read_script_source(),
        ["analysis/out.json"],
        toolkit.context.declared_output_paths,
    )

    assert diagnosis["writeNotExecutedPaths"] == ["analysis/out.json"]
    assert "notReferencedPaths" not in diagnosis
    assert "未执行到" in diagnosis["outputHint"]


@pytest.mark.anyio
async def test_applied_draft_patch_with_remaining_violations_keeps_draft(
    binding, runtime  # noqa: F811
):
    toolkit = _toolkit(binding, runtime)
    source = (
        'import json\njson.dump({}, open("data/x.json", "w"))\n'
        'json.dump({}, open("data/y.json", "w"))\n'
    )
    await toolkit.write_script(source)

    # 两次补丁都已应用、各修掉一处违规：属于逐步修正，不应作废草稿。
    first = await toolkit.edit_script(
        multi_edit_patch(source, [('"data/x.json"', '"analysis/out.json"')])
    )
    await _post_hook(toolkit, "edit_script", first)
    assert first["code"] == "report_python_source_path_invalid"
    patched = source.replace('"data/x.json"', '"analysis/out.json"')
    second = await toolkit.edit_script(
        multi_edit_patch(patched, [("\njson.dump({}, open(\"data/y.json\", \"w\"))", "")])
    )
    await _post_hook(toolkit, "edit_script", second)

    assert second["ok"] is True
    assert second["status"] == "draft_promoted"


@pytest.mark.anyio
async def test_discarded_draft_receipt_points_to_write_script(binding, runtime):  # noqa: F811
    toolkit = _toolkit(binding, runtime)
    await _rejected(toolkit)
    missing = multi_edit_patch(REJECTED_SOURCE, [("not in draft", "x = 1")])

    for _ in range(2):
        result = await toolkit.edit_script(missing)
        await _post_hook(toolkit, "edit_script", result)

    assert result["draftDiscarded"] is True
    assert "draftSha256" not in result["details"]
    assert result["details"]["nextTools"] == ["write_script"]


def test_plotly_io_writers_take_path_from_second_argument():
    import ast

    from smart_reporting.reporting.code_agent.toolkit import (
        _declared_output_write_paths,
        _referenced_literal_paths,
    )

    tree = ast.parse(
        "import plotly.io as pio\n"
        'pio.write_image(fig, "charts/a.png")\n'
        'pio.write_json(fig, "charts/a.plotly.json")\n'
        'fig.write_image("charts/b.png")\n'
    )
    declared = frozenset({"charts/a.png", "charts/a.plotly.json", "charts/b.png"})

    assert _declared_output_write_paths(tree, declared) == declared
    assert _referenced_literal_paths(tree) == declared


@pytest.mark.anyio
async def test_formal_script_edit_failures_do_not_discard_draft(binding, runtime):  # noqa: F811
    toolkit = _toolkit(binding, runtime)
    await _rejected(toolkit)
    # 以不存在的正式脚本 SHA 打补丁：失败与草稿无关，不能计入草稿空转。
    unrelated = multi_edit_patch("x = 1\n", [("x = 1", "x = 2")])

    for _ in range(3):
        result = await toolkit.edit_script(unrelated)
        await _post_hook(toolkit, "edit_script", result)

    assert result["ok"] is False
    assert "draftDiscarded" not in result
    assert toolkit.rejected_draft_sha256 is not None


def test_plotly_offline_plot_filename_is_recognized_as_write():
    import ast

    from smart_reporting.reporting.code_agent.toolkit import (
        _declared_output_write_paths,
        _referenced_literal_paths,
    )

    tree = ast.parse('import plotly\nplotly.offline.plot(fig, filename="charts/b.html")\n')

    assert _declared_output_write_paths(tree, frozenset({"charts/b.html"})) == {"charts/b.html"}
    assert _referenced_literal_paths(tree) == {"charts/b.html"}


def test_deterministic_setup_failures_are_not_final_attempt_degradable():
    from smart_reporting.reporting.code_agent.failure_policy import final_attempt_degradable
    from smart_reporting.reporting.models import ReportingError

    for code in ("report_coding_task_workspace_mismatch", "report_capability_state_invalid"):
        assert final_attempt_degradable(ReportingError(code, "m")) is False
    assert final_attempt_degradable(
        ReportingError("report_code_custom_tool_protocol_error", "m")
    ) is True


@pytest.mark.anyio
async def test_run_script_precreates_declared_output_subdirectories(workspace):  # noqa: F811
    from smart_reporting.reporting.code_agent.context import (
        ReportingCodingTaskBinding,
        ReportingCodingTaskContext,
    )
    from smart_reporting.reporting.code_mode import ScriptProcessResult

    output = "analysis/charts/sub/out.json"
    context = ReportingCodingTaskContext(
        task_id="task-1",
        task_kind="analysis",
        code_mode_session_id="code-task-1",
        workspace_key=workspace.identity.workspace_key,
        workspace_root=workspace.identity.root,
        script_path="analysis/a.py",
        authorized_read_paths=(),
        authorized_write_paths=("analysis/a.py", output),
        declared_output_paths=(output,),
        max_source_bytes=128 * 1024,
    )

    class ScriptRuntime:
        async def execute_script_process(self, _session_id, task_workspace, _path, **_kwargs):
            # 模拟脚本进程：只按签发完整路径写文件，不自行创建父目录。
            task_workspace.paths.to_host_path(output).write_text("{}", encoding="utf-8")
            return ScriptProcessResult(
                SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0
            )

    toolkit = ReportingCodeModeToolkit(
        ReportingCodingTaskBinding(context, workspace),
        ScriptRuntime(),
        ReportingLspProcessManager(),
    )
    written = await toolkit.write_script(f'open("{output}", "w").write("{{}}")\n')
    assert written["ok"] is True

    result = await toolkit.run_script()

    assert result["ok"] is True


@pytest.mark.anyio
async def test_view_image_skips_plotly_interactive_spec(workspace):  # noqa: F811
    from smart_reporting.reporting.code_agent.context import (
        ReportingCodingTaskBinding,
        ReportingCodingTaskContext,
    )

    context = ReportingCodingTaskContext(
        task_id="task-1",
        task_kind="visualization",
        code_mode_session_id="code-task-1",
        workspace_key=workspace.identity.workspace_key,
        workspace_root=workspace.identity.root,
        script_path="charts/chart.py",
        authorized_read_paths=(),
        authorized_write_paths=("charts/chart.py", "charts/a.png", "charts/a.plotly.json"),
        declared_output_paths=("charts/a.png", "charts/a.plotly.json"),
        max_source_bytes=128 * 1024,
    )
    toolkit = ReportingCodeModeToolkit(
        ReportingCodingTaskBinding(context, workspace), object(), ReportingLspProcessManager()
    )

    # 交互规格不得送入图片检查：否则返回 report_chart_source_invalid 并诱导修复脚本。
    result = await toolkit.view_image(paths=["charts/a.plotly.json"])

    assert result["code"] == "report_code_visual_path_not_image"


@pytest.mark.anyio
async def test_execution_failure_reports_outputs_written_before_crash(workspace):  # noqa: F811
    from smart_reporting.reporting.code_agent.context import (
        ReportingCodingTaskBinding,
        ReportingCodingTaskContext,
    )
    from smart_reporting.reporting.code_mode import ScriptProcessResult

    first, second = "analysis/out_a.json", "analysis/out_b.json"
    context = ReportingCodingTaskContext(
        task_id="task-1",
        task_kind="analysis",
        code_mode_session_id="code-task-1",
        workspace_key=workspace.identity.workspace_key,
        workspace_root=workspace.identity.root,
        script_path="analysis/a.py",
        authorized_read_paths=(),
        authorized_write_paths=("analysis/a.py", first, second),
        declared_output_paths=(first, second),
        max_source_bytes=128 * 1024,
    )

    class CrashingRuntime:
        async def execute_script_process(self, _session_id, task_workspace, _path, **_kwargs):
            # 第一张写出后，第二张的数据断言失败，脚本以非零退出。
            task_workspace.paths.to_host_path(first).write_text("{}", encoding="utf-8")
            cell = SimpleNamespace(
                status="error", stdout="", stderr="AssertionError: rows empty", traceback=None
            )
            return ScriptProcessResult(cell, 1)

    toolkit = ReportingCodeModeToolkit(
        ReportingCodingTaskBinding(context, workspace),
        CrashingRuntime(),
        ReportingLspProcessManager(),
    )
    await toolkit.write_script(
        f'open("{first}", "w").write("{{}}")\nopen("{second}", "w").write("{{}}")\n'
    )

    result = await toolkit.run_script()

    assert result["code"] == "report_code_mode_execution_failed"
    assert result["details"]["presentPaths"] == [first]
    assert result["details"]["missingPaths"] == [second]
    assert "只局部修复" in result["details"]["outputHint"]
