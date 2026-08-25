import asyncio
import hashlib
import json
import os
import re
from collections.abc import AsyncIterator, Iterator
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, ClassVar
from urllib.parse import urlparse

import tiktoken
from agno.compression.manager import CompressionManager
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.session.summary import SessionSummary, SessionSummaryManager
from agno.session.team import TeamSession
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError

SKILL_CONTENT_WINDOW = 10
SKILL_PRUNE_MIN_CHARS = 5000
SKILL_TOOL_NAMES = frozenset({"get_skill_instructions", "get_skill_reference", "get_skill_script"})
# 这是所有 Coding 上下文的绝对顶线，具体 Agent 仍取自身配置与该值的较小者。
# Reporting 模型已明确支持 1M 上下文；继续固定 256K 会在模型调用前错误拒绝合法的
# Profile 定点分析与逐章成稿上下文，而普通 Coding Agent 的 262K 配置不会因此扩大。
CODING_CONTEXT_TOKEN_LIMIT = 1024 * 1024
CODING_OUTPUT_TOKEN_RESERVE = 32 * 1024
CODING_RECENT_ASSISTANT_TURNS = 2
CODING_CHECKPOINT_MAX_BYTES = 32 * 1024
CODING_CONTEXT_REBASE_THRESHOLD = 0.75
CODING_CONTEXT_REBASE_TARGET = 0.50
CODING_TOOL_BATCH_LIMIT = 10
TIKTOKEN_O200K_CACHE_KEY = "fb374d419588a4632f3f557e76b4b70aebbca790"
TIKTOKEN_O200K_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
_PROJECTED_INPUT_TOKEN_BUDGET_ATTR = "_coding_input_token_budget"
CODING_TOOL_NAMES = frozenset(
    {
        "terminal",
        "process",
        "patch",
        "create_file",
        "create_files",
        "overwrite_file",
        "replace_text",
        "apply_patch",
        "verify",
        "finish_task",
        "update_plan",
        "list_files",
        "read_file",
        "read_lines",
        "search_text",
        "tree",
        "git_status",
        "git_diff",
        "read_tool_output",
        "view_image",
    }
)
SUMMARY_METADATA_KEY = "agentos_rolling_summary"
COMPRESSIBLE_HISTORY_TOOLS = frozenset(
    {
        "sandbox_exec",
        "sandbox_process_poll",
        "exec_command",
        "poll_process",
        "write_stdin",
        "stop_process",
        "report_analyze_dataset",
    }
)
_ADDITIONAL_CONTEXT = re.compile(
    r"\n*<additional context>.*?</additional context>\s*",
    re.DOTALL | re.IGNORECASE,
)
_SENSITIVE_HISTORY = re.compile(
    r"(?:authorization\s+token)|授权\s*token|[\"']?token[\"']?\s*[:=]",
    re.IGNORECASE,
)
_EXACT_METADATA_KEYS = frozenset(
    {
        "ok",
        "status",
        "exitCode",
        "exit_code",
        "outcome",
        "imageCount",
        "jobId",
        "path",
        "paths",
        "markdownPath",
        "output_path",
        "pageCount",
        "pdfPath",
        "job_id",
        "roundCount",
        "sessionId",
        "session_id",
        "commandId",
        "sha256",
        "size",
        "successfulRoundCount",
        "timedOut",
        "timeout_seconds",
        "truncated",
    }
)
_FORBIDDEN_SUMMARY_CONTENT = re.compile(
    r"(?:authorization\s+token)|授权\s*token|"
    r"[\"']?token[\"']?\s*[:=]",
    re.IGNORECASE,
)


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


def validate_configured_tiktoken_cache() -> None:
    cache_dir = str(os.environ.get("TIKTOKEN_CACHE_DIR") or "").strip()
    if not cache_dir:
        return
    cache_path = Path(cache_dir) / TIKTOKEN_O200K_CACHE_KEY
    if not cache_path.is_file():
        # 在启动期完成官方编码下载，避免把公网等待推迟到首个模型请求。内网部署仍可
        # 预置同一文件；已有缓存不会发起网络请求，下载失败则保持失败关闭。
        logger.info("tiktoken_cache_download_started encoding=o200k_base")
        try:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            tiktoken.get_encoding("o200k_base")
        except Exception as exc:
            logger.error(
                "tiktoken_cache_download_failed encoding=o200k_base error_type={}",
                type(exc).__name__,
            )
            raise RuntimeError(
                "TIKTOKEN_CACHE_DIR 无法下载 o200k_base 缓存，请检查网络和目录写权限。"
            ) from exc
        if not cache_path.is_file():
            raise RuntimeError("o200k_base 下载完成但 TIKTOKEN_CACHE_DIR 中未生成缓存文件。")
        logger.info("tiktoken_cache_download_completed encoding=o200k_base")
    digest = hashlib.sha256(cache_path.read_bytes()).hexdigest()
    if digest != TIKTOKEN_O200K_SHA256:
        raise RuntimeError("TIKTOKEN_CACHE_DIR 的 o200k_base 离线缓存校验失败。")


def _model_log_fields(model: Any) -> tuple[str, str]:
    model_id = str(getattr(model, "id", None) or "-")
    base_url = getattr(model, "base_url", None)
    if not isinstance(base_url, str):
        return model_id, "-"
    parsed_url = urlparse(base_url)
    host = parsed_url.hostname or "-"
    try:
        port = parsed_url.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"
    return model_id, host


def _tool_count(args: tuple[Any, ...], kwargs: dict[str, Any]) -> int:
    tools = kwargs.get("tools", args[2] if len(args) > 2 else None)
    return len(tools) if isinstance(tools, (list, tuple)) else 0


def _skill_resource(message: Message) -> tuple[tuple[str, str, str], str, dict[str, Any]] | None:
    if message.role != "tool" or message.tool_name not in SKILL_TOOL_NAMES:
        return None
    args = dict(message.tool_args) if isinstance(message.tool_args, dict) else {}
    if message.tool_name == "get_skill_script" and args.get("execute") is True:
        return None
    try:
        payload = (
            json.loads(message.content) if isinstance(message.content, str) else message.content
        )
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or "error" in payload:
        return None
    skill_name = payload.get("skill_name") or args.get("skill_name")
    if not isinstance(skill_name, str) or not skill_name:
        return None
    path: Any
    body: Any
    if message.tool_name == "get_skill_instructions":
        path = "SKILL.md"
        body = payload.get("instructions")
        reload_args = {**args, "skill_name": skill_name}
    elif message.tool_name == "get_skill_reference":
        path = payload.get("reference_path") or args.get("reference_path")
        body = payload.get("content")
        reload_args = {**args, "skill_name": skill_name, "reference_path": path}
    else:
        path = payload.get("script_path") or args.get("script_path")
        body = payload.get("content")
        reload_args = {
            **args,
            "skill_name": skill_name,
            "script_path": path,
            "execute": False,
        }
    if not isinstance(path, str) or not path or not isinstance(body, str):
        return None
    return (message.tool_name, skill_name, path), body, reload_args


def _skill_pruned_content(message: Message, body: str, reload_args: dict[str, Any]) -> str:
    return json.dumps(
        {
            "marker": "SKILL_PRUNED",
            "tool": message.tool_name,
            "skill": reload_args["skill_name"],
            "path": next(
                (
                    reload_args[key]
                    for key in ("reference_path", "script_path")
                    if key in reload_args
                ),
                "SKILL.md",
            ),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "chars": len(body),
            "reload": reload_args,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class ToolCompressionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=4000)
    key_findings: list[str] = Field(default_factory=list, max_length=8)


class RollingSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(default="", max_length=2000)
    decisions: list[str] = Field(default_factory=list, max_length=20)
    artifacts: list[str] = Field(default_factory=list, max_length=50)
    completed: list[str] = Field(default_factory=list, max_length=30)
    pending: list[str] = Field(default_factory=list, max_length=30)


def _message_text(message: Message) -> str:
    content = message.get_content(use_compressed_content=True)
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def _strip_stale_context(content: str) -> str:
    return _ADDITIONAL_CONTEXT.sub("", content).strip()


def _status_value(run: Any) -> str:
    status = getattr(run, "status", None)
    return str(getattr(status, "value", status) or "").lower()


def _fallback_token_count(value: str) -> int:
    return max(1, (len(value.encode("utf-8")) + 1) // 2)


def _fallback_context_token_count(
    messages: list[Message], tools: Any = None, response_format: Any = None
) -> int:
    parts: list[str] = []
    for message in messages:
        parts.extend(
            (
                str(message.role or ""),
                str(message.compressed_content or message.content or ""),
                str(message.tool_name or ""),
                json.dumps(message.tool_calls or [], ensure_ascii=False, default=str),
                json.dumps(message.tool_args or {}, ensure_ascii=False, default=str),
            )
        )
    if tools is not None:
        parts.append(json.dumps(tools, ensure_ascii=False, default=str))
    if response_format is not None:
        parts.append(json.dumps(response_format, ensure_ascii=False, default=str))
    return _fallback_token_count("\n".join(parts))


def _session_history_runs(session: Any) -> list[Any]:
    runs = list(getattr(session, "runs", None) or [])
    if isinstance(session, TeamSession):
        return [run for run in runs if getattr(run, "parent_run_id", None) is None]
    return runs


def _exact_metadata(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (TypeError, ValueError):
            return {}
    exact: dict[str, Any] = {}

    def collect(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                child = value[key]
                child_path = f"{path}.{key}"
                if key in _EXACT_METADATA_KEYS:
                    if isinstance(child, (str, int, float, bool, type(None))):
                        exact[child_path] = child
                    elif isinstance(child, list) and all(
                        isinstance(item, (str, int, float, bool, type(None))) for item in child
                    ):
                        exact[child_path] = child
                collect(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                collect(child, f"{path}[{index}]")

    collect(content, "$")
    return exact


def _compression_messages(tool_result: Message) -> list[Message]:
    return [
        Message(
            role="system",
            content=(
                "压缩分析工具输出。只总结关键发现，不推导权限状态或敏感标识符；"
                "不要在摘要中复制令牌、快照或 modifiers。必须只返回符合指定 schema 的 JSON 对象。"
            ),
        ),
        Message(role="user", content=_message_text(tool_result)),
    ]


def _parse_compression_response(response: Any) -> ToolCompressionResponse | None:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, ToolCompressionResponse):
        return parsed
    content = getattr(response, "content", None)
    if not isinstance(content, str):
        return None
    try:
        return ToolCompressionResponse.model_validate_json(content)
    except ValidationError:
        return None


def _compressed_content(tool_result: Message, payload: ToolCompressionResponse) -> str:
    payload_json = payload.model_dump_json(exclude_none=True)
    if _FORBIDDEN_SUMMARY_CONTENT.search(payload_json):
        return ""
    return json.dumps(
        {
            "tool": tool_result.tool_name,
            "exact": _exact_metadata(tool_result.content),
            "summary": payload.summary,
            "keyFindings": payload.key_findings,
            "authoritative": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class ProtectedCompressionManager(CompressionManager):
    @staticmethod
    def _compress_skill_results(messages: list[Message]) -> bool:
        resources: list[tuple[int, Message, tuple[str, str, str], str, dict[str, Any]]] = []
        for index, message in enumerate(messages):
            parsed = _skill_resource(message)
            if parsed is not None and message.compressed_content is None:
                key, body, reload_args = parsed
                resources.append((index, message, key, body, reload_args))
        latest = {key: index for index, _message, key, _body, _args in resources}
        window_start = max(0, len(messages) - SKILL_CONTENT_WINDOW)
        changed = False
        for index, message, key, body, reload_args in resources:
            duplicate = latest[key] != index
            expired = index < window_start and len(body) > SKILL_PRUNE_MIN_CHARS
            if duplicate or expired:
                message.compressed_content = _skill_pruned_content(message, body, reload_args)
                changed = True
        return changed

    @staticmethod
    def _has_skill_compression_candidate(messages: list[Message]) -> bool:
        parsed = [(index, _skill_resource(message)) for index, message in enumerate(messages)]
        latest = {resource[0]: index for index, resource in parsed if resource is not None}
        window_start = max(0, len(messages) - SKILL_CONTENT_WINDOW)
        return any(
            resource is not None
            and messages[index].compressed_content is None
            and (
                latest[resource[0]] != index
                or (index < window_start and len(resource[1]) > SKILL_PRUNE_MIN_CHARS)
            )
            for index, resource in parsed
        )

    def _eligible(self, message: Message) -> bool:
        return bool(
            message.role == "tool"
            and message.from_history
            and message.tool_name in COMPRESSIBLE_HISTORY_TOOLS
            and message.compressed_content is None
        )

    def should_compress(self, messages, tools=None, model=None, response_format=None):
        if not self.compress_tool_results:
            return False
        if self._has_skill_compression_candidate(messages):
            return True
        eligible = [message for message in messages if self._eligible(message)]
        if not eligible:
            return False
        if self.compress_token_limit is not None and model is not None:
            try:
                if (
                    model.count_tokens(messages, tools, response_format)
                    >= self.compress_token_limit
                ):
                    return True
            except Exception:
                # 分词器失败不能中断主 run；压缩只是历史上下文优化。
                pass
        return bool(
            self.compress_tool_results_limit is not None
            and len(eligible) >= self.compress_tool_results_limit
        )

    async def ashould_compress(self, messages, tools=None, model=None, response_format=None):
        return self.should_compress(messages, tools, model, response_format)

    def _compress_tool_result(self, tool_result, run_metrics=None):
        if self.model is None:
            return None
        try:
            response = self.model.response(
                messages=_compression_messages(tool_result),
                response_format=ToolCompressionResponse,
            )
        except Exception:
            return None
        payload = _parse_compression_response(response)
        return _compressed_content(tool_result, payload) if payload is not None else None

    async def _acompress_tool_result(self, tool_result, run_metrics=None):
        if self.model is None:
            return None
        try:
            response = await self.model.aresponse(
                messages=_compression_messages(tool_result),
                response_format=ToolCompressionResponse,
            )
        except Exception:
            return None
        payload = _parse_compression_response(response)
        return _compressed_content(tool_result, payload) if payload is not None else None

    def compress(self, messages, run_metrics=None):
        self._compress_skill_results(messages)
        for message in messages:
            if not self._eligible(message):
                continue
            compressed = self._compress_tool_result(message, run_metrics=run_metrics)
            if compressed:
                message.compressed_content = compressed

    async def acompress(self, messages, run_metrics=None):
        self._compress_skill_results(messages)
        eligible = [message for message in messages if self._eligible(message)]
        compressed = await asyncio.gather(
            *(self._acompress_tool_result(message, run_metrics=run_metrics) for message in eligible)
        )
        for message, value in zip(eligible, compressed):
            if value:
                message.compressed_content = value

    async def compress_history_message(self, message: Message) -> Message:
        candidate = deepcopy(message)
        candidate.from_history = True
        if self._eligible(candidate):
            value = await self._acompress_tool_result(candidate)
            if value:
                candidate.compressed_content = value
        return candidate


class ContextBudgetController(ProtectedCompressionManager):
    def __init__(
        self,
        *,
        model: Any,
        context_token_budget: int,
        output_token_reserve: int = CODING_OUTPUT_TOKEN_RESERVE,
    ) -> None:
        self.context_token_limit = min(context_token_budget, CODING_CONTEXT_TOKEN_LIMIT)
        self.output_token_reserve = max(CODING_OUTPUT_TOKEN_RESERVE, output_token_reserve)
        self.input_token_budget = max(1, self.context_token_limit - self.output_token_reserve)
        # Agno 的 canonical history 仍由 Agent 保留；这里仅把同一输入预算传给模型投影层。
        # 之前投影层使用全局默认 hard cap，Reporting 的压缩预算因此没有真正生效。
        try:
            setattr(model, _PROJECTED_INPUT_TOKEN_BUDGET_ATTR, self.input_token_budget)
        except Exception:
            # 非 Agno 测试模型可能拒绝动态属性；压缩管理器本身仍可独立工作。
            pass
        super().__init__(
            model=model,
            compress_tool_results=True,
            compress_token_limit=self.input_token_budget,
        )

    @staticmethod
    def _protected_start(messages: list[Message]) -> int:
        assistant_indexes = [
            index
            for index, message in enumerate(messages)
            if message.role in {"assistant", "model"}
        ]
        if len(assistant_indexes) < CODING_RECENT_ASSISTANT_TURNS:
            return 0
        return assistant_indexes[-CODING_RECENT_ASSISTANT_TURNS]

    @classmethod
    def _protected_indexes(cls, messages: list[Message]) -> set[int]:
        protected_start = cls._protected_start(messages)
        protected = set(range(protected_start, len(messages)))
        for role in ("user",):
            latest = next(
                (
                    index
                    for index in range(len(messages) - 1, -1, -1)
                    if messages[index].role == role
                ),
                None,
            )
            if latest is not None:
                protected.add(latest)
        for tool_name in ("update_plan", "verify", "finish_task"):
            latest = next(
                (
                    index
                    for index in range(len(messages) - 1, -1, -1)
                    if messages[index].role == "tool" and messages[index].tool_name == tool_name
                ),
                None,
            )
            if latest is not None:
                protected.add(latest)
        for index in range(max(0, len(messages) - SKILL_CONTENT_WINDOW), len(messages)):
            if messages[index].tool_name in SKILL_TOOL_NAMES:
                protected.add(index)
        return protected

    @staticmethod
    def _coding_receipt(message: Message) -> str:
        content = str(message.content or "")
        args = dict(message.tool_args) if isinstance(message.tool_args, dict) else {}
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            payload = None
        status = None
        reload_args = None
        state: dict[str, Any] = {}
        if isinstance(payload, dict):
            status = payload.get("status") or payload.get("code") or payload.get("exitCode")
            handle = payload.get("outputHandle")
            if isinstance(handle, str) and handle:
                reload_args = {"handle": handle, "offset": 0, "max_bytes": 65536}
            for key in (
                "path",
                "sha256",
                "nextOffset",
                "totalBytes",
                "hasMore",
                "mutation_sequence",
                "mutationSequence",
                "execution_id",
                "exit_code",
            ):
                value = payload.get(key)
                if isinstance(value, str | int | bool):
                    state[key] = value
            files = payload.get("files")
            if isinstance(files, list):
                state["files"] = [
                    {
                        key: item[key]
                        for key in (
                            "operation",
                            "path",
                            "size",
                            "sha256",
                            "before_sha256",
                            "after_sha256",
                        )
                        if isinstance(item.get(key), str | int)
                    }
                    for item in files[:20]
                    if isinstance(item, dict)
                ]
        args_json = json.dumps(
            args, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        arguments: Any = (
            args
            if len(args_json.encode("utf-8")) <= 512
            else {
                "keys": sorted(args),
                "sha256": hashlib.sha256(args_json.encode("utf-8")).hexdigest(),
            }
        )
        return json.dumps(
            {
                "marker": "CODING_TOOL_RECEIPT",
                "tool": message.tool_name,
                "arguments": arguments,
                "status": status,
                "state": state or None,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "reload": reload_args,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _checkpoint(messages: list[Message]) -> str:
        mutations = []
        verifications = []
        changed_files: dict[str, dict[str, Any]] = {}
        active_processes: dict[str, dict[str, Any]] = {}
        skill_receipts: dict[tuple[str, str, str], dict[str, Any]] = {}
        plan = None
        completion = None
        validator = None
        for message in messages:
            checkpoint_payload = _checkpoint_payload(message)
            if checkpoint_payload is not None:
                plan = checkpoint_payload.get("plan", plan)
                completion = checkpoint_payload.get("completion", completion)
                validator = checkpoint_payload.get("validator", validator)
                mutation = checkpoint_payload.get("mutation")
                if isinstance(mutation, int):
                    mutations.append(mutation)
                for item in checkpoint_payload.get("changedFiles", []):
                    if isinstance(item, str):
                        changed_files[item] = {"path": item}
                    elif isinstance(item, dict) and isinstance(item.get("path"), str):
                        changed_files[item["path"]] = item
                if isinstance(checkpoint_payload.get("activeProcesses"), list):
                    for item in checkpoint_payload["activeProcesses"][:20]:
                        if isinstance(item, dict) and isinstance(item.get("executionId"), str):
                            active_processes[item["executionId"]] = item
                for item in checkpoint_payload.get("skillReceipts", []):
                    if not isinstance(item, dict):
                        continue
                    key = (
                        str(item.get("tool", "")),
                        str(item.get("skill", "")),
                        str(item.get("path", "")),
                    )
                    skill_receipts.pop(key, None)
                    skill_receipts[key] = item
            skill = _skill_resource(message)
            if skill is not None:
                key, body, reload_args = skill
                skill_receipts.pop(key, None)
                skill_receipts[key] = {
                    "tool": key[0],
                    "skill": key[1],
                    "path": key[2],
                    "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "reload": reload_args,
                }
            if message.role != "tool" or message.tool_name not in CODING_TOOL_NAMES:
                continue
            content = str(message.content or "")
            try:
                payload = json.loads(content)
            except (TypeError, ValueError):
                payload = None
            if isinstance(payload, dict):
                mutation = payload.get("mutation_sequence") or payload.get("mutationSequence")
                if mutation is not None:
                    mutations.append(mutation)
                if message.tool_name == "verify":
                    verifications.append(
                        {
                            "executionId": payload.get("execution_id"),
                            "status": payload.get("status"),
                            "exitCode": payload.get("exit_code"),
                        }
                    )
                    validator = payload.get("error") or payload
                if message.tool_name == "update_plan":
                    plan = payload
                if message.tool_name == "finish_task":
                    completion = payload.get("error") or payload
                for item in (
                    payload.get("files", []) if isinstance(payload.get("files"), list) else []
                ):
                    if isinstance(item, dict) and isinstance(item.get("path"), str):
                        changed_files[item["path"]] = {
                            key: item[key]
                            for key in ("path", "sha256", "before_sha256", "after_sha256")
                            if isinstance(item.get(key), str)
                        }
                if message.tool_name == "process" and isinstance(payload.get("processes"), list):
                    for item in payload["processes"]:
                        if not isinstance(item, dict) or not isinstance(
                            item.get("execution_id"), str
                        ):
                            continue
                        execution_id = item["execution_id"]
                        if item.get("status") in {
                            "completed",
                            "failed",
                            "terminated",
                            "lost",
                            "cancelled",
                        }:
                            active_processes.pop(execution_id, None)
                        else:
                            active_processes[execution_id] = {
                                "executionId": execution_id,
                                "status": item.get("status"),
                            }
                execution_id = payload.get("execution_id")
                if isinstance(execution_id, str):
                    if payload.get("status") in {
                        "completed",
                        "failed",
                        "terminated",
                        "lost",
                        "cancelled",
                    }:
                        active_processes.pop(execution_id, None)
                    elif payload.get("status") in {"running", "starting"}:
                        active_processes[execution_id] = {
                            "executionId": execution_id,
                            "status": payload.get("status"),
                        }
        payload = {
            "marker": "CODING_CHECKPOINT",
            "version": 2,
            "plan": plan,
            "changedFiles": list(changed_files.values())[-50:],
            "mutation": mutations[-1] if mutations else None,
            "verification": verifications[-1] if verifications else None,
            "validator": validator,
            "completion": completion,
            "activeProcesses": list(active_processes.values())[-20:],
            "skillReceipts": list(skill_receipts.values())[-10:],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(encoded.encode("utf-8")) <= CODING_CHECKPOINT_MAX_BYTES:
            return encoded
        payload["plan"] = _bounded_json_value(plan, 4096)
        payload["validator"] = _bounded_json_value(validator, 4096)
        payload["completion"] = _bounded_json_value(completion, 4096)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        for field in ("skillReceipts", "changedFiles", "activeProcesses"):
            values = payload[field]
            while values and len(encoded.encode("utf-8")) > CODING_CHECKPOINT_MAX_BYTES:
                values.pop(0)
                encoded = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
        return encoded

    def _coding_candidates(self, messages: list[Message]) -> list[Message]:
        protected = self._protected_indexes(messages)
        return [
            message
            for index, message in enumerate(messages)
            if index not in protected
            and message.role == "tool"
            and message.tool_name in CODING_TOOL_NAMES
            and message.tool_name not in SKILL_TOOL_NAMES
            and message.compressed_content is None
        ]

    def _effective_token_count(self, messages: list[Message]) -> int:
        if self.model is None:
            return _fallback_context_token_count(messages)
        effective = []
        for message in messages:
            candidate = deepcopy(message)
            if candidate.compressed_content is not None:
                candidate.content = candidate.compressed_content
            effective.append(candidate)
        try:
            return self.model.count_tokens(effective)
        except Exception:
            return _fallback_context_token_count(effective)

    def should_compress(self, messages, tools=None, model=None, response_format=None):
        counting_model = model or self.model
        model_id, _host = _model_log_fields(counting_model)
        started_at = perf_counter()
        tool_count = len(tools) if isinstance(tools, (list, tuple)) else 0
        logger.info(
            "context_budget_check_started model_id={} message_count={} tool_count={} "
            "input_token_budget={}",
            model_id,
            len(messages),
            tool_count,
            self.input_token_budget,
        )
        fallback = False
        try:
            token_count = (
                counting_model.count_tokens(messages, tools, response_format)
                if counting_model is not None
                else 0
            )
        except Exception as error:
            fallback = True
            logger.warning(
                "context_budget_token_count_failed model_id={} duration_ms={} error_type={}",
                model_id,
                _duration_ms(started_at),
                type(error).__name__,
            )
            token_count = _fallback_context_token_count(messages, tools, response_format)
        should_compress = token_count > self.input_token_budget
        logger.info(
            "context_budget_check_completed model_id={} duration_ms={} message_count={} "
            "tool_count={} input_tokens={} input_token_budget={} fallback={} "
            "should_compress={}",
            model_id,
            _duration_ms(started_at),
            len(messages),
            tool_count,
            token_count,
            self.input_token_budget,
            str(fallback).lower(),
            str(should_compress).lower(),
        )
        return should_compress

    async def ashould_compress(self, messages, tools=None, model=None, response_format=None):
        return self.should_compress(messages, tools, model, response_format)

    def compress(self, messages, run_metrics=None):
        # Canonical Agno messages must remain untouched. Projection happens in the model wrapper.
        return None

    async def acompress(self, messages, run_metrics=None):
        self.compress(messages, run_metrics=run_metrics)

    def prepare_context(self, messages: list[Message]) -> list[Message]:
        return CodingContextProjector.project(
            messages,
            model=self.model,
            hard_cap=self.input_token_budget,
        )

    async def compress_history_message(self, message: Message) -> Message:
        candidate = deepcopy(message)
        candidate.from_history = True
        if candidate.role == "tool" and candidate.tool_name in CODING_TOOL_NAMES:
            candidate.compressed_content = self._coding_receipt(candidate)
        return candidate


def _json_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _checkpoint_payload(message: Message) -> dict[str, Any] | None:
    for value in (message.compressed_content, message.content):
        payload = _json_payload(value)
        if payload is not None and payload.get("marker") == "CODING_CHECKPOINT":
            return payload
    return None


def _bounded_json_value(value: Any, max_bytes: int) -> Any:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) <= max_bytes:
        return value
    return {
        "truncated": True,
        "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "bytes": len(encoded.encode("utf-8")),
    }


class CodingContextHardLimitError(RuntimeError):
    code = "coding_context_hard_limit_exceeded"


class CodingContextProjector:
    _large_argument_fields = {
        "terminal": frozenset({"command"}),
        "verify": frozenset({"command"}),
        "finish_task": frozenset({"summary"}),
        "create_file": frozenset({"content"}),
        "overwrite_file": frozenset({"content"}),
        "replace_text": frozenset({"old_string", "new_string"}),
        "apply_patch": frozenset({"patch"}),
        "patch": frozenset({"content", "old_string", "new_string", "patch"}),
    }
    _min_argument_chars = 1024

    @classmethod
    def _compact_arguments(cls, tool_name: str, raw: Any) -> Any:
        if not isinstance(raw, str):
            return raw
        try:
            arguments = json.loads(raw)
        except (TypeError, ValueError):
            return raw
        if not isinstance(arguments, dict):
            return raw
        changed = False
        if tool_name == "create_files" and isinstance(arguments.get("files"), list):
            compacted_files = []
            for item in arguments["files"]:
                if not isinstance(item, dict):
                    compacted_files.append(item)
                    continue
                compacted = dict(item)
                content = compacted.get("content")
                if isinstance(content, str) and len(content) > cls._min_argument_chars:
                    path = compacted.get("path")
                    reload_suffix = (
                        f" reload=read_file(path={path!r})"
                        if isinstance(path, str) and path
                        else ""
                    )
                    compacted["content"] = (
                        "[CONTEXT_PRUNED"
                        f" chars={len(content)}"
                        f" sha256={hashlib.sha256(content.encode()).hexdigest()}"
                        f"{reload_suffix}]"
                    )
                    changed = True
                compacted_files.append(compacted)
            arguments["files"] = compacted_files
        for field_name in cls._large_argument_fields.get(tool_name, frozenset()):
            value = arguments.get(field_name)
            if not isinstance(value, str) or len(value) <= cls._min_argument_chars:
                continue
            reload_path = arguments.get("path")
            reload_suffix = (
                f" reload=read_file(path={reload_path!r})"
                if isinstance(reload_path, str) and reload_path
                else ""
            )
            arguments[field_name] = (
                "[CONTEXT_PRUNED"
                f" chars={len(value)}"
                f" sha256={hashlib.sha256(value.encode()).hexdigest()}"
                f"{reload_suffix}]"
            )
            changed = True
        return (
            json.dumps(arguments, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            if changed
            else raw
        )

    last_metrics: ClassVar[dict[str, int | bool]] = {}

    @staticmethod
    def _token_count(
        messages: list[Message], model: Any, tools: Any = None, response_format: Any = None
    ) -> int:
        started_at = perf_counter()
        try:
            return int(model.count_tokens(messages, tools, response_format))
        except Exception as error:
            model_id, _host = _model_log_fields(model)
            logger.warning(
                "context_projection_token_count_failed model_id={} duration_ms={} error_type={}",
                model_id,
                _duration_ms(started_at),
                type(error).__name__,
            )
            return _fallback_context_token_count(messages, tools, response_format)

    @staticmethod
    def _complete_rounds(messages: list[Message]) -> list[list[Message]]:
        rounds: list[list[Message]] = []
        index = 0
        while index < len(messages):
            assistant = messages[index]
            if assistant.role not in {"assistant", "model"}:
                index += 1
                continue
            if not assistant.tool_calls:
                rounds.append([assistant])
                index += 1
                continue
            call_ids = {
                call.get("id")
                for call in assistant.tool_calls
                if isinstance(call, dict) and isinstance(call.get("id"), str)
            }
            results: list[Message] = []
            cursor = index + 1
            while cursor < len(messages) and messages[cursor].role == "tool":
                if messages[cursor].tool_call_id in call_ids:
                    results.append(messages[cursor])
                cursor += 1
            result_ids = {message.tool_call_id for message in results}
            if call_ids and call_ids.issubset(result_ids):
                rounds.append([assistant, *results])
            index = cursor
        return rounds

    @staticmethod
    def _runtime_feedback(messages: list[Message]) -> Message | None:
        mutation: int | None = None
        verified_mutation: int | None = None
        failure: dict[str, Any] | None = None
        finish_accepted = False
        pending_steps: list[str] | None = None
        for message in messages:
            checkpoint = _checkpoint_payload(message)
            payload = checkpoint or (
                _json_payload(message.content) if message.role == "tool" else None
            )
            if payload is None:
                continue
            candidate = payload.get("mutation_sequence", payload.get("mutationSequence"))
            if candidate is None and checkpoint is not None:
                candidate = checkpoint.get("mutation")
            if isinstance(candidate, int):
                mutation = candidate
            tool_name = message.tool_name
            if tool_name == "update_plan" and payload.get("ok") is True:
                plan = payload.get("plan")
                if isinstance(plan, list):
                    pending_steps = [
                        str(item.get("step"))
                        for item in plan
                        if isinstance(item, dict)
                        and item.get("status") != "completed"
                        and isinstance(item.get("step"), str)
                    ]
            if tool_name == "verify" or checkpoint is not None:
                verification = checkpoint.get("verification") if checkpoint is not None else payload
                if isinstance(verification, dict):
                    success = verification.get("exitCode", verification.get("exit_code")) == 0
                    if success and isinstance(mutation, int):
                        verified_mutation = mutation
                        failure = None
            if tool_name == "finish_task" and payload.get("ok") is True:
                finish_accepted = True
            error = payload.get("error")
            if isinstance(error, dict) or payload.get("code") in {
                "coding_tool_batch_rejected",
                "verification_acceptance_failed",
            }:
                failure = error if isinstance(error, dict) else payload
        if finish_accepted:
            return None
        feedback: dict[str, Any]
        if failure is not None:
            feedback = {
                "marker": "CODING_RUNTIME_FEEDBACK",
                "version": 1,
                "code": failure.get("code", "coding_runtime_action_required"),
                "mutation": mutation,
                "failedItems": failure.get("failedRequirements", []),
                "passedItems": failure.get("passedRequirements", []),
                "requiredActions": failure.get("requiredActions", []),
            }
        elif pending_steps:
            feedback = {
                "marker": "CODING_RUNTIME_FEEDBACK",
                "version": 1,
                "code": "coding_runtime_action_required",
                "mutation": mutation,
                "pendingSteps": pending_steps,
                "requiredActions": [
                    "继续完成 pendingSteps；全部完成后在最后一次 mutation 上重新验证并调用 "
                    "finish_task。"
                ],
            }
        elif mutation is not None and verified_mutation != mutation:
            feedback = {
                "marker": "CODING_RUNTIME_FEEDBACK",
                "version": 1,
                "code": "coding_verification_required",
                "mutation": mutation,
                "requiredActions": ["在当前 mutation 上执行与改动范围匹配的验证。"],
            }
        elif mutation is not None:
            feedback = {
                "marker": "CODING_RUNTIME_FEEDBACK",
                "version": 1,
                "code": "coding_finish_required",
                "mutation": mutation,
                "requiredActions": ["当前 mutation 已验证；调用 finish_task 提交完成回执。"],
            }
        else:
            return None
        return Message(
            role="user",
            content=json.dumps(feedback, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        )

    @classmethod
    def project(
        cls,
        messages: list[Message],
        *,
        model: Any = None,
        tools: Any = None,
        response_format: Any = None,
        hard_cap: int = CODING_CONTEXT_TOKEN_LIMIT - CODING_OUTPUT_TOKEN_RESERVE,
    ) -> list[Message]:
        projected = deepcopy(messages)
        compact_call_ids = {
            message.tool_call_id
            for message in projected
            if message.role == "tool"
            and message.tool_name in CODING_TOOL_NAMES
            and message.compressed_content is not None
            and isinstance(message.tool_call_id, str)
        }
        for message in projected:
            if message.role not in {"assistant", "model"} or not message.tool_calls:
                continue
            for tool_call in message.tool_calls:
                if not isinstance(tool_call, dict) or tool_call.get("id") not in compact_call_ids:
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    continue
                tool_name = function.get("name")
                if not isinstance(tool_name, str):
                    continue
                function["arguments"] = cls._compact_arguments(tool_name, function.get("arguments"))
        counting_model = model or OpenAIChat(id="token-counter")
        canonical_tokens = cls._token_count(projected, counting_model, tools, response_format)
        feedback = cls._runtime_feedback(projected)
        if feedback is not None:
            projected.append(feedback)
        threshold = max(1, int(hard_cap * CODING_CONTEXT_REBASE_THRESHOLD))
        projected_tokens = cls._token_count(projected, counting_model, tools, response_format)
        if canonical_tokens <= threshold and projected_tokens <= hard_cap:
            cls.last_metrics = {
                "canonical_message_count": len(messages),
                "projected_message_count": len(projected),
                "canonical_estimated_tokens": canonical_tokens,
                "projected_estimated_tokens": projected_tokens,
                "checkpoint_bytes": 0,
                "dropped_complete_rounds": 0,
                "window_rebased": False,
            }
            return projected

        system_messages = [message for message in projected if message.role == "system"]
        user_messages = [
            message
            for message in projected
            if message.role == "user"
            and not str(message.content or "").startswith('{"marker":"CODING_RUNTIME_FEEDBACK"')
        ]
        prefix = [*system_messages]
        if user_messages:
            prefix.append(user_messages[0])
            if user_messages[-1] is not user_messages[0]:
                prefix.append(user_messages[-1])
        checkpoint = ContextBudgetController._checkpoint(projected)
        checkpoint_message = Message(role="user", content=checkpoint)
        rounds = cls._complete_rounds(projected)
        selected_rounds = rounds[-CODING_RECENT_ASSISTANT_TURNS:]
        candidate = [*prefix, checkpoint_message]
        for round_messages in selected_rounds:
            candidate.extend(round_messages)
        if feedback is not None:
            candidate.append(feedback)

        target = max(1, int(hard_cap * CODING_CONTEXT_REBASE_TARGET))
        while (
            selected_rounds
            and cls._token_count(candidate, counting_model, tools, response_format) > target
        ):
            removed = selected_rounds.pop(0)
            start = next(index for index, message in enumerate(candidate) if message is removed[0])
            del candidate[start : start + len(removed)]
        projected_tokens = cls._token_count(candidate, counting_model, tools, response_format)
        if projected_tokens > hard_cap:
            raise CodingContextHardLimitError(
                "不可约简的编码上下文前缀与工具 schema 超过模型输入 hard cap。"
            )
        cls.last_metrics = {
            "canonical_message_count": len(messages),
            "projected_message_count": len(candidate),
            "canonical_estimated_tokens": canonical_tokens,
            "projected_estimated_tokens": projected_tokens,
            "checkpoint_bytes": len(checkpoint.encode("utf-8")),
            "dropped_complete_rounds": len(rounds) - len(selected_rounds),
            "window_rebased": True,
        }
        return candidate


_PARALLEL_SAFE_READ_TOOLS = frozenset(
    {
        "list_files",
        "read_file",
        "read_lines",
        "search_text",
        "tree",
        "git_status",
        "git_diff",
        "read_tool_output",
        "view_image",
        "get_skill_instructions",
        "get_skill_reference",
        "inspect_profile_index",
        "report_list_data_sources",
        "report_describe_data_source",
    }
)


def _parallel_safe_tool_call(function_call: Any) -> bool:
    name = str(getattr(getattr(function_call, "function", None), "name", "") or "")
    arguments = getattr(function_call, "arguments", None)
    return _parallel_safe_tool(name, arguments)


def _parallel_safe_tool(name: str, arguments: Any) -> bool:
    if name in _PARALLEL_SAFE_READ_TOOLS:
        return True
    return bool(
        name == "get_skill_script"
        and isinstance(arguments, dict)
        and arguments.get("execute", False) is False
    )


def _tool_batch_admission(function_calls: list[Any]) -> tuple[bool, str]:
    size = len(function_calls)
    if size <= 1:
        return True, "single"
    if size <= CODING_TOOL_BATCH_LIMIT and all(
        _parallel_safe_tool_call(function_call) for function_call in function_calls
    ):
        return True, "parallel_safe_read"
    return True, "serialized"


def _tool_batch_attributes(size: int, admitted: bool, admission: str) -> dict[str, Any]:
    return {
        "tool_batch_size": size,
        "tool_batch_admission": admission,
        "tool_batch_rejection_code": "" if admitted else "coding_tool_batch_rejected",
    }


def _stream_value(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _update_stream_tool_calls(response: Any, calls: dict[int, dict[str, Any]]) -> None:
    for fallback_index, tool_call in enumerate(getattr(response, "tool_calls", None) or []):
        raw_index = _stream_value(tool_call, "index", fallback_index)
        index = raw_index if isinstance(raw_index, int) else fallback_index
        current = calls.setdefault(index, {"name": "", "arguments": ""})
        function = _stream_value(tool_call, "function")
        if function is None:
            continue
        name = _stream_value(function, "name")
        if name:
            current["name"] = str(name)
        arguments = _stream_value(function, "arguments")
        if isinstance(arguments, str):
            current["arguments"] += arguments
        elif isinstance(arguments, dict):
            current["arguments"] = arguments


def _stream_tool_batch_attributes(calls: dict[int, dict[str, Any]]) -> dict[str, Any]:
    parsed_calls = []
    for call in calls.values():
        arguments = call["arguments"]
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
        parsed_calls.append((str(call["name"]), arguments))
    size = len(parsed_calls)
    parallel = size <= 1 or (
        size <= CODING_TOOL_BATCH_LIMIT
        and all(_parallel_safe_tool(name, arguments) for name, arguments in parsed_calls)
    )
    admission = "single" if size <= 1 else "parallel_safe_read" if parallel else "serialized"
    return _tool_batch_attributes(size, True, admission)


def _tool_call_batches(function_calls: list[Any]) -> list[list[Any]]:
    """保留模型调用顺序；安全读取限量并发，其他调用逐个串行。

    并发资格只来自服务端工具分类，不能由模型参数声明扩大。写入、执行、验收和
    finish 均以单调用批次进入 Agno 原执行器，保留其 hook、回执和停止语义。
    """
    batches: list[list[Any]] = []
    reads: list[Any] = []

    def flush_reads() -> None:
        nonlocal reads
        if reads:
            batches.append(reads)
            reads = []

    for function_call in function_calls:
        if _parallel_safe_tool_call(function_call):
            reads.append(function_call)
            if len(reads) == CODING_TOOL_BATCH_LIMIT:
                flush_reads()
            continue
        flush_reads()
        batches.append([function_call])
    flush_reads()
    return batches


def _set_current_span_attributes(attributes: dict[str, Any]) -> None:
    try:
        from opentelemetry import trace as trace_api

        span = trace_api.get_current_span()
        for key, value in attributes.items():
            span.set_attribute(key, value)
    except Exception:
        return


_CODING_REQUEST_METRICS: ContextVar[dict[str, Any] | None] = ContextVar(
    "coding_request_metrics", default=None
)


class ProjectedOpenAIChat(OpenAIChat):
    _coding_input_token_budget: int | None = None

    def _project(self, messages: list[Message], args: tuple[Any, ...], kwargs: dict[str, Any]):
        response_format = kwargs.get("response_format", args[1] if len(args) > 1 else None)
        tools = kwargs.get("tools", args[2] if len(args) > 2 else None)
        hard_cap = getattr(self, _PROJECTED_INPUT_TOKEN_BUDGET_ATTR, None)
        if not isinstance(hard_cap, int) or hard_cap < 1:
            hard_cap = CODING_CONTEXT_TOKEN_LIMIT - CODING_OUTPUT_TOKEN_RESERVE
        projected = CodingContextProjector.project(
            messages,
            model=self,
            tools=tools,
            response_format=response_format,
            hard_cap=hard_cap,
        )
        return projected, dict(CodingContextProjector.last_metrics)

    def get_request_params(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        params = super().get_request_params(*args, **kwargs)
        metrics = _CODING_REQUEST_METRICS.get()
        if metrics is not None:
            _set_current_span_attributes(metrics)
        return params

    def invoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        model_id, host = _model_log_fields(self)
        projection_started_at = perf_counter()
        projected, metrics = self._project(messages, args, kwargs)
        logger.info(
            "model_projection_completed mode=sync model_id={} host={} duration_ms={} "
            "message_count={} projected_message_count={} tool_count={} "
            "canonical_estimated_tokens={} projected_estimated_tokens={} window_rebased={}",
            model_id,
            host,
            _duration_ms(projection_started_at),
            len(messages),
            len(projected),
            _tool_count(args, kwargs),
            metrics.get("canonical_estimated_tokens", 0),
            metrics.get("projected_estimated_tokens", 0),
            str(bool(metrics.get("window_rebased", False))).lower(),
        )
        token = _CODING_REQUEST_METRICS.set(metrics)
        provider_started_at = perf_counter()
        failed = False
        logger.info("model_provider_request_started mode=sync model_id={} host={}", model_id, host)
        try:
            return super().invoke(projected, *args, **kwargs)
        except BaseException as error:
            failed = True
            logger.warning(
                "model_provider_request_failed mode=sync model_id={} host={} duration_ms={} "
                "error_type={}",
                model_id,
                host,
                _duration_ms(provider_started_at),
                type(error).__name__,
            )
            raise
        finally:
            logger.info(
                "model_provider_request_completed mode=sync model_id={} host={} duration_ms={} "
                "failed={}",
                model_id,
                host,
                _duration_ms(provider_started_at),
                str(failed).lower(),
            )
            _CODING_REQUEST_METRICS.reset(token)

    async def ainvoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        model_id, host = _model_log_fields(self)
        projection_started_at = perf_counter()
        projected, metrics = self._project(messages, args, kwargs)
        logger.info(
            "model_projection_completed mode=async model_id={} host={} duration_ms={} "
            "message_count={} projected_message_count={} tool_count={} "
            "canonical_estimated_tokens={} projected_estimated_tokens={} window_rebased={}",
            model_id,
            host,
            _duration_ms(projection_started_at),
            len(messages),
            len(projected),
            _tool_count(args, kwargs),
            metrics.get("canonical_estimated_tokens", 0),
            metrics.get("projected_estimated_tokens", 0),
            str(bool(metrics.get("window_rebased", False))).lower(),
        )
        token = _CODING_REQUEST_METRICS.set(metrics)
        provider_started_at = perf_counter()
        failed = False
        logger.info("model_provider_request_started mode=async model_id={} host={}", model_id, host)
        try:
            return await super().ainvoke(projected, *args, **kwargs)
        except BaseException as error:
            failed = True
            logger.warning(
                "model_provider_request_failed mode=async model_id={} host={} duration_ms={} "
                "error_type={}",
                model_id,
                host,
                _duration_ms(provider_started_at),
                type(error).__name__,
            )
            raise
        finally:
            logger.info(
                "model_provider_request_completed mode=async model_id={} host={} duration_ms={} "
                "failed={}",
                model_id,
                host,
                _duration_ms(provider_started_at),
                str(failed).lower(),
            )
            _CODING_REQUEST_METRICS.reset(token)

    def invoke_stream(self, messages: list[Message], *args: Any, **kwargs: Any) -> Iterator[Any]:
        model_id, host = _model_log_fields(self)
        projection_started_at = perf_counter()
        projected, metrics = self._project(messages, args, kwargs)
        logger.info(
            "model_projection_completed mode=sync_stream model_id={} host={} duration_ms={} "
            "message_count={} projected_message_count={} tool_count={} "
            "canonical_estimated_tokens={} projected_estimated_tokens={} window_rebased={}",
            model_id,
            host,
            _duration_ms(projection_started_at),
            len(messages),
            len(projected),
            _tool_count(args, kwargs),
            metrics.get("canonical_estimated_tokens", 0),
            metrics.get("projected_estimated_tokens", 0),
            str(bool(metrics.get("window_rebased", False))).lower(),
        )
        tool_calls: dict[int, dict[str, Any]] = {}
        token = _CODING_REQUEST_METRICS.set(metrics)
        provider_started_at = perf_counter()
        first_chunk_ms: int | None = None
        chunk_count = 0
        failed = False
        logger.info("model_provider_stream_started mode=sync model_id={} host={}", model_id, host)
        try:
            for response in super().invoke_stream(projected, *args, **kwargs):
                chunk_count += 1
                if first_chunk_ms is None:
                    first_chunk_ms = _duration_ms(provider_started_at)
                    logger.info(
                        "model_provider_first_chunk mode=sync model_id={} host={} duration_ms={}",
                        model_id,
                        host,
                        first_chunk_ms,
                    )
                _update_stream_tool_calls(response, tool_calls)
                if tool_calls:
                    _set_current_span_attributes(_stream_tool_batch_attributes(tool_calls))
                yield response
        except BaseException as error:
            failed = True
            logger.warning(
                "model_provider_stream_failed mode=sync model_id={} host={} duration_ms={} "
                "chunk_count={} error_type={}",
                model_id,
                host,
                _duration_ms(provider_started_at),
                chunk_count,
                type(error).__name__,
            )
            raise
        finally:
            logger.info(
                "model_provider_stream_completed mode=sync model_id={} host={} duration_ms={} "
                "first_chunk_ms={} chunk_count={} failed={}",
                model_id,
                host,
                _duration_ms(provider_started_at),
                first_chunk_ms if first_chunk_ms is not None else "-",
                chunk_count,
                str(failed).lower(),
            )
            _CODING_REQUEST_METRICS.reset(token)

    async def ainvoke_stream(
        self, messages: list[Message], *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        model_id, host = _model_log_fields(self)
        projection_started_at = perf_counter()
        projected, metrics = self._project(messages, args, kwargs)
        logger.info(
            "model_projection_completed mode=async_stream model_id={} host={} duration_ms={} "
            "message_count={} projected_message_count={} tool_count={} "
            "canonical_estimated_tokens={} projected_estimated_tokens={} window_rebased={}",
            model_id,
            host,
            _duration_ms(projection_started_at),
            len(messages),
            len(projected),
            _tool_count(args, kwargs),
            metrics.get("canonical_estimated_tokens", 0),
            metrics.get("projected_estimated_tokens", 0),
            str(bool(metrics.get("window_rebased", False))).lower(),
        )
        tool_calls: dict[int, dict[str, Any]] = {}
        token = _CODING_REQUEST_METRICS.set(metrics)
        provider_started_at = perf_counter()
        first_chunk_ms: int | None = None
        chunk_count = 0
        failed = False
        logger.info("model_provider_stream_started mode=async model_id={} host={}", model_id, host)
        try:
            async for response in super().ainvoke_stream(projected, *args, **kwargs):
                chunk_count += 1
                if first_chunk_ms is None:
                    first_chunk_ms = _duration_ms(provider_started_at)
                    logger.info(
                        "model_provider_first_chunk mode=async model_id={} host={} duration_ms={}",
                        model_id,
                        host,
                        first_chunk_ms,
                    )
                _update_stream_tool_calls(response, tool_calls)
                if tool_calls:
                    _set_current_span_attributes(_stream_tool_batch_attributes(tool_calls))
                yield response
        except BaseException as error:
            failed = True
            logger.warning(
                "model_provider_stream_failed mode=async model_id={} host={} duration_ms={} "
                "chunk_count={} error_type={}",
                model_id,
                host,
                _duration_ms(provider_started_at),
                chunk_count,
                type(error).__name__,
            )
            raise
        finally:
            logger.info(
                "model_provider_stream_completed mode=async model_id={} host={} duration_ms={} "
                "first_chunk_ms={} chunk_count={} failed={}",
                model_id,
                host,
                _duration_ms(provider_started_at),
                first_chunk_ms if first_chunk_ms is not None else "-",
                chunk_count,
                str(failed).lower(),
            )
            _CODING_REQUEST_METRICS.reset(token)

    def run_function_calls(self, function_calls, function_call_results, *args, **kwargs):
        for batch in _tool_call_batches(function_calls):
            yield from super().run_function_calls(batch, function_call_results, *args, **kwargs)

    async def arun_function_calls(self, function_calls, function_call_results, *args, **kwargs):
        for batch in _tool_call_batches(function_calls):
            async for event in super().arun_function_calls(
                batch, function_call_results, *args, **kwargs
            ):
                yield event


def projected_coding_model(
    model: OpenAIChat,
    *,
    input_token_budget: int | None = None,
) -> ProjectedOpenAIChat:
    if (
        isinstance(model, ProjectedOpenAIChat)
        and (model.request_params or {}).get("parallel_tool_calls") is True
    ):
        if isinstance(input_token_budget, int) and input_token_budget > 0:
            setattr(model, _PROJECTED_INPUT_TOKEN_BUDGET_ATTR, input_token_budget)
        return model
    values = {field.name: getattr(model, field.name) for field in fields(model)}
    values["request_params"] = {
        **(model.request_params or {}),
        "parallel_tool_calls": True,
    }
    projected = ProjectedOpenAIChat(**values)
    if isinstance(input_token_budget, int) and input_token_budget > 0:
        setattr(projected, _PROJECTED_INPUT_TOKEN_BUDGET_ATTR, input_token_budget)
    return projected


def _summary_messages(runs: list[Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for run in runs:
        for message in getattr(run, "messages", None) or []:
            role = str(getattr(message, "role", "") or "")
            if role == "user":
                content = _strip_stale_context(_message_text(message))
            elif role in {"assistant", "model"}:
                role = "assistant"
                content = _message_text(message)
            else:
                continue
            if content and not _SENSITIVE_HISTORY.search(content):
                messages.append({"role": role, "content": content})
    return messages


def _parse_rolling_summary(response: Any) -> RollingSummaryResponse | None:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, RollingSummaryResponse):
        return parsed
    if isinstance(parsed, dict):
        try:
            return RollingSummaryResponse.model_validate(parsed)
        except ValidationError:
            pass
    content = getattr(response, "content", None)
    if not isinstance(content, str):
        return None
    content = content.strip()
    fenced = re.fullmatch(
        r"```(?:json)?[ \t]*\r?\n(?P<body>.*)\r?\n```",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if fenced is not None:
        content = fenced.group("body").strip()
    try:
        return RollingSummaryResponse.model_validate_json(content)
    except ValidationError:
        return None


class RollingSessionSummaryManager(SessionSummaryManager):
    @staticmethod
    def source_digest(runs: list[Any]) -> str:
        payload = [
            {
                "runId": str(getattr(run, "run_id", "") or ""),
                "messages": _summary_messages([run]),
            }
            for run in runs
        ]
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _metadata(session: Any) -> dict[str, Any]:
        session_data = getattr(session, "session_data", None)
        if not isinstance(session_data, dict):
            return {}
        metadata = session_data.get(SUMMARY_METADATA_KEY)
        return metadata if isinstance(metadata, dict) else {}

    def _summary_input(self, session: Any) -> tuple[str | None, list[Any], int]:
        runs = _session_history_runs(session)
        metadata = self._metadata(session)
        previous = str(getattr(getattr(session, "summary", None), "summary", "") or "").strip()
        last_run_id = str(metadata.get("lastSourceRunId") or "")
        previous_version = int(metadata.get("version") or 0)
        last_index = next(
            (
                index
                for index, run in enumerate(runs)
                if str(getattr(run, "run_id", "") or "") == last_run_id
            ),
            -1,
        )
        valid_previous = bool(
            previous
            and not _FORBIDDEN_SUMMARY_CONTENT.search(previous)
            and last_index >= 0
            and metadata.get("sourceDigest") == self.source_digest(runs[: last_index + 1])
        )
        if not valid_previous:
            return None, runs, 0
        return previous, runs[last_index + 1 :], previous_version

    @staticmethod
    def _request_messages(previous: str | None, new_runs: list[Any]) -> list[Message] | None:
        messages = _summary_messages(new_runs)
        if not messages:
            return None
        payload = {
            "previousSummary": previous,
            "newMessages": messages,
        }
        return [
            Message(
                role="system",
                content=(
                    "更新非权威滚动会话摘要。只输出用户目标、已确认决策、工作区文件、"
                    "完成事项和待办事项；不得包含或推导权限状态或授权 token。"
                    "必须只返回符合指定 schema 的 JSON 对象。"
                ),
            ),
            Message(
                role="user",
                content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ),
        ]

    def _apply_summary(
        self,
        session: Any,
        payload: RollingSummaryResponse,
        runs: list[Any],
        previous_version: int,
    ) -> SessionSummary | None:
        serialized = payload.model_dump_json(exclude_none=True)
        if _FORBIDDEN_SUMMARY_CONTENT.search(serialized):
            return None
        now = datetime.now(UTC)
        summary = SessionSummary(summary=serialized, topics=["滚动历史"], updated_at=now)
        session.summary = summary
        if not isinstance(getattr(session, "session_data", None), dict):
            session.session_data = {}
        latest_run_id = str(getattr(runs[-1], "run_id", "") or "")
        session.session_data[SUMMARY_METADATA_KEY] = {
            "version": previous_version + 1,
            "lastSourceRunId": latest_run_id,
            "sourceDigest": self.source_digest(runs),
            "updatedAt": now.isoformat(),
        }
        self.summaries_updated = True
        return summary

    def create_session_summary(self, session, run_metrics=None):
        previous, new_runs, version = self._summary_input(session)
        messages = self._request_messages(previous, new_runs)
        if messages is None:
            return getattr(session, "summary", None)
        model = self.model
        if model is None:
            return getattr(session, "summary", None)
        try:
            response = model.response(messages=messages, response_format=RollingSummaryResponse)
            payload = _parse_rolling_summary(response)
        except Exception as error:
            logger.warning("rolling_summary_failed error_type={}", type(error).__name__)
            return getattr(session, "summary", None)
        if payload is None:
            logger.warning(
                "rolling_summary_invalid parsed_type={} content_type={}",
                type(getattr(response, "parsed", None)).__name__,
                type(getattr(response, "content", None)).__name__,
            )
            return getattr(session, "summary", None)
        return self._apply_summary(
            session,
            payload,
            list(getattr(session, "runs", None) or []),
            version,
        ) or getattr(session, "summary", None)

    async def acreate_session_summary(self, session, run_metrics=None):
        previous, new_runs, version = self._summary_input(session)
        messages = self._request_messages(previous, new_runs)
        if messages is None:
            return getattr(session, "summary", None)
        model = self.model
        if model is None:
            return getattr(session, "summary", None)
        try:
            response = await model.aresponse(
                messages=messages,
                response_format=RollingSummaryResponse,
            )
            payload = _parse_rolling_summary(response)
        except Exception as error:
            logger.warning("rolling_summary_failed error_type={}", type(error).__name__)
            return getattr(session, "summary", None)
        if payload is None:
            logger.warning(
                "rolling_summary_invalid parsed_type={} content_type={}",
                type(getattr(response, "parsed", None)).__name__,
                type(getattr(response, "content", None)).__name__,
            )
            return getattr(session, "summary", None)
        return self._apply_summary(
            session,
            payload,
            list(getattr(session, "runs", None) or []),
            version,
        ) or getattr(session, "summary", None)


def clear_terminal_reasoning(run_output: Any) -> None:
    for attribute in (
        "reasoning_content",
        "redacted_reasoning_content",
        "reasoning_messages",
        "reasoning_steps",
    ):
        if hasattr(run_output, attribute):
            setattr(run_output, attribute, None)
    if hasattr(run_output, "model_provider_data"):
        run_output.model_provider_data = _without_reasoning(run_output.model_provider_data)
    for message in getattr(run_output, "messages", None) or []:
        for attribute in ("reasoning_content", "redacted_reasoning_content"):
            if hasattr(message, attribute):
                setattr(message, attribute, None)
        if hasattr(message, "provider_data"):
            message.provider_data = _without_reasoning(message.provider_data)


def clear_terminal_session_reasoning(session: Any) -> None:
    for run in getattr(session, "runs", None) or []:
        if _status_value(run) in {"completed", "cancelled", "error", "regenerated"}:
            clear_terminal_reasoning(run)


def _without_reasoning(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_reasoning(item)
            for key, item in value.items()
            if "reasoning" not in str(key).lower() and "thinking" not in str(key).lower()
        }
    if isinstance(value, list):
        return [_without_reasoning(item) for item in value]
    return value
