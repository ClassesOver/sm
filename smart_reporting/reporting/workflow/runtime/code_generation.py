"""受控 Reporting Coding Agent 的脚本签发与两阶段修复协议。"""

from __future__ import annotations

import copy
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from agno.agent import Agent
from agno.run import RunContext
from agno.tools.function import Function

from ...models import ReportingError
from ..checkpoint import FileIdentity

ToolCallable = Callable[..., Awaitable[Mapping[str, Any]] | Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class CodeGenerationResult:
    script_file: FileIdentity


def _tool_parameters(name: str) -> dict[str, Any]:
    if name == "read_file":
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": {"patch": {"type": "string", "minLength": 1}},
        "required": ["patch"],
        "additionalProperties": False,
    }


async def _invoke(callback: ToolCallable, arguments: dict[str, Any], run_context: RunContext | None) -> Mapping[str, Any]:
    if run_context is not None:
        try:
            signature = inspect.signature(callback)
            if "run_context" in signature.parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            ):
                arguments = {**arguments, "run_context": run_context}
        except (TypeError, ValueError):
            pass
    result = callback(**arguments)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, Mapping):
        raise ReportingError("report_code_generation_tool_invalid", "Coding 工具回执不是对象。")
    return result


class ReportingCodeGenerationRunner:
    """每次阶段调用都创建独立上下文，并以唯一 patch 工具回执收口。"""

    def __init__(
        self,
        *,
        agent: Agent | Callable[[], Agent] | None = None,
        agent_factory: Callable[[], Agent] | None = None,
    ):
        if agent is None and agent_factory is None:
            raise TypeError("ReportingCodeGenerationRunner requires agent or agent_factory")
        self._agent_source = agent_factory if agent_factory is not None else agent

    def _fresh_agent(self) -> Agent:
        if callable(self._agent_source) and not isinstance(self._agent_source, Agent):
            return self._agent_source()
        return copy.copy(self._agent_source)

    @staticmethod
    def _configure(agent: Agent, function: Function, tool_choice: str) -> None:
        agent.tools = [function]
        agent.tool_choice = {"type": "function", "function": {"name": tool_choice}}
        agent.tool_call_limit = 1
        agent.add_history_to_context = False
        agent.num_history_runs = 0
        agent.store_history_messages = False
        agent.session_state = {}
        agent.session_id = None

    @staticmethod
    def _prompt(payload: Mapping[str, Any]) -> str:
        return json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _validate_script_path(path: str) -> None:
        candidate = PurePosixPath(path) if isinstance(path, str) else PurePosixPath("")
        if (
            not isinstance(path, str)
            or not path
            or "\\" in path
            or candidate.is_absolute()
            or ".." in candidate.parts
            or candidate.suffix != ".py"
        ):
            raise ReportingError("report_code_generation_path_invalid", "脚本路径不是安全的工作区相对 Python 文件。")

    async def generate(
        self,
        script_path: str,
        task_facts: Mapping[str, Any],
        apply_analysis_patch: ToolCallable,
        run_context: RunContext | None = None,
    ) -> CodeGenerationResult:
        """运行一次写阶段；普通输出和零/多次工具调用均失败。"""
        self._validate_script_path(script_path)
        result: CodeGenerationResult | None = None

        async def capture_patch(**kwargs: Any) -> Mapping[str, Any]:
            nonlocal result
            try:
                receipt = await _invoke(
                    apply_analysis_patch, {"patch": kwargs.get("patch", "")}, run_context
                )
            except ReportingError as error:
                # 上游工具 details 可能包含参数；Coding 边界只透出稳定码和短路径。
                raise ReportingError(
                    error.code,
                    "脚本 patch 未被接受。",
                    details={"path": script_path},
                ) from error
            if receipt.get("ok") is not True:
                raise ReportingError(str(receipt.get("code", "report_code_generation_patch_failed")), "脚本 patch 未被接受。")
            artifacts = receipt.get("artifacts")
            if not isinstance(artifacts, list) or len(artifacts) != 1:
                raise ReportingError("report_code_generation_artifact_invalid", "脚本 patch 必须返回唯一文件身份。")
            try:
                identity = FileIdentity.model_validate(artifacts[0])
            except Exception as error:
                raise ReportingError("report_code_generation_artifact_invalid", "脚本 patch 文件身份无效。") from error
            if identity.path != script_path:
                raise ReportingError("report_code_generation_path_mismatch", "脚本写入回执路径与签发路径不一致。")
            result = CodeGenerationResult(identity)
            return receipt

        calls = 0
        async def wrapped_patch(**kwargs: Any) -> Mapping[str, Any]:
            nonlocal calls
            calls += 1
            if calls > 1:
                raise ReportingError("report_code_generation_multiple_patches", "单轮 Coding Agent 只能提交一次 patch。")
            return await capture_patch(**kwargs)

        agent = self._fresh_agent()
        self._configure(agent, Function(name="apply_analysis_patch", description="提交 unified diff。", parameters=_tool_parameters("apply_analysis_patch"), strict=True, entrypoint=wrapped_patch, stop_after_tool_call=True), "apply_analysis_patch")
        try:
            await agent.arun(self._prompt({"scriptPath": script_path, "facts": dict(task_facts)}), run_context=run_context)
        except ReportingError:
            raise
        except Exception as error:
            raise ReportingError("report_code_generation_agent_failed", "Coding Agent 调用失败。") from error
        if result is None:
            raise ReportingError("report_code_generation_no_patch", "Coding Agent 未提交脚本 patch。")
        return result

    async def repair(
        self,
        script_file: FileIdentity,
        diagnostic: Mapping[str, Any],
        read_file: ToolCallable,
        apply_analysis_patch: ToolCallable,
        run_context: RunContext | None = None,
    ) -> CodeGenerationResult:
        """先只读一次受信脚本回执，再用 fresh Agent 提交一次修复 patch。"""
        self._validate_script_path(script_file.path)
        reads = 0
        read_receipt: Mapping[str, Any] | None = None

        async def read_tool(*, path: str, **_kwargs: Any) -> Mapping[str, Any]:
            nonlocal reads, read_receipt
            reads += 1
            if reads > 1 or path != script_file.path:
                raise ReportingError("report_code_generation_read_invalid", "修复阶段只能读取签发脚本一次。")
            receipt = await _invoke(read_file, {"path": path}, run_context)
            content = receipt.get("content")
            if receipt.get("ok", True) is False or not isinstance(content, str):
                raise ReportingError("report_code_generation_read_invalid", "脚本读取回执无效。")
            if receipt.get("path") != script_file.path or receipt.get("sha256") != script_file.sha256:
                raise ReportingError("report_code_generation_read_invalid", "脚本读取回执身份不匹配。")
            if receipt.get("offset", 0) != 0 or receipt.get("nextOffset") != receipt.get("totalBytes"):
                raise ReportingError("report_code_generation_read_incomplete", "脚本读取回执分页不完整。")
            read_receipt = receipt
            return receipt

        reader = self._fresh_agent()
        self._configure(reader, Function(name="read_file", description="读取签发脚本。", parameters=_tool_parameters("read_file"), strict=True, entrypoint=read_tool, stop_after_tool_call=True), "read_file")
        try:
            await reader.arun(self._prompt({"scriptPath": script_file.path, "task": "读取脚本并返回受信回执"}), run_context=run_context)
        except ReportingError:
            raise
        except Exception as error:
            raise ReportingError("report_code_generation_read_invalid", "修复读取阶段失败。") from error
        if reads != 1 or read_receipt is None:
            raise ReportingError("report_code_generation_read_invalid", "修复读取阶段未读取签发脚本。")
        return await self.generate(
            script_file.path,
            {"readReceipt": dict(read_receipt), "diagnostic": dict(diagnostic)},
            apply_analysis_patch,
            run_context,
        )
