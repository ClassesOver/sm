from __future__ import annotations

import hashlib
import inspect
import json

import pytest
from agno.exceptions import ModelRateLimitError
from agno.models.message import Message
from agno.run import RunStatus
from agno.run.agent import RunOutput
from loguru import logger

from smart_reporting.reporting.agent import ReportingCodeOpenAIResponses
from smart_reporting.reporting.model_policy import ThinkingDecision, bind_reporting_thinking
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.code_generation import (
    CodeGenerationResult,
    ReportingCodeGenerationRunner,
)

SOURCE = "value = 1\nprint(value)\n"
UPDATED_SOURCE = "value = 2\nprint(value)\n"


class FakeAgent:
    def __init__(self, action):
        self.action = action
        self.tools = []
        self.tool_choice = None

    async def arun(self, _prompt, **_kwargs):
        self.prompt = _prompt
        return await self.action(self)


def test_fresh_code_agent_drops_reasoning_only_for_bound_off_decision() -> None:
    template = FakeAgent(lambda _agent: None)
    template.reasoning_model = object()
    template.reasoning_agent = object()
    runner = ReportingCodeGenerationRunner(agent=template)
    off = ThinkingDecision(
        operation="visualization_script",
        complexity="complex",
        enabled=False,
        reasoning_effort=None,
        thinking_budget=0,
        attempt=0,
        reason="initial_off",
    )

    with bind_reporting_thinking(off):
        fresh = runner._fresh_agent()

    assert fresh.reasoning_model is None
    assert fresh.reasoning_agent is None
    assert template.reasoning_model is not None
    assert template.reasoning_agent is not None


def identity(path: str, content: str) -> FileIdentity:
    raw = content.encode()
    return FileIdentity(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def read_receipt(script: FileIdentity, content: str = "print(1)\n") -> dict[str, object]:
    size = len(content.encode())
    return {
        "ok": True,
        "path": script.path,
        "content": content,
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "offset": 0,
        "nextOffset": size,
        "totalBytes": size,
    }


@pytest.mark.anyio
async def test_generate_exposes_only_source_and_returns_single_identity():
    calls = []

    async def action(agent):
        assert [tool.name for tool in agent.tools] == ["submit_python_source"]
        assert agent.tool_choice["function"]["name"] == "submit_python_source"
        return await agent.tools[0].entrypoint(source=SOURCE)

    async def patch(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "artifacts": [identity("analysis/script.py", "print(1)\n")]}

    runner = ReportingCodeGenerationRunner(agent=FakeAgent(action))
    result = await runner.generate("analysis/script.py", {"fact": 1}, patch)

    assert isinstance(result, CodeGenerationResult)
    assert result.script_file.path == "analysis/script.py"
    assert calls == [
        {
            "patch": (
                "--- /dev/null\n"
                "+++ b/analysis/script.py\n"
                "@@ -0,0 +1,2 @@\n"
                "+value = 1\n"
                "+print(value)\n"
            )
        }
    ]


@pytest.mark.anyio
async def test_generate_restores_escaped_physical_lines_without_changing_string_escapes():
    escaped_source = r'value = "A\\nB"\nprint(value)\n'
    restored_source = 'value = "A\\nB"\nprint(value)\n'
    patches: list[str] = []

    async def action(agent):
        return await agent.tools[0].entrypoint(source=escaped_source)

    async def patch(*, patch: str):
        patches.append(patch)
        return {"ok": True, "artifacts": [identity("analysis/script.py", restored_source)]}

    await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
        "analysis/script.py", {}, patch
    )

    assert patches == [
        (
            "--- /dev/null\n"
            "+++ b/analysis/script.py\n"
            "@@ -0,0 +1,2 @@\n"
            '+value = "A\\nB"\n'
            "+print(value)\n"
        )
    ]


@pytest.mark.anyio
async def test_generate_unwraps_json_encoded_source_string():
    source = 'value = "A\\nB"\nprint(value)\n'
    wrapped_source = json.dumps(source)
    patches: list[str] = []

    async def action(agent):
        return await agent.tools[0].entrypoint(source=wrapped_source)

    async def patch(*, patch: str):
        patches.append(patch)
        return {"ok": True, "artifacts": [identity("analysis/script.py", source)]}

    await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
        "analysis/script.py", {"fact": 1}, patch
    )

    assert patches == [
        (
            "--- /dev/null\n"
            "+++ b/analysis/script.py\n"
            "@@ -0,0 +1,2 @@\n"
            '+value = "A\\nB"\n'
            "+print(value)\n"
        )
    ]


@pytest.mark.anyio
async def test_generate_logs_script_base_info_at_info_level():
    async def action(agent):
        return await agent.tools[0].entrypoint(source=SOURCE)

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity("analysis/script.py", "print(1)\n")]}

    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO", format="{level}:{message}")
    try:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {"fact": 1}, patch
        )
    finally:
        logger.remove(sink_id)

    events = [
        line for line in "".join(records).splitlines() if "report_code_generation_base_info" in line
    ]
    assert events == [
        "INFO:report_code_generation_base_info "
        'script={"operation":"create","path":"analysis/script.py","size":9,'
        '"sha256":"cc42155088fca5730758db72b2a5bca33112a941dfaa2d43098ec422ce4ea213"}'
    ]


@pytest.mark.anyio
async def test_generate_logs_six_internal_step_durations_without_source():
    async def action(agent):
        return await agent.tools[0].entrypoint(source=SOURCE)

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity("analysis/script.py", "print(1)\n")]}

    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO", format="{message}")
    try:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {"fact": 1}, patch
        )
    finally:
        logger.remove(sink_id)

    events = [
        line
        for line in "".join(records).splitlines()
        if "report_code_generation_step_completed" in line
    ]
    assert len(events) == 6
    assert [f"step={index}" in event for index, event in enumerate(events, start=1)] == [True] * 6
    assert [
        name in event
        for name, event in zip(
            (
                "model_generate_source",
                "source_shape_validate",
                "python_compile",
                "patch_build",
                "patch_apply",
                "receipt_validate",
            ),
            events,
            strict=True,
        )
    ] == [True] * 6
    assert all("duration_ms=" in event and "total_duration_ms=" in event for event in events)
    assert all("operation=create path=analysis/script.py" in event for event in events)
    assert SOURCE not in "".join(events)


@pytest.mark.anyio
async def test_generate_passes_bounded_previous_failure_to_fresh_retry():
    prompts: list[dict[str, object]] = []

    async def action(agent):
        prompts.append(json.loads(agent.prompt))
        return await agent.tools[0].entrypoint(source=SOURCE)

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity("analysis/script.py", "print(1)\n")]}

    diagnostic = {
        "code": "report_python_source_shape_invalid",
        "message": "m" * 800,
        "details": {
            "path": "analysis/script.py",
            "unsignedPaths": [
                None,
                "",
                "x" * 1025,
                *[f"datasets/input-{index}.csv" for index in range(25)],
            ],
            "line": 284,
            "offset": 62,
            "size": 131073,
            "lineCount": 1,
            "maxLineLength": 131072,
            "source": "SECRET_SOURCE",
        },
    }
    await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
        "analysis/script.py",
        {},
        patch,
        diagnostic=diagnostic,
        max_source_bytes=128 * 1024,
    )

    assert prompts[0]["diagnostic"] == {
        "code": "report_python_source_shape_invalid",
        "message": "m" * 512,
        "details": {
            "path": "analysis/script.py",
            "unsignedPaths": [f"datasets/input-{index}.csv" for index in range(20)],
            "line": 284,
            "offset": 62,
            "size": 131073,
            "lineCount": 1,
            "maxLineLength": 131072,
        },
    }
    assert prompts[0]["sourceProtocol"] == {
        "path": "analysis/script.py",
        "maxSourceBytes": 128 * 1024,
        "maxPhysicalLineBytes": 8 * 1024,
        "minPhysicalLines": 2,
        "lineEnding": "LF",
        "trailingNewline": True,
        "pythonVersion": "3.12",
        "compilationRequired": True,
        "authorizedPaths": ["analysis/script.py"],
        "factUsageRequirements": [
            "facts 仅是源码生成上下文，脚本执行时不存在 facts、taskFacts 或 "
            "visualizationFacts 变量",
            "读取 authorizedPaths 中的 JSON 文件后，必须按该文件自身根结构访问；"
            "不得添加 facts、taskFacts 或 visualizationFacts 包装层",
        ],
        "syntaxRequirements": [
            "提交前确保完整源码可通过 ast.parse 和 compile",
            "source 参数必须包含真实 LF 换行；不得使用两个字符 \\n 代替物理换行",
            "使用普通赋值和显式 if；不得使用 := 赋值表达式或 if False/if True 死代码分支",
            "文件读写只可逐字使用 authorizedPaths；不得使用 __file__、cwd、chdir、"
            "os.path.join 或目录回退推导工作区路径",
        ],
    }
    assert "SECRET_SOURCE" not in json.dumps(prompts, ensure_ascii=False)


@pytest.mark.anyio
async def test_repair_requests_full_analysis_script_from_real_read_callback():
    content = "value = 1\n" + ("#" + "x" * 4094 + "\n") * 17
    assert 64 * 1024 < len(content.encode()) < 128 * 1024
    script = identity("analysis/script.py", content)
    observed_max_bytes: list[int] = []

    async def action(agent):
        tool = agent.tools[0]
        if tool.name == "read_file":
            return await tool.entrypoint(path=script.path)
        return await tool.entrypoint(source=UPDATED_SOURCE)

    async def read_file(*, path: str, max_bytes: int):
        observed_max_bytes.append(max_bytes)
        assert path == script.path
        return read_receipt(script, content)

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity(script.path, "value = 2\nprint(value)\n")]}

    await ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(action)).repair(
        script,
        {"code": "report_analysis_script_failed"},
        read_file,
        patch,
        max_source_bytes=128 * 1024,
    )

    assert observed_max_bytes == [128 * 1024]


@pytest.mark.anyio
async def test_repair_agent_reads_only_signed_script_before_submitting_source():
    source = "print(1)\n"
    script = identity("analysis/script.py", source)
    read_paths: list[str] = []

    agents = []

    async def action(agent):
        agents.append(agent)
        ReportingCodeOpenAIResponses(
            id="test-model",
            api_key="test-key",
            base_url="http://localhost",
        ).get_request_params(
            messages=[Message(role="user", content=agent.prompt)],
            tools=agent.tools,
            tool_choice=agent.tool_choice,
        )
        assert len(agent.tools) == 1
        tool = agent.tools[0]
        if tool.name == "read_file":
            assert agent.tool_choice["function"]["name"] == "read_file"
            assert agent.tool_call_limit == 1
            pytest.fail("repair Agent must not receive a read_file phase")

        assert tool.name == "submit_python_source"
        assert agent.tool_choice["function"]["name"] == "submit_python_source"
        assert agent.tool_call_limit == 1
        prompt = json.loads(agent.prompt)
        assert "readableFiles" not in prompt["facts"]
        assert "readReceipts" not in prompt["facts"]
        assert "readToolRequirements" not in prompt["sourceProtocol"]
        return await tool.entrypoint(source=UPDATED_SOURCE)

    async def read_file(*, path: str, max_bytes: int):
        assert max_bytes == 128 * 1024
        read_paths.append(path)
        if path == script.path:
            return read_receipt(script, source)
        pytest.fail(f"repair must not read JSON input: {path}")

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity(script.path, UPDATED_SOURCE)]}

    await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
        script,
        {"code": "execution_output_error"},
        read_file,
        patch,
    )

    assert read_paths == [script.path]
    assert [[tool.name for tool in agent.tools] for agent in agents] == [
        ["submit_python_source"],
    ]


def test_repair_does_not_expose_signed_json_read_inputs():
    assert "readable_files" not in inspect.signature(
        ReportingCodeGenerationRunner.repair
    ).parameters


@pytest.mark.anyio
async def test_repair_preserves_bounded_execution_failure_details():
    script = identity("analysis/script.py", "print(1)\n")
    patch_prompts: list[dict[str, object]] = []
    embedded_source = "value = 1\\n" * 500
    failure_output = (
        "Traceback (most recent call last):\n"
        '  File "<target_code>", line 72, in <module>\n'
        f"    exec(compile({embedded_source!r}, '<string>', 'exec'), globals(), globals())\n"
        '  File "<string>", line 8, in <module>\n'
        "FileNotFoundError: [Errno 2] No such file or directory: '/报表/数据集/input.csv'\n"
    )

    async def action(agent):
        tool = agent.tools[0]
        if tool.name == "read_file":
            return await tool.entrypoint(path=script.path)
        patch_prompts.append(json.loads(agent.prompt))
        return await tool.entrypoint(source=UPDATED_SOURCE)

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity(script.path, "print(2)\n")]}

    await ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(action)).repair(
        script,
        {
            "code": "report_analysis_script_failed",
            "details": {
                "exitCode": 7,
                "output": failure_output,
                "outputTruncated": True,
                "toolCode": "sandbox_process_failed",
                "toolMessage": "process failed",
                "secret": "SECRET_DETAIL",
            },
        },
        lambda **_kwargs: read_receipt(script),
        patch,
    )

    diagnostic = patch_prompts[0]["facts"]["diagnostic"]
    assert diagnostic["details"]["exitCode"] == 7
    assert diagnostic["details"]["outputTruncated"] is True
    assert diagnostic["details"]["toolCode"] == "sandbox_process_failed"
    assert diagnostic["details"]["toolMessage"] == "process failed"
    assert "<generated source omitted>" in diagnostic["details"]["output"]
    assert "FileNotFoundError: [Errno 2]" in diagnostic["details"]["output"]
    assert embedded_source[:100] not in diagnostic["details"]["output"]
    assert len(diagnostic["details"]["output"]) <= 2000
    assert "SECRET_DETAIL" not in json.dumps(patch_prompts, ensure_ascii=False)
    assert patch_prompts[0]["sourceProtocol"]["path"] == script.path


@pytest.mark.anyio
async def test_generate_rejects_plain_text_without_mutation():
    async def action(_agent):
        return "print('source')"

    mutated = False

    async def patch(**_kwargs):
        nonlocal mutated
        mutated = True
        return {"ok": True, "artifacts": []}

    runner = ReportingCodeGenerationRunner(agent=FakeAgent(action))
    with pytest.raises(ReportingError) as raised:
        await runner.generate("analysis/script.py", {}, patch)

    assert raised.value.code == "report_code_generation_no_source"
    assert mutated is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    "source",
    [
        "import os\ndataset_path = os.path.join(os.path.dirname(__file__), '..', 'input.csv')\n",
        "import os\ndataset_path = os.path.join(os.getcwd(), 'input.csv')\n",
        "from pathlib import Path\ndataset_path = Path.cwd() / 'input.csv'\n",
        "import os\ndataset_path = os.path.join('报表', '..', '数据集', 'input.csv')\n",
        "import os.path\ndataset_path = os.path.join('报表', '数据集', 'input.csv')\n",
        "from os import getcwd\ndataset_path = getcwd() + '/datasets/income.csv'\n",
        "from os import chdir\nchdir('报表')\nopen('datasets/income.csv')\n",
    ],
)
async def test_generate_rejects_script_relative_workspace_paths_without_mutation(source: str):
    mutated = False

    async def action(agent):
        return await agent.tools[0].entrypoint(source=source)

    async def patch(**_kwargs):
        nonlocal mutated
        mutated = True
        return {"ok": True, "artifacts": []}

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert raised.value.code == "report_python_source_path_invalid"
    assert "签发路径" in raised.value.message
    assert mutated is False


@pytest.mark.anyio
async def test_generate_reports_exact_forbidden_path_operations_for_retry() -> None:
    source = (
        "import os\n"
        "base_dir = os.path.dirname(os.path.abspath(__file__))\n"
        "input_path = os.path.join(base_dir, '..', 'datasets', 'income.csv')\n"
    )

    async def action(agent):
        return await agent.tools[0].entrypoint(source=source)

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, lambda **_kwargs: pytest.fail("must not mutate")
        )

    assert raised.value.code == "report_python_source_path_invalid"
    assert raised.value.details == {
        "path": "analysis/script.py",
        "unsignedPaths": [],
        "forbiddenPathOperations": [
            "__file__",
            "os.path.abspath",
            "os.path.dirname",
            "os.path.join",
        ],
    }


@pytest.mark.anyio
async def test_generate_accepts_parent_marker_as_non_path_data() -> None:
    source = "import pandas as pd\ndf = pd.read_csv('datasets/income.csv', na_values=['..'])\n"

    async def action(agent):
        return await agent.tools[0].entrypoint(source=source)

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity("analysis/script.py", source)]}

    result = await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
        "analysis/script.py",
        {"datasets": [{"path": "datasets/income.csv"}]},
        patch,
    )

    assert result.script_file.path == "analysis/script.py"


@pytest.mark.anyio
async def test_generate_rejects_unsigned_workspace_path_without_mutation() -> None:
    source = "import pandas as pd\ndf = pd.read_csv('datasets/guessed.csv')\n"
    mutated = False

    async def action(agent):
        return await agent.tools[0].entrypoint(source=source)

    async def patch(**_kwargs):
        nonlocal mutated
        mutated = True
        return {"ok": True, "artifacts": []}

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py",
            {"datasets": [{"path": "datasets/income.csv"}]},
            patch,
        )

    assert raised.value.code == "report_python_source_path_invalid"
    assert mutated is False


@pytest.mark.anyio
async def test_generate_rejects_zero_tool_calls_without_mutation():
    async def action(_agent):
        return None

    async def patch(**_kwargs):
        pytest.fail("zero tool calls must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert raised.value.code == "report_code_generation_no_source"


@pytest.mark.anyio
async def test_generate_preserves_recorded_model_rate_limit_from_agno_error_status():
    class RateLimitedModel:
        @staticmethod
        def report_run_error():
            return ModelRateLimitError(
                "insufficient_quota: provider-secret",
                status_code=429,
                model_id="test-model",
            )

    async def action(_agent):
        return RunOutput(status=RunStatus.error)

    agent = FakeAgent(action)
    agent.model = RateLimitedModel()

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=agent).generate(
            "analysis/script.py", {}, lambda **_kwargs: pytest.fail("must not mutate")
        )

    assert raised.value.code == "report_code_generation_rate_limited"
    assert raised.value.message == "Coding Agent 模型调用受限，请稍后重试。"
    assert raised.value.details == {"statusCode": 429}
    assert "provider-secret" not in str(raised.value)


@pytest.mark.anyio
async def test_generate_does_not_report_agno_error_status_as_no_source():
    async def action(_agent):
        return RunOutput(status=RunStatus.error)

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, lambda **_kwargs: pytest.fail("must not mutate")
        )

    assert raised.value.code == "report_code_generation_agent_failed"


@pytest.mark.anyio
async def test_repair_reads_once_then_uses_source_generation_agent():
    script = identity("analysis/script.py", "print(1)\n")
    seen_tools = []
    agents = []

    async def action(agent):
        agents.append(agent)
        tool = agent.tools[0]
        seen_tools.append(tool.name)
        if tool.name == "read_file":
            return await tool.entrypoint(path="analysis/script.py")
        return await tool.entrypoint(source=UPDATED_SOURCE)

    async def read_file(**kwargs):
        receipt = read_receipt(script)
        receipt["path"] = kwargs["path"]
        return receipt

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity(script.path, "print(2)\n")]}

    runner = ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(action))
    result = await runner.repair(script, {"code": "bad"}, read_file, patch)

    assert result.script_file.sha256 == hashlib.sha256(b"print(2)\n").hexdigest()
    assert seen_tools == ["submit_python_source"]
    assert len(agents) == 1


@pytest.mark.anyio
async def test_repair_logs_script_base_info_at_info_level():
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        tool = agent.tools[0]
        if tool.name == "read_file":
            return await tool.entrypoint(path=script.path)
        return await tool.entrypoint(source=UPDATED_SOURCE)

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity(script.path, "print(2)\n")]}

    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO", format="{level}:{message}")
    try:
        await ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(action)).repair(
            script,
            {
                "code": "report_visualization_script_failed",
                "message": "章节图表脚本执行未被接受。",
                "details": {
                    "path": "analysis/script.py",
                    "exitCode": 1,
                    "output": "Traceback: chart rendering failed",
                    "toolCode": "execution_output_error",
                    "toolMessage": "Python 脚本执行失败。",
                },
            },
            lambda **_kwargs: read_receipt(script),
            patch,
        )
    finally:
        logger.remove(sink_id)

    events = [
        line for line in "".join(records).splitlines() if "report_code_repair_base_info" in line
    ]
    assert events == [
        "INFO:report_code_repair_base_info "
        'script={"operation":"repair","path":"analysis/script.py","size":9,'
        '"sha256":"0111afd387e1ad576083c5039aa542faa2ed4a53d3e128bd03de990f9ea4255f",'
        '"diagnosticCode":"report_visualization_script_failed",'
        '"diagnostic":{"code":"report_visualization_script_failed",'
        '"message":"章节图表脚本执行未被接受。","details":{"path":"analysis/script.py",'
        '"exitCode":1,"output":"Traceback: chart rendering failed",'
        '"toolCode":"execution_output_error","toolMessage":"Python 脚本执行失败。"}}}'
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("output", [None, "print('direct source')"])
async def test_repair_rejects_write_stage_without_a_patch(output):
    script = identity("analysis/script.py", "print(1)\n")
    agents = []

    async def action(agent):
        agents.append(agent)
        if agent.tools[0].name == "read_file":
            return await agent.tools[0].entrypoint(path=script.path)
        return output

    async def read_file(**_kwargs):
        return read_receipt(script)

    async def patch(**_kwargs):
        pytest.fail("write stage without patch must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_no_source"
    assert [agent.tools[0].name for agent in agents] == ["submit_python_source"]


@pytest.mark.anyio
async def test_repair_reads_directly_and_invokes_only_source_generation_agent():
    script = identity("analysis/script.py", "print(1)\n")
    reasoning_model = object()
    reasoning_agent = object()
    observed = []

    async def action(agent):
        observed.append((agent.tools[0].name, agent.reasoning_model, agent.reasoning_agent))
        if agent.tools[0].name == "read_file":
            return await agent.tools[0].entrypoint(path=script.path)
        return await agent.tools[0].entrypoint(source=UPDATED_SOURCE)

    template = FakeAgent(action)
    template.reasoning_model = reasoning_model
    template.reasoning_agent = reasoning_agent

    async def read_file(**_kwargs):
        return read_receipt(script)

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity(script.path, UPDATED_SOURCE)]}

    await ReportingCodeGenerationRunner(agent=template).repair(script, {}, read_file, patch)

    assert observed == [("submit_python_source", reasoning_model, reasoning_agent)]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("offset", True),
        ("nextOffset", True),
        ("totalBytes", True),
        ("offset", -1),
        ("nextOffset", -1),
        ("totalBytes", -1),
    ],
)
async def test_repair_rejects_invalid_pagination_values(field, value):
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        receipt = read_receipt(script)
        receipt[field] = value
        return receipt

    async def patch(**_kwargs):
        pytest.fail("invalid read receipt must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_invalid"
    assert raised.value.details == {"path": script.path}


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["offset", "nextOffset", "totalBytes"])
async def test_repair_requires_all_pagination_fields(field):
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        receipt = read_receipt(script)
        receipt.pop(field)
        return receipt

    async def patch(**_kwargs):
        pytest.fail("incomplete read receipt must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_invalid"
    assert raised.value.details == {"path": script.path}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "update",
    [
        {"nextOffset": 1},
        {"totalBytes": 1},
        {"sha256": "0" * 64},
        {"content": "print(2)\n"},
    ],
)
async def test_repair_rejects_incomplete_or_identity_mismatched_read_receipt(update):
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        return {**read_receipt(script), **update}

    async def patch(**_kwargs):
        pytest.fail("invalid read receipt must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code in {
        "report_code_generation_read_incomplete",
        "report_code_generation_read_invalid",
    }
    assert raised.value.details == {"path": script.path}


@pytest.mark.anyio
async def test_repair_requires_read_byte_count_to_match_script_identity():
    original = identity("analysis/script.py", "print(1)\n")
    script = FileIdentity(path=original.path, size=original.size + 1, sha256=original.sha256)

    async def action(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        return read_receipt(original)

    async def patch(**_kwargs):
        pytest.fail("identity byte mismatch must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_invalid"
    assert raised.value.details == {"path": script.path}


@pytest.mark.anyio
async def test_repair_rejects_oversized_read_receipt_before_patch_prompt():
    content = "#" * (128 * 1024 + 1)
    script = identity("analysis/script.py", content)
    prompts = []

    async def action(agent):
        prompts.append(agent.prompt)
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        return read_receipt(script, content)

    async def patch(**_kwargs):
        pytest.fail("oversized read receipt must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_too_large"
    assert raised.value.details == {"path": script.path}
    assert prompts == []


@pytest.mark.anyio
async def test_repair_normalizes_diagnostic_and_read_receipt_before_patch_prompt():
    script = identity("analysis/script.py", "print(1)\n")
    prompts = []

    async def action(agent):
        tool = agent.tools[0]
        if tool.name == "read_file":
            return await tool.entrypoint(path=script.path)
        prompts.append(json.loads(agent.prompt))
        return await tool.entrypoint(source=UPDATED_SOURCE)

    async def read_file(**_kwargs):
        return {**read_receipt(script), "untrusted": "x" * 10_000}

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity(script.path, "print(2)\n")]}

    diagnostic = {
        "code": "repair_failed",
        "message": "m" * 10_000,
        "details": {"path": script.path, "line": 4, "source": "SECRET_SOURCE"},
        "receipt": "SECRET_RECEIPT",
    }
    await ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(action)).repair(
        script, diagnostic, read_file, patch
    )

    facts = prompts[0]["facts"]
    assert set(facts["diagnostic"]) <= {"code", "message", "details"}
    assert facts["diagnostic"]["code"] == "repair_failed"
    assert len(facts["diagnostic"]["message"]) <= 512
    assert facts["diagnostic"]["details"] == {"path": script.path, "line": 4}
    assert "SECRET_SOURCE" not in agent_prompt_text(facts)
    assert "SECRET_RECEIPT" not in agent_prompt_text(facts)
    assert set(facts["readReceipt"]) == {"path", "sha256", "content", "totalBytes"}


@pytest.mark.anyio
async def test_repair_preserves_bounded_missing_facts_in_patch_prompt():
    script = identity("analysis/script.py", "print(1)\n")
    prompts = []

    async def action(agent):
        tool = agent.tools[0]
        if tool.name == "read_file":
            return await tool.entrypoint(path=script.path)
        prompts.append(json.loads(agent.prompt))
        return await tool.entrypoint(source=UPDATED_SOURCE)

    async def read_file(**_kwargs):
        return read_receipt(script)

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity(script.path, "print(2)\n")]}

    missing_facts = [f"fact-{index}: " + "x" * 600 for index in range(30)]
    await ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(action)).repair(
        script,
        {"code": "repair_failed", "message": "brief diagnostic"},
        read_file,
        patch,
        task_facts={
            "missingFacts": missing_facts,
            "outputContract": {
                "format": "json",
                "requiredRootKeys": ["findings", "reconciliations", "warnings"],
                "additionalRootKeys": False,
            },
            "pythonSource": "SECRET_SOURCE",
        },
    )

    facts = prompts[0]["facts"]
    assert set(facts) == {"readReceipt", "diagnostic", "taskFacts"}
    assert facts["taskFacts"].keys() == {"missingFacts", "outputContract"}
    assert len(facts["taskFacts"]["missingFacts"]) == 20
    assert all(len(item) == 512 for item in facts["taskFacts"]["missingFacts"])
    assert facts["taskFacts"]["missingFacts"][0].startswith("fact-0:")
    assert facts["taskFacts"]["outputContract"] == {
        "format": "json",
        "requiredRootKeys": ["findings", "reconciliations", "warnings"],
        "additionalRootKeys": False,
    }
    assert "SECRET_SOURCE" not in agent_prompt_text(facts)


@pytest.mark.anyio
async def test_repair_preserves_bounded_visual_facts_without_receipt_metadata():
    script = identity("charts/charts.py", "print(1)\n")
    prompts = []

    async def action(agent):
        tool = agent.tools[0]
        if tool.name == "read_file":
            return await tool.entrypoint(path=script.path)
        prompts.append(json.loads(agent.prompt))
        return await tool.entrypoint(source=UPDATED_SOURCE)

    async def read_file(**_kwargs):
        return read_receipt(script)

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity(script.path, "print(2)\n")]}

    missing_charts = [
        {
            "chartId": f"chart-{index}" + "x" * 200,
            "sourcePath": f"charts/{index}.png" + "x" * 1_100,
            "title": f"图表 {index}" + "x" * 300,
            "sha256": "SECRET_CHART_SHA",
        }
        for index in range(101)
    ]
    inspections = [
        {
            "sourcePath": f"charts/{index}.png" + "x" * 1_100,
            "visualReviewStatus": "needs_revision",
            "requiresRevision": True,
            "issues": [
                {
                    "category": "text_overlap",
                    "severity": "critical",
                    "description": "标签重叠" + "x" * 600,
                    "evidence": "SECRET_ISSUE_EVIDENCE",
                }
                for _ in range(21)
            ],
            "warnings": ["警告" + "x" * 600 for _ in range(21)],
            "suggestions": ["建议" + "x" * 600 for _ in range(21)],
            "summary": "视觉检查摘要" + "x" * 2_100,
            "sha256": "SECRET_RECEIPT_SHA",
            "modelId": "SECRET_MODEL_ID",
            "rawResponse": "SECRET_RAW_RESPONSE",
        }
        for index in range(101)
    ]
    await ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(action)).repair(
        script,
        {"code": "repair_failed", "message": "brief diagnostic"},
        read_file,
        patch,
        task_facts={
            "missingFacts": ["缺少的数值"],
            "missingCharts": missing_charts,
            "inspections": inspections,
            "draft": {"pythonSource": "SECRET_SOURCE"},
        },
    )

    task_facts = prompts[0]["facts"]["taskFacts"]
    assert task_facts.keys() == {"missingFacts", "missingCharts", "inspections"}
    assert task_facts["missingFacts"] == ["缺少的数值"]
    assert len(task_facts["missingCharts"]) == 100
    assert task_facts["missingCharts"][0].keys() == {"chartId", "sourcePath", "title"}
    assert all(len(chart["chartId"]) == 128 for chart in task_facts["missingCharts"])
    assert all(len(chart["sourcePath"]) == 1024 for chart in task_facts["missingCharts"])
    assert all(len(chart["title"]) == 200 for chart in task_facts["missingCharts"])
    assert len(task_facts["inspections"]) == 100
    inspection = task_facts["inspections"][0]
    assert inspection.keys() == {
        "sourcePath",
        "visualReviewStatus",
        "requiresRevision",
        "issues",
        "warnings",
        "suggestions",
        "summary",
    }
    assert len(inspection["sourcePath"]) == 1024
    assert inspection["visualReviewStatus"] == "needs_revision"
    assert inspection["requiresRevision"] is True
    assert len(inspection["issues"]) == 20
    assert inspection["issues"][0] == {
        "category": "text_overlap",
        "severity": "critical",
        "description": "标签重叠" + "x" * 496,
    }
    assert len(inspection["warnings"]) == len(inspection["suggestions"]) == 20
    assert all(len(item) == 500 for item in inspection["warnings"])
    assert all(len(item) == 500 for item in inspection["suggestions"])
    assert len(inspection["summary"]) == 2000
    prompt_text = agent_prompt_text(task_facts)
    assert "SECRET_CHART_SHA" not in prompt_text
    assert "SECRET_ISSUE_EVIDENCE" not in prompt_text
    assert "SECRET_RECEIPT_SHA" not in prompt_text
    assert "SECRET_MODEL_ID" not in prompt_text
    assert "SECRET_RAW_RESPONSE" not in prompt_text
    assert "SECRET_SOURCE" not in prompt_text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "task_facts",
    [
        {"missingFacts": "not-an-array"},
        {"missingFacts": ["valid", {"source": "SECRET_SOURCE"}]},
        {"missingFacts": ["valid", 3]},
        {"outputContract": "输出 JSON"},
        {
            "outputContract": {
                "format": "json",
                "requiredRootKeys": ["findings", "findings"],
                "additionalRootKeys": False,
            }
        },
        {
            "outputContract": {
                "format": "json",
                "requiredRootKeys": ["findings"],
                "additionalRootKeys": "false",
            }
        },
        {"missingCharts": "not-an-array"},
        {"missingCharts": [{"chartId": "chart", "sourcePath": "charts/x.png"}]},
        {"missingCharts": [{"chartId": "chart", "sourcePath": 1, "title": "标题"}]},
        {"inspections": "not-an-array"},
        {
            "inspections": [
                {
                    "sourcePath": "charts/x.png",
                    "visualReviewStatus": "passed",
                    "requiresRevision": "false",
                }
            ]
        },
        {
            "inspections": [
                {
                    "sourcePath": "charts/x.png",
                    "visualReviewStatus": "passed",
                    "requiresRevision": False,
                    "issues": [{"category": "cropping", "severity": "warning"}],
                }
            ]
        },
        {
            "inspections": [
                {
                    "sourcePath": "charts/x.png",
                    "visualReviewStatus": "not a stable status",
                    "requiresRevision": False,
                }
            ]
        },
    ],
)
async def test_repair_rejects_illegal_task_facts_before_read(task_facts):
    script = identity("analysis/script.py", "print(1)\n")

    async def action(_agent):
        pytest.fail("invalid task facts must fail before model invocation")

    async def read_file(**_kwargs):
        pytest.fail("invalid task facts must not read")

    async def patch(**_kwargs):
        pytest.fail("invalid task facts must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch, task_facts=task_facts
        )

    assert raised.value.code == "report_code_generation_task_facts_invalid"
    assert raised.value.details == {"path": script.path}


@pytest.mark.anyio
@pytest.mark.parametrize("task_facts", ["missing facts", ["missing facts"], object()])
async def test_repair_rejects_non_mapping_task_facts_before_read(task_facts):
    script = identity("analysis/script.py", "print(1)\n")

    async def action(_agent):
        pytest.fail("invalid task facts must fail before model invocation")

    async def read_file(**_kwargs):
        pytest.fail("invalid task facts must not read")

    async def patch(**_kwargs):
        pytest.fail("invalid task facts must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch, task_facts=task_facts
        )

    assert raised.value.code == "report_code_generation_task_facts_invalid"
    assert raised.value.details == {"path": script.path}


def agent_prompt_text(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.anyio
async def test_repair_redacts_read_callback_errors():
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        raise ReportingError(
            "workspace_read_failed", "SECRET_SOURCE", details={"content": "secret"}
        )

    async def patch(**_kwargs):
        pytest.fail("read errors must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "workspace_read_failed"
    assert raised.value.details == {"path": script.path}
    assert "SECRET_SOURCE" not in str(raised.value.details)


@pytest.mark.anyio
async def test_repair_redacts_non_reporting_read_errors():
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        raise RuntimeError("SECRET_TOOL_RECEIPT")

    async def patch(**_kwargs):
        pytest.fail("read errors must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_failed"
    assert raised.value.details == {"path": script.path}
    assert "SECRET_TOOL_RECEIPT" not in str(raised.value.details)


@pytest.mark.anyio
async def test_generate_rejects_second_source_after_one_mutation():
    calls = 0

    async def action(agent):
        await agent.tools[0].entrypoint(source=SOURCE)
        await agent.tools[0].entrypoint(source=UPDATED_SOURCE)

    async def patch(**_kwargs):
        nonlocal calls
        calls += 1
        return {"ok": True, "artifacts": [identity("analysis/script.py", "print(1)\n")]}

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert raised.value.code == "report_code_generation_multiple_sources"
    assert calls == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "receipt",
    [
        {"ok": False, "code": "patch_rejected", "message": "patch rejected"},
        {"ok": True, "artifacts": []},
        {
            "ok": True,
            "artifacts": [
                identity("analysis/script.py", "print(1)\n"),
                identity("analysis/other.py", "print(2)\n"),
            ],
        },
        {"ok": True, "artifacts": [identity("analysis/other.py", "print(1)\n")]},
    ],
)
async def test_generate_rejects_failed_or_ambiguous_patch_receipts(receipt):
    async def action(agent):
        return await agent.tools[0].entrypoint(source=SOURCE)

    async def patch(**_kwargs):
        return receipt

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert raised.value.code in {
        "patch_rejected",
        "report_code_generation_artifact_invalid",
        "report_code_generation_path_mismatch",
    }
    if receipt.get("ok") is False:
        assert raised.value.message == "patch rejected"
    assert "SECRET_SOURCE" not in str(raised.value.details)


@pytest.mark.anyio
async def test_generate_preserves_only_bounded_patch_failure_diagnostics():
    async def action(agent):
        return await agent.tools[0].entrypoint(source=SOURCE)

    async def patch(**_kwargs):
        return {
            "ok": False,
            "code": "report_python_source_shape_invalid",
            "message": "shape invalid",
            "details": {
                "path": "analysis/script.py",
                "size": 131073,
                "lineCount": 1,
                "maxLineLength": 131072,
                "source": "SECRET_SOURCE",
            },
        }

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert raised.value.code == "report_python_source_shape_invalid"
    assert raised.value.message == "shape invalid"
    assert raised.value.details == {
        "path": "analysis/script.py",
        "size": 131073,
        "lineCount": 1,
        "maxLineLength": 131072,
    }


@pytest.mark.anyio
async def test_generate_preserves_reporting_error_code_and_message_after_tool_throw():
    async def action(agent):
        return await agent.tools[0].entrypoint(source=SOURCE)

    async def patch(**_kwargs):
        raise ReportingError(
            "report_python_source_shape_invalid",
            "脚本必须以 LF 换行结尾。",
            details={"path": "analysis/script.py", "source": "SECRET_SOURCE"},
        )

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert raised.value.code == "report_python_source_shape_invalid"
    assert raised.value.message == "脚本必须以 LF 换行结尾。"
    assert raised.value.details == {"path": "analysis/script.py"}
    assert "SECRET_SOURCE" not in str(raised.value)


@pytest.mark.anyio
async def test_generate_does_not_misclassify_swallowed_patch_error_as_no_patch():
    async def action(agent):
        try:
            await agent.tools[0].entrypoint(source=SOURCE)
        except ReportingError:
            # Agno's Function layer can turn tool exceptions into a tool receipt.
            return None
        return None

    async def patch(**_kwargs):
        raise ReportingError(
            "report_python_source_shape_invalid",
            "脚本必须以 LF 换行结尾。",
            details={"path": "analysis/script.py"},
        )

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert raised.value.code == "report_python_source_shape_invalid"
    assert raised.value.message == "脚本必须以 LF 换行结尾。"


@pytest.mark.anyio
async def test_generate_builds_update_diff_from_complete_source():
    prompts: list[dict[str, object]] = []
    patches: list[str] = []

    async def action(agent):
        prompts.append(json.loads(agent.prompt))
        return await agent.tools[0].entrypoint(source=UPDATED_SOURCE)

    async def patch(*, patch: str):
        patches.append(patch)
        return {"ok": True, "artifacts": [identity("analysis/script.py", "print(2)\n")]}

    await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
        "analysis/script.py",
        {},
        patch,
        _operation="update",
        _previous_source=SOURCE,
    )

    protocol = prompts[0]["sourceProtocol"]
    assert protocol["path"] == "analysis/script.py"
    assert protocol["minPhysicalLines"] == 2
    assert protocol["lineEnding"] == "LF"
    assert protocol["trailingNewline"] is True
    assert patches == [
        (
            "--- a/analysis/script.py\n"
            "+++ b/analysis/script.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-value = 1\n"
            "-print(value)\n"
            "+value = 2\n"
            "+print(value)\n"
        )
    ]


@pytest.mark.anyio
async def test_generate_rejects_malformed_tool_arguments_without_mutation():
    mutated = False

    async def action(agent):
        await agent.tools[0].entrypoint()  # truncated custom input has no source

    async def patch(**_kwargs):
        nonlocal mutated
        mutated = True
        return {"ok": True, "artifacts": [identity("analysis/script.py", "print(1)\n")]}

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert raised.value.code == "report_python_source_shape_invalid"
    assert mutated is False
    assert raised.value.details == {
        "path": "analysis/script.py",
        "size": 0,
        "lineCount": 0,
        "maxLineLength": 0,
    }


@pytest.mark.anyio
async def test_generate_reports_bounded_python_syntax_location_without_source():
    invalid_source = (
        "total_current = 10\n"
        "total_prior = 8\n"
        "total_delta = total_current - prior_total_base := total_prior\n"
    )
    mutated = False

    async def action(agent):
        return await agent.tools[0].entrypoint(source=invalid_source)

    async def patch(**_kwargs):
        nonlocal mutated
        mutated = True
        return {"ok": True, "artifacts": []}

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert raised.value.code == "report_python_source_shape_invalid"
    assert raised.value.message == (
        "签发 Python 源码存在 Python 3.12 语法错误，已拒绝写入：invalid syntax。"
    )
    assert raised.value.details == {
        "path": "analysis/script.py",
        "size": len(invalid_source.encode()),
        "lineCount": 3,
        "maxLineLength": max(len(line.encode()) for line in invalid_source.splitlines()),
        "line": 3,
        "offset": 48,
    }
    assert raised.value.__suppress_context__ is True
    assert invalid_source.splitlines()[2] not in str(raised.value)
    assert invalid_source.splitlines()[2] not in str(raised.value.details)
    assert mutated is False
