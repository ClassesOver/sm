"""复用已持久化输入定向重放图表 Coding Agent，不重跑数据准备。"""

# ruff: noqa: E402 - 直接运行脚本时先把仓库根目录加入模块搜索路径。

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools.workspace import Workspace
from pydantic import ValidationError

from smart_reporting.integrations.model_config import (
    OPENAI_COMPATIBLE_ROLE_MAP,
    is_dashscope_endpoint,
)
from smart_reporting.reporting.agent import create_reporting_code_agent_factory
from smart_reporting.reporting.bootstrap import (
    _VISUALIZATION_CODE_INSTRUCTIONS,
    _VISUALIZATION_CODE_LEGACY_INSTRUCTIONS,
)
from smart_reporting.reporting.code_agent.context import (
    ExecutionReceipt,
    ReportingCodingTaskContext,
)
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_mode import create_reporting_code_mode_runtime
from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingWorkspaceIdentity,
)
from smart_reporting.reporting.structured_output import ReportingStructuredOutputExecutor
from smart_reporting.reporting.vision import ReportVisionReviewer
from smart_reporting.reporting.workflow.benchmark_bundle import (
    BenchmarkModelConfig,
    prepare_frozen_planner_coding_bundle,
    validate_frozen_planner_coding_bundle,
)
from smart_reporting.reporting.workflow.benchmark_execution import (
    build_benchmark_planner_agent,
    prepare_benchmark_coding_payload,
)
from smart_reporting.reporting.workflow.benchmark_variants import (
    BenchmarkVariant,
    LegacyAnalysisEvidenceDecision,
)
from smart_reporting.reporting.workflow.runtime.analysis import (
    visualization_coding_facts,
    visualization_read_paths,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    MAX_SUPPLEMENTAL_EVIDENCE_BYTES,
    _compact_existing_facts,
    supplemental_evidence_schema_error,
    validate_supplemental_evidence,
)
from smart_reporting.reporting.workflow.runtime.base import (
    _ANALYSIS_CODE_INSTRUCTIONS,
    _ANALYSIS_CODE_LEGACY_INSTRUCTIONS,
)
from smart_reporting.reporting.workflow.runtime.code_generation import (
    REPORTING_CODING_TASK_CONTEXT_METADATA_KEY,
    ReportingCodeGenerationRunner,
)
from smart_reporting.reporting.workflow.runtime.phase_models import VisualizationPlanDraft
from smart_reporting.runtime.database import psycopg_db_url
from smart_reporting.runtime.logging import configure_application_logging
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.task_execution import TaskExecutionScope


class ReplayObservedOpenAIChat(OpenAIChat):
    """仅为冻结回放保留 provider 逐请求状态，不改变请求参数或重试。"""

    def _request_metrics_sink(self) -> list[dict[str, Any]]:
        sink = self.__dict__.get("_reporting_replay_request_metrics")
        if not isinstance(sink, list):
            sink = []
            self.__dict__["_reporting_replay_request_metrics"] = sink
        return sink

    def replay_request_metrics(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._request_metrics_sink()]

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        sink = self._request_metrics_sink()
        metric: dict[str, Any] = {
            "requestIndex": len(sink) + 1,
            "providerRequestId": "unknown",
            "durationMs": "unknown",
            "inputTokens": "unknown",
            "outputTokens": "unknown",
            "reasoningTokens": "unknown",
            "cacheReadTokens": "unknown",
            "status": "started",
        }
        sink.append(metric)
        started_at = perf_counter()
        try:
            response = await super().ainvoke(*args, **kwargs)
        except Exception:
            metric.update(
                durationMs=max(0, round((perf_counter() - started_at) * 1000)),
                status="failed",
            )
            raise
        usage = getattr(response, "response_usage", None)
        provider_data = getattr(response, "provider_data", None)
        provider_request_id = (
            provider_data.get("id") if isinstance(provider_data, Mapping) else None
        )
        metric.update(
            providerRequestId=(
                provider_request_id
                if isinstance(provider_request_id, str) and provider_request_id
                else "unknown"
            ),
            durationMs=max(0, round((perf_counter() - started_at) * 1000)),
            inputTokens=(
                usage.input_tokens if usage is not None else "unknown"
            ),
            outputTokens=(
                usage.output_tokens if usage is not None else "unknown"
            ),
            reasoningTokens=(
                usage.reasoning_tokens if usage is not None else "unknown"
            ),
            cacheReadTokens=(
                usage.cache_read_tokens if usage is not None else "unknown"
            ),
            status="completed",
        )
        return response


@dataclass(frozen=True, slots=True)
class CodingOnlyBenchmarkLink:
    payload: dict[str, Any]
    model_config: BenchmarkModelConfig
    task_kind: Literal["analysis"] = "analysis"
    benchmark_mode: Literal["coding-only"] = "coding-only"


class ReplayWallTimeout(TimeoutError):
    """显式回放预算耗尽；不代表生产模型请求自动重试。"""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        super().__init__(f"replay wall timeout after {seconds:g}s")


async def run_with_wall_timeout(awaitable, *, seconds: float | None):
    if seconds is None:
        return await awaitable
    if seconds <= 0:
        raise ValueError("wall timeout 必须为正数")
    task = asyncio.ensure_future(awaitable)
    done, _ = await asyncio.wait({task}, timeout=seconds)
    if not done:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        raise ReplayWallTimeout(seconds)
    return await task


async def run_frozen_benchmark_planner(
    bundle_dir: Path,
    *,
    variant: BenchmarkVariant,
    model: OpenAIChat,
    metrics_sink: list[dict] | None = None,
) -> tuple[dict, list[dict], dict]:
    """执行冻结章节的 planner，并返回可直接交给现有 Coding replay 的 payload。"""

    manifest, payloads = validate_frozen_planner_coding_bundle(bundle_dir)
    _, planner = build_benchmark_planner_agent(
        model=model,
        task_kind=manifest.task_kind,
        variant=variant,
    )
    coding_payload = payloads["executionContext"].get("codingPayload")
    task = coding_payload.get("task") if isinstance(coding_payload, dict) else None
    task_id = task.get("task_id") if isinstance(task, dict) else None
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("benchmark executionContext 缺少 Coding task_id")
    planner_metrics: list[dict] = metrics_sink if metrics_sink is not None else []
    metrics_start = len(planner_metrics)

    def record_metrics(output, requests: int) -> None:
        metrics = getattr(output, "metrics", None)
        planner_metrics.append(
            {
                "requests": requests,
                "inputTokens": getattr(metrics, "input_tokens", None),
                "outputTokens": getattr(metrics, "output_tokens", None),
                "reasoningTokens": getattr(metrics, "reasoning_tokens", None),
                "status": "completed",
            }
        )

    run_context = RunContext(
        run_id=f"benchmark-{task_id}-{variant.value}",
        session_id=f"benchmark-{task_id}-{variant.value}",
        session_state={},
    )
    planner_started = perf_counter()
    try:
        planner_output = await ReportingStructuredOutputExecutor(planner).run(
            json.dumps(payloads["plannerRequest"], ensure_ascii=False, separators=(",", ":")),
            scope=TaskExecutionScope(
                task_id,
                "benchmark-user",
                "benchmark-thread",
                "benchmark-sandbox",
                f"benchmark-{manifest.task_kind}-planner",
            ),
            run_context=run_context,
            model_metrics_recorder=record_metrics,
        )
    except Exception:
        planner_duration_ms = max(0, round((perf_counter() - planner_started) * 1000))
        if len(planner_metrics) > metrics_start:
            planner_metrics[-1]["durationMs"] = planner_duration_ms
            planner_metrics[-1]["status"] = "failed"
        else:
            planner_metrics.append({
                "requests": 0,
                "inputTokens": None,
                "outputTokens": None,
                "reasoningTokens": None,
                "durationMs": planner_duration_ms,
                "status": "failed",
            })
        raise
    if manifest.task_kind == "analysis" and planner_metrics:
        requires_evidence = getattr(
            planner_output, "requires_supplemental_evidence", None
        )
        requirements = getattr(planner_output, "coding_requirements", ())
        if isinstance(requires_evidence, bool):
            planner_metrics[-1]["plannerDecision"] = {
                "requiresSupplementalEvidence": requires_evidence,
                "codingRequirementCount": (
                    len(requirements) if isinstance(requirements, (list, tuple)) else 0
                ),
            }
    planner_duration_ms = max(0, round((perf_counter() - planner_started) * 1000))
    if len(planner_metrics) > metrics_start:
        planner_metrics[-1]["durationMs"] = planner_duration_ms
    else:
        planner_metrics.append(
            {
                "requests": 0,
                "inputTokens": None,
                "outputTokens": None,
                "reasoningTokens": None,
                "durationMs": planner_duration_ms,
            }
        )
    payload = prepare_benchmark_coding_payload(
        task_kind=manifest.task_kind,
        variant=variant,
        execution_context=payloads["executionContext"],
        acceptance=payloads["acceptance"],
        planner_output=planner_output,
    )
    return payload, planner_metrics, manifest.model_dump(mode="json", by_alias=True)


def build_replay_model(
    settings,
    *,
    reasoning_effort: str,
    benchmark_model_config: BenchmarkModelConfig | None = None,
    benchmark_stage: Literal["planner", "coding"] = "coding",
) -> OpenAIChat:
    """按冻结配置构造 Chat 外壳，并保留 Coding Responses 专用参数。"""

    config = benchmark_model_config
    effort = (
        (
            config.planner_reasoning_effort or config.reasoning_effort
            if benchmark_stage == "planner"
            else config.reasoning_effort
        )
        if config is not None
        else reasoning_effort
    )
    if config is not None:
        dashscope = is_dashscope_endpoint(settings.openai_base_url)
        if (config.enable_thinking_location == "top_level") != dashscope and (
            config.enable_thinking_location != "chat_template_kwargs"
        ):
            raise ValueError(
                "benchmark enableThinkingLocation 与 provider 传输契约不一致"
            )
    extra_body: dict[str, object] = {}
    if config is not None and config.enable_thinking_location == "top_level":
        extra_body["enable_thinking"] = config.enable_thinking
    elif config is not None and config.enable_thinking_location == "chat_template_kwargs":
        extra_body["chat_template_kwargs"] = {
            "enable_thinking": config.enable_thinking
        }
    model = ReplayObservedOpenAIChat(
        id=config.model if config is not None else settings.model_standard_id,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        max_tokens=(
            config.max_output_tokens
            if config is not None
            else settings.report_output_token_reserve
        ),
        timeout=settings.model_timeout_seconds,
        max_retries=0,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        reasoning_effort=effort,
        extra_body=extra_body or None,
    )
    if config is not None:
        model.__dict__["_reporting_reasoning_summary"] = config.reasoning_summary
    model.replay_request_metrics()
    return model


def replay_model_request_metrics(model: Any) -> list[dict[str, Any]]:
    """读取冻结回放模型的逐 provider 请求指标。"""

    reader = getattr(model, "replay_request_metrics", None)
    return reader() if callable(reader) else []


def build_replay_failure(
    error: BaseException,
    *,
    seconds: float,
    workspace: Path,
    model_metrics: list[dict],
    coding_metrics: list[dict],
    planner_metrics: list[dict] | None = None,
    planner_request_metrics: list[dict] | None = None,
    phase: str | None = None,
    request_metrics: list[dict] | None = None,
) -> dict:
    timed_out = isinstance(error, ReplayWallTimeout)
    failure = {
        "type": type(error).__name__,
        "code": (
            "report_replay_wall_timeout"
            if timed_out
            else str(getattr(error, "code", type(error).__name__))
        ),
        "message": str(getattr(error, "message", str(error))),
        "details": dict(getattr(error, "details", {}) or {}),
    }
    if timed_out:
        failure["details"].update({"wallTimeoutSeconds": error.seconds, "censored": True})
        if phase is not None:
            failure["details"]["phase"] = phase
    result = {
        "status": "timed_out" if timed_out else "failed",
        "seconds": seconds,
        "workspace": str(workspace),
        "modelMetrics": model_metrics,
        "codingMetrics": coding_metrics,
        "requestMetrics": request_metrics or [],
        "failure": failure,
    }
    if timed_out:
        result["censored"] = True
    if planner_metrics is not None:
        result["plannerMetrics"] = planner_metrics
    if planner_request_metrics is not None:
        result["plannerRequestMetrics"] = planner_request_metrics
    return result


def write_replay_result(output_path: Path | None, payload: dict) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if output_path is None:
        print(encoded)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(encoded + "\n", encoding="utf-8")


def write_failure_artifact(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """失败时立即落盘；独占创建，防止后续修复或复用输出路径覆盖原始证据。"""
    encoded = (json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
    return {"path": str(path), "sha256": hashlib.sha256(encoded).hexdigest(), "size": len(encoded)}


def normalize_replay_payload(
    payload: dict, *, deterministic_facts_path: Path | None = None
) -> dict:
    """按任务类型恢复生产授权路径，不给分析任务套用可视化投影。"""

    normalized = deepcopy(payload)
    task = normalized.get("task")
    facts = normalized.get("facts")
    if not isinstance(task, dict) or not isinstance(facts, dict):
        raise ValueError("回放 payload 缺少 task 或 facts 对象")
    if task.get("task_kind") == "visualization":
        task["authorized_read_paths"] = visualization_read_paths(
            facts["visualizationFacts"]
        )
        facts["visualizationFacts"] = visualization_coding_facts(
            facts["visualizationFacts"]
        )
    elif deterministic_facts_path is not None:
        deterministic_facts = json.loads(
            deterministic_facts_path.read_text(encoding="utf-8")
        )
        compact = _compact_existing_facts(deterministic_facts)
        current_analysis = facts.get("currentAnalysis")
        if (
            compact is not None
            and isinstance(current_analysis, Mapping)
            and compact.get("analysisId") != current_analysis.get("analysisId")
        ):
            raise ValueError("deterministic facts analysisId 与当前分析项不一致")
        if compact is not None:
            facts["existingFacts"] = compact
    return normalized


def prepare_replay_files(
    root: Path,
    task: ReportingCodingTaskContext,
    initial_script_path: Path | None,
) -> None:
    """清理旧产物，并按需从已有脚本开始回放。"""

    script_path = root / task.script_path
    for path in task.declared_output_paths:
        (root / path).unlink(missing_ok=True)
    if initial_script_path is None:
        script_path.unlink(missing_ok=True)
        return
    script_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(initial_script_path, script_path)


def _file_identity(path: Path, relative_path: str) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": relative_path,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def prepare_replay_bundle(
    payload: dict,
    bundle_dir: Path,
    initial_script_path: Path | None,
) -> dict[str, object]:
    """将签发输入固化为不依赖历史临时 Workspace 的回放 bundle。"""

    task = ReportingCodingTaskContext(**payload["task"])
    source_root = Path(task.workspace_root)
    inputs = [
        (relative_path, source_root / relative_path)
        for relative_path in sorted(task.authorized_read_paths)
    ]
    missing = [relative_path for relative_path, path in inputs if not path.is_file()]
    if missing:
        raise ValueError(f"回放签发输入不存在：{missing}")
    if initial_script_path is not None and not initial_script_path.is_file():
        raise ValueError("回放初始脚本不存在")
    if bundle_dir.exists() and any(bundle_dir.iterdir()):
        raise ValueError("回放 bundle 目录必须为空")

    workspace_dir = bundle_dir / "workspace"
    input_identities: list[dict[str, object]] = []
    for relative_path, source_path in inputs:
        target = workspace_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        input_identities.append(_file_identity(target, relative_path))

    initial_script_identity: dict[str, object] | None = None
    if initial_script_path is not None:
        seed_path = bundle_dir / "seed" / initial_script_path.name
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(initial_script_path, seed_path)
        initial_script_identity = _file_identity(
            seed_path, seed_path.relative_to(bundle_dir).as_posix()
        )

    portable_payload = deepcopy(payload)
    portable_payload["task"]["workspace_root"] = "workspace"
    encoded_payload = json.dumps(
        portable_payload, ensure_ascii=False, indent=2
    ).encode("utf-8")
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "payload.json").write_bytes(encoded_payload + b"\n")
    manifest: dict[str, object] = {
        "version": 1,
        "taskKind": task.task_kind,
        "payloadSha256": hashlib.sha256(encoded_payload + b"\n").hexdigest(),
        "inputs": input_identities,
        **(
            {"initialScript": initial_script_identity}
            if initial_script_identity is not None
            else {}
        ),
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_replay_bundle(payload_path: Path) -> dict[str, object]:
    """校验 bundle payload、签发输入和可选脚本种子的冻结身份。"""

    bundle_dir = payload_path.parent.resolve()
    payload_bytes = payload_path.read_bytes()
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("payloadSha256") != hashlib.sha256(payload_bytes).hexdigest():
        raise ValueError("回放 payload 身份不一致")
    payload = json.loads(payload_bytes)
    task_payload = payload.get("task")
    if not isinstance(task_payload, dict):
        raise ValueError("回放 payload 缺少 task 对象")
    workspace_value = task_payload.get("workspace_root")
    if not isinstance(workspace_value, str) or not workspace_value:
        raise ValueError("回放 payload 缺少 workspace_root")
    workspace_root = (bundle_dir / workspace_value).resolve()
    if workspace_root != bundle_dir and bundle_dir not in workspace_root.parents:
        raise ValueError("回放 bundle workspace_root 越界")
    resolved_task = dict(task_payload)
    resolved_task["workspace_root"] = str(workspace_root)
    task = ReportingCodingTaskContext(**resolved_task)

    raw_inputs = manifest.get("inputs")
    if not isinstance(raw_inputs, list):
        raise ValueError("回放 manifest 缺少 inputs")
    identities = {
        item.get("path"): item
        for item in raw_inputs
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if set(identities) != set(task.authorized_read_paths):
        raise ValueError("回放授权输入集合身份不一致")
    for relative_path in task.authorized_read_paths:
        current = _file_identity(workspace_root / relative_path, relative_path)
        if current != identities[relative_path]:
            raise ValueError(f"回放授权输入身份不一致：{relative_path}")

    initial_script = manifest.get("initialScript")
    if initial_script is not None:
        if not isinstance(initial_script, dict) or not isinstance(
            initial_script.get("path"), str
        ):
            raise ValueError("回放初始脚本身份无效")
        seed_path = (bundle_dir / initial_script["path"]).resolve()
        if bundle_dir not in seed_path.parents:
            raise ValueError("回放初始脚本路径越界")
        if _file_identity(seed_path, initial_script["path"]) != initial_script:
            raise ValueError("回放初始脚本身份不一致")
    return manifest


def link_coding_only_benchmark(
    benchmark_bundle_dir: Path,
    coding_only_payload_path: Path,
    *,
    variant: BenchmarkVariant,
) -> CodingOnlyBenchmarkLink:
    """联结 v2 冻结配置与已签名的 legacy analysis Coding payload。"""

    benchmark_manifest, benchmark_payloads = validate_frozen_planner_coding_bundle(
        benchmark_bundle_dir.resolve()
    )
    replay_manifest = validate_replay_bundle(coding_only_payload_path.resolve())
    if benchmark_manifest.task_kind != "analysis" or replay_manifest.get(
        "taskKind"
    ) != "analysis":
        raise ValueError("Coding-only benchmark 首版仅支持 analysis")
    if variant is not BenchmarkVariant.LEGACY:
        raise ValueError("Coding-only benchmark 首版仅支持 legacy variant")
    if replay_manifest.get("version") != 1:
        raise ValueError("Coding-only payload 必须来自 version 1 replay bundle")

    payload = json.loads(coding_only_payload_path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("Coding-only payload 必须是 JSON 对象")
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise ValueError("Coding-only payload 缺少 facts 对象")
    decision = LegacyAnalysisEvidenceDecision.model_validate(
        facts.get("evidenceDecision")
    )
    if not decision.requires_supplemental_evidence:
        raise ValueError("Coding-only payload 必须要求 supplemental evidence")

    base_payload = deepcopy(payload)
    base_payload["facts"].pop("evidenceDecision")
    benchmark_payload = benchmark_payloads["executionContext"].get("codingPayload")
    if base_payload != benchmark_payload:
        raise ValueError("Coding-only Coding payload 与 v2 executionContext 不一致")

    raw_replay_inputs = replay_manifest.get("inputs")
    if not isinstance(raw_replay_inputs, list) or any(
        not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}
        for item in raw_replay_inputs
    ):
        raise ValueError("Coding-only 与 v2 授权输入身份不一致")
    replay_inputs = sorted(
        (item["path"], item["size"], item["sha256"])
        for item in raw_replay_inputs
    )
    benchmark_inputs = sorted(
        (
            item.path.removeprefix("workspace/"),
            item.size,
            item.sha256,
        )
        for item in benchmark_manifest.inputs
    )
    if replay_inputs != benchmark_inputs:
        raise ValueError("Coding-only 与 v2 授权输入路径、大小或 SHA 身份不一致")
    return CodingOnlyBenchmarkLink(
        payload=payload,
        model_config=benchmark_manifest.model_config_snapshot,
    )


def replay_instructions(
    task_kind: str, *, variant: BenchmarkVariant | None = None
) -> tuple[str, ...]:
    """复用生产阶段指令，避免探针通过额外提示改变模型行为。"""

    if task_kind == "visualization":
        return (
            _VISUALIZATION_CODE_LEGACY_INSTRUCTIONS
            if variant is BenchmarkVariant.LEGACY
            else _VISUALIZATION_CODE_INSTRUCTIONS
        )
    if task_kind == "analysis":
        return (
            _ANALYSIS_CODE_LEGACY_INSTRUCTIONS
            if variant is BenchmarkVariant.LEGACY
            else _ANALYSIS_CODE_INSTRUCTIONS
        )
    raise ValueError(f"不支持的 Coding 回放任务类型：{task_kind}")


def analysis_evidence_diagnostic(
    content: str | bytes, current_analysis: Mapping[str, object]
) -> dict | None:
    """使用生产契约校验分析回放产物；业务对账失败仍是合法软告警。"""

    try:
        validate_supplemental_evidence(content, current_analysis)
    except ValidationError as error:
        rejection = supplemental_evidence_schema_error(error)
        return {
            "code": rejection.code,
            "message": rejection.message,
            "details": rejection.details,
        }
    return None


def find_task_payload(rows, task_kind: str) -> dict:
    for attributes in rows:
        messages = attributes.get("messages") if isinstance(attributes, dict) else None
        if not isinstance(messages, list):
            continue
        for message in messages:
            if message.get("role") != "user" or not isinstance(message.get("content"), str):
                continue
            try:
                payload = json.loads(message["content"])
            except ValueError:
                continue
            if (
                isinstance(payload, dict)
                and payload.get("task", {}).get("task_kind") == task_kind
            ):
                return payload
    raise ValueError(f"没有找到 {task_kind} Coding 任务输入")


def _trace_json_value(attributes: Mapping[str, object], key: str) -> dict[str, Any] | None:
    value = attributes.get(key)
    if not isinstance(value, str):
        return None
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _trace_coding_payload(
    attributes: Mapping[str, object],
) -> dict[str, Any] | None:
    payload = _trace_json_value(attributes, "input.value")
    if payload is None:
        return None
    metadata = _trace_json_value(attributes, "metadata")
    host_task = (
        metadata.get(REPORTING_CODING_TASK_CONTEXT_METADATA_KEY)
        if isinstance(metadata, Mapping)
        else None
    )
    if not isinstance(host_task, Mapping):
        return payload
    model_task = payload.get("task")
    if not isinstance(model_task, Mapping) or any(
        host_task.get(key) != value for key, value in model_task.items()
    ):
        raise ValueError("Coding trace 的模型 task 与宿主 task context 不一致")
    restored = deepcopy(payload)
    restored["task"] = dict(host_task)
    return restored


def _trace_candidates(rows, agent_id: str, identity_key: str, identity: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        attributes = row.get("attributes") if isinstance(row, Mapping) else None
        if not isinstance(attributes, Mapping) or attributes.get("agno.agent.id") != agent_id:
            continue
        payload = _trace_json_value(attributes, "input.value")
        if payload is None or payload.get(identity_key) != identity:
            continue
        candidates.append(
            {
                "payload": payload,
                "output": _trace_json_value(attributes, "output.value"),
                "span_id": row.get("span_id"),
            }
        )
    return candidates


def extract_benchmark_trace_inputs(
    rows,
    *,
    task_kind: str,
    task_identity: str,
) -> dict[str, Any]:
    """从已查询的 Agno agent spans 提取 planner 前输入和 Coding 基础 payload。

    该函数只做身份配对与严格投影，不读取模型配置、不调用 provider，也不从旧
    planner 输出猜造 candidate 字段。
    """

    if task_kind == "analysis":
        planner_candidates = []
        for row in rows:
            attributes = row.get("attributes") if isinstance(row, Mapping) else None
            if not isinstance(attributes, Mapping) or attributes.get(
                "agno.agent.id"
            ) != "report-analysis-evidence-planner":
                continue
            payload = _trace_json_value(attributes, "input.value")
            if not isinstance(payload, dict) or payload.get("currentAnalysis", {}).get(
                "analysisId"
            ) != task_identity:
                continue
            planner_candidates.append(
                {
                    "payload": payload,
                    "output": _trace_json_value(attributes, "output.value"),
                    "span_id": row.get("span_id"),
                }
            )
        coding_candidates: list[dict[str, Any]] = []
        for row in rows:
            attributes = row.get("attributes") if isinstance(row, Mapping) else None
            if not isinstance(attributes, Mapping) or attributes.get(
                "agno.agent.id"
            ) != "report-analysis-script-writer":
                continue
            payload = _trace_coding_payload(attributes)
            if not isinstance(payload, dict):
                continue
            if (
                payload.get("task", {}).get("task_kind") == task_kind
                and payload.get("facts", {}).get("currentAnalysis", {}).get("analysisId")
                == task_identity
            ):
                coding_candidates.append(
                    {
                        "payload": payload,
                        "output": _trace_json_value(attributes, "output.value"),
                        "span_id": row.get("span_id"),
                    }
                )
        if len(planner_candidates) != 1 or len(coding_candidates) != 1:
            raise ValueError("分析 trace 必须唯一匹配 planner 和 Coding span")
        planner = planner_candidates[0]
        coding = coding_candidates[0]
        planner_request = deepcopy(planner["payload"])
        coding_payload = deepcopy(coding["payload"])
        facts = coding_payload.get("facts")
        if not isinstance(facts, dict):
            raise ValueError("分析 Coding trace 缺少 facts")
        if planner_request.get("currentAnalysis") != facts.get("currentAnalysis"):
            raise ValueError("分析 planner 与 Coding 的 currentAnalysis 身份不一致")
        if isinstance(planner_request.get("datasets"), list) and (
            not isinstance(facts.get("datasets"), list)
            or planner_request["datasets"] != facts["datasets"]
        ):
            raise ValueError("分析 planner 与 Coding 的 datasets 不一致")
        projection = None
        if not isinstance(planner_request.get("datasets"), list):
            try:
                planner_decision = LegacyAnalysisEvidenceDecision.model_validate(
                    planner.get("output")
                )
                coding_decision = LegacyAnalysisEvidenceDecision.model_validate(
                    facts.get("evidenceDecision")
                )
            except ValidationError as error:
                raise ValueError("分析 planner 或 Coding 缺少有效的补证决策") from error
            if planner_decision != coding_decision:
                raise ValueError("分析 planner 与 Coding 的补证决策不一致")

            datasets = facts.get("datasets")
            dataset_paths = [
                item.get("path") if isinstance(item, Mapping) else None
                for item in datasets or ()
            ]
            task = coding_payload.get("task")
            authorized_paths = (
                task.get("authorized_read_paths") if isinstance(task, Mapping) else None
            )
            if (
                not isinstance(datasets, list)
                or not datasets
                or any(not isinstance(path, str) or not path for path in dataset_paths)
                or len(dataset_paths) != len(set(dataset_paths))
                or not isinstance(authorized_paths, list)
                or len(authorized_paths) != len(set(authorized_paths))
                or set(dataset_paths) != set(authorized_paths)
            ):
                raise ValueError("分析 datasets 路径与 Coding 授权读取路径不一致")
            planner_request["datasets"] = deepcopy(datasets)
            projection = {
                "kind": "analysisDatasetsFromCodingFacts",
                "plannerSpan": planner["span_id"],
                "codingSpan": coding["span_id"],
            }
        facts.pop("evidenceDecision", None)
        facts.pop("codingRequirements", None)
        extracted = {
            "plannerRequest": planner_request,
            "codingPayload": coding_payload,
            "sourceSpans": {
                "planner": planner["span_id"],
                "coding": coding["span_id"],
            },
        }
        if projection is not None:
            extracted["projection"] = projection
        return extracted

    if task_kind != "visualization":
        raise ValueError("task_kind 必须是 analysis 或 visualization")
    planner_candidates = _trace_candidates(
        rows, "reporting-visualization-generator", "sectionCode", task_identity
    )
    if len(planner_candidates) != 1:
        raise ValueError("可视化 trace 必须唯一匹配 planner span")
    planner = planner_candidates[0]
    request = planner["payload"]
    facts = request.get("visualizationFacts")
    if not isinstance(facts, list) or any(
        not isinstance(item, dict) or not item.get("dataDescriptors") for item in facts
    ):
        raise ValueError("可视化 planner trace 缺少 dataDescriptors，不能生成 candidate bundle")
    planner_output = planner.get("output")
    if not isinstance(planner_output, dict):
        raise ValueError("可视化 planner trace 缺少结构化输出")
    try:
        candidate_plan = VisualizationPlanDraft.model_validate(planner_output)
    except ValidationError as error:
        raise ValueError("可视化 planner trace 缺少有效的 candidate 计划") from error
    chart_paths = {
        path
        for chart in candidate_plan.charts
        for path in (chart.source_path, chart.interactive_path)
        if path is not None
    }
    coding_candidates = []
    for row in rows:
        attributes = row.get("attributes") if isinstance(row, Mapping) else None
        if not isinstance(attributes, Mapping) or attributes.get(
            "agno.agent.id"
        ) != "reporting-visualization-code-agent":
            continue
        payload = _trace_coding_payload(attributes)
        if not isinstance(payload, dict) or payload.get("task", {}).get("task_kind") != task_kind:
            continue
        declared = set(payload.get("task", {}).get("declared_output_paths", ()))
        if declared == chart_paths:
            coding_candidates.append({"payload": payload, "span_id": row.get("span_id")})
    if len(coding_candidates) != 1:
        raise ValueError("可视化 trace 必须按 declared_output_paths 唯一匹配 Coding span")
    coding_payload = deepcopy(coding_candidates[0]["payload"])
    coding_facts = coding_payload.get("facts")
    if not isinstance(coding_facts, dict):
        raise ValueError("可视化 Coding trace 缺少 facts")
    neutral_facts = visualization_coding_facts(facts)
    candidate_facts = visualization_coding_facts(facts, plan=candidate_plan)
    if coding_facts.get("visualizationFacts") != candidate_facts:
        raise ValueError("可视化 planner 与 Coding 的 visualizationFacts 投影不一致")
    coding_facts["visualizationFacts"] = neutral_facts
    coding_facts.pop("visualizationPlan", None)
    return {
        "plannerRequest": request,
        "codingPayload": coding_payload,
        "sourceSpans": {
            "planner": planner["span_id"],
            "coding": coding_candidates[0]["span_id"],
        },
    }


def load_task(run_id, task_kind: str):
    with psycopg.connect(psycopg_db_url()) as connection:
        rows = connection.execute(
            "SELECT attributes FROM ai.agno_spans WHERE name='OpenAIResponses.ainvoke' "
            "AND attributes->>'input.value' LIKE %s ORDER BY start_time LIMIT 300",
            (f"%{run_id}%",),
        )
        candidates = []
        for (attributes,) in rows:
            raw = json.loads(attributes["input.value"])
            candidates.append({"messages": raw.get("messages", [])})
    return find_task_payload(candidates, task_kind)


def load_trace_spans(trace_id: str) -> list[dict[str, Any]]:
    """读取指定 trace 的 agent spans；只用于离线提取，不调用模型。"""

    with psycopg.connect(psycopg_db_url()) as connection:
        rows = connection.execute(
            "SELECT span_id,parent_span_id,attributes "
            "FROM ai.agno_spans WHERE trace_id=%s ORDER BY start_time",
            (trace_id,),
        ).fetchall()
    return [
        {"span_id": span_id, "parent_span_id": parent_id, "attributes": attributes}
        for span_id, parent_id, attributes in rows
    ]


async def main(
    run_id: str | None,
    payload_path: Path | None,
    task_kind: str,
    reasoning_effort: str,
    output_path: Path | None,
    deterministic_facts_path: Path | None,
    initial_script_path: Path | None,
    prepare_only_dir: Path | None = None,
    validate_only: bool = False,
    benchmark_bundle_dir: Path | None = None,
    benchmark_variant: BenchmarkVariant | None = None,
    benchmark_prepare_dir: Path | None = None,
    planner_request_path: Path | None = None,
    coding_payload_path: Path | None = None,
    acceptance_path: Path | None = None,
    model_config_path: Path | None = None,
    trace_id: str | None = None,
    trace_identity: str | None = None,
    benchmark_extract_dir: Path | None = None,
    coding_only_payload_path: Path | None = None,
    wall_timeout_seconds: float | None = None,
    compact_continuation: bool = False,
) -> int:
    configure_application_logging(debug=False)
    if benchmark_extract_dir is not None:
        if not trace_id or not trace_identity or not acceptance_path or not model_config_path:
            raise ValueError(
                "trace 提取必须提供 trace_id、analysis-id/section-code、acceptance 和 model-config"
            )
        extracted = extract_benchmark_trace_inputs(
            load_trace_spans(trace_id),
            task_kind=task_kind,
            task_identity=trace_identity,
        )
        model_config = BenchmarkModelConfig.model_validate_json(model_config_path.read_bytes())
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
        if not isinstance(acceptance, dict):
            raise ValueError("trace 提取 acceptance 必须是 JSON 对象")
        manifest = prepare_frozen_planner_coding_bundle(
            benchmark_extract_dir.resolve(),
            task_kind=task_kind,
            planner_request=extracted["plannerRequest"],
            coding_payload=extracted["codingPayload"],
            acceptance=acceptance,
            model_config=model_config,
        )
        write_replay_result(
            output_path,
            {
                "status": "extracted",
                "bundle": str(benchmark_extract_dir.resolve()),
                "sourceSpans": extracted["sourceSpans"],
                "manifest": manifest.model_dump(mode="json", by_alias=True),
            },
        )
        return 0
    if benchmark_prepare_dir is not None:
        required_paths = (
            planner_request_path,
            coding_payload_path,
            acceptance_path,
            model_config_path,
        )
        if any(path is None for path in required_paths):
            raise ValueError("version 2 prepare 缺少显式输入文件")
        planner_request = json.loads(planner_request_path.read_text(encoding="utf-8"))
        coding_payload = json.loads(coding_payload_path.read_text(encoding="utf-8"))
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
        if not all(
            isinstance(payload, dict)
            for payload in (planner_request, coding_payload, acceptance)
        ):
            raise ValueError("version 2 prepare 输入必须是 JSON 对象")
        model_config = BenchmarkModelConfig.model_validate_json(
            model_config_path.read_bytes()
        )
        manifest = prepare_frozen_planner_coding_bundle(
            benchmark_prepare_dir.resolve(),
            task_kind=task_kind,
            planner_request=planner_request,
            coding_payload=coding_payload,
            acceptance=acceptance,
            model_config=model_config,
        )
        write_replay_result(
            output_path,
            {
                "status": "prepared",
                "bundle": str(benchmark_prepare_dir.resolve()),
                "manifest": manifest.model_dump(mode="json", by_alias=True),
            },
        )
        return 0
    if validate_only:
        if benchmark_bundle_dir is not None:
            manifest, _ = validate_frozen_planner_coding_bundle(
                benchmark_bundle_dir.resolve()
            )
            write_replay_result(
                output_path,
                {
                    "status": "validated",
                    "bundle": str(benchmark_bundle_dir.resolve()),
                    "manifest": manifest.model_dump(mode="json", by_alias=True),
                },
            )
            return 0
        if payload_path is None:
            raise ValueError("validate-only 必须使用 --payload 指定 bundle payload")
        manifest = validate_replay_bundle(payload_path.resolve())
        write_replay_result(
            output_path,
            {
                "status": "validated",
                "bundle": str(payload_path.resolve().parent),
                "manifest": manifest,
            },
        )
        return 0
    benchmark_manifest = None
    coding_only_link = None
    if benchmark_bundle_dir is not None:
        if benchmark_variant is None:
            raise ValueError("benchmark bundle 必须显式指定 variant")
        if coding_only_payload_path is not None:
            coding_only_link = link_coding_only_benchmark(
                benchmark_bundle_dir,
                coding_only_payload_path,
                variant=benchmark_variant,
            )
            payload = deepcopy(coding_only_link.payload)
            task_kind = coding_only_link.task_kind
        else:
            benchmark_manifest, benchmark_payloads = (
                validate_frozen_planner_coding_bundle(benchmark_bundle_dir.resolve())
            )
            payload = deepcopy(
                benchmark_payloads["executionContext"].get("codingPayload")
            )
            if not isinstance(payload, dict):
                raise ValueError("benchmark executionContext 缺少 codingPayload")
            task_kind = benchmark_manifest.task_kind
    else:
        if payload_path is not None and (payload_path.parent / "manifest.json").is_file():
            replay_manifest = validate_replay_bundle(payload_path.resolve())
            seed_identity = replay_manifest.get("initialScript")
            if initial_script_path is not None and (
                not isinstance(seed_identity, dict)
                or _file_identity(initial_script_path, seed_identity["path"]) != seed_identity
            ):
                raise ValueError("回放显式初始脚本与冻结身份不一致")
            if isinstance(seed_identity, dict):
                initial_script_path = payload_path.parent.resolve() / seed_identity["path"]
        payload = normalize_replay_payload(
            json.loads(payload_path.read_text(encoding="utf-8"))
            if payload_path is not None
            else load_task(run_id, task_kind),
            deterministic_facts_path=deterministic_facts_path,
        )
    source_root = Path(payload["task"]["workspace_root"])
    if not source_root.is_absolute():
        source_parent = (
            coding_only_payload_path.parent.resolve()
            if coding_only_payload_path is not None
            else benchmark_bundle_dir.resolve()
            if benchmark_bundle_dir is not None
            else payload_path.parent.resolve()
            if payload_path is not None
            else None
        )
        if source_parent is None:
            raise ValueError("相对 workspace_root 必须来自 --payload")
        source_root = (source_parent / source_root).resolve()
        payload["task"]["workspace_root"] = str(source_root)
    if prepare_only_dir is not None:
        manifest = prepare_replay_bundle(
            payload, prepare_only_dir.resolve(), initial_script_path
        )
        write_replay_result(
            output_path,
            {
                "status": "prepared",
                "bundle": str(prepare_only_dir.resolve()),
                "manifest": manifest,
            },
        )
        return 0

    settings = AgentSettings.from_environment()
    root = Path(tempfile.mkdtemp(prefix="reporting-visualization-replay-")).resolve()
    started = perf_counter()
    planner_metrics: list[dict] = []
    planner_model = None
    phase = "setup"
    first_failure_artifact: dict[str, Any] | None = None

    def record_failure_artifact(snapshot: Mapping[str, Any]) -> None:
        nonlocal first_failure_artifact
        artifact_path = (
            output_path.with_name(output_path.name + ".first-run-failure.json")
            if output_path is not None else root / "first-run-failure.json"
        )
        first_failure_artifact = write_failure_artifact(artifact_path, snapshot)

    def remaining_wall_timeout() -> float | None:
        if wall_timeout_seconds is None:
            return None
        remaining = wall_timeout_seconds - (perf_counter() - started)
        if remaining <= 0:
            raise ReplayWallTimeout(wall_timeout_seconds)
        return remaining

    try:
        shutil.copytree(source_root, root, dirs_exist_ok=True)
        model_config = (
            coding_only_link.model_config
            if coding_only_link is not None
            else benchmark_manifest.model_config_snapshot
            if benchmark_manifest is not None
            else None
        )
        model = build_replay_model(
            settings,
            reasoning_effort=reasoning_effort,
            benchmark_model_config=model_config,
        )
        if benchmark_bundle_dir is not None and coding_only_link is None:
            phase = "planner"
            planner_model = build_replay_model(
                settings,
                reasoning_effort=reasoning_effort,
                benchmark_model_config=model_config,
                benchmark_stage="planner",
            )
            payload, _, _ = await run_with_wall_timeout(
                run_frozen_benchmark_planner(
                    benchmark_bundle_dir.resolve(),
                    variant=benchmark_variant,
                    model=planner_model,
                    metrics_sink=planner_metrics,
                ),
                seconds=remaining_wall_timeout(),
            )
            payload = normalize_replay_payload(payload)
        payload["task"]["workspace_root"] = str(root)
        task = ReportingCodingTaskContext(**payload["task"])
        prepare_replay_files(root, task, initial_script_path)
        workspace = HostReportingWorkspace(
            ReportingWorkspaceIdentity(
                workflow_session_id=f"{task.task_kind}-replay",
                workspace_key=task.workspace_key,
                scope_fingerprint="visualization-replay",
                root=root,
                workspace=Workspace(str(root)),
            )
        )
        coding_model = None

        def capture_coding_model(created_model) -> None:
            nonlocal coding_model
            coding_model = created_model

        factory = create_reporting_code_agent_factory(
            model=model,
            name=f"{task.task_kind}-replay",
            task_kind=task.task_kind,
            instructions=replay_instructions(
                task.task_kind,
                variant=benchmark_variant if benchmark_bundle_dir is not None else None,
            ),
            model_created=capture_coding_model,
        )
        runtime = create_reporting_code_mode_runtime(
            root, analysis_concurrency=1, section_concurrency=1, timeout=120
        )
        lsp = ReportingLspProcessManager()
        model_metrics = []
        coding_metrics = []
        runner = ReportingCodeGenerationRunner(
            factory,
            runtime,
            lsp,
            vision_reviewer=ReportVisionReviewer(settings, workspace),
            model_metrics_recorder=lambda output, requests: model_metrics.append({
                "requests": requests,
                "inputTokens": getattr(output.metrics, "input_tokens", None),
                "outputTokens": getattr(output.metrics, "output_tokens", None),
                "reasoningTokens": getattr(output.metrics, "reasoning_tokens", None),
            }),
            coding_metrics_recorder=coding_metrics.append,
            failure_artifact_recorder=record_failure_artifact,
            compact_continuation=compact_continuation,
        )
        output_preflight = None
        if task.task_kind == "analysis":
            current_analysis = payload["facts"].get("currentAnalysis")
            evidence_path = str(payload["facts"].get("evidencePath") or "")

            async def validate_analysis_output(
                receipt: ExecutionReceipt,
            ) -> Mapping[str, object] | None:
                output = next(
                    (item for item in receipt.output_files if item.path == evidence_path),
                    None,
                )
                if output is None or not 0 < output.size <= MAX_SUPPLEMENTAL_EVIDENCE_BYTES:
                    return {
                        "code": "report_analysis_evidence_too_large",
                        "message": "补充 evidence 缺失、超过 10 MiB 安全上限或大小无效。",
                    }
                content = await workspace.read_limited_regular_file(
                    task.task_id,
                    output.path,
                    max_bytes=MAX_SUPPLEMENTAL_EVIDENCE_BYTES,
                )
                return analysis_evidence_diagnostic(
                    content,
                    current_analysis if isinstance(current_analysis, Mapping) else {},
                )

            output_preflight = validate_analysis_output
        try:
            phase = "coding"
            result = await run_with_wall_timeout(
                runner.run(
                    task,
                    workspace,
                    payload["facts"],
                    run_context=RunContext(
                        run_id=f"{task.task_kind}-replay",
                        session_id=f"{task.task_kind}-replay",
                        session_state={},
                    ),
                    output_preflight=output_preflight,
                ),
                seconds=remaining_wall_timeout(),
            )
            result_payload = {
                "status": "passed",
                "seconds": round(perf_counter() - started, 3),
                "workspace": str(root),
                "modelMetrics": model_metrics,
                "codingMetrics": coding_metrics,
                "firstRunFailureArtifact": first_failure_artifact or "unknown",
                "requestMetrics": replay_model_request_metrics(
                    coding_model or model
                ),
                "script": result.script_file.model_dump(mode="json"),
                "images": [
                    item.model_dump(mode="json")
                    for item in result.execution_receipt.output_files
                ],
                "reviews": [
                    item.model_dump(mode="json") for item in result.visual_inspection_receipts
                ],
            }
            if benchmark_bundle_dir is not None:
                result_payload["variant"] = benchmark_variant.value
                if coding_only_link is not None:
                    result_payload["benchmarkMode"] = coding_only_link.benchmark_mode
                else:
                    result_payload["plannerMetrics"] = planner_metrics
                    result_payload["plannerRequestMetrics"] = (
                        replay_model_request_metrics(planner_model)
                    )
            write_replay_result(output_path, result_payload)
            return 0
        except Exception as error:
            request_metrics_reader = getattr(
                coding_model, "code_run_request_metrics", None
            )
            coding_request_metrics = replay_model_request_metrics(
                coding_model or model
            )
            if not coding_request_metrics and callable(request_metrics_reader):
                coding_request_metrics = request_metrics_reader()
            failure_payload = build_replay_failure(
                error,
                seconds=round(perf_counter() - started, 3),
                workspace=root,
                model_metrics=model_metrics,
                coding_metrics=coding_metrics,
                planner_metrics=(
                    planner_metrics
                    if benchmark_bundle_dir is not None and coding_only_link is None
                    else None
                ),
                planner_request_metrics=(
                    replay_model_request_metrics(planner_model)
                    if benchmark_bundle_dir is not None and coding_only_link is None
                    else None
                ),
                phase=phase,
                request_metrics=coding_request_metrics,
            )
            if coding_only_link is not None:
                failure_payload["benchmarkMode"] = coding_only_link.benchmark_mode
                failure_payload["variant"] = benchmark_variant.value
            failure_payload["firstRunFailureArtifact"] = first_failure_artifact or "unknown"
            write_replay_result(output_path, failure_payload)
            return 1
        finally:
            await runtime.aclose()
            await lsp.aclose()
    except Exception as error:
        failure_payload = build_replay_failure(
            error,
            seconds=round(perf_counter() - started, 3),
            workspace=root,
            model_metrics=[],
            coding_metrics=[],
            planner_metrics=(
                planner_metrics
                if benchmark_bundle_dir is not None and coding_only_link is None
                else None
            ),
            planner_request_metrics=(
                replay_model_request_metrics(planner_model)
                if benchmark_bundle_dir is not None and coding_only_link is None
                else None
            ),
            phase=phase,
        )
        if coding_only_link is not None:
            failure_payload["benchmarkMode"] = coding_only_link.benchmark_mode
            failure_payload["variant"] = benchmark_variant.value
        write_replay_result(output_path, failure_payload)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run-id")
    source.add_argument("--payload", type=Path)
    source.add_argument("--benchmark-bundle", type=Path)
    source.add_argument("--planner-request", type=Path)
    source.add_argument("--trace-id")
    parser.add_argument(
        "--task-kind",
        choices=("analysis", "visualization"),
        default="visualization",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high"),
        default="high",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--deterministic-facts", type=Path)
    parser.add_argument("--initial-script", type=Path)
    parser.add_argument(
        "--wall-timeout-seconds",
        type=float,
        help="可选的整轮 planner/Coding wall-timeout；默认不设置，不改变生产请求超时。",
    )
    parser.add_argument(
        "--compact-continuation",
        action="store_true",
        help="benchmark-only：修复阶段重建短会话，不复用上一轮 provider history。",
    )
    parser.add_argument("--variant", choices=("legacy", "candidate"))
    parser.add_argument(
        "--coding-only-payload",
        type=Path,
        help="使用已签名 v1 analysis payload 跳过 planner，仅执行 legacy Coding。",
    )
    parser.add_argument("--coding-payload", type=Path)
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--model-config", type=Path)
    parser.add_argument("--prepare-benchmark", type=Path, metavar="BUNDLE_DIR")
    parser.add_argument("--trace-identity", help="analysis-id 或 section-code")
    parser.add_argument("--extract-benchmark", type=Path, metavar="BUNDLE_DIR")
    parser.add_argument(
        "--prepare-only",
        type=Path,
        metavar="BUNDLE_DIR",
        help="只固化可携带回放输入，不创建模型或执行 Coding Agent。",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="只校验 bundle payload 和输入身份，不创建模型或执行 Coding Agent。",
    )
    args = parser.parse_args()
    if args.validate_only and args.payload is None and args.benchmark_bundle is None:
        parser.error("--validate-only 必须与 --payload 或 --benchmark-bundle 一起使用")
    if args.validate_only and args.prepare_only is not None:
        parser.error("--validate-only 与 --prepare-only 不能同时使用")
    if args.benchmark_bundle is not None and args.variant is None and not args.validate_only:
        parser.error("--benchmark-bundle 执行时必须指定 --variant")
    if args.benchmark_bundle is None and args.variant is not None:
        parser.error("--variant 只能与 --benchmark-bundle 一起使用")
    if args.coding_only_payload is not None and args.benchmark_bundle is None:
        parser.error("--coding-only-payload 必须与 --benchmark-bundle 一起使用")
    if args.coding_only_payload is not None and args.variant != "legacy":
        parser.error("--coding-only-payload 首版只支持 --variant legacy")
    if args.benchmark_bundle is not None and args.prepare_only is not None:
        parser.error("--benchmark-bundle 不支持 --prepare-only")
    benchmark_prepare_inputs = (
        args.planner_request,
        args.coding_payload,
        args.acceptance,
        args.model_config,
        args.prepare_benchmark,
    )
    if args.planner_request is not None and any(
        value is None for value in benchmark_prepare_inputs
    ):
        parser.error(
            "--planner-request 必须同时提供 --coding-payload、--acceptance、"
            "--model-config 和 --prepare-benchmark"
        )
    if args.planner_request is None and (
        args.coding_payload is not None
        or args.prepare_benchmark is not None
        or (
            args.trace_id is None
            and (args.acceptance is not None or args.model_config is not None)
        )
    ):
        parser.error("version 2 prepare 参数必须与 --planner-request 一起使用")
    if args.extract_benchmark is not None and args.trace_id is None:
        parser.error("--extract-benchmark 必须与 --trace-id 一起使用")
    if args.wall_timeout_seconds is not None and args.wall_timeout_seconds <= 0:
        parser.error("--wall-timeout-seconds 必须为正数")
    raise SystemExit(asyncio.run(main(
        args.run_id,
        args.payload,
        args.task_kind,
        args.reasoning_effort,
        args.output,
        args.deterministic_facts,
        args.initial_script,
        args.prepare_only,
        args.validate_only,
        args.benchmark_bundle,
        BenchmarkVariant.parse(args.variant) if args.variant is not None else None,
        args.prepare_benchmark,
        args.planner_request,
        args.coding_payload,
        args.acceptance,
        args.model_config,
        args.trace_id,
        args.trace_identity,
        args.extract_benchmark,
        args.coding_only_payload,
        args.wall_timeout_seconds,
        args.compact_continuation,
    )))
