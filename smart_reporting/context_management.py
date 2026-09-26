import asyncio
import hashlib
import json
import os
import re
import tempfile
from collections.abc import AsyncIterator, Iterator, Mapping
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

import requests
from agno.compression.manager import CompressionManager
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.session.summary import SessionSummary, SessionSummaryManager
from agno.session.team import TeamSession
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .runtime.observability import duration_ms

SKILL_CONTENT_WINDOW = 10
SKILL_PRUNE_MIN_CHARS = 5000
SKILL_TOOL_NAMES = frozenset({"get_skill_instructions", "get_skill_reference", "get_skill_script"})
# 这是所有受控任务上下文的绝对顶线，具体 Agent 仍取自身配置与该值的较小者。
# Reporting 模型已明确支持 1M 上下文；继续固定 256K 会在模型调用前错误拒绝合法的
# Profile 定点分析与逐章成稿上下文，其他 Agent 的配置不会因此扩大。
TASK_EXECUTION_CONTEXT_TOKEN_LIMIT = 1024 * 1024
TASK_EXECUTION_OUTPUT_TOKEN_RESERVE = 32 * 1024
TASK_EXECUTION_RECENT_ASSISTANT_TURNS = 2
TASK_EXECUTION_CHECKPOINT_MAX_BYTES = 32 * 1024
TASK_EXECUTION_CONTEXT_REBASE_THRESHOLD = 0.75
TASK_EXECUTION_CONTEXT_REBASE_TARGET = 0.50
# Coding 专用请求前门禁：低于窗口重建阈值与 provider 硬窗口。达到门禁后先对旧
# custom 工具调用做确定性摘要（保留 call 身份），只有仍超重建阈值时才整轮丢弃。
CODING_CUSTOM_HISTORY_TOKEN_THRESHOLD = 0.60
# 2026-09-23 冻结回放校准：真实样本单请求输入峰值约 30.6K（p75≈20.0K），按比例
# 派生的门禁（0.60×hard_cap≈118K）永不触发。绝对门禁取样本 p75–p90 下沿，使触发
# 点落在长修复链后半程；首轮（≤8K）与短任务稳态平台（约 16.5K）不触发，安全下界
# 18K。小窗口模型仍受比例门禁约束，取两者较小值。
CODING_COMPACTION_INPUT_TOKEN_GATE = 20_000
# provider 实测输入的绝对膨胀门禁：本地 token 估算与 provider 计数已证实会大幅偏离
# （cli 复盘：本地投影 ~36K 时 provider 实测 172K）。上一请求实测输入达到该门禁即
# 强制触发确定性压缩，不再依赖本地估算。
CODING_COMPACTION_PROVIDER_INPUT_GATE = 100_000
# 对齐 Codex 两级工具元数据预算：单个旧调用摘要 8 KiB，整批旧历史元数据 32 KiB。
CODING_CUSTOM_HISTORY_SUMMARY_MAX_BYTES = 8 * 1024
CODING_CUSTOM_HISTORY_METADATA_MAX_BYTES = 32 * 1024
TASK_EXECUTION_TOOL_BATCH_LIMIT = 10
TIKTOKEN_O200K_CACHE_KEY = "fb374d419588a4632f3f557e76b4b70aebbca790"
TIKTOKEN_O200K_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
TIKTOKEN_O200K_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
TIKTOKEN_DOWNLOAD_TIMEOUT = (5, 30)
TIKTOKEN_DOWNLOAD_MAX_BYTES = 16 * 1024 * 1024
_PROJECTED_INPUT_TOKEN_BUDGET_ATTR = "_task_execution_input_token_budget"
TASK_EXECUTION_TOOL_NAMES = frozenset(
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
_CODING_FREEFORM_TOOL_ARGUMENTS = {
    "write_script": "source",
    "run": "code",
    "edit_script": "patch",
}
SUMMARY_METADATA_KEY = "agentos_rolling_summary"
COMPRESSIBLE_HISTORY_TOOLS = frozenset(
    {
        "terminal",
        "process",
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


def _download_tiktoken_cache(cache_path: Path) -> None:
    """有界下载官方编码，并在身份校验后原子发布到 tiktoken 缓存路径。"""

    temporary_path: Path | None = None
    try:
        # requests 的二元 timeout 分别约束连接和相邻响应字节等待；防火墙静默丢包时
        # 必须在应用导入阶段有界失败，不能让健康检查永远没有启动机会。
        with requests.get(
            TIKTOKEN_O200K_URL,
            timeout=TIKTOKEN_DOWNLOAD_TIMEOUT,
            stream=True,
        ) as response:
            response.raise_for_status()
            digest = hashlib.sha256()
            total = 0
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=cache_path.parent,
                prefix=f".{cache_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > TIKTOKEN_DOWNLOAD_MAX_BYTES:
                        raise RuntimeError("o200k_base 下载内容超过大小上限。")
                    digest.update(chunk)
                    temporary.write(chunk)
        if digest.hexdigest() != TIKTOKEN_O200K_SHA256:
            raise RuntimeError("o200k_base 下载内容校验失败。")
        os.replace(temporary_path, cache_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


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
            _download_tiktoken_cache(cache_path)
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


_CONTEXT_COMPONENT_ROLES = ("system", "user", "assistant", "tool", "other")


def _serialized_context_bytes(value: Any) -> int:
    if value is None:
        return 0
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        encoded = str(value)
    return len(encoded.encode("utf-8"))


def _context_message_bytes(message: Message) -> tuple[str, int]:
    role = str(message.role or "").lower()
    bucket = role if role in _CONTEXT_COMPONENT_ROLES else "other"
    payload = {
        "role": role,
        "content": _message_text(message),
        "name": getattr(message, "name", None),
        "toolName": getattr(message, "tool_name", None),
        "toolCallId": getattr(message, "tool_call_id", None),
        "toolArgs": getattr(message, "tool_args", None),
        "toolCalls": getattr(message, "tool_calls", None),
    }
    return bucket, _serialized_context_bytes(payload)


def _context_composition_bytes(
    messages: list[Message], tools: Any = None, response_format: Any = None
) -> dict[str, int]:
    """统计上下文组成的字节量；只返回大小，不返回任何输入内容。"""

    components = {role: 0 for role in _CONTEXT_COMPONENT_ROLES}
    for message in messages:
        try:
            role, size = _context_message_bytes(message)
        except Exception:
            # 观测不能改变模型请求行为；遇到第三方 Message 的异常字段时只跳过该项。
            continue
        components[role] += size
    components["message"] = sum(components.values())
    components["tool_schema"] = _serialized_context_bytes(tools)
    components["response_format"] = _serialized_context_bytes(response_format)
    components["total"] = (
        components["message"] + components["tool_schema"] + components["response_format"]
    )
    return components


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
        output_token_reserve: int = TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
    ) -> None:
        self.context_token_limit = min(context_token_budget, TASK_EXECUTION_CONTEXT_TOKEN_LIMIT)
        self.output_token_reserve = max(TASK_EXECUTION_OUTPUT_TOKEN_RESERVE, output_token_reserve)
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
    def _task_execution_receipt(message: Message) -> str:
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
                "marker": "TASK_EXECUTION_TOOL_RECEIPT",
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
            if message.role != "tool" or message.tool_name not in TASK_EXECUTION_TOOL_NAMES:
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
            "marker": "TASK_EXECUTION_CHECKPOINT",
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
        if len(encoded.encode("utf-8")) <= TASK_EXECUTION_CHECKPOINT_MAX_BYTES:
            return encoded
        payload["plan"] = _bounded_json_value(plan, 4096)
        payload["validator"] = _bounded_json_value(validator, 4096)
        payload["completion"] = _bounded_json_value(completion, 4096)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        for field in ("skillReceipts", "changedFiles", "activeProcesses"):
            values = payload[field]
            while values and len(encoded.encode("utf-8")) > TASK_EXECUTION_CHECKPOINT_MAX_BYTES:
                values.pop(0)
                encoded = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
        return encoded

    def should_compress(self, messages, tools=None, model=None, response_format=None):
        counting_model = model or self.model
        started_at = perf_counter()
        try:
            token_count = (
                counting_model.count_tokens(messages, tools, response_format)
                if counting_model is not None
                else 0
            )
        except Exception as error:
            model_id, _host = _model_log_fields(counting_model)
            logger.warning(
                "context_budget_token_count_failed model_id={} duration_ms={} error_type={}",
                model_id,
                duration_ms(started_at),
                type(error).__name__,
            )
            token_count = _fallback_context_token_count(messages, tools, response_format)
        return token_count > self.input_token_budget

    def compress(self, messages, run_metrics=None):
        # Canonical Agno messages must remain untouched. Projection happens in the model wrapper.
        return None

    async def acompress(self, messages, run_metrics=None):
        self.compress(messages, run_metrics=run_metrics)

    def prepare_context(self, messages: list[Message]) -> list[Message]:
        return TaskExecutionContextProjector.project(
            messages,
            model=self.model,
            hard_cap=self.input_token_budget,
        )

    async def compress_history_message(self, message: Message) -> Message:
        candidate = deepcopy(message)
        candidate.from_history = True
        if candidate.role == "tool" and candidate.tool_name in TASK_EXECUTION_TOOL_NAMES:
            candidate.compressed_content = self._task_execution_receipt(candidate)
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
        if payload is not None and payload.get("marker") in {
            "TASK_EXECUTION_CHECKPOINT",
            "CODING_CHECKPOINT",
        }:
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


class TaskExecutionContextHardLimitError(RuntimeError):
    code = "task_execution_context_hard_limit_exceeded"

    def __init__(
        self,
        message: str,
        *,
        metrics: Mapping[str, int | bool],
    ) -> None:
        super().__init__(message)
        self.metrics = dict(metrics)


_CODING_CUSTOM_SUMMARY_MARKER = "CODING_CUSTOM_HISTORY_SUMMARY"
_CODING_CUSTOM_RESULT_MARKER = "CODING_CUSTOM_HISTORY_RESULT"


def _coding_custom_result_code(payload: Mapping[str, Any]) -> int | str | None:
    for key in ("exitCode", "exit_code"):
        value = payload.get(key)
        if type(value) is int:
            return value
    value = payload.get("code")
    if isinstance(value, str) and 0 < len(value) <= 128:
        return value
    return None


def _coding_custom_result_sha(payload: Mapping[str, Any]) -> str | None:
    candidates = [payload.get("sourceSha256"), payload.get("sha256")]
    details = payload.get("details")
    if isinstance(details, Mapping):
        candidates.append(details.get("sourceSha256"))
    for candidate in candidates:
        if isinstance(candidate, str) and 0 < len(candidate) <= 128:
            return candidate
    return None


class TaskExecutionContextProjector:
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

    @classmethod
    def _scan_coding_custom_history(
        cls, messages: list[Message], protected_call_ids: frozenset[str]
    ) -> list[dict[str, Any]]:
        """按时间顺序收集 custom 工具调用及其结果；只读，不改写任何消息。"""

        results: dict[str, Message] = {}
        for message in messages:
            if message.role == "tool" and isinstance(message.tool_call_id, str):
                results[message.tool_call_id] = message
        entries: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            if message.role not in {"assistant", "model"}:
                continue
            for call in message.tool_calls or ():
                if not isinstance(call, dict):
                    continue
                provider_data = call.get("provider_data")
                function = call.get("function")
                name = function.get("name") if isinstance(function, dict) else None
                raw_input = (
                    provider_data.get("raw_input") if isinstance(provider_data, dict) else None
                )
                if (
                    not isinstance(provider_data, dict)
                    or provider_data.get("reporting_wire_type") != "custom"
                    or name not in _CODING_FREEFORM_TOOL_ARGUMENTS
                    or not isinstance(raw_input, str)
                    or not raw_input
                    or not isinstance(function, dict)
                ):
                    continue
                identities = {
                    value
                    for key in ("call_id", "id")
                    if isinstance(value := call.get(key), str) and value
                }
                if not identities:
                    continue
                result = next(
                    (results[identity] for identity in identities if identity in results), None
                )
                entries.append(
                    {
                        "index": index,
                        "call": call,
                        "function": function,
                        "name": name,
                        "raw_input": raw_input,
                        "call_id": call.get("call_id") or call.get("id"),
                        "identities": identities,
                        "result": result,
                        # 当前调用（最近一次 custom 调用）与交付状态保护身份保留原文。
                        "compactable": result is not None
                        and not identities & protected_call_ids,
                    }
                )
        if entries:
            entries[-1]["compactable"] = False
        return entries

    @staticmethod
    def _next_tool_names(messages: list[Message], start: int) -> list[str]:
        for message in messages[start:]:
            if message.role in {"assistant", "model"} and message.tool_calls:
                return [
                    name
                    for call in message.tool_calls
                    if isinstance(call, dict)
                    and isinstance(call.get("function"), dict)
                    and isinstance(name := call["function"].get("name"), str)
                ]
        return []

    @classmethod
    def _summarize_coding_custom_history(
        cls,
        entries: list[dict[str, Any]],
        messages: list[Message],
        *,
        metadata_budget_enabled: bool = True,
    ) -> dict[str, int | bool]:
        """把可压缩的旧 custom 调用改写为固定结构摘要；调用身份与 wire 类型不变。

        摘要字段固定为 tool/status/code/sourceSha256/patchSha256/bytes/callId/
        nextTools；旧结果改写为只含状态的回执，stdout/stderr 与源码证据只保留在
        Workspace 与审计文件中。预算降级顺序对齐 Codex：先缩减结果元数据，再缩减
        旧调用摘要；当前调用与受保护身份已在扫描阶段排除，不参与缩减。
        """

        built: list[dict[str, Any]] = []
        for entry in entries:
            if not entry["compactable"]:
                continue
            result = entry["result"]
            payload = _json_payload(result.content) or {}
            failed = (
                result.tool_call_error is True
                or payload.get("ok") is False
                or payload.get("error") is not None
            )
            argument_sha = hashlib.sha256(entry["raw_input"].encode("utf-8")).hexdigest()
            result_sha = _coding_custom_result_sha(payload)
            if entry["name"] == "edit_script":
                source_sha, patch_sha = result_sha, argument_sha
            else:
                source_sha, patch_sha = result_sha or argument_sha, None
            summary = {
                "marker": _CODING_CUSTOM_SUMMARY_MARKER,
                "tool": entry["name"],
                "status": "failed" if failed else "completed",
                "code": _coding_custom_result_code(payload),
                "sourceSha256": source_sha,
                "patchSha256": patch_sha,
                "bytes": len(entry["raw_input"].encode("utf-8")),
                "callId": entry["call_id"],
                "nextTools": cls._next_tool_names(messages, entry["index"] + 1),
            }
            receipt = {
                "marker": _CODING_CUSTOM_RESULT_MARKER,
                "tool": entry["name"],
                "status": summary["status"],
                "ok": not failed,
                "bytes": len(str(result.content or "").encode("utf-8")),
                "callId": entry["call_id"],
            }
            built.append({"entry": entry, "summary": summary, "receipt": receipt, "truncated": False})

        def _encoded_size(value: Any) -> int:
            return len(
                json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
                    "utf-8"
                )
            )

        # 单个旧调用参数摘要上限 8 KiB：超出时按可选字段顺序丢弃。
        for item in built:
            if (
                not metadata_budget_enabled
                or _encoded_size(item["summary"]) <= CODING_CUSTOM_HISTORY_SUMMARY_MAX_BYTES
            ):
                continue
            item["truncated"] = True
            for field in ("nextTools", "code", "patchSha256", "sourceSha256"):
                item["summary"][field] = [] if field == "nextTools" else None
                if _encoded_size(item["summary"]) <= CODING_CUSTOM_HISTORY_SUMMARY_MAX_BYTES:
                    break

        def _total_bytes() -> int:
            return sum(
                _encoded_size(item["summary"]) + _encoded_size(item["receipt"]) for item in built
            )

        # 整批旧历史元数据上限 32 KiB：先丢结果元数据，最后才缩减旧调用摘要。
        if metadata_budget_enabled and _total_bytes() > CODING_CUSTOM_HISTORY_METADATA_MAX_BYTES:
            for item in built:
                if "bytes" in item["receipt"]:
                    del item["receipt"]["bytes"]
                    item["truncated"] = True
        if metadata_budget_enabled and _total_bytes() > CODING_CUSTOM_HISTORY_METADATA_MAX_BYTES:
            for item in built:
                if item["summary"].get("nextTools"):
                    item["summary"]["nextTools"] = []
                    item["truncated"] = True
        if metadata_budget_enabled and _total_bytes() > CODING_CUSTOM_HISTORY_METADATA_MAX_BYTES:
            for item in built:
                for field in ("code", "patchSha256", "sourceSha256"):
                    if item["summary"].get(field) is not None:
                        item["summary"][field] = None
                        item["truncated"] = True
                if _total_bytes() <= CODING_CUSTOM_HISTORY_METADATA_MAX_BYTES:
                    break

        # 最终兜底：降级链走完后仍越界时，从最旧开始把摘要缩减为仅身份字段；
        # 极端长链下仍越界则丢弃最旧摘要（该调用保留原始 wire），全部如实计数。
        if metadata_budget_enabled and _total_bytes() > CODING_CUSTOM_HISTORY_METADATA_MAX_BYTES:
            for item in built:
                if _total_bytes() <= CODING_CUSTOM_HISTORY_METADATA_MAX_BYTES:
                    break
                item["summary"] = {
                    key: item["summary"][key]
                    for key in ("marker", "tool", "status", "callId")
                }
                item["receipt"] = {
                    key: item["receipt"][key]
                    for key in ("marker", "tool", "status", "ok", "callId")
                }
                item["truncated"] = True
        metadata_budget_exceeded = (
            metadata_budget_enabled
            and _total_bytes() > CODING_CUSTOM_HISTORY_METADATA_MAX_BYTES
        )

        bytes_before = 0
        bytes_after = 0
        for item in built:
            entry = item["entry"]
            result = entry["result"]
            bytes_before += len(entry["raw_input"].encode("utf-8")) + len(
                str(result.content or "").encode("utf-8")
            )
            summary_json = json.dumps(
                item["summary"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            receipt_json = json.dumps(
                item["receipt"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            bytes_after += len(summary_json.encode("utf-8")) + len(receipt_json.encode("utf-8"))
            entry["call"]["provider_data"]["raw_input"] = summary_json
            entry["function"]["arguments"] = json.dumps(
                {_CODING_FREEFORM_TOOL_ARGUMENTS[entry["name"]]: summary_json},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            result.content = receipt_json
            if result.compressed_content is not None:
                result.compressed_content = receipt_json
        return {
            "compaction_triggered": bool(built),
            "compacted_calls": len(built),
            "bytes_before": bytes_before,
            "bytes_after": bytes_after,
            "metadata_bytes": bytes_after,
            "truncated_calls": sum(item["truncated"] for item in built),
            "dropped_summaries": 0,
            "metadata_budget_exceeded": metadata_budget_exceeded,
        }

    @staticmethod
    def _coding_custom_history_metadata_bytes(messages: list[Message]) -> int:
        summary_bytes = sum(
            len(raw_input.encode("utf-8"))
            for message in messages
            for call in message.tool_calls or ()
            if isinstance(call, dict)
            and isinstance((provider_data := call.get("provider_data")), dict)
            and isinstance(raw_input := provider_data.get("raw_input"), str)
            and _CODING_CUSTOM_SUMMARY_MARKER in raw_input
        )
        receipt_bytes = sum(
            len(content.encode("utf-8"))
            for message in messages
            if message.role == "tool"
            and isinstance((content := message.content), str)
            and _CODING_CUSTOM_RESULT_MARKER in content
        )
        return summary_bytes + receipt_bytes

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
                duration_ms(started_at),
                type(error).__name__,
            )
            return _fallback_context_token_count(messages, tools, response_format)

    @staticmethod
    def _token_count_with_stats(
        messages: list[Message], model: Any, tools: Any = None, response_format: Any = None
    ) -> tuple[int, int]:
        """_token_count 的计数版：额外返回本次计数耗时（ms），供投影耗时日志汇总。"""

        started_at = perf_counter()
        tokens = TaskExecutionContextProjector._token_count(messages, model, tools, response_format)
        return tokens, duration_ms(started_at)

    @staticmethod
    def _composition_metrics(
        messages: list[Message],
        projected: list[Message],
        tools: Any = None,
        response_format: Any = None,
    ) -> dict[str, int]:
        canonical = _context_composition_bytes(messages, tools, response_format)
        projected_components = _context_composition_bytes(projected, tools, response_format)
        metrics: dict[str, int] = {
            "tool_schema_bytes": canonical["tool_schema"],
            "response_format_bytes": canonical["response_format"],
        }
        for role in _CONTEXT_COMPONENT_ROLES:
            metrics[f"canonical_{role}_bytes"] = canonical[role]
            metrics[f"projected_{role}_bytes"] = projected_components[role]
        metrics["canonical_message_bytes"] = canonical["message"]
        metrics["projected_message_bytes"] = projected_components["message"]
        metrics["canonical_context_bytes"] = canonical["total"]
        metrics["projected_context_bytes"] = projected_components["total"]
        return metrics

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
            # 每个调用可能同时携带 Responses 的 call_id 和 item id 两种身份
            # （见 code_agent/protocol.py 的 custom tool 桥接）；结果只会用其中
            # 一个回填 tool_call_id。按调用分别收集身份集合，只要结果覆盖了该
            # 调用任一身份即视为已完成，避免因为只取单一身份而把完整轮次误判
            # 为不完整并整段丢弃。
            call_identity_sets = [
                {
                    identity
                    for key in ("call_id", "id")
                    if isinstance(identity := call.get(key), str)
                }
                for call in assistant.tool_calls
                if isinstance(call, dict)
            ]
            all_identities = {
                identity for identities in call_identity_sets for identity in identities
            }
            results: list[Message] = []
            cursor = index + 1
            while cursor < len(messages) and messages[cursor].role == "tool":
                if messages[cursor].tool_call_id in all_identities:
                    results.append(messages[cursor])
                cursor += 1
            result_ids = {message.tool_call_id for message in results}
            if call_identity_sets and all(
                identities & result_ids for identities in call_identity_sets
            ):
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
                "marker": "TASK_EXECUTION_RUNTIME_FEEDBACK",
                "version": 1,
                "code": failure.get("code", "coding_runtime_action_required"),
                "mutation": mutation,
                "failedItems": failure.get("failedRequirements", []),
                "passedItems": failure.get("passedRequirements", []),
                "requiredActions": failure.get("requiredActions", []),
            }
        elif pending_steps:
            feedback = {
                "marker": "TASK_EXECUTION_RUNTIME_FEEDBACK",
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
                "marker": "TASK_EXECUTION_RUNTIME_FEEDBACK",
                "version": 1,
                "code": "coding_verification_required",
                "mutation": mutation,
                "requiredActions": ["在当前 mutation 上执行与改动范围匹配的验证。"],
            }
        elif mutation is not None:
            feedback = {
                "marker": "TASK_EXECUTION_RUNTIME_FEEDBACK",
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
    def project_with_metrics(
        cls,
        messages: list[Message],
        *,
        model: Any = None,
        tools: Any = None,
        response_format: Any = None,
        hard_cap: int = TASK_EXECUTION_CONTEXT_TOKEN_LIMIT - TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
        protected_call_ids: frozenset[str] = frozenset(),
        history_summary_enabled: bool = True,
        metadata_budget_enabled: bool = True,
        provider_input_hint: int | None = None,
    ) -> tuple[list[Message], dict[str, int | bool]]:
        projection_started_at = perf_counter()
        count_calls = 0
        count_duration_ms = 0

        def counted_token_count(
            counted: list[Message],
        ) -> int:
            nonlocal count_calls, count_duration_ms
            tokens, elapsed = cls._token_count_with_stats(
                counted, counting_model, tools, response_format
            )
            count_calls += 1
            count_duration_ms += elapsed
            return tokens

        projected = deepcopy(messages)
        compact_call_ids = {
            message.tool_call_id
            for message in projected
            if message.role == "tool"
            and message.tool_name in TASK_EXECUTION_TOOL_NAMES
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
        pre_compaction_tokens = counted_token_count(projected)
        custom_entries = cls._scan_coding_custom_history(projected, protected_call_ids)
        compactable_metadata_bytes = sum(
            len(entry["raw_input"].encode("utf-8"))
            + len(str(entry["result"].content or "").encode("utf-8"))
            for entry in custom_entries
            if entry["compactable"]
        )
        custom_history_metrics: dict[str, int | bool] = {
            "history_candidate": any(entry["compactable"] for entry in custom_entries),
            "compaction_triggered": False,
            "compacted_calls": 0,
            "bytes_before": 0,
            "bytes_after": 0,
            # 可压缩历史的压缩前原始字节；metadata_bytes 统一为压缩后摘要字节
            # （未触发时为 0），两条路径口径一致，跨 run 可比较。
            "compactable_history_bytes": compactable_metadata_bytes,
            "metadata_bytes": 0,
            "truncated_calls": 0,
            "dropped_summaries": 0,
            "metadata_budget_exceeded": False,
            "compaction_tokens_before": 0,
            "compaction_tokens_after": 0,
            "input_inflation_detected": False,
        }
        # 请求前 token 门禁：达到 Coding 专用阈值（低于窗口重建阈值与 provider 硬
        # 窗口）或旧历史元数据超 32 KiB 预算时，先用确定性摘要替换完整旧历史。
        coding_history_gate = min(
            max(1, int(hard_cap * CODING_CUSTOM_HISTORY_TOKEN_THRESHOLD)),
            CODING_COMPACTION_INPUT_TOKEN_GATE,
        )
        provider_input_inflated = (
            isinstance(provider_input_hint, int)
            and not isinstance(provider_input_hint, bool)
            and provider_input_hint >= CODING_COMPACTION_PROVIDER_INPUT_GATE
        )
        if provider_input_inflated:
            custom_history_metrics["input_inflation_detected"] = True
            logger.warning(
                "report_code_input_inflation provider_input={} local_estimate={} gate={}",
                provider_input_hint,
                pre_compaction_tokens,
                CODING_COMPACTION_PROVIDER_INPUT_GATE,
            )
        canonical_tokens = pre_compaction_tokens
        if (
            history_summary_enabled
            and custom_history_metrics["history_candidate"]
            and (
                pre_compaction_tokens >= coding_history_gate
                or provider_input_inflated
                or (
                    metadata_budget_enabled
                    and compactable_metadata_bytes > CODING_CUSTOM_HISTORY_METADATA_MAX_BYTES
                )
            )
        ):
            custom_history_metrics.update(
                cls._summarize_coding_custom_history(
                    custom_entries, projected, metadata_budget_enabled=metadata_budget_enabled
                )
            )
            canonical_tokens = counted_token_count(projected)
            custom_history_metrics["compaction_tokens_before"] = pre_compaction_tokens
            custom_history_metrics["compaction_tokens_after"] = canonical_tokens
            logger.info(
                "coding_custom_history_compacted compacted_calls={} bytes_before={} "
                "bytes_after={} truncated_calls={} tokens_before={} tokens_after={}",
                custom_history_metrics["compacted_calls"],
                custom_history_metrics["bytes_before"],
                custom_history_metrics["bytes_after"],
                custom_history_metrics["truncated_calls"],
                pre_compaction_tokens,
                canonical_tokens,
            )
        feedback = cls._runtime_feedback(projected)
        if feedback is not None:
            projected.append(feedback)
        threshold = max(1, int(hard_cap * TASK_EXECUTION_CONTEXT_REBASE_THRESHOLD))
        projected_tokens = counted_token_count(projected)
        # benchmark 基线语义：摘要关闭时恢复旧行为——只要存在可压缩的已完成 custom
        # 历史就强制走窗口重建（不因低于阈值而保留完整旧历史），保证 G1 与 B0 生产
        # 基线同口径。摘要开启时低于门禁则原样保留。
        legacy_baseline_rebase = (
            not history_summary_enabled and custom_history_metrics["history_candidate"]
        )
        if (
            not legacy_baseline_rebase
            and not custom_history_metrics["metadata_budget_exceeded"]
            and not provider_input_inflated
            and canonical_tokens <= threshold
            and projected_tokens <= hard_cap
        ):
            metrics: dict[str, int | bool] = {
                "canonical_message_count": len(messages),
                "projected_message_count": len(projected),
                "canonical_estimated_tokens": canonical_tokens,
                "projected_estimated_tokens": projected_tokens,
                "input_token_hard_cap": hard_cap,
                "checkpoint_bytes": 0,
                "dropped_complete_rounds": 0,
                "window_rebased": False,
                **custom_history_metrics,
                **cls._composition_metrics(messages, projected, tools, response_format),
            }
            logger.debug(
                "context_projection_timing window_rebased={} message_count={} "
                "projection_ms={} count_calls={} count_ms={}",
                False,
                len(messages),
                duration_ms(projection_started_at),
                count_calls,
                count_duration_ms,
            )
            return projected, metrics

        system_messages = [message for message in projected if message.role == "system"]
        user_messages = [
            message
            for message in projected
            if message.role == "user"
            and not str(message.content or "").startswith(
                (
                    '{"marker":"TASK_EXECUTION_RUNTIME_FEEDBACK"',
                    '{"marker":"CODING_RUNTIME_FEEDBACK"',
                )
            )
        ]
        prefix = [*system_messages]
        if user_messages:
            prefix.append(user_messages[0])
            if user_messages[-1] is not user_messages[0]:
                prefix.append(user_messages[-1])
        checkpoint = ContextBudgetController._checkpoint(projected)
        checkpoint_message = Message(role="user", content=checkpoint)
        rounds = cls._complete_rounds(projected)

        protected_round_indexes: set[int] = set()
        if protected_call_ids:
            for idx, round_messages in enumerate(rounds):
                for message in round_messages:
                    if message.tool_calls:
                        for call in message.tool_calls:
                            if not isinstance(call, dict):
                                continue
                            call_ids = {
                                value
                                for key in ("id", "call_id")
                                if isinstance(value := call.get(key), str)
                            }
                            if call_ids & protected_call_ids:
                                protected_round_indexes.add(idx)
                                break

        incomplete_batches: list[list[Message]] = []
        idx = 0
        while idx < len(projected):
            message = projected[idx]
            if (
                message.role in {"assistant", "model"}
                and message.tool_calls
            ):
                call_identity_sets = [
                    {
                        identity
                        for key in ("call_id", "id")
                        if isinstance(identity := call.get(key), str)
                    }
                    for call in message.tool_calls
                    if isinstance(call, dict)
                ]
                all_identities = {
                    identity for identities in call_identity_sets for identity in identities
                }
                batch = [message]
                j = idx + 1
                while j < len(projected) and projected[j].role == "tool":
                    if projected[j].tool_call_id in all_identities:
                        batch.append(projected[j])
                    j += 1
                if not (
                    call_identity_sets
                    and all(
                        identities & {m.tool_call_id for m in batch[1:]}
                        for identities in call_identity_sets
                    )
                ):
                    incomplete_batches.append(batch)
                idx = j
            else:
                idx += 1

        protected_rounds = [
            round_messages
            for idx, round_messages in enumerate(rounds)
            if idx in protected_round_indexes
        ]
        recent_start = max(0, len(rounds) - TASK_EXECUTION_RECENT_ASSISTANT_TURNS)
        recent_rounds = [
            round_messages
            for idx, round_messages in enumerate(rounds)
            if idx >= recent_start and idx not in protected_round_indexes
        ]
        selected_rounds = [*protected_rounds, *recent_rounds]
        # 按原始位置归并 incomplete batch 与保留轮次：尾部 incomplete batch 不得
        # 被搬到比它更早完成的轮次之前，保持 wire 层时间序。
        message_positions = {id(message): index for index, message in enumerate(projected)}
        positioned = [
            (message_positions.get(id(group[0]), len(projected)), group)
            for group in [*incomplete_batches, *selected_rounds]
        ]
        positioned.sort(key=lambda item: item[0])
        candidate = [*prefix, checkpoint_message]
        for _position, group in positioned:
            candidate.extend(group)
        if feedback is not None:
            candidate.append(feedback)

        final_metadata_bytes = cls._coding_custom_history_metadata_bytes(candidate)
        custom_history_metrics["metadata_bytes"] = final_metadata_bytes
        custom_history_metrics["bytes_after"] = final_metadata_bytes
        custom_history_metrics["metadata_budget_exceeded"] = (
            metadata_budget_enabled
            and final_metadata_bytes > CODING_CUSTOM_HISTORY_METADATA_MAX_BYTES
        )

        target = max(1, int(hard_cap * TASK_EXECUTION_CONTEXT_REBASE_TARGET))
        deletable_start = len(protected_rounds)
        while (
            len(selected_rounds) > deletable_start
            and counted_token_count(candidate) > target
        ):
            removed = selected_rounds.pop(deletable_start)
            start = next(index for index, message in enumerate(candidate) if message is removed[0])
            del candidate[start : start + len(removed)]
        final_metadata_bytes = cls._coding_custom_history_metadata_bytes(candidate)
        custom_history_metrics["metadata_bytes"] = final_metadata_bytes
        custom_history_metrics["bytes_after"] = final_metadata_bytes
        custom_history_metrics["metadata_budget_exceeded"] = (
            metadata_budget_enabled
            and final_metadata_bytes > CODING_CUSTOM_HISTORY_METADATA_MAX_BYTES
        )
        projected_tokens = counted_token_count(candidate)
        if projected_tokens > hard_cap:
            metrics = {
                "canonical_message_count": len(messages),
                "projected_message_count": len(candidate),
                "canonical_estimated_tokens": canonical_tokens,
                "projected_estimated_tokens": projected_tokens,
                "irreducible_prefix_estimated_tokens": projected_tokens,
                "input_token_hard_cap": hard_cap,
                "checkpoint_bytes": len(checkpoint.encode("utf-8")),
                "dropped_complete_rounds": len(rounds) - len(selected_rounds),
                "window_rebased": True,
                **custom_history_metrics,
                **cls._composition_metrics(messages, candidate, tools, response_format),
            }
            model_id, host = _model_log_fields(counting_model)
            logger.bind(
                model_id=model_id,
                host=host,
                canonical_estimated_tokens=canonical_tokens,
                irreducible_prefix_estimated_tokens=projected_tokens,
                input_token_hard_cap=hard_cap,
                tool_schema_bytes=metrics["tool_schema_bytes"],
                response_format_bytes=metrics["response_format_bytes"],
                projected_context_bytes=metrics["projected_context_bytes"],
            ).error("task_execution_context_hard_limit_exceeded")
            raise TaskExecutionContextHardLimitError(
                "不可约简的任务执行上下文前缀与请求协议超过模型输入 hard cap。",
                metrics=metrics,
            )
        metrics = {
            "canonical_message_count": len(messages),
            "projected_message_count": len(candidate),
            "canonical_estimated_tokens": canonical_tokens,
            "projected_estimated_tokens": projected_tokens,
            "input_token_hard_cap": hard_cap,
            "checkpoint_bytes": len(checkpoint.encode("utf-8")),
            "dropped_complete_rounds": len(rounds) - len(selected_rounds),
            "window_rebased": True,
            **custom_history_metrics,
            **cls._composition_metrics(messages, candidate, tools, response_format),
        }
        logger.debug(
            "context_projection_timing window_rebased={} message_count={} "
            "projection_ms={} count_calls={} count_ms={} dropped_complete_rounds={}",
            True,
            len(messages),
            duration_ms(projection_started_at),
            count_calls,
            count_duration_ms,
            len(rounds) - len(selected_rounds),
        )
        return candidate, metrics

    @classmethod
    def project(
        cls,
        messages: list[Message],
        *,
        model: Any = None,
        tools: Any = None,
        response_format: Any = None,
        hard_cap: int = TASK_EXECUTION_CONTEXT_TOKEN_LIMIT - TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
    ) -> list[Message]:
        projected, _metrics = cls.project_with_metrics(
            messages,
            model=model,
            tools=tools,
            response_format=response_format,
            hard_cap=hard_cap,
        )
        return projected


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
        size <= TASK_EXECUTION_TOOL_BATCH_LIMIT
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
            if len(reads) == TASK_EXECUTION_TOOL_BATCH_LIMIT:
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


_TASK_EXECUTION_REQUEST_METRICS: ContextVar[dict[str, Any] | None] = ContextVar(
    "task_execution_request_metrics", default=None
)


class ProjectedOpenAIChat(OpenAIChat):
    _task_execution_input_token_budget: int | None = None

    def _project(self, messages: list[Message], args: tuple[Any, ...], kwargs: dict[str, Any]):
        response_format = kwargs.get("response_format", args[1] if len(args) > 1 else None)
        tools = kwargs.get("tools", args[2] if len(args) > 2 else None)
        hard_cap = getattr(self, _PROJECTED_INPUT_TOKEN_BUDGET_ATTR, None)
        if not isinstance(hard_cap, int) or hard_cap < 1:
            hard_cap = TASK_EXECUTION_CONTEXT_TOKEN_LIMIT - TASK_EXECUTION_OUTPUT_TOKEN_RESERVE
        return TaskExecutionContextProjector.project_with_metrics(
            messages,
            model=self,
            tools=tools,
            response_format=response_format,
            hard_cap=hard_cap,
        )

    def get_request_params(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        params = super().get_request_params(*args, **kwargs)
        metrics = _TASK_EXECUTION_REQUEST_METRICS.get()
        if metrics is not None:
            _set_current_span_attributes(metrics)
        return params

    def invoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        model_id, host = _model_log_fields(self)
        projected, metrics = self._project(messages, args, kwargs)
        token = _TASK_EXECUTION_REQUEST_METRICS.set(metrics)
        provider_started_at = perf_counter()
        failed = False
        interrupted = False
        try:
            return super().invoke(projected, *args, **kwargs)
        except BaseException as error:
            if not isinstance(error, Exception):
                interrupted = True
                raise
            failed = True
            logger.warning(
                "model_provider_request_failed mode=sync model_id={} host={} duration_ms={} "
                "error_type={}",
                model_id,
                host,
                duration_ms(provider_started_at),
                type(error).__name__,
            )
            raise
        finally:
            if not interrupted:
                logger.debug(
                    "model_provider_request_completed mode=sync model_id={} host={} duration_ms={} "
                    "failed={}",
                    model_id,
                    host,
                    duration_ms(provider_started_at),
                    str(failed).lower(),
                )
            _TASK_EXECUTION_REQUEST_METRICS.reset(token)

    async def ainvoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        model_id, host = _model_log_fields(self)
        projected, metrics = self._project(messages, args, kwargs)
        token = _TASK_EXECUTION_REQUEST_METRICS.set(metrics)
        provider_started_at = perf_counter()
        failed = False
        interrupted = False
        try:
            return await super().ainvoke(projected, *args, **kwargs)
        except BaseException as error:
            if not isinstance(error, Exception):
                interrupted = True
                raise
            failed = True
            logger.warning(
                "model_provider_request_failed mode=async model_id={} host={} duration_ms={} "
                "error_type={}",
                model_id,
                host,
                duration_ms(provider_started_at),
                type(error).__name__,
            )
            raise
        finally:
            if not interrupted:
                logger.debug(
                    "model_provider_request_completed mode=async model_id={} host={} duration_ms={} "
                    "failed={}",
                    model_id,
                    host,
                    duration_ms(provider_started_at),
                    str(failed).lower(),
                )
            _TASK_EXECUTION_REQUEST_METRICS.reset(token)

    def invoke_stream(self, messages: list[Message], *args: Any, **kwargs: Any) -> Iterator[Any]:
        model_id, host = _model_log_fields(self)
        projected, metrics = self._project(messages, args, kwargs)
        tool_calls: dict[int, dict[str, Any]] = {}
        token = _TASK_EXECUTION_REQUEST_METRICS.set(metrics)
        provider_started_at = perf_counter()
        first_chunk_ms: int | None = None
        chunk_count = 0
        failed = False
        interrupted = False
        try:
            for response in super().invoke_stream(projected, *args, **kwargs):
                chunk_count += 1
                if first_chunk_ms is None:
                    first_chunk_ms = duration_ms(provider_started_at)
                _update_stream_tool_calls(response, tool_calls)
                if tool_calls:
                    _set_current_span_attributes(_stream_tool_batch_attributes(tool_calls))
                yield response
        except BaseException as error:
            if not isinstance(error, Exception):
                interrupted = True
                raise
            failed = True
            logger.warning(
                "model_provider_stream_failed mode=sync model_id={} host={} duration_ms={} "
                "chunk_count={} error_type={}",
                model_id,
                host,
                duration_ms(provider_started_at),
                chunk_count,
                type(error).__name__,
            )
            raise
        finally:
            if not interrupted:
                logger.debug(
                    "model_provider_stream_completed mode=sync model_id={} host={} duration_ms={} "
                    "first_chunk_ms={} chunk_count={} failed={}",
                    model_id,
                    host,
                    duration_ms(provider_started_at),
                    first_chunk_ms if first_chunk_ms is not None else "-",
                    chunk_count,
                    str(failed).lower(),
                )
            _TASK_EXECUTION_REQUEST_METRICS.reset(token)

    async def ainvoke_stream(
        self, messages: list[Message], *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        model_id, host = _model_log_fields(self)
        projected, metrics = self._project(messages, args, kwargs)
        tool_calls: dict[int, dict[str, Any]] = {}
        token = _TASK_EXECUTION_REQUEST_METRICS.set(metrics)
        provider_started_at = perf_counter()
        first_chunk_ms: int | None = None
        chunk_count = 0
        failed = False
        interrupted = False
        try:
            async for response in super().ainvoke_stream(projected, *args, **kwargs):
                chunk_count += 1
                if first_chunk_ms is None:
                    first_chunk_ms = duration_ms(provider_started_at)
                _update_stream_tool_calls(response, tool_calls)
                if tool_calls:
                    _set_current_span_attributes(_stream_tool_batch_attributes(tool_calls))
                yield response
        except BaseException as error:
            if not isinstance(error, Exception):
                interrupted = True
                raise
            failed = True
            logger.warning(
                "model_provider_stream_failed mode=async model_id={} host={} duration_ms={} "
                "chunk_count={} error_type={}",
                model_id,
                host,
                duration_ms(provider_started_at),
                chunk_count,
                type(error).__name__,
            )
            raise
        finally:
            if not interrupted:
                logger.debug(
                    "model_provider_stream_completed mode=async model_id={} host={} duration_ms={} "
                    "first_chunk_ms={} chunk_count={} failed={}",
                    model_id,
                    host,
                    duration_ms(provider_started_at),
                    first_chunk_ms if first_chunk_ms is not None else "-",
                    chunk_count,
                    str(failed).lower(),
                )
            _TASK_EXECUTION_REQUEST_METRICS.reset(token)

    def run_function_calls(self, function_calls, function_call_results, *args, **kwargs):
        for batch in _tool_call_batches(function_calls):
            yield from super().run_function_calls(batch, function_call_results, *args, **kwargs)

    async def arun_function_calls(self, function_calls, function_call_results, *args, **kwargs):
        for batch in _tool_call_batches(function_calls):
            async for event in super().arun_function_calls(
                batch, function_call_results, *args, **kwargs
            ):
                yield event


def projected_task_execution_model(
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
