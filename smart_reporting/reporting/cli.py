"""直接执行顶层 Agno Reporting Workflow 的 CLI。"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import PurePosixPath
from time import monotonic
from typing import Any
from uuid import uuid4

from agno.run.base import RunStatus
from agno.workflow import OnReject
from loguru import logger
from pydantic import BaseModel

from ..async_utils import complete_cleanup
from ..runtime.execution import close_execution_resources, create_execution_context
from ..runtime.logging import configure_application_logging
from ..runtime.settings import AgentSettings
from .bootstrap import create_report_runtime
from .contract import REPORT_WORKFLOW_SCOPE_STATE_KEY, parse_reporting_workflow_input
from .models import ReportingError
from .workflow.scope import (
    REPORT_WORKFLOW_ENTRYPOINT_DEPENDENCY,
    REPORT_WORKFLOW_SCOPE_DEPENDENCY,
)
from .workflow.state import ReportingStateError

_CLI_PROGRESS_TOOLS = frozenset(
    {
        "complete_analysis_item",
        "finish_task",
        "render_report_section",
        "request_analysis_rework",
    }
)
_CLI_PROGRESS_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_CLI_PROGRESS_PATH_PATTERN = re.compile(r"^[A-Za-z0-9_./-]{1,512}$")
DEFAULT_TENANT_DATABASE = "default"
DEFAULT_TENANT_COMPANY_ID = "default"


def _write_cli_line(value: str) -> None:
    print(value, flush=True)


class _CliProgressSink:
    """把 Reporting Agent 流式事件转换为不含参数和结果正文的 CLI 进度。"""

    def __init__(
        self,
        write: Callable[[str], None],
        *,
        clock: Callable[[], float] = monotonic,
        interval_seconds: float = 30.0,
    ) -> None:
        self._write = write
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._last_write = clock()
        self._event_count = 0
        self._model_wait: dict[str, Any] | None = None

    @staticmethod
    def _safe_value(value: Any) -> str | None:
        text = value if isinstance(value, str) else ""
        return text if _CLI_PROGRESS_VALUE_PATTERN.fullmatch(text) else None

    @staticmethod
    def _safe_path(value: Any) -> str | None:
        if not isinstance(value, str) or not _CLI_PROGRESS_PATH_PATTERN.fullmatch(value):
            return None
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            return None
        return value

    def _write_fields(self, fields: list[str]) -> None:
        self._write(" ".join(["Reporting 进度:", *fields]))
        self._last_write = self._clock()

    def emit_log_record(self, message: Any) -> None:
        """只投影显式标记的结构化字段，不读取日志正文或工具参数。"""
        record = getattr(message, "record", None)
        extra = record.get("extra") if isinstance(record, dict) else None
        if not isinstance(extra, dict):
            return
        kind = extra.get("reporting_progress")
        status = self._safe_value(extra.get("status"))
        if kind == "workflow_step":
            step_id = self._safe_value(extra.get("step_id"))
            if step_id is not None and status is not None:
                self._write_fields([f"step={step_id}", f"status={status}"])
            return
        if kind == "code_model_request":
            model_id = self._safe_value(extra.get("model_id"))
            request_index = extra.get("request_index")
            request_limit = extra.get("request_limit")
            if (
                model_id is None
                or status is None
                or isinstance(request_index, bool)
                or not isinstance(request_index, int)
                or isinstance(request_limit, bool)
                or not isinstance(request_limit, int)
                or request_index < 1
                or request_limit < request_index
            ):
                return
            fields = [
                f"model={model_id}",
                f"request={request_index}/{request_limit}",
                f"status={'waiting' if status == 'started' else status}",
            ]
            if status == "started":
                started_at = self._clock()
                self._model_wait = {
                    "model_id": model_id,
                    "request_index": request_index,
                    "request_limit": request_limit,
                    "started_at": started_at,
                }
                fields.append("elapsed=0s")
            else:
                self._model_wait = None
                duration_ms = extra.get("duration_ms")
                if isinstance(duration_ms, int) and not isinstance(duration_ms, bool):
                    fields.append(f"duration={max(0, duration_ms) / 1000:.1f}s")
            self._write_fields(fields)
            return
        if kind == "code_tool":
            tool_name = self._safe_value(extra.get("tool_name"))
            if tool_name is None or status is None:
                return
            fields = [f"tool={tool_name}", f"status={status}"]
            path = self._safe_path(extra.get("path"))
            if path is not None:
                fields.append(f"path={path}")
            code = self._safe_value(extra.get("code"))
            if code is not None:
                fields.append(f"code={code}")
            self._write_fields(fields)

    def emit_heartbeat(self) -> None:
        waiting = self._model_wait
        if waiting is None:
            return
        current = self._clock()
        if current - self._last_write < self._interval_seconds:
            return
        elapsed = max(0, round(current - waiting["started_at"]))
        self._write_fields(
            [
                f"model={waiting['model_id']}",
                f"request={waiting['request_index']}/{waiting['request_limit']}",
                "status=waiting",
                f"elapsed={elapsed}s",
            ]
        )

    async def emit_reporting_event(
        self, _scope: Any, _workflow_run_id: str, raw_event: Any
    ) -> None:
        event_value = getattr(raw_event, "event", None) or getattr(raw_event, "type", None)
        event_type = str(getattr(event_value, "value", event_value) or "")
        phase = {
            "toolcallcompleted": "completed",
            "toolcallerror": "error",
        }.get(event_type.replace("_", "").lower())
        tool = getattr(raw_event, "tool", None)
        tool_name = str(getattr(tool, "tool_name", "") or "")
        if phase is None or not _CLI_PROGRESS_VALUE_PATTERN.fullmatch(tool_name):
            return
        if bool(getattr(tool, "tool_call_error", False)):
            phase = "error"
        result = getattr(tool, "result", None)
        code: str | None = None
        analysis_id: str | None = None
        if isinstance(result, dict):
            if result.get("ok") is False:
                phase = "rejected"
            elif result.get("ok") is True:
                phase = "accepted"
            raw_code = result.get("code")
            if isinstance(raw_code, str) and _CLI_PROGRESS_VALUE_PATTERN.fullmatch(raw_code):
                code = raw_code
            raw_analysis_id = result.get("analysisId")
            if isinstance(raw_analysis_id, str) and _CLI_PROGRESS_VALUE_PATTERN.fullmatch(
                raw_analysis_id
            ):
                analysis_id = raw_analysis_id

        self._event_count += 1
        current = self._clock()
        if (
            tool_name not in _CLI_PROGRESS_TOOLS
            and phase not in {"error", "rejected"}
            and current - self._last_write < self._interval_seconds
        ):
            return
        fields = [
            "Reporting 进度:",
            f"tool={tool_name}",
            f"status={phase}",
            f"events={self._event_count}",
        ]
        if analysis_id is not None:
            fields.append(f"analysisId={analysis_id}")
        if code is not None:
            fields.append(f"code={code}")
        self._write(" ".join(fields))
        self._last_write = current


async def _emit_cli_progress_heartbeats(
    sink: _CliProgressSink, interval_seconds: float
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        sink.emit_heartbeat()


@asynccontextmanager
async def _bind_cli_progress(
    sink: _CliProgressSink,
    *,
    heartbeat_interval_seconds: float = 1.0,
):
    sink_id = logger.add(
        sink.emit_log_record,
        filter=lambda record: bool(record["extra"].get("reporting_progress")),
    )
    heartbeat = asyncio.create_task(
        _emit_cli_progress_heartbeats(sink, heartbeat_interval_seconds)
    )
    try:
        yield
    finally:
        logger.remove(sink_id)
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)


def _cli_settings(settings: AgentSettings, *, debug: bool) -> AgentSettings:
    return settings if settings.debug is debug else replace(settings, debug=debug)


def read_report_input(*, read: Callable[[str], str] = input) -> str:
    lines: list[str] = []
    while True:
        line = read("" if lines else "自然语言或 ReportRequestEnvelope JSON（/run 提交）:\n")
        if line.strip() == "/run":
            break
        lines.append(line)
    value = "\n".join(lines).strip()
    if not value:
        raise ReportingError("report_request_invalid", "报表请求不能为空。")
    return value


def parse_report_input(value: str) -> dict[str, Any]:
    request = parse_reporting_workflow_input(value)
    return request.model_dump(mode="json", by_alias=True, exclude_none=True)


def resolve_requirement(
    requirement: Any,
    *,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> str:
    content = getattr(getattr(requirement, "step_output", None), "content", None)
    if isinstance(content, BaseModel):
        content = content.model_dump(mode="json", by_alias=True)
    message = str(getattr(requirement, "output_review_message", "") or "请审核工作流输出。")
    write(message)
    if content is not None:
        write(json.dumps(content, ensure_ascii=False, indent=2, default=str))

    if (
        str(getattr(requirement, "step_id", "")) == "normalize-report-request"
        and isinstance(content, dict)
        and content.get("clarificationQuestion")
    ):
        feedback = read("提交补充信息: ").strip()
        if not feedback:
            raise ValueError("补充信息不能为空。")
        requirement.reject(feedback=feedback)
        return "continue"

    if str(getattr(requirement, "step_id", "")) != "generate-outline":
        requirement.confirm()
        return "continue"

    action = read("批准 [a] / 拒绝 [r] / 取消 [c]: ").strip().lower()
    if action == "a":
        requirement.confirm()
        return "continue"
    if action == "r":
        feedback = read("修改意见: ").strip()
        if not feedback:
            raise ValueError("拒绝时必须提供修改意见。")
        requirement.reject(feedback=feedback)
        return "continue"
    if action == "c":
        requirement.on_reject = OnReject.cancel
        requirement.reject(feedback="用户取消报表工作流。")
        return "cancel"
    raise ValueError("未知审核操作。")


@asynccontextmanager
async def _workflow_execution_lock(runtime: Any, run_id: str):
    repository = getattr(runtime, "state_repository", None)
    lock = getattr(repository, "workflow_execution_lock", None)
    if not callable(lock):
        raise ReportingError(
            "report_workflow_runtime_invalid", "Reporting runtime 缺少 workflow 执行锁。"
        )
    try:
        async with lock(run_id):
            yield
    except ReportingStateError as error:
        raise ReportingError(error.code, error.message) from error


async def drive_workflow(
    workflow: Any,
    runtime: Any,
    report_input: dict[str, Any],
    *,
    run_id: str,
    session_id: str,
    user_id: str,
    database: str | None = None,
    company_id: str | None = None,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> dict[str, Any]:
    if bool(database) != bool(company_id):
        raise ReportingError(
            "report_workflow_context_missing", "租户 database 和 companyId 必须同时提供。"
        )
    database = database or DEFAULT_TENANT_DATABASE
    company_id = company_id or DEFAULT_TENANT_COMPANY_ID
    async with _workflow_execution_lock(runtime, run_id):
        return await _drive_workflow_unlocked(
            workflow,
            report_input,
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            database=database,
            company_id=company_id,
            read=read,
            write=write,
        )


async def _drive_workflow_unlocked(
    workflow: Any,
    report_input: dict[str, Any],
    *,
    run_id: str,
    session_id: str,
    user_id: str,
    database: str,
    company_id: str,
    read: Callable[[str], str],
    write: Callable[[str], None],
) -> dict[str, Any]:
    scope = {
        "externalRunId": run_id,
        "threadId": session_id,
        "userId": user_id,
        "database": database,
        "companyId": company_id,
    }
    dependencies = {
        REPORT_WORKFLOW_SCOPE_DEPENDENCY: scope,
        REPORT_WORKFLOW_ENTRYPOINT_DEPENDENCY: "cli",
    }
    output = await workflow.arun(
        report_input,
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        session_state={REPORT_WORKFLOW_SCOPE_STATE_KEY: scope},
        dependencies=dependencies,
        stream=False,
    )
    output = await _continue_workflow_reviews(
        workflow,
        output,
        dependencies=dependencies,
        read=read,
        write=write,
        retry_delivery_error=True,
    )

    status = _status(output)
    content = getattr(output, "content", None)
    return {
        "status": status,
        "runId": run_id,
        "sessionId": session_id,
        "content": content,
    }


async def _continue_workflow_reviews(
    workflow: Any,
    output: Any,
    *,
    dependencies: dict[str, Any],
    read: Callable[[str], str],
    write: Callable[[str], None],
    retry_delivery_error: bool,
) -> Any:
    delivery_retries = 0
    while _status(output) == "paused":
        error_requirements = list(getattr(output, "error_requirements", None) or [])
        unresolved_errors = [
            item for item in error_requirements if not bool(getattr(item, "is_resolved", False))
        ]
        if unresolved_errors:
            requirement = unresolved_errors[-1]
            step_id = str(getattr(requirement, "step_id", ""))
            if step_id not in {"assemble-report", "validate-report"}:
                raise ReportingError(
                    "report_workflow_resume_unsupported",
                    "仅支持恢复最终汇编或 PDF/Word 双格式验收步骤。",
                )
            if not retry_delivery_error or delivery_retries >= 1:
                break
            step_label = "最终报告汇编" if step_id == "assemble-report" else "PDF/Word 双格式验收"
            write(f"{step_label}失败，正在基于同一持久化 run 重试末端步骤。")
            requirement.retry()
            delivery_retries += 1
            output = await workflow.acontinue_run(
                run_response=output,
                dependencies=dependencies,
                stream=False,
            )
            continue
        requirements = list(getattr(output, "step_requirements", None) or [])
        unresolved = [
            item for item in requirements if not bool(getattr(item, "is_resolved", False))
        ]
        if not unresolved:
            raise ReportingError("report_workflow_review_invalid", "报表工作流没有待处理审核项。")
        resolve_requirement(unresolved[-1], read=read, write=write)
        output = await workflow.acontinue_run(
            run_response=output,
            step_requirements=requirements,
            dependencies=dependencies,
            stream=False,
        )
    return output


async def resume_workflow(
    workflow: Any,
    runtime: Any,
    *,
    run_id: str,
    session_id: str,
    user_id: str,
    database: str,
    company_id: str,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> dict[str, Any]:
    """显式恢复同一 Agno run，不创建新 run。"""

    if bool(database) != bool(company_id):
        raise ReportingError(
            "report_workflow_context_missing", "租户 database 和 companyId 必须同时提供。"
        )
    database = database or DEFAULT_TENANT_DATABASE
    company_id = company_id or DEFAULT_TENANT_COMPANY_ID

    async with _workflow_execution_lock(runtime, run_id):
        return await _resume_workflow_unlocked(
            workflow,
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            database=database,
            company_id=company_id,
            read=read,
            write=write,
        )


async def _resume_workflow_unlocked(
    workflow: Any,
    *,
    run_id: str,
    session_id: str,
    user_id: str,
    database: str,
    company_id: str,
    read: Callable[[str], str],
    write: Callable[[str], None],
) -> dict[str, Any]:
    output = await workflow.aget_run_output(
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
    )
    if output is None:
        raise ReportingError("report_workflow_run_not_found", "找不到指定的 Reporting run。")
    status = _status(output)
    if status not in {"paused", "running"}:
        raise ReportingError(
            "report_workflow_resume_invalid",
            "指定 Reporting run 当前不是可恢复暂停或中断状态。",
        )
    scope = {
        "externalRunId": run_id,
        "threadId": session_id,
        "userId": user_id,
        "database": database,
        "companyId": company_id,
    }
    dependencies = {
        REPORT_WORKFLOW_SCOPE_DEPENDENCY: scope,
        REPORT_WORKFLOW_ENTRYPOINT_DEPENDENCY: "cli",
    }

    if status == "running":
        # Agno Workflow 2.8.2 只允许 acontinue_run 接收 PAUSED，但进程被终止时
        # 数据库保留的最后 checkpoint 是 RUNNING。这里只转换同一持久化 run 的
        # 执行态，由 Agno 已保存的 step results 决定续点。
        output.status = RunStatus.paused
        output = await workflow.acontinue_run(
            run_response=output,
            dependencies=dependencies,
            stream=False,
        )
    output = await _continue_workflow_reviews(
        workflow,
        output,
        dependencies=dependencies,
        read=read,
        write=write,
        retry_delivery_error=True,
    )
    status = _status(output)
    return {
        "status": status,
        "runId": run_id,
        "sessionId": session_id,
        "content": getattr(output, "content", None),
    }


async def run_cli(
    *,
    settings: AgentSettings | None = None,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = _write_cli_line,
    resume_run_id: str | None = None,
    resume_session_id: str | None = None,
    database: str | None = None,
    company_id: str | None = None,
    debug: bool = True,
) -> dict[str, Any]:
    if (resume_run_id is None) != (resume_session_id is None):
        raise ReportingError(
            "report_workflow_resume_invalid",
            "恢复时必须同时提供 runId 和 sessionId。",
        )
    if bool(database) != bool(company_id):
        raise ReportingError(
            "report_workflow_context_missing", "租户 database 和 companyId 必须同时提供。"
        )
    database = database or DEFAULT_TENANT_DATABASE
    company_id = company_id or DEFAULT_TENANT_COMPANY_ID
    report_input = (
        None if resume_run_id is not None else parse_report_input(read_report_input(read=read))
    )
    current_settings = settings or AgentSettings.from_environment()
    current_settings = _cli_settings(current_settings, debug=debug)
    context = create_execution_context(current_settings)
    progress_sink = _CliProgressSink(write)
    reporting_agent_template, runtime = create_report_runtime(context, context.settings)
    workflow = runtime.workflow()
    run_id = resume_run_id or f"cli-report-{uuid4().hex}"
    session_id = resume_session_id or f"cli-report-{uuid4().hex}"
    try:
        async with _bind_cli_progress(progress_sink):
            if resume_run_id is not None:
                result = await resume_workflow(
                    workflow,
                    runtime,
                    run_id=run_id,
                    session_id=session_id,
                    user_id="cli",
                    database=database,
                    company_id=company_id,
                    read=read,
                    write=write,
                )
            else:
                assert report_input is not None
                result = await drive_workflow(
                    workflow,
                    runtime,
                    report_input,
                    run_id=run_id,
                    session_id=session_id,
                    user_id="cli",
                    database=database,
                    company_id=company_id,
                    read=read,
                    write=write,
                )
        write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        await complete_cleanup(close_execution_resources(context, reporting_agent_template))
    return result


def _status(output: Any) -> str:
    value = getattr(output, "status", None)
    normalized = value.value if isinstance(value, RunStatus) else str(value or "")
    status = normalized.lower()
    return "failed" if status in {"error", "failed"} else status


def main(argv: list[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        parser = argparse.ArgumentParser(description="运行或恢复 Reporting CLI。")
        parser.add_argument("--resume-run-id")
        parser.add_argument("--resume-session-id")
        parser.add_argument("--tenant-database")
        parser.add_argument("--tenant-company-id")
        parser.add_argument(
            "--debug",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="启用详细调试日志（默认启用，使用 --no-debug 关闭）。",
        )
        parsed = parser.parse_args(arguments)
        configure_application_logging(debug=parsed.debug)
        result = asyncio.run(
            run_cli(
                resume_run_id=parsed.resume_run_id,
                resume_session_id=parsed.resume_session_id,
                database=parsed.tenant_database,
                company_id=parsed.tenant_company_id,
                debug=parsed.debug,
            )
        )
        if result.get("status") != "completed":
            raise SystemExit(1)
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
