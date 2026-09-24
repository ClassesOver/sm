"""Planner + Coding 性能基准的可携带冻结输入契约。"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..code_agent.context import ReportingCodingTaskContext


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class BenchmarkFileIdentity(_StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if "\\" in value or path.is_absolute() or ".." in path.parts or value.endswith("/"):
            raise ValueError("benchmark 文件必须使用安全相对路径")
        return path.as_posix()


class BenchmarkModelConfig(_StrictModel):
    model: str = Field(min_length=1, max_length=256)
    reasoning_effort: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh", "max"
    ] = Field(alias="reasoningEffort")
    planner_reasoning_effort: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh", "max"
    ] | None = Field(default=None, alias="plannerReasoningEffort")
    reasoning_summary: Literal["auto", "concise", "detailed"] = Field(
        alias="reasoningSummary"
    )
    enable_thinking_location: Literal[
        "top_level", "chat_template_kwargs", "omitted"
    ] = Field(alias="enableThinkingLocation")
    enable_thinking: bool | None = Field(default=None, alias="enableThinking")
    max_output_tokens: int | None = Field(default=None, alias="maxOutputTokens", gt=0)
    parallel_tool_calls: bool = Field(alias="parallelToolCalls")
    tool_choice: Literal["auto"] = Field(alias="toolChoice")

    @model_validator(mode="after")
    def validate_wire_contract(self) -> BenchmarkModelConfig:
        if not self.parallel_tool_calls:
            raise ValueError("benchmark 必须固定 parallelToolCalls=true")
        if self.planner_reasoning_effort is not None and (
            (self.planner_reasoning_effort == "none")
            != (self.reasoning_effort == "none")
        ):
            raise ValueError(
                "plannerReasoningEffort 与 reasoningEffort 不得跨越 none 边界"
            )
        if self.enable_thinking_location == "omitted" and self.enable_thinking is not None:
            raise ValueError("enableThinkingLocation=omitted 时不得携带 enableThinking")
        if self.enable_thinking_location != "omitted" and self.enable_thinking is None:
            raise ValueError("enableThinking 投影位置存在时必须固定其布尔值")
        if (
            self.enable_thinking_location != "omitted"
            and self.enable_thinking != (self.reasoning_effort != "none")
        ):
            raise ValueError("enableThinking 必须与 reasoningEffort 的启用状态一致")
        return self


class FrozenPlannerCodingBundleManifest(_StrictModel):
    version: Literal[2]
    task_kind: Literal["analysis", "visualization"] = Field(alias="taskKind")
    planner_request: BenchmarkFileIdentity = Field(alias="plannerRequest")
    execution_context: BenchmarkFileIdentity = Field(alias="executionContext")
    acceptance: BenchmarkFileIdentity
    inputs: tuple[BenchmarkFileIdentity, ...]
    model_config_snapshot: BenchmarkModelConfig = Field(alias="modelConfig")

    @model_validator(mode="after")
    def validate_unique_paths(self) -> FrozenPlannerCodingBundleManifest:
        identities = (
            self.planner_request,
            self.execution_context,
            self.acceptance,
            *self.inputs,
        )
        paths = [item.path for item in identities]
        if len(paths) != len(set(paths)):
            raise ValueError("benchmark bundle 文件路径不能重复")
        return self


def _identity(path: Path, relative_path: str) -> BenchmarkFileIdentity:
    content = path.read_bytes()
    return BenchmarkFileIdentity(
        path=relative_path,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _write_json(path: Path, payload: dict[str, Any]) -> BenchmarkFileIdentity:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return _identity(path, path.name)


def _validate_analysis_datasets(
    facts: Mapping[str, Any],
    authorized_read_paths: tuple[str, ...],
    input_identities: Mapping[str, BenchmarkFileIdentity],
) -> None:
    datasets = facts.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("analysis datasets 路径集合不能为空")
    paths: list[str] = []
    for dataset in datasets:
        if not isinstance(dataset, Mapping):
            raise ValueError("analysis datasets 路径声明无效")
        path = dataset.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("analysis datasets 路径声明无效")
        paths.append(path)
    if len(paths) != len(set(paths)):
        raise ValueError("analysis datasets 路径不能重复")
    if set(paths) != set(authorized_read_paths):
        raise ValueError("analysis datasets 路径集合与授权输入不一致")
    for dataset, path in zip(datasets, paths, strict=True):
        identity = input_identities[path]
        if dataset.get("size") != identity.size or dataset.get("sha256") != identity.sha256:
            raise ValueError(f"analysis dataset 身份不一致：{path}")


def prepare_frozen_planner_coding_bundle(
    bundle_dir: Path,
    *,
    task_kind: Literal["analysis", "visualization"],
    planner_request: dict[str, Any],
    coding_payload: dict[str, Any],
    acceptance: dict[str, Any],
    model_config: BenchmarkModelConfig,
) -> FrozenPlannerCodingBundleManifest:
    """固化 planner 前输入和 variant-neutral Coding 上下文。"""

    root = bundle_dir.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("benchmark bundle 目录必须为空")
    portable_payload = deepcopy(coding_payload)
    task_payload = portable_payload.get("task")
    facts = portable_payload.get("facts")
    if not isinstance(task_payload, dict) or not isinstance(facts, dict):
        raise ValueError("benchmark Coding payload 缺少 task 或 facts")
    if any(
        field in facts
        for field in ("evidenceDecision", "codingRequirements", "visualizationPlan")
    ):
        raise ValueError("benchmark Coding 基础 facts 不得包含 planner 产物")
    task = ReportingCodingTaskContext(**task_payload)
    if task.task_kind != task_kind:
        raise ValueError("benchmark Coding taskKind 不一致")
    source_root = Path(task.workspace_root).resolve()
    sources = [
        (relative_path, source_root / relative_path)
        for relative_path in task.authorized_read_paths
    ]
    missing = [relative_path for relative_path, path in sources if not path.is_file()]
    if missing:
        raise ValueError(f"benchmark 授权输入不存在：{missing}")
    if task_kind == "analysis":
        _validate_analysis_datasets(
            facts,
            task.authorized_read_paths,
            {
                relative_path: _identity(source_path, relative_path)
                for relative_path, source_path in sources
            },
        )

    root.mkdir(parents=True, exist_ok=True)
    input_identities: list[BenchmarkFileIdentity] = []
    for relative_path, source_path in sources:
        target_relative = (PurePosixPath("workspace") / relative_path).as_posix()
        target = root / target_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        input_identities.append(_identity(target, target_relative))

    portable_payload["task"]["workspace_root"] = "workspace"
    planner_identity = _write_json(root / "planner-request.json", planner_request)
    context_identity = _write_json(
        root / "execution-context.json",
        {"taskKind": task_kind, "codingPayload": portable_payload},
    )
    acceptance_identity = _write_json(root / "acceptance.json", acceptance)
    manifest = FrozenPlannerCodingBundleManifest(
        version=2,
        taskKind=task_kind,
        plannerRequest=planner_identity,
        executionContext=context_identity,
        acceptance=acceptance_identity,
        inputs=tuple(input_identities),
        modelConfig=model_config,
    )
    (root / "manifest.json").write_text(
        manifest.model_dump_json(by_alias=True, indent=2) + "\n",
        encoding="utf-8",
    )
    validated, _ = validate_frozen_planner_coding_bundle(root)
    return validated


def _validate_identity(root: Path, identity: BenchmarkFileIdentity) -> bytes:
    path = (root / identity.path).resolve()
    if root != path and root not in path.parents:
        raise ValueError("benchmark 文件路径越界")
    if not path.is_file():
        raise ValueError(f"benchmark 文件不存在：{identity.path}")
    content = path.read_bytes()
    if len(content) != identity.size or hashlib.sha256(content).hexdigest() != identity.sha256:
        raise ValueError(f"benchmark 文件身份不一致：{identity.path}")
    return content


def validate_frozen_planner_coding_bundle(
    bundle_dir: Path,
) -> tuple[FrozenPlannerCodingBundleManifest, dict[str, Any]]:
    """校验同一章节 A/B 共用的 planner 前输入；不创建模型或执行工具。"""

    root = bundle_dir.resolve()
    manifest = FrozenPlannerCodingBundleManifest.model_validate_json(
        (root / "manifest.json").read_bytes()
    )
    payloads: dict[str, Any] = {}
    for name, identity in (
        ("plannerRequest", manifest.planner_request),
        ("executionContext", manifest.execution_context),
        ("acceptance", manifest.acceptance),
    ):
        try:
            payload = json.loads(_validate_identity(root, identity))
        except json.JSONDecodeError as error:
            raise ValueError(f"benchmark {name} 不是有效 JSON") from error
        if not isinstance(payload, dict):
            raise ValueError(f"benchmark {name} 必须是 JSON 对象")
        payloads[name] = payload
    for identity in manifest.inputs:
        _validate_identity(root, identity)
    if payloads["executionContext"].get("taskKind") != manifest.task_kind:
        raise ValueError("benchmark executionContext 与 taskKind 不一致")
    coding_payload = payloads["executionContext"].get("codingPayload")
    if not isinstance(coding_payload, dict):
        raise ValueError("benchmark executionContext 缺少 codingPayload")
    task_payload = coding_payload.get("task")
    facts = coding_payload.get("facts")
    if not isinstance(task_payload, dict) or not isinstance(facts, dict):
        raise ValueError("benchmark Coding payload 缺少 task 或 facts")
    if task_payload.get("workspace_root") != "workspace":
        raise ValueError("benchmark Coding workspace_root 必须为 workspace")
    task = ReportingCodingTaskContext(**task_payload)
    if task.task_kind != manifest.task_kind:
        raise ValueError("benchmark Coding taskKind 不一致")
    expected_inputs = {
        (PurePosixPath("workspace") / relative_path).as_posix()
        for relative_path in task.authorized_read_paths
    }
    if {identity.path for identity in manifest.inputs} != expected_inputs:
        raise ValueError("benchmark 授权输入集合身份不一致")
    if manifest.task_kind == "analysis":
        identities_by_path = {identity.path: identity for identity in manifest.inputs}
        _validate_analysis_datasets(
            facts,
            task.authorized_read_paths,
            {
                relative_path: identities_by_path[
                    (PurePosixPath("workspace") / relative_path).as_posix()
                ]
                for relative_path in task.authorized_read_paths
            },
        )
    if any(
        field in facts
        for field in ("evidenceDecision", "codingRequirements", "visualizationPlan")
    ):
        raise ValueError("benchmark Coding 基础 facts 不得包含 planner 产物")
    if "variant" in payloads["plannerRequest"] or "variant" in payloads["executionContext"]:
        raise ValueError("冻结 bundle 不得内嵌 legacy/candidate variant")
    _validate_required_charts(payloads["plannerRequest"], task_payload)
    return manifest, payloads


def _validate_required_charts(
    planner_request: Mapping[str, Any], task_payload: Mapping[str, Any]
) -> None:
    """plannerRequest 携带 requiredCharts 时的形状与一致性校验。

    requiredCharts 是冻结的图表身份契约：chartId 全局唯一；
    sourcePath/interactivePath 的并集必须与 Coding declared_output_paths 严格相等。
    仅适用于 visualization 任务，其他任务携带即拒绝。
    条目中的未知键静默忽略，允许前向兼容扩展。
    """
    required = planner_request.get("requiredCharts")
    if required is None:
        return
    if task_payload.get("task_kind") != "visualization":
        raise ValueError("benchmark requiredCharts 仅适用于 visualization 任务")
    if not isinstance(required, list) or not required:
        raise ValueError("benchmark requiredCharts 必须是非空列表")
    chart_ids: list[str] = []
    paths: list[str] = []
    for item in required:
        if not isinstance(item, Mapping):
            raise ValueError("benchmark requiredCharts 项必须是对象")
        chart_id = item.get("chartId")
        source_path = item.get("sourcePath")
        interactive_path = item.get("interactivePath")
        if not isinstance(chart_id, str) or not chart_id:
            raise ValueError("benchmark requiredCharts 缺少 chartId")
        if not isinstance(source_path, str) or not source_path:
            raise ValueError("benchmark requiredCharts 缺少 sourcePath")
        if interactive_path is not None and not isinstance(interactive_path, str):
            raise ValueError("benchmark requiredCharts interactivePath 必须是字符串或 null")
        if interactive_path == "":
            raise ValueError(
                "benchmark requiredCharts interactivePath 不能是空字符串（无交互产物用 null）"
            )
        chart_ids.append(chart_id)
        paths.append(source_path)
        if interactive_path:
            paths.append(interactive_path)
    if len(chart_ids) != len(set(chart_ids)):
        raise ValueError("benchmark requiredCharts chartId 不能重复")
    if len(paths) != len(set(paths)):
        raise ValueError("benchmark requiredCharts sourcePath/interactivePath 不能重复")
    declared = task_payload.get("declared_output_paths")
    declared_set = set(declared) if isinstance(declared, (list, tuple)) else set()
    if set(paths) != declared_set:
        raise ValueError(
            "benchmark requiredCharts 路径集合与 declared_output_paths 不一致："
            f"missing={sorted(declared_set - set(paths))} "
            f"unexpected={sorted(set(paths) - declared_set)}"
        )
