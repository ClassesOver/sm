import asyncio
import hashlib
import json
import logging
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from ag_ui.core import Context
from agno.compression.manager import CompressionManager
from agno.models.message import Message
from agno.session.summary import SessionSummary, SessionSummaryManager
from agno.session.team import TeamSession
from pydantic import BaseModel, ConfigDict, Field, ValidationError

HISTORY_CONTEXT_DESCRIPTION = "AgentOS 预算历史（非权威）"
MAX_SUMMARY_TOKENS = 4096
MIN_COMPRESSION_CHARS = 2000
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
_STALE_ODOO_HISTORY = re.compile(
    r"snapshotId|hostRevision|modifiers|[\"']?token[\"']?\s*[:=]",
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
    r"snapshotId|hostRevision|modifiers|(?:authorization\s+token)|授权\s*token|"
    r"[\"']?token[\"']?\s*[:=]",
    re.IGNORECASE,
)
logger = logging.getLogger(__name__)


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


def _normalized_run(run: Any) -> dict[str, Any] | None:
    messages: list[dict[str, str]] = []
    for message in getattr(run, "messages", None) or []:
        role = str(getattr(message, "role", "") or "")
        content = _message_text(message)
        if role == "user":
            content = _strip_stale_context(content)
        elif role in {"assistant", "model"}:
            role = "assistant"
        elif role == "tool":
            tool_name = str(getattr(message, "tool_name", "") or "")
            if tool_name not in COMPRESSIBLE_HISTORY_TOOLS:
                continue
            role = f"tool:{tool_name}"
        else:
            continue
        if content and not _STALE_ODOO_HISTORY.search(content):
            messages.append({"role": role, "content": content})
    if not messages:
        return None
    return {"runId": str(getattr(run, "run_id", "") or ""), "messages": messages}


def _fallback_token_count(value: str) -> int:
    return max(1, (len(value.encode("utf-8")) + 1) // 2)


def _count_text_tokens(model: Any, value: str) -> int | None:
    try:
        return int(model.count_tokens([Message(role="user", content=value)]))
    except Exception:
        return None


def _encoded_run(run: Any) -> tuple[dict[str, Any], str] | None:
    normalized = _normalized_run(run)
    if normalized is None:
        return None
    return normalized, json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def _latest_fallback_run(runs: list[Any], remaining: int) -> list[dict[str, Any]]:
    for run in reversed(runs):
        if _status_value(run) not in {"completed", ""}:
            continue
        encoded_run = _encoded_run(run)
        if encoded_run is None:
            continue
        normalized, encoded = encoded_run
        if _fallback_token_count(encoded) <= remaining:
            return [normalized]
    return []


def _session_history_runs(session: Any) -> list[Any]:
    runs = list(getattr(session, "runs", None) or [])
    if isinstance(session, TeamSession):
        return [run for run in runs if getattr(run, "parent_run_id", None) is None]
    return runs


def build_history_context(
    session: Any,
    model: Any,
    *,
    history_token_budget: int,
    include_summary: bool = True,
    status: dict[str, Any] | None = None,
) -> Context | None:
    summary_value = (
        str(getattr(getattr(session, "summary", None), "summary", "") or "").strip()
        if include_summary
        else ""
    )
    summary_tokens = _count_text_tokens(model, summary_value) if summary_value else 0
    token_count_failed = summary_tokens is None
    if summary_tokens is None:
        summary_tokens = _fallback_token_count(summary_value)
    if summary_tokens > min(MAX_SUMMARY_TOKENS, history_token_budget):
        summary_value = ""
        summary_tokens = 0

    remaining = max(0, history_token_budget - summary_tokens)
    runs = _session_history_runs(session)
    if token_count_failed:
        fallback_selected = _latest_fallback_run(runs, remaining)
        if status is not None:
            fallback_tokens = sum(
                _fallback_token_count(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
                for item in fallback_selected
            )
            _set_history_status(
                status,
                session=session,
                budget=history_token_budget,
                used=min(history_token_budget, summary_tokens + fallback_tokens),
                summary_included=bool(summary_value),
                selected_run_count=len(fallback_selected),
                reliable=False,
            )
        return _history_context(summary_value, fallback_selected)

    selected: list[dict[str, Any]] = []
    for run in reversed(runs):
        if _status_value(run) not in {"completed", ""}:
            continue
        encoded_run = _encoded_run(run)
        if encoded_run is None:
            continue
        normalized, encoded = encoded_run
        tokens = _count_text_tokens(model, encoded)
        if tokens is None:
            selected = _latest_fallback_run(runs, remaining)
            if status is not None:
                fallback_tokens = sum(
                    _fallback_token_count(
                        json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                    )
                    for item in selected
                )
                _set_history_status(
                    status,
                    session=session,
                    budget=history_token_budget,
                    used=min(history_token_budget, summary_tokens + fallback_tokens),
                    summary_included=bool(summary_value),
                    selected_run_count=len(selected),
                    reliable=False,
                )
            return _history_context(summary_value, selected)
        if tokens > remaining:
            continue
        selected.append(normalized)
        remaining -= tokens

    selected.reverse()
    if status is not None:
        _set_history_status(
            status,
            session=session,
            budget=history_token_budget,
            used=history_token_budget - remaining,
            summary_included=bool(summary_value),
            selected_run_count=len(selected),
            reliable=True,
        )
    return _history_context(summary_value, selected)


def _set_history_status(
    status: dict[str, Any],
    *,
    session: Any,
    budget: int,
    used: int,
    summary_included: bool,
    selected_run_count: int,
    reliable: bool,
) -> None:
    metadata = getattr(session, "session_data", None)
    summary_metadata = metadata.get(SUMMARY_METADATA_KEY, {}) if isinstance(metadata, dict) else {}
    status.clear()
    status.update(
        {
            "historyTokenBudget": budget,
            "historyTokensUsed": used,
            "historyTokensRemaining": max(0, budget - used),
            "summaryIncluded": summary_included,
            "summaryVersion": int(summary_metadata.get("version") or 0)
            if isinstance(summary_metadata, dict)
            else 0,
            "selectedRunCount": selected_run_count,
            "tokenCountReliable": reliable,
        }
    )


def _history_context(summary_value: str, selected: list[dict[str, Any]]) -> Context | None:
    if not summary_value and not selected:
        return None
    payload = {
        "authoritative": False,
        "notice": "仅用于理解历史意图；页面事实必须使用本轮最新 HRP 宿主快照。",
        "summary": summary_value or None,
        "runs": selected,
    }
    return Context(
        description=HISTORY_CONTEXT_DESCRIPTION,
        value=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


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
                "压缩分析工具输出。只总结关键发现，不推导权限、Odoo 页面状态或标识符；"
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
        for message in messages:
            if not self._eligible(message):
                continue
            compressed = self._compress_tool_result(message, run_metrics=run_metrics)
            if compressed:
                message.compressed_content = compressed

    async def acompress(self, messages, run_metrics=None):
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


async def build_budgeted_history_context(
    session: Any,
    model: Any,
    *,
    history_token_budget: int,
    compression_manager: ProtectedCompressionManager | None,
    include_summary: bool = True,
    status: dict[str, Any] | None = None,
) -> tuple[Context | None, bool]:
    changed = False
    if compression_manager is not None:
        originals: list[Message] = []
        tasks = []
        for run in _session_history_runs(session):
            if _status_value(run) not in {"completed", ""}:
                continue
            for message in getattr(run, "messages", None) or []:
                if (
                    message.role == "tool"
                    and message.tool_name in COMPRESSIBLE_HISTORY_TOOLS
                    and message.compressed_content is None
                    and len(str(message.content or "")) >= MIN_COMPRESSION_CHARS
                ):
                    originals.append(message)
                    tasks.append(compression_manager.compress_history_message(message))
        candidates = await asyncio.gather(*tasks) if tasks else []
        for original, candidate in zip(originals, candidates):
            if candidate.compressed_content:
                original.compressed_content = candidate.compressed_content
                changed = True

    return (
        build_history_context(
            session,
            model,
            history_token_budget=history_token_budget,
            include_summary=include_summary,
            status=status,
        ),
        changed,
    )


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
            if content and not _STALE_ODOO_HISTORY.search(content):
                messages.append({"role": role, "content": content})
    return messages


def _parse_rolling_summary(response: Any) -> RollingSummaryResponse | None:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, RollingSummaryResponse):
        return parsed
    content = getattr(response, "content", None)
    if not isinstance(content, str):
        return None
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
                    "完成事项和待办事项；不得包含或推导 Odoo 当前记录值、权限状态、"
                    "snapshotId、hostRevision、授权 token 或 modifiers。"
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
            logger.warning("rolling_summary_failed error_type=%s", type(error).__name__)
            return getattr(session, "summary", None)
        if payload is None:
            logger.warning("rolling_summary_invalid")
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
            logger.warning("rolling_summary_failed error_type=%s", type(error).__name__)
            return getattr(session, "summary", None)
        if payload is None:
            logger.warning("rolling_summary_invalid")
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
