import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
import requests
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse
from agno.session.summary import SessionSummary
from agno.tools import Function
from agno.tools.function import FunctionCall
from loguru import logger

import smart_reporting.context_management as context_management_module
from smart_reporting.context_management import (
    CODING_CHECKPOINT_MAX_BYTES,
    CODING_TOOL_BATCH_LIMIT,
    COMPRESSIBLE_HISTORY_TOOLS,
    SKILL_PRUNE_MIN_CHARS,
    TIKTOKEN_DOWNLOAD_TIMEOUT,
    TIKTOKEN_O200K_CACHE_KEY,
    CodingContextHardLimitError,
    CodingContextProjector,
    ContextBudgetController,
    ProjectedOpenAIChat,
    ProtectedCompressionManager,
    RollingSessionSummaryManager,
    RollingSummaryResponse,
    ToolCompressionResponse,
    _parse_rolling_summary,
    clear_terminal_reasoning,
    clear_terminal_session_reasoning,
    projected_coding_model,
    validate_configured_tiktoken_cache,
)


def test_coding_process_outputs_are_compressible_history():
    assert {"exec_command", "poll_process", "write_stdin", "stop_process"}.issubset(
        COMPRESSIBLE_HISTORY_TOOLS
    )


def test_projected_coding_model_enables_parallel_calls_without_mutating_base_model():
    base = OpenAIChat(
        id="coding-model",
        request_params={"temperature": 0},
        extra_body={"enable_thinking": True},
    )

    projected = projected_coding_model(base)

    assert projected is not base
    assert projected.id == base.id
    assert projected.extra_body == base.extra_body
    assert projected.request_params == {
        "temperature": 0,
        "parallel_tool_calls": True,
    }
    assert base.request_params == {"temperature": 0}
    assert projected.get_request_params()["parallel_tool_calls"] is True


def test_projected_coding_model_使用Reporting输入预算作为投影hard_cap(monkeypatch):
    base = OpenAIChat(id="budgeted-model")
    projected = projected_coding_model(base, input_token_budget=1234)
    observed = {}

    def project(messages, **kwargs):
        observed["hard_cap"] = kwargs["hard_cap"]
        return messages

    monkeypatch.setattr(context_management_module.CodingContextProjector, "project", project)
    projected._project([Message(role="user", content="继续")], (), {})

    assert observed["hard_cap"] == 1234


class CountingModel:
    id = "test-model"
    supports_native_structured_outputs = False
    supports_json_schema_outputs = False

    def count_tokens(self, messages, tools=None, output_schema=None):
        return sum(len(str(message.content)) for message in messages)


class SummaryModel(CountingModel):
    supports_native_structured_outputs = True

    def __init__(self, parsed=None, content=None, error=None):
        self.parsed = parsed
        self.content = content
        self.error = error
        self.requests = []

    def response(self, messages, response_format=None, **kwargs):
        self.requests.append(messages)
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.content, parsed=self.parsed)

    async def aresponse(self, messages, response_format=None, **kwargs):
        return self.response(messages, response_format=response_format, **kwargs)


class BrokenCountingModel(CountingModel):
    def count_tokens(self, messages, tools=None, output_schema=None):
        raise RuntimeError("tokenizer unavailable")


def run(*messages, run_id="run-1"):
    return SimpleNamespace(
        run_id=run_id,
        messages=list(messages),
        status="completed",
    )


def test_protected_compression_only_selects_historical_analysis_results():
    manager = ProtectedCompressionManager(model=CountingModel(), compress_tool_results_limit=1)
    historical_analysis = Message(
        role="tool",
        tool_name="report_analyze_dataset",
        content='{"ok":true,"sha256":"abc"}',
    )
    historical_analysis.from_history = True
    current_analysis = Message(
        role="tool",
        tool_name="report_analyze_dataset",
        content='{"ok":true,"sha256":"current"}',
    )
    odoo_result = Message(role="tool", tool_name="odoo.open_record", content='{"token":"secret"}')
    odoo_result.from_history = True
    process_result = Message(
        role="tool",
        tool_name="sandbox_process_poll",
        content='{"status":"completed","exitCode":0,"output":"large"}',
    )
    process_result.from_history = True

    assert manager.should_compress([historical_analysis]) is True
    assert manager.should_compress([current_analysis]) is False
    assert manager.should_compress([odoo_result]) is False
    assert manager.should_compress([process_result]) is True


def test_compression_tokenizer_failure_does_not_fail_main_run():
    manager = ProtectedCompressionManager(model=CountingModel(), compress_token_limit=1)
    analysis = Message(role="tool", tool_name="sandbox_exec", content="large output")
    analysis.from_history = True

    assert manager.should_compress([analysis], model=BrokenCountingModel()) is False


def test_coding_context_controller_keeps_below_budget_history_uncompressed():
    controller = ContextBudgetController(model=CountingModel(), context_token_budget=200_000)
    old = Message(
        role="tool",
        tool_name="terminal",
        tool_args={"command": "pytest"},
        content=json.dumps({"status": "completed", "outputHandle": "opaque", "output": "x" * 1000}),
    )
    recent = Message(role="tool", tool_name="read_file", content='{"content":"latest"}')
    messages = [
        Message(role="assistant", content="first"),
        old,
        Message(role="assistant", content="second"),
        recent,
        Message(role="assistant", content="third"),
    ]

    prepared = controller.prepare_context(messages)

    assert old.compressed_content is None
    assert prepared[1].compressed_content is None
    assert prepared[3].compressed_content is None
    assert controller.context_token_limit == 200_000
    assert controller.input_token_budget == 200_000 - 32 * 1024


def test_reporting_context_controller按模型窗口保留最大输出预算():
    controller = ContextBudgetController(
        model=CountingModel(),
        context_token_budget=1_048_576,
        output_token_reserve=393_216,
    )

    assert controller.context_token_limit == 1_048_576
    assert controller.output_token_reserve == 393_216
    assert controller.input_token_budget == 655_360


def test_context_budget_check_logs_safe_timing_without_message_content():
    controller = ContextBudgetController(
        model=CountingModel(),
        context_token_budget=200_000,
    )
    sensitive_prompt = "private-report-prompt"
    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO", format="{message}")

    try:
        should_compress = controller.should_compress(
            [Message(role="user", content=sensitive_prompt)],
            tools=[{"type": "function", "function": {"name": "safe_tool"}}],
        )
    finally:
        logger.remove(sink_id)

    log_text = "".join(records)
    assert should_compress is False
    assert "context_budget_check_started" in log_text
    assert "context_budget_check_completed" in log_text
    assert "message_count=1" in log_text
    assert "tool_count=1" in log_text
    assert sensitive_prompt not in log_text


def test_configured_tiktoken_cache_downloads_missing_o200k_file(monkeypatch, tmp_path):
    cache_path = tmp_path / TIKTOKEN_O200K_CACHE_KEY
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    valid_content = b"synthetic-o200k-cache"
    monkeypatch.setattr(
        context_management_module,
        "TIKTOKEN_O200K_SHA256",
        hashlib.sha256(valid_content).hexdigest(),
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, *, chunk_size: int):
            assert chunk_size == 64 * 1024
            yield valid_content[:5]
            yield valid_content[5:]

    def download(url: str, **kwargs):
        assert url == context_management_module.TIKTOKEN_O200K_URL
        assert kwargs == {"timeout": TIKTOKEN_DOWNLOAD_TIMEOUT, "stream": True}
        return Response()

    monkeypatch.setattr(context_management_module.requests, "get", download)
    validate_configured_tiktoken_cache()
    assert cache_path.read_bytes() == valid_content
    assert not any(path.name.endswith(".tmp") for path in tmp_path.iterdir())


def test_configured_tiktoken_cache_rejects_failed_download(monkeypatch, tmp_path):
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))

    def fail_download(_url: str, **kwargs):
        assert kwargs["timeout"] == TIKTOKEN_DOWNLOAD_TIMEOUT
        raise requests.Timeout("network unavailable")

    monkeypatch.setattr(context_management_module.requests, "get", fail_download)
    with pytest.raises(RuntimeError, match="无法下载 o200k_base"):
        validate_configured_tiktoken_cache()


def test_configured_tiktoken_cache_removes_partial_read_after_timeout(monkeypatch, tmp_path):
    cache_path = tmp_path / TIKTOKEN_O200K_CACHE_KEY
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, *, chunk_size: int):
            yield b"partial"
            raise requests.ReadTimeout(f"read timeout after {chunk_size} bytes")

    monkeypatch.setattr(
        context_management_module.requests,
        "get",
        lambda *_args, **_kwargs: Response(),
    )

    with pytest.raises(RuntimeError, match="无法下载 o200k_base"):
        validate_configured_tiktoken_cache()
    assert not cache_path.exists()
    assert not any(path.name.endswith(".tmp") for path in tmp_path.iterdir())


def test_configured_tiktoken_cache_requires_valid_o200k_file(monkeypatch, tmp_path):
    cache_path = tmp_path / TIKTOKEN_O200K_CACHE_KEY
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))

    cache_path.write_bytes(b"invalid")
    with pytest.raises(RuntimeError, match="缓存校验失败"):
        validate_configured_tiktoken_cache()

    valid_content = b"synthetic-o200k-cache"
    cache_path.write_bytes(valid_content)
    monkeypatch.setattr(
        context_management_module,
        "TIKTOKEN_O200K_SHA256",
        hashlib.sha256(valid_content).hexdigest(),
    )
    monkeypatch.setattr(
        context_management_module.requests,
        "get",
        lambda *_args, **_kwargs: pytest.fail("有效缓存不应触发下载"),
    )
    validate_configured_tiktoken_cache()


def test_context_projection_logs_safe_token_count_fallback() -> None:
    class FailingTokenModel:
        id = "intranet-tokenizer"

        @staticmethod
        def count_tokens(_messages, _tools=None, _response_format=None):
            raise ConnectionError("private-tokenizer-url")

    sensitive_prompt = "private-projection-prompt"
    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO", format="{message}")

    try:
        projected = CodingContextProjector.project(
            [Message(role="user", content=sensitive_prompt)],
            model=FailingTokenModel(),
        )
    finally:
        logger.remove(sink_id)

    log_text = "".join(records)
    assert len(projected) == 1
    assert "context_projection_token_count_failed" in log_text
    assert "model_id=intranet-tokenizer" in log_text
    assert "error_type=ConnectionError" in log_text
    assert sensitive_prompt not in log_text
    assert "private-tokenizer-url" not in log_text


def test_coding_context_projection_keeps_append_only_provider_prefix_stable():
    create_args = json.dumps({"path": "report.md", "content": "x" * 2000})
    messages = [
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-create",
                    "type": "function",
                    "function": {"name": "create_file", "arguments": create_args},
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="create_file",
            tool_call_id="call-create",
            content='{"ok":true}',
        ),
        Message(role="assistant", content="继续检查"),
    ]

    first = CodingContextProjector.project(messages)
    second = CodingContextProjector.project(
        [*messages, Message(role="assistant", content="准备下一步")]
    )

    def provider_value(message):
        return (
            message.role,
            message.get_content(use_compressed_content=True),
            message.tool_call_id,
            message.tool_calls,
        )

    assert [provider_value(message) for message in first] == [
        provider_value(message) for message in second[: len(first)]
    ]

    messages[1].compressed_content = ContextBudgetController._coding_receipt(messages[1])
    rebased_first = CodingContextProjector.project(messages)
    rebased_second = CodingContextProjector.project(
        [*messages, Message(role="assistant", content="压缩后继续")]
    )

    assert [provider_value(message) for message in rebased_first] == [
        provider_value(message) for message in rebased_second[: len(rebased_first)]
    ]


def test_coding_context_controller_defers_skill_pruning_until_budget_rebase():
    body = "x" * (SKILL_PRUNE_MIN_CHARS + 1)
    old = skill_result(body)
    messages = [old, *[Message(role="assistant", content=str(i)) for i in range(10)]]
    controller = ContextBudgetController(model=CountingModel(), context_token_budget=200_000)

    stable = controller.prepare_context(messages)

    assert stable[0].compressed_content is None
    assert old.compressed_content is None

    rebased = CodingContextProjector.project(messages, model=CountingModel(), hard_cap=2_000)

    checkpoint = next(
        json.loads(message.content)
        for message in rebased
        if isinstance(message.content, str) and "CODING_CHECKPOINT" in message.content
    )
    assert checkpoint["skillReceipts"][0]["path"] == "SKILL.md"
    assert old.compressed_content is None


def test_coding_context_controller_emits_structured_checkpoint_when_over_budget():
    messages = [
        Message(role="assistant", content="first"),
        Message(role="tool", tool_name="terminal", content='{"output":"large"}'),
        Message(
            role="tool",
            tool_name="patch",
            content='{"mutation_sequence":3,"files":[{"path":"app.py"}]}',
        ),
        Message(
            role="tool",
            tool_name="process",
            content='{"processes":[{"execution_id":"serve","status":"running"}]}',
        ),
        skill_result("rules", path="guide.md", tool_name="get_skill_reference"),
        Message(role="assistant", content="second"),
        Message(role="assistant", content="third"),
        Message(role="assistant", content="padding " + "x" * 2_000),
    ]

    prepared = CodingContextProjector.project(messages, model=CountingModel(), hard_cap=1_500)

    checkpoint = next(
        json.loads(message.content)
        for message in prepared
        if isinstance(message.content, str) and "CODING_CHECKPOINT" in message.content
    )
    assert checkpoint["marker"] == "CODING_CHECKPOINT"
    assert checkpoint["version"] == 2
    assert checkpoint["changedFiles"] == [{"path": "app.py"}]
    assert checkpoint["mutation"] == 3
    assert checkpoint["activeProcesses"] == [{"executionId": "serve", "status": "running"}]
    assert checkpoint["skillReceipts"][0]["path"] == "guide.md"
    assert "toolReceipts" not in checkpoint


def test_coding_context_controller_uses_fallback_count_when_tokenizer_fails():
    controller = ContextBudgetController(model=BrokenCountingModel(), context_token_budget=32_769)
    messages = [
        Message(role="assistant", content="old " + "x" * 1_000),
        Message(role="assistant", content="second"),
        Message(role="assistant", content="third"),
    ]

    assert controller.should_compress(messages) is True

    prepared = CodingContextProjector.project(messages, model=BrokenCountingModel(), hard_cap=400)

    assert any(
        json.loads(message.content).get("marker") == "CODING_CHECKPOINT"
        for message in prepared
        if isinstance(message.content, str) and message.content.startswith("{")
    )
    assert messages[0].compressed_content is None


def _tool_round(index: int, content: str = "result") -> list[Message]:
    call_id = f"call-{index}"
    return [
        Message(
            role="assistant",
            content=f"round {index}",
            tool_calls=[
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({"path": f"file-{index}.txt"}),
                    },
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="read_file",
            tool_call_id=call_id,
            content=content,
        ),
    ]


def test_coding_context_projector_rebases_1000_rounds_without_mutating_canonical_history():
    messages = [Message(role="system", content="system"), Message(role="user", content="goal")]
    for index in range(1_000):
        messages.extend(_tool_round(index, "x" * 100))
    canonical = [message.model_dump() for message in messages]

    projected = CodingContextProjector.project(messages, model=CountingModel(), hard_cap=64 * 1024)

    assert [message.model_dump() for message in messages] == canonical
    assert CountingModel().count_tokens(projected) <= 64 * 1024
    assert CodingContextProjector.last_metrics["canonical_message_count"] == len(messages)
    assert CodingContextProjector.last_metrics["window_rebased"] is True
    assert CodingContextProjector.last_metrics["dropped_complete_rounds"] > 0
    checkpoint_message = next(
        message
        for message in projected
        if isinstance(message.content, str)
        and '"version":2' in message.content
        and "CODING_CHECKPOINT" in message.content
    )
    checkpoint = json.loads(checkpoint_message.content)
    assert len(checkpoint_message.content.encode()) <= CODING_CHECKPOINT_MAX_BYTES
    assert "toolReceipts" not in checkpoint
    assistant_call_ids = {
        call["id"]
        for message in projected
        for call in (message.tool_calls or [])
        if message.role in {"assistant", "model"}
    }
    assert all(
        message.tool_call_id in assistant_call_ids
        for message in projected
        if message.role == "tool"
    )


def test_coding_context_projector_counts_tool_schema_and_rejects_irreducible_prefix():
    class SchemaCountingModel(CountingModel):
        def count_tokens(self, messages, tools=None, output_schema=None):
            return super().count_tokens(messages) + len(json.dumps(tools or []))

    messages = [Message(role="system", content="required"), Message(role="user", content="goal")]

    with pytest.raises(CodingContextHardLimitError) as rejected:
        CodingContextProjector.project(
            messages,
            model=SchemaCountingModel(),
            tools=[{"name": "large", "description": "x" * 1_000}],
            hard_cap=100,
        )

    assert rejected.value.code == "coding_context_hard_limit_exceeded"


def test_coding_checkpoint_v2_reads_v1_state_and_stays_bounded():
    v1 = {
        "marker": "CODING_CHECKPOINT",
        "plan": {"step": "latest"},
        "changedFiles": ["legacy.py"],
        "mutation": 7,
        "verification": {"executionId": "verify-7", "exitCode": 0},
        "activeProcesses": [{"executionId": "serve", "status": "running"}],
        "skillReceipts": [],
        "toolReceipts": [{"tool": "terminal"}],
    }
    messages = [
        Message(role="system", content="system"),
        Message(role="user", content=json.dumps(v1)),
        Message(role="assistant", content="x" * 4_000),
    ]

    projected = CodingContextProjector.project(messages, model=CountingModel(), hard_cap=2_000)
    checkpoint_message = next(
        message
        for message in projected
        if isinstance(message.content, str)
        and '"version":2' in message.content
        and "CODING_CHECKPOINT" in message.content
    )
    checkpoint = json.loads(checkpoint_message.content)

    assert checkpoint["version"] == 2
    assert checkpoint["mutation"] == 7
    assert checkpoint["changedFiles"] == [{"path": "legacy.py"}]
    assert "toolReceipts" not in checkpoint
    assert len(checkpoint_message.content.encode()) <= CODING_CHECKPOINT_MAX_BYTES


def test_runtime_feedback_replaces_older_failure_with_latest_success_state():
    messages = [
        Message(
            role="tool",
            tool_name="verify",
            content=json.dumps(
                {
                    "mutation_sequence": 3,
                    "exit_code": 1,
                    "error": {
                        "code": "verification_failed",
                        "requiredActions": ["fix"],
                    },
                }
            ),
        ),
        Message(
            role="tool",
            tool_name="verify",
            content=json.dumps({"mutation_sequence": 3, "exit_code": 0}),
        ),
    ]

    projected = CodingContextProjector.project(messages, model=CountingModel())
    feedback = json.loads(projected[-1].content)

    assert feedback["marker"] == "CODING_RUNTIME_FEEDBACK"
    assert feedback["code"] == "coding_finish_required"


def test_runtime_feedback_keeps_incomplete_plan_in_working_state_after_verification():
    messages = [
        Message(
            role="tool",
            tool_name="update_plan",
            content=json.dumps(
                {
                    "ok": True,
                    "plan": [
                        {"step": "生成报告", "status": "completed"},
                        {"step": "生成清单", "status": "in_progress"},
                    ],
                }
            ),
        ),
        Message(
            role="tool",
            tool_name="verify",
            content=json.dumps({"mutation_sequence": 3, "exit_code": 0}),
        ),
    ]

    projected = CodingContextProjector.project(messages, model=CountingModel())
    feedback = json.loads(projected[-1].content)

    assert feedback["marker"] == "CODING_RUNTIME_FEEDBACK"
    assert feedback["code"] == "coding_runtime_action_required"
    assert feedback["pendingSteps"] == ["生成清单"]
    assert feedback["requiredActions"] == [
        "继续完成 pendingSteps；全部完成后在最后一次 mutation 上重新验证并调用 finish_task。"
    ]


def _function_call(name, entrypoint, index, arguments=None):
    return FunctionCall(
        function=Function(name=name, entrypoint=entrypoint),
        arguments=arguments or {},
        call_id=f"call-{index}",
    )


@pytest.mark.anyio
async def test_projected_model_runs_ten_safe_reads_in_parallel_and_keeps_result_order():
    model = ProjectedOpenAIChat(id="test")
    assert CODING_TOOL_BATCH_LIMIT == 10
    entered = 0
    all_entered = asyncio.Event()
    release = asyncio.Event()

    async def read_file(path):
        nonlocal entered
        entered += 1
        if entered == CODING_TOOL_BATCH_LIMIT:
            all_entered.set()
        await release.wait()
        return path

    calls = [
        _function_call("read_file", read_file, index, {"path": str(index)})
        for index in range(CODING_TOOL_BATCH_LIMIT)
    ]
    results = []

    async def run_batch():
        async for _event in model.arun_function_calls(calls, results):
            pass

    task = asyncio.create_task(run_batch())
    await asyncio.wait_for(all_entered.wait(), timeout=1)
    release.set()
    await asyncio.wait_for(task, timeout=1)

    assert [message.tool_call_id for message in results] == [
        f"call-{index}" for index in range(CODING_TOOL_BATCH_LIMIT)
    ]


@pytest.mark.anyio
async def test_projected_model_writes_request_and_batch_metrics_inside_model_stream(
    monkeypatch,
):
    stream_active = False
    captured = []

    async def model_stream(_self, _messages, *_args, **_kwargs):
        nonlocal stream_active
        stream_active = True
        _self.get_request_params()
        yield ModelResponse(
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    function=SimpleNamespace(name="read_file", arguments='{"path":"a"}'),
                ),
                SimpleNamespace(
                    index=1,
                    function=SimpleNamespace(name="apply_patch", arguments="{}"),
                ),
            ]
        )
        stream_active = False

    def capture(attributes):
        assert stream_active is True
        captured.append(attributes)

    monkeypatch.setattr(OpenAIChat, "ainvoke_stream", model_stream)
    monkeypatch.setattr(context_management_module, "_set_current_span_attributes", capture)
    model = ProjectedOpenAIChat(id="test")

    async for _response in model.ainvoke_stream(
        [Message(role="system", content="system"), Message(role="user", content="goal")],
        Message(role="assistant"),
    ):
        pass

    assert len(captured) == 2
    assert captured[0]["canonical_message_count"] == 2
    assert captured[0]["projected_message_count"] == 2
    assert captured[1]["tool_batch_size"] == 2
    assert captured[1]["tool_batch_admission"] == "serialized"
    assert captured[1]["tool_batch_rejection_code"] == ""


@pytest.mark.anyio
async def test_projected_model_logs_safe_provider_timing_and_host(monkeypatch):
    async def model_stream(_self, _messages, *_args, **_kwargs):
        yield ModelResponse(content="private-model-output")

    monkeypatch.setattr(OpenAIChat, "ainvoke_stream", model_stream)
    model = ProjectedOpenAIChat(
        id="intranet-model",
        base_url="http://internal-user:internal-password@vllm.internal:8000/v1",
        api_key="private-api-key",
    )
    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO", format="{message}")

    try:
        responses = [
            response
            async for response in model.ainvoke_stream(
                [Message(role="user", content="private-model-input")]
            )
        ]
    finally:
        logger.remove(sink_id)

    log_text = "".join(records)
    assert len(responses) == 1
    assert "model_projection_completed" in log_text
    assert "model_provider_first_chunk" in log_text
    assert "model_provider_stream_completed" in log_text
    assert "host=vllm.internal:8000" in log_text
    assert "private-model-input" not in log_text
    assert "private-model-output" not in log_text
    assert "internal-user" not in log_text
    assert "internal-password" not in log_text
    assert "private-api-key" not in log_text


@pytest.mark.anyio
async def test_projected_model_writes_metrics_inside_non_stream_model_call(monkeypatch):
    call_active = False
    captured = []

    async def model_call(self, _messages, *_args, **_kwargs):
        nonlocal call_active
        call_active = True
        self.get_request_params()
        call_active = False
        return ModelResponse(content="done")

    def capture(attributes):
        assert call_active is True
        captured.append(attributes)

    monkeypatch.setattr(OpenAIChat, "ainvoke", model_call)
    monkeypatch.setattr(context_management_module, "_set_current_span_attributes", capture)
    model = ProjectedOpenAIChat(id="test")

    await model.ainvoke(
        [Message(role="system", content="system"), Message(role="user", content="goal")],
        Message(role="assistant"),
    )

    assert len(captured) == 1
    assert captured[0]["canonical_message_count"] == 2
    assert captured[0]["projected_message_count"] == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "names",
    [
        ["read_file"] * 11,
        ["read_file", "apply_patch"],
        ["verify", "finish_task"],
    ],
)
async def test_projected_model_serializes_unsafe_or_oversized_tool_batches(names, monkeypatch):
    model = ProjectedOpenAIChat(id="test")
    entrypoint_calls = []

    async def entrypoint(index):
        entrypoint_calls.append(index)
        return index

    calls = [
        _function_call(name, entrypoint, index, {"index": index})
        for index, name in enumerate(names)
    ]
    results = []

    async for _event in model.arun_function_calls(calls, results):
        pass

    assert entrypoint_calls == list(range(len(names)))
    assert len(results) == len(calls)
    assert [message.tool_call_id for message in results] == [
        f"call-{index}" for index in range(len(names))
    ]


@pytest.mark.anyio
async def test_projected_model混合批次按原顺序执行且不返回重试错误():
    model = ProjectedOpenAIChat(id="test")
    executed = []

    async def entrypoint(**arguments):
        executed.append(arguments)
        return arguments

    calls = [
        _function_call(
            "terminal",
            entrypoint,
            0,
            {"command": "python3 -m pytest -q", "timeout": 120},
        ),
        _function_call("update_plan", entrypoint, 1, {"plan": []}),
    ]
    results = []

    async for _event in model.arun_function_calls(calls, results):
        pass

    assert executed == [
        {"command": "python3 -m pytest -q", "timeout": 120},
        {"plan": []},
    ]
    assert all("coding_tool_batch_rejected" not in str(message.content) for message in results)


@pytest.mark.anyio
async def test_projected_model_allows_one_exclusive_tool_call():
    model = ProjectedOpenAIChat(id="test")
    calls = 0

    async def apply_patch():
        nonlocal calls
        calls += 1
        return "done"

    results = []
    async for _event in model.arun_function_calls(
        [_function_call("apply_patch", apply_patch, 1)], results
    ):
        pass

    assert calls == 1
    assert len(results) == 1


def test_coding_context_projector_compacts_consumed_tool_pair_without_mutating_raw():
    large_content = "x" * 5000
    create_args = json.dumps({"path": "report.md", "content": large_content})
    latest_args = json.dumps({"command": "python verify.py"})
    messages = [
        Message(
            role="assistant",
            content="create",
            tool_calls=[
                {
                    "id": "call-create",
                    "type": "function",
                    "function": {"name": "create_file", "arguments": create_args},
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="create_file",
            tool_call_id="call-create",
            tool_args={"path": "report.md", "content": large_content},
            content=json.dumps(
                {
                    "ok": True,
                    "files": [{"path": "report.md", "sha256": "a" * 64}],
                    "mutation_sequence": 1,
                }
            ),
        ),
        Message(
            role="assistant",
            content="verify",
            tool_calls=[
                {
                    "id": "call-latest",
                    "type": "function",
                    "function": {"name": "terminal", "arguments": latest_args},
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="terminal",
            tool_call_id="call-latest",
            tool_args={"command": "python verify.py"},
            content=json.dumps({"status": "completed", "output": "ok"}),
        ),
        Message(role="assistant", content="continue"),
    ]
    receipt = ContextBudgetController._coding_receipt(messages[1])
    messages[1].compressed_content = receipt

    projected = CodingContextProjector.project(messages)

    assert messages[0].tool_calls[0]["function"]["arguments"] == create_args
    assert messages[1].compressed_content == receipt
    compact_args = json.loads(projected[0].tool_calls[0]["function"]["arguments"])
    assert compact_args["path"] == "report.md"
    assert "CONTEXT_PRUNED" in compact_args["content"]
    assert large_content not in projected[0].tool_calls[0]["function"]["arguments"]
    assert json.loads(projected[1].compressed_content)["marker"] == "CODING_TOOL_RECEIPT"
    assert projected[0].tool_calls[0]["id"] == projected[1].tool_call_id == "call-create"
    assert projected[2].tool_calls[0]["function"]["arguments"] == latest_args
    assert projected[3].compressed_content is None


def test_coding_context_projector_compacts_create_files_content_without_mutating_raw():
    large_content = "x" * 5000
    arguments = json.dumps(
        {
            "files": [
                {"path": "a.py", "content": large_content},
                {"path": "b.py", "content": "small"},
            ]
        }
    )

    compacted = CodingContextProjector._compact_arguments("create_files", arguments)

    payload = json.loads(compacted)
    assert json.loads(arguments)["files"][0]["content"] == large_content
    assert "CONTEXT_PRUNED" in payload["files"][0]["content"]
    assert "reload=read_file(path='a.py')" in payload["files"][0]["content"]
    assert payload["files"][1]["content"] == "small"


def test_coding_context_projector_keeps_recent_read_facts_after_another_tool_call():
    facts = '{"path":"summary.json","content":"AUTHORITATIVE_FACTS"}'
    messages = [
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-read",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"summary.json"}',
                    },
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="read_file",
            tool_call_id="call-read",
            content=facts,
        ),
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-tree",
                    "type": "function",
                    "function": {"name": "tree", "arguments": '{"path":""}'},
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="tree",
            tool_call_id="call-tree",
            content='{"files":["summary.json"]}',
        ),
    ]

    projected = CodingContextProjector.project(messages)

    assert projected[1].content == facts
    assert projected[1].compressed_content is None
    assert projected[3].compressed_content is None
    assert messages[1].content == facts
    assert messages[1].compressed_content is None


def test_coding_context_projector_keeps_uncompressed_latest_mutation_arguments():
    first_content = "first" * 1000
    latest_content = "latest" * 1000
    first_args = json.dumps({"path": "analysis.py", "content": first_content})
    latest_args = json.dumps(
        {
            "path": "analysis.py",
            "content": latest_content,
            "expected_sha256": "a" * 64,
        }
    )
    messages = [
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-create",
                    "type": "function",
                    "function": {"name": "create_file", "arguments": first_args},
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="create_file",
            tool_call_id="call-create",
            content='{"ok":true}',
        ),
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-overwrite",
                    "type": "function",
                    "function": {"name": "overwrite_file", "arguments": latest_args},
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="overwrite_file",
            tool_call_id="call-overwrite",
            content='{"ok":true}',
        ),
        Message(role="assistant", content="continue"),
    ]
    messages[1].compressed_content = ContextBudgetController._coding_receipt(messages[1])

    projected = CodingContextProjector.project(messages)

    assert "CONTEXT_PRUNED" in projected[0].tool_calls[0]["function"]["arguments"]
    assert projected[2].tool_calls[0]["function"]["arguments"] == latest_args
    assert messages[0].tool_calls[0]["function"]["arguments"] == first_args
    assert messages[2].tool_calls[0]["function"]["arguments"] == latest_args


def test_coding_tool_receipt_preserves_bounded_continuation_state():
    message = Message(
        role="tool",
        tool_name="overwrite_file",
        tool_args={"path": "analysis.py", "content": "x" * 5000},
        content=json.dumps(
            {
                "ok": True,
                "execution_id": "execution-1",
                "mutation_sequence": 7,
                "files": [
                    {
                        "operation": "update",
                        "path": "analysis.py",
                        "size": 5000,
                        "sha256": "b" * 64,
                    }
                ],
            }
        ),
    )

    receipt = json.loads(ContextBudgetController._coding_receipt(message))

    assert receipt["state"] == {
        "execution_id": "execution-1",
        "mutation_sequence": 7,
        "files": [
            {
                "operation": "update",
                "path": "analysis.py",
                "size": 5000,
                "sha256": "b" * 64,
            }
        ],
    }
    assert receipt["arguments"] == {
        "keys": ["content", "path"],
        "sha256": hashlib.sha256(
            json.dumps(
                {"content": "x" * 5000, "path": "analysis.py"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }


def skill_result(
    body: str,
    *,
    tool_name: str = "get_skill_instructions",
    path: str | None = None,
    execute: bool = False,
) -> Message:
    args = {"skill_name": "review"}
    payload = {"skill_name": "review"}
    if tool_name == "get_skill_instructions":
        payload["instructions"] = body
    elif tool_name == "get_skill_reference":
        args["reference_path"] = path
        payload.update(reference_path=path, content=body)
    else:
        args.update(script_path=path, execute=execute)
        payload.update(script_path=path, content=body)
    message = Message(
        role="tool",
        tool_name=tool_name,
        tool_args=args,
        content=json.dumps(payload),
    )
    return message


def test_skill_compression_prunes_only_old_large_content_and_preserves_raw_result():
    manager = ProtectedCompressionManager(model=CountingModel(), compress_tool_results_limit=100)
    boundary = skill_result("x" * SKILL_PRUNE_MIN_CHARS)
    old = skill_result(
        "y" * (SKILL_PRUNE_MIN_CHARS + 1),
        tool_name="get_skill_reference",
        path="guide.md",
    )
    messages = [boundary, old, *[Message(role="assistant", content=str(i)) for i in range(10)]]
    original = old.content

    assert manager.should_compress(messages) is True
    manager.compress(messages)

    assert boundary.compressed_content is None
    assert old.content == original
    marker = json.loads(old.compressed_content)
    assert marker == {
        "chars": SKILL_PRUNE_MIN_CHARS + 1,
        "marker": "SKILL_PRUNED",
        "path": "guide.md",
        "reload": {"reference_path": "guide.md", "skill_name": "review"},
        "sha256": hashlib.sha256(("y" * 5001).encode()).hexdigest(),
        "skill": "review",
        "tool": "get_skill_reference",
    }


def test_skill_compression_prunes_duplicate_but_keeps_latest_and_exempts_executed_script():
    manager = ProtectedCompressionManager(model=CountingModel(), compress_tool_results_limit=100)
    first = skill_result("first")
    latest = skill_result("latest")
    executed = skill_result(
        "script output",
        tool_name="get_skill_script",
        path="check.py",
        execute=True,
    )
    messages = [first, Message(role="assistant", content="continue"), latest, executed]

    manager.compress(messages)

    assert json.loads(first.compressed_content)["marker"] == "SKILL_PRUNED"
    assert latest.compressed_content is None
    assert executed.compressed_content is None


@pytest.mark.anyio
async def test_compression_preserves_coding_process_continuation_metadata():
    manager = ProtectedCompressionManager(
        model=SummaryModel(parsed=ToolCompressionResponse(summary="服务仍在运行")),
        compress_tool_results_limit=1,
    )
    process_result = Message(
        role="tool",
        tool_name="exec_command",
        content=json.dumps(
            {
                "status": "running",
                "session_id": 7,
                "timeout_seconds": 3600,
                "outcome": "running",
                "output": "x" * 3000,
            }
        ),
    )

    candidate = await manager.compress_history_message(process_result)

    assert candidate.compressed_content is not None
    compressed = json.loads(candidate.compressed_content)
    assert compressed["exact"]["$.session_id"] == 7
    assert compressed["exact"]["$.timeout_seconds"] == 3600
    assert compressed["exact"]["$.outcome"] == "running"
    assert "xxx" not in candidate.compressed_content


@pytest.mark.anyio
async def test_rolling_summary_uses_previous_summary_and_only_new_messages():
    response = RollingSummaryResponse(
        goal="生成员工报表",
        decisions=["输出 PDF"],
        artifacts=["报表/员工.md"],
        completed=["完成数据分析"],
        pending=["渲染 PDF"],
    )
    model = SummaryModel(parsed=response)
    manager = RollingSessionSummaryManager(model=model)
    first = run(
        Message(role="user", content="旧请求"),
        Message(role="assistant", content="旧回答"),
        run_id="run-1",
    )
    second = run(
        Message(role="user", content="继续生成 PDF"),
        Message(role="tool", tool_name="odoo.open_record", content='{"snapshotId":"secret"}'),
        Message(role="assistant", content='旧绑定 token="secret-token"'),
        Message(role="assistant", content="已准备 Markdown"),
        run_id="run-2",
    )
    session = SimpleNamespace(
        runs=[first, second],
        summary=SessionSummary(summary='{"goal":"旧目标"}'),
        session_data={
            "agentos_rolling_summary": {
                "version": 1,
                "lastSourceRunId": "run-1",
                "sourceDigest": manager.source_digest([first]),
            }
        },
    )

    result = await manager.acreate_session_summary(session)

    assert result is session.summary
    assert "JSON" in str(model.requests[0][0].content)
    request = str(model.requests[0][-1].content)
    assert "旧目标" in request
    assert "继续生成 PDF" in request
    assert "已准备 Markdown" in request
    assert "旧请求" not in request
    assert "snapshotId" not in request
    assert "secret-token" not in request
    metadata = session.session_data["agentos_rolling_summary"]
    assert metadata["version"] == 2
    assert metadata["lastSourceRunId"] == "run-2"


def test_rolling_summary_accepts_structured_dict():
    response = SimpleNamespace(
        parsed={
            "goal": "生成员工报表",
            "decisions": ["输出 PDF"],
            "artifacts": [],
            "completed": [],
            "pending": [],
        },
        content=None,
    )

    result = _parse_rolling_summary(response)

    assert result is not None
    assert result.goal == "生成员工报表"


def test_rolling_summary_accepts_complete_json_fence():
    content = """```json
{"goal":"生成员工报表","decisions":[],"artifacts":[],"completed":[],"pending":[]}
```"""

    result = _parse_rolling_summary(SimpleNamespace(parsed=None, content=content))

    assert result is not None
    assert result.goal == "生成员工报表"


@pytest.mark.parametrize(
    "content",
    [
        '摘要如下：{"goal":"目标"}',
        '{"goal":"目标","unexpected":true}',
    ],
)
def test_rolling_summary_rejects_prose_and_unknown_fields(content):
    response = SimpleNamespace(parsed=None, content=content)

    assert _parse_rolling_summary(response) is None


@pytest.mark.anyio
async def test_rolling_summary_rebuilds_after_history_replacement():
    response = RollingSummaryResponse(
        goal="重建目标",
        decisions=[],
        artifacts=[],
        completed=[],
        pending=[],
    )
    model = SummaryModel(parsed=response)
    manager = RollingSessionSummaryManager(model=model)
    first = run(Message(role="user", content="被替换的新内容"), run_id="run-1")
    session = SimpleNamespace(
        runs=[first],
        summary=SessionSummary(summary='{"goal":"失效摘要"}'),
        session_data={
            "agentos_rolling_summary": {
                "version": 4,
                "lastSourceRunId": "run-1",
                "sourceDigest": "stale-digest",
            }
        },
    )

    await manager.acreate_session_summary(session)

    request = str(model.requests[0][-1].content)
    assert "失效摘要" not in request
    assert "被替换的新内容" in request
    assert session.session_data["agentos_rolling_summary"]["version"] == 1


@pytest.mark.anyio
async def test_rolling_summary_failure_keeps_previous_version():
    model = SummaryModel(error=RuntimeError("provider unavailable"))
    manager = RollingSessionSummaryManager(model=model)
    first = run(Message(role="user", content="旧请求"), run_id="run-1")
    second = run(Message(role="user", content="新请求"), run_id="run-2")
    previous = SessionSummary(summary='{"goal":"保留目标"}')
    metadata = {
        "version": 2,
        "lastSourceRunId": "run-1",
        "sourceDigest": manager.source_digest([first]),
    }
    session = SimpleNamespace(
        runs=[first, second],
        summary=previous,
        session_data={"agentos_rolling_summary": metadata.copy()},
    )

    result = await manager.acreate_session_summary(session)

    assert result is previous
    assert session.summary is previous
    assert session.session_data["agentos_rolling_summary"] == metadata


def test_terminal_reasoning_is_removed_before_persistence():
    message = Message(
        role="assistant",
        content="最终答复",
        reasoning_content="raw reasoning",
        redacted_reasoning_content="encrypted reasoning",
        provider_data={"reasoning_content": "provider reasoning", "request_id": "req-1"},
    )
    output = SimpleNamespace(
        reasoning_content="run reasoning",
        reasoning_messages=[message],
        reasoning_steps=[{"reasoning": "step reasoning"}],
        model_provider_data={"thinking": "provider thinking", "request_id": "req-1"},
        messages=[message],
    )

    clear_terminal_reasoning(output)

    assert output.reasoning_content is None
    assert output.reasoning_messages is None
    assert output.reasoning_steps is None
    assert output.model_provider_data == {"request_id": "req-1"}
    assert message.reasoning_content is None
    assert message.redacted_reasoning_content is None
    assert message.provider_data == {"request_id": "req-1"}


def test_session_persistence_clears_terminal_but_keeps_paused_reasoning():
    completed = SimpleNamespace(status="completed", reasoning_content="terminal", messages=[])
    paused = SimpleNamespace(status="paused", reasoning_content="resume state", messages=[])
    session = SimpleNamespace(runs=[completed, paused])

    clear_terminal_session_reasoning(session)

    assert completed.reasoning_content is None
    assert paused.reasoning_content == "resume state"
