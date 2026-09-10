from __future__ import annotations

import hashlib
import json

import pytest
from loguru import logger

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
        "syntaxRequirements": [
            "提交前确保完整源码可通过 ast.parse 和 compile",
            "使用普通赋值和显式 if；不得使用 := 赋值表达式或 if False/if True 死代码分支",
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
async def test_repair_preserves_bounded_execution_failure_details():
    script = identity("analysis/script.py", "print(1)\n")
    patch_prompts: list[dict[str, object]] = []

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
                "output": "failure-output-" * 500,
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
    assert len(diagnostic["details"]["output"]) == 2000
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
async def test_repair_reads_once_then_uses_fresh_patch_agent():
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
    assert seen_tools == ["read_file", "submit_python_source"]
    assert agents[0] is not agents[1]


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
            {"code": "report_analysis_script_failed"},
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
        '"diagnosticCode":"report_analysis_script_failed"}'
    ]


@pytest.mark.anyio
async def test_repair_rejects_reading_a_path_other_than_issued_script():
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        return await agent.tools[0].entrypoint(path="analysis/other.py")

    async def read_file(**_kwargs):
        pytest.fail("wrong read path must not reach callback")

    async def patch(**_kwargs):
        pytest.fail("wrong read path must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_invalid"
    assert raised.value.details == {"path": script.path}


@pytest.mark.anyio
async def test_repair_rejects_a_second_read_before_write_stage():
    script = identity("analysis/script.py", "print(1)\n")
    reads = 0

    async def action(agent):
        await agent.tools[0].entrypoint(path=script.path)
        await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        nonlocal reads
        reads += 1
        return read_receipt(script)

    async def patch(**_kwargs):
        pytest.fail("second read must not reach write stage")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_invalid"
    assert reads == 1


@pytest.mark.anyio
@pytest.mark.parametrize("output", [None, "print('direct source')"])
async def test_repair_rejects_read_stage_without_a_read_tool_call(output):
    script = identity("analysis/script.py", "print(1)\n")

    async def action(_agent):
        return output

    async def read_file(**_kwargs):
        pytest.fail("zero read tool calls must not reach callback")

    async def patch(**_kwargs):
        pytest.fail("zero read tool calls must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_invalid"
    assert raised.value.details == {"path": script.path}


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
    assert [agent.tools[0].name for agent in agents] == ["read_file", "submit_python_source"]


@pytest.mark.anyio
async def test_repair_malformed_read_call_fails_before_a_fresh_retry_succeeds():
    script = identity("analysis/script.py", "print(1)\n")
    patch_calls = 0

    async def malformed(agent):
        await agent.tools[0].entrypoint()

    async def read(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def write(agent):
        return await agent.tools[0].entrypoint(source=UPDATED_SOURCE)

    actions = iter([malformed, read, write])
    runner = ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(next(actions)))

    async def read_file(**_kwargs):
        return read_receipt(script)

    async def patch(**_kwargs):
        nonlocal patch_calls
        patch_calls += 1
        return {"ok": True, "artifacts": [identity(script.path, "print(2)\n")]}

    with pytest.raises(ReportingError) as raised:
        await runner.repair(script, {}, read_file, patch)

    assert raised.value.code == "report_code_generation_read_invalid"
    assert patch_calls == 0

    result = await runner.repair(script, {}, read_file, patch)

    assert result.script_file.path == script.path
    assert patch_calls == 1


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
    assert len(prompts) == 1


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
        task_facts={"missingFacts": missing_facts, "pythonSource": "SECRET_SOURCE"},
    )

    facts = prompts[0]["facts"]
    assert set(facts) == {"readReceipt", "diagnostic", "taskFacts"}
    assert facts["taskFacts"].keys() == {"missingFacts"}
    assert len(facts["taskFacts"]["missingFacts"]) == 20
    assert all(len(item) == 512 for item in facts["taskFacts"]["missingFacts"])
    assert facts["taskFacts"]["missingFacts"][0].startswith("fact-0:")
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
