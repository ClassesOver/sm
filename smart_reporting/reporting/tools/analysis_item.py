"""Reporting 分析结论的无状态规范化与耐久绑定。"""

# mypy: disable-error-code="attr-defined"
# 运行时由 toolkit 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。

from __future__ import annotations

import ast
import hashlib
import json
import re
import shlex
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any

from agno.run import RunContext
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from ...task_execution import abuild_workspace_changes, parse_unified_diff
from ...workspace import WorkspaceError, WorkspacePathConflict, WorkspaceService
from ..models import ReportingError
from ..workflow.checkpoint import (
    MetricDefinition,
)
from ..workflow.state import ReportingRunState
from .validation import (
    _jsonschema_error_message,
    _stable_digest,
    analysis_patch_parameters,
)
from .visualization import MAX_VISUALIZATION_SCRIPT_BYTES

MAX_ANALYSIS_PYTHON_DEPENDENCIES = 100
MAX_ANALYSIS_PYTHON_SOURCE_BYTES = 2 * 1024 * 1024
MAX_ANALYSIS_WRITE_INTENT_BYTES = 4 * 1024 * 1024
_ANALYSIS_SUMMARY_PERIOD_PATTERN = re.compile(
    r"(?P<year>\d{4})年(?:(?P<full>全年)|(?P<start>\d{1,2})(?:[-—–至到](?P<end>\d{1,2}))?月)"
)
_ANALYSIS_SUMMARY_SENTENCE_PATTERN = re.compile(r"[^。！？\n]+[。！？]?|\n")
_INCOMPARABLE_YOY_WARNING = "摘要中的比较期间长度不一致，已将“同比”规范为“参考对比”。"


def _fact_metric_codes(bundle: Mapping[str, Any]) -> tuple[str, ...]:
    """从单项确定性事实中提取真实指标代码，避免沿用计划阶段的通用占位符。"""

    codes = {
        code
        for metric in bundle.get("metrics", ())
        if isinstance(metric, Mapping)
        for code in metric.get("metricCodes", ())
        if isinstance(code, str) and code
    }
    codes.update(
        metric["code"]
        for metric in bundle.get("derivedMetrics", ())
        if isinstance(metric, Mapping) and isinstance(metric.get("code"), str) and metric["code"]
    )
    return tuple(sorted(codes))


def _missing_metric_definition_codes(
    *,
    fact_bundles: tuple[Mapping[str, Any], ...],
    chart_metric_codes: tuple[str, ...],
    metric_definitions: tuple[MetricDefinition, ...],
) -> tuple[str, ...]:
    """返回冻结事实或图表引用、但没有完整定义的指标 code。"""

    referenced: set[str] = {code for code in chart_metric_codes if isinstance(code, str) and code}
    for bundle in fact_bundles:
        referenced.update(_fact_metric_codes(bundle))
    defined = {item.code for item in metric_definitions}
    return tuple(sorted(referenced - defined))


def _normalize_analysis_summary_comparability(summary: str) -> tuple[str, tuple[str, ...]]:
    """只规范摘要中能确定识别为不等长月份窗口的“同比”表述。"""

    normalized: list[str] = []
    changed = False
    for sentence in _ANALYSIS_SUMMARY_SENTENCE_PATTERN.findall(summary):
        periods = list(_ANALYSIS_SUMMARY_PERIOD_PATTERN.finditer(sentence))
        lengths = [
            12
            if match.group("full")
            else int(match.group("end") or match.group("start")) - int(match.group("start")) + 1
            for match in periods[:2]
        ]
        if "同比" in sentence and len(lengths) == 2 and lengths[0] != lengths[1]:
            sentence = sentence.replace("同比", "参考对比")
            changed = True
        normalized.append(sentence)
    return "".join(normalized), ((_INCOMPARABLE_YOY_WARNING,) if changed else ())


def _derive_durable_analysis_binding(
    durable_item: Mapping[str, Any],
) -> dict[str, Any]:
    """从单项耐久账本派生 Finalize 绑定，忽略模型的过期精简副本。

    ProfileCoverage 由服务端独立证明完整性；只有单项结论实际读取并提交的 receipt
    才能绑定 evidence。Dataset 相同不能证明该查询被当前结论使用。
    """

    dataset_ids = [value for value in durable_item.get("datasetIds", ()) if isinstance(value, str)]
    explicit_receipt_ids = [
        value for value in durable_item.get("profileReadReceiptIds", ()) if isinstance(value, str)
    ]
    return {
        **dict(durable_item),
        "datasetIds": dataset_ids,
        "citationIds": [
            value for value in durable_item.get("citationIds", ()) if isinstance(value, str)
        ],
        "chartIds": [value for value in durable_item.get("chartIds", ()) if isinstance(value, str)],
        "profileReadReceiptIds": list(dict.fromkeys(explicit_receipt_ids)),
    }


class RuntimeAnalysisMixin:
    def _validate_analysis_write_arguments(
        self, tool_name: str, arguments: Mapping[str, Any]
    ) -> tuple[dict[str, Any], tuple[str, ...], dict[str, str], int]:
        """按公开 unified diff schema 冻结完整写入身份。"""

        schemas = {"apply_analysis_patch": analysis_patch_parameters}
        schema_factory = schemas.get(tool_name)
        if schema_factory is None:
            raise ReportingError(
                "report_analysis_write_intent_invalid", "暂存工具不支持该写入类型。"
            )
        raw = deepcopy(dict(arguments))
        try:
            Draft202012Validator(schema_factory()).validate(raw)
        except JsonSchemaValidationError as error:
            path = "arguments"
            for part in error.absolute_path:
                path += f"[{part}]" if isinstance(part, int) else f".{part}"
            expected_fields = sorted(schema_factory()["properties"])
            raise ReportingError(
                "report_analysis_write_intent_invalid",
                f"{tool_name} 参数不符合公开 schema；请仅修正 details.path 指向的字段。",
                details={
                    "toolName": tool_name,
                    "path": path,
                    "validator": str(error.validator),
                    "message": _jsonschema_error_message(error),
                    "expectedFields": expected_fields,
                },
            ) from error
        expected_states: dict[str, str] = {}

        def add_path(value: str, state: str) -> None:
            try:
                path = WorkspaceService.normalize_path(value, allow_root=False)[0]
            except WorkspaceError as error:
                raise ReportingError(
                    "report_analysis_write_intent_invalid", "写入目标路径无效。"
                ) from error
            if path in expected_states:
                raise ReportingError(
                    "report_analysis_write_intent_invalid", "写入目标路径不能重复。"
                )
            expected_states[path] = state

        operations = parse_unified_diff(raw["patch"])
        expected_sha256 = raw.get("expected_sha256", {})
        if not isinstance(expected_sha256, dict):
            raise ReportingError(
                "report_analysis_write_intent_invalid", "expected_sha256 必须是对象。"
            )
        normalized_expected: dict[str, str] = {}
        for path, digest in expected_sha256.items():
            if not isinstance(path, str) or not isinstance(digest, str):
                raise ReportingError(
                    "report_analysis_write_intent_invalid", "基线 SHA-256 映射无效。"
                )
            normalized_path = WorkspaceService.normalize_path(path, allow_root=False)[0]
            if (
                normalized_path in normalized_expected
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ReportingError(
                    "report_analysis_write_intent_invalid", "基线 SHA-256 映射无效。"
                )
            normalized_expected[normalized_path] = digest
        operation_paths = {
            WorkspaceService.normalize_path(item.path, allow_root=False)[0] for item in operations
        }
        if set(normalized_expected) - operation_paths:
            raise ReportingError(
                "report_analysis_write_intent_invalid", "基线 SHA-256 包含非补丁目标路径。"
            )
        for operation in operations:
            add_path(operation.path, "present")
        raw["expected_sha256"] = normalized_expected

        payload_bytes = len(
            json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if payload_bytes > MAX_ANALYSIS_WRITE_INTENT_BYTES:
            raise ReportingError(
                "report_analysis_write_intent_too_large", "单次 analysis 写入意图超过大小上限。"
            )
        return raw, tuple(expected_states), expected_states, payload_bytes

    @staticmethod
    def _analysis_write_desired_identities(
        tool_name: str,
        canonical: Mapping[str, Any],
    ) -> dict[str, dict[str, Any]]:
        contents: dict[str, str] = {}
        if tool_name == "apply_analysis_patch":
            for operation in canonical.get("operations", ()):
                if isinstance(operation, Mapping) and isinstance(operation.get("path"), str):
                    content = operation.get("content")
                    if isinstance(content, str):
                        contents[operation["path"]] = content
        return {
            WorkspaceService.normalize_path(path, allow_root=False)[0]: {
                "path": WorkspaceService.normalize_path(path, allow_root=False)[0],
                "size": len(content.encode("utf-8")),
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
            for path, content in contents.items()
        }

    async def _analysis_write_hash_files(
        self,
        *,
        thread_id: str,
        paths: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        """读取写入回执；基础设施异常保留原类型交由 Agent retry。"""

        return await self.runtime.workspace.batch_hash_files(thread_id, paths)

    async def _recover_pending_analysis_write(
        self,
        *,
        scope: Any,
        tool_name: str,
        canonical: Mapping[str, Any],
        paths: tuple[str, ...],
        intent_sha256: str,
        payload_bytes: int,
    ) -> dict[str, Any] | None:
        """提交已落盘但回执丢失的确定性写入；身份不一致时失败关闭。"""

        desired = self._analysis_write_desired_identities(tool_name, canonical)
        if not desired:
            return None
        current = await self._analysis_write_hash_files(
            thread_id=scope.thread_id,
            paths=paths,
        )
        current_by_path = {item.get("path"): item for item in current if isinstance(item, dict)}
        if all(current_by_path.get(path) == identity for path, identity in desired.items()):
            artifacts = [current_by_path[path] for path in paths]
            await self._apply_durable(
                scope,
                name="commit_write_intent",
                payload={"intentId": intent_sha256, "artifacts": artifacts},
                command_id=f"write-commit:{intent_sha256}",
            )
            return {
                "ok": True,
                "status": "committed",
                "intentSha256": intent_sha256,
                "bytes": payload_bytes,
                "artifacts": artifacts,
                "recovered": True,
            }
        present_paths = [
            path
            for path in desired
            if isinstance(current_by_path.get(path), dict)
            and current_by_path[path].get("missing") is not True
        ]
        if present_paths:
            raise ReportingError(
                "report_analysis_write_identity_mismatch",
                "待恢复写入的文件身份与已保存意图不一致。",
                details={"paths": present_paths},
            )
        return None

    async def _preflight_analysis_python_write(
        self,
        *,
        scope: Any,
        tool_name: str,
        canonical: Mapping[str, Any],
    ) -> None:
        """在提交 Workspace mutation 前拒绝会破坏 Python 语法的写入。"""

        changes = list(canonical.get("operations", ()))

        # Kernel patch 的实际提交发生在这之后；预检只使用同一候选文本，保证语法错误时
        # Workspace 与 write intent 都不产生可恢复但无效的中间状态。
        _parameters, contract = self._phase_parameters(scope, "analysis")
        workspace = contract.get("visualizationWorkspace")
        script_path = workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
        normalized_script = (
            WorkspaceService.normalize_path(script_path, allow_root=False)[0]
            if contract.get("taskKind") == "visualization_section"
            else None
        )
        for change in changes:
            path = change.get("path")
            content = change.get("content")
            if (
                change.get("operation") not in {"create", "update"}
                or not isinstance(path, str)
                or not path.endswith(".py")
                or not isinstance(content, str)
            ):
                continue
            # visualization 的签发脚本必须能在一次工具回执中完整恢复。这里校验最终
            # 候选文本，使 replace/patch 也无法通过分次写入绕过，并且发生在 intent
            # 与 Workspace mutation 之前；错误详情只记录身份信息，不泄露脚本正文。
            content_bytes = len(content.encode("utf-8"))
            if path == normalized_script and content_bytes > MAX_VISUALIZATION_SCRIPT_BYTES:
                raise ReportingError(
                    "report_visualization_script_too_large",
                    "visualization 签发脚本超过 64 KiB 完整读取边界，已拒绝写入。",
                    details={
                        "path": path,
                        "size": content_bytes,
                        "limit": MAX_VISUALIZATION_SCRIPT_BYTES,
                    },
                )
            try:
                tree = ast.parse(content, filename=path)
                compile(tree, path, "exec")
            except SyntaxError as error:
                raise ReportingError(
                    "report_analysis_python_syntax_invalid",
                    "写入会使分析 Python 脚本语法无效，已拒绝写入。",
                    details={"path": path, "line": error.lineno, "offset": error.offset},
                ) from error

    async def apply_analysis_patch(
        self,
        patch: str,
        expected_sha256: dict[str, str] | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """保存固定操作的写入意图、执行写入并返回文件身份。"""

        canonical_tool_name = "apply_analysis_patch"
        canonical_input = {
            "patch": patch,
            **({"expected_sha256": expected_sha256} if expected_sha256 else {}),
        }

        async def call(scope: Any) -> dict[str, Any]:
            _parameters, contract = self._phase_parameters(scope, "analysis")
            canonical, paths, expected_states, payload_bytes = (
                self._validate_analysis_write_arguments(canonical_tool_name, canonical_input)
            )
            raw_operations = await abuild_workspace_changes(
                self.runtime.workspace,
                scope.thread_id,
                canonical["patch"],
                canonical.get("expected_sha256"),
            )
            canonical["operations"] = raw_operations
            self._require_analysis_task_output_paths(contract, paths)
            await self._preflight_analysis_python_write(
                scope=scope,
                tool_name=canonical_tool_name,
                canonical=canonical,
            )
            payload = json.dumps(
                {
                    "version": "1",
                    "toolName": canonical_tool_name,
                    "arguments": canonical,
                    "affectedPaths": list(paths),
                    "expectedStates": expected_states,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            intent_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            intent = json.loads(payload)
            intent["intentId"] = intent_sha256
            durable = await self._durable_state(scope)
            existing = durable.payload.get("writeIntents", {}).get(intent_sha256)
            if isinstance(existing, dict) and existing.get("status") == "committed":
                artifacts = existing.get("artifacts")
                if not isinstance(artifacts, list):
                    raise ReportingError(
                        "report_analysis_write_intent_invalid", "已提交写入意图缺少文件身份。"
                    )
                current = await self._analysis_write_hash_files(
                    thread_id=scope.thread_id,
                    paths=paths,
                )
                if current != artifacts:
                    raise ReportingError(
                        "report_analysis_write_identity_mismatch",
                        "已提交写入意图的文件身份发生变化。",
                    )
                return {
                    "ok": True,
                    "status": "committed",
                    "intentSha256": intent_sha256,
                    "bytes": payload_bytes,
                    "artifacts": artifacts,
                }
            if isinstance(existing, dict) and existing.get("status") == "pending":
                recovered = await self._recover_pending_analysis_write(
                    scope=scope,
                    tool_name=canonical_tool_name,
                    canonical=canonical,
                    paths=paths,
                    intent_sha256=intent_sha256,
                    payload_bytes=payload_bytes,
                )
                if recovered is not None:
                    return recovered
            await self._apply_durable(
                scope,
                name="record_write_intent",
                payload={"intent": intent},
                command_id=f"write-intent:{intent_sha256}",
            )
            try:
                result = await self.runtime.patch(
                    "patch", None, None, None, False, canonical["patch"], run_context, _scope=scope
                )
            except WorkspacePathConflict as error:
                try:
                    current_files = await self._analysis_write_hash_files(
                        thread_id=scope.thread_id,
                        paths=paths,
                    )
                except Exception:
                    current_files = []
                raise ReportingError(
                    "report_analysis_write_path_conflict",
                    "写入目标文件已存在或内容身份已变化。",
                    details={
                        "paths": list(paths),
                        "currentFiles": current_files,
                        "recoveryOperation": "apply_analysis_patch",
                    },
                ) from error
            if result.get("ok") is not True:
                return result
            identities = await self._analysis_write_hash_files(
                thread_id=scope.thread_id,
                paths=paths,
            )
            by_path = {item.get("path"): item for item in identities if isinstance(item, dict)}
            for path, expected_state in expected_states.items():
                identity = by_path.get(path, {})
                if (expected_state == "absent") != bool(identity.get("missing")):
                    raise ReportingError(
                        "report_analysis_write_identity_mismatch",
                        "写入后的文件身份与服务端意图不一致。",
                    )
            response = {
                "ok": True,
                "status": "committed",
                "intentSha256": intent_sha256,
                "bytes": payload_bytes,
                "artifacts": identities,
            }
            await self._apply_durable(
                scope,
                name="commit_write_intent",
                payload={"intentId": intent_sha256, "artifacts": identities},
                command_id=f"write-commit:{intent_sha256}",
            )
            if len(json.dumps(response, ensure_ascii=False).encode("utf-8")) > 8 * 1024:
                return await self.runtime.bound_tool_result(
                    scope, response, run_context, retain=True
                )
            return response

        try:
            external_run_id = self.runtime.bound_external_run_id(run_context)
            async with self.runtime.task_scheduler(external_run_id) as scheduler, scheduler.write():
                scope = await self.runtime.scope(run_context)
                self._require_phase_tool(
                    scope,
                    allowed=frozenset({"analysis"}),
                    tool_name=canonical_tool_name,
                    run_context=run_context,
                )
                return await call(scope)
        except (ReportingError, WorkspaceError, ValueError) as error:
            return self._failure(error)

    @staticmethod
    def _direct_python_script_path(command: Any, workdir: Any) -> str | None:
        if not isinstance(command, str) or "\n" in command:
            return None
        try:
            parts = shlex.split(command)
        except ValueError:
            return None
        if (
            not parts
            or re.fullmatch(r"python(?:3(?:\.\d+)?)?", PurePosixPath(parts[0]).name) is None
        ):
            return None
        script: str | None = None
        for argument in parts[1:]:
            if argument == "-m":
                return None
            if script is None and argument.startswith("-"):
                continue
            script = argument
            break
        if script is None or not script.endswith(".py"):
            return None
        base = PurePosixPath(str(workdir or ""))
        candidate = base / script
        return WorkspaceService.normalize_path(candidate.as_posix(), allow_root=False)[0]

    async def _installed_python_modules(
        self,
        *,
        thread_id: str,
        module_names: set[str],
    ) -> set[str]:
        if not module_names:
            return set()
        probe = (
            "import importlib.util,json,sys;"
            "names=json.loads(sys.argv[1]);"
            "print(json.dumps([name for name in names if importlib.util.find_spec(name) is not None]))"
        )
        command = shlex.join(["python3", "-I", "-c", probe, json.dumps(sorted(module_names))])
        result = await self.runtime.workspace.execute_isolated(thread_id, command, timeout=30)
        if getattr(result, "exit_code", None) != 0:
            raise ReportingError(
                "report_analysis_dependency_probe_failed",
                "无法确认分析脚本依赖是否完整，已拒绝执行脚本。",
            )
        try:
            parsed = json.loads(str(getattr(result, "result", "") or ""))
        except (TypeError, ValueError) as error:
            raise ReportingError(
                "report_analysis_dependency_probe_failed",
                "分析脚本依赖探测结果无效，已拒绝执行脚本。",
            ) from error
        return (
            {item for item in parsed if isinstance(item, str)}
            if isinstance(parsed, list)
            else set()
        )

    async def _analysis_python_source(self, *, thread_id: str, path: str) -> bytes:
        return await self.runtime.workspace.read_limited_regular_file(
            thread_id,
            path,
            max_bytes=MAX_ANALYSIS_PYTHON_SOURCE_BYTES,
        )

    async def _analysis_python_dependency_rejection(
        self,
        *,
        scope: Any,
        command: Any,
        workdir: Any,
    ) -> dict[str, Any] | None:
        try:
            script_path = self._direct_python_script_path(command, workdir)
            if script_path is None:
                return None
            pending = [script_path]
            visited: set[str] = set()
            unresolved: dict[str, tuple[str, ...]] = {}
            while pending:
                current_path = pending.pop()
                if current_path in visited:
                    continue
                if len(visited) >= MAX_ANALYSIS_PYTHON_DEPENDENCIES:
                    raise ReportingError(
                        "report_analysis_dependency_limit",
                        "分析脚本本地依赖超过服务端预检上限，已拒绝执行。",
                    )
                visited.add(current_path)
                try:
                    content = await self._analysis_python_source(
                        thread_id=scope.thread_id,
                        path=current_path,
                    )
                except WorkspaceError as error:
                    raise ReportingError(
                        "report_analysis_script_missing",
                        f"待执行 Python 脚本不存在：{current_path}",
                    ) from error
                source = content.decode("utf-8")
                tree = ast.parse(source, filename=current_path)
                compile(tree, current_path, "exec")
                current_dir = PurePosixPath(current_path).parent
                imports: set[tuple[str, int]] = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.update((alias.name, 0) for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports.add((node.module, node.level))
                        elif node.level:
                            imports.update(
                                (alias.name, node.level)
                                for alias in node.names
                                if alias.name != "*"
                            )
                for module_name, level in imports:
                    module_parts = module_name.split(".")
                    base = current_dir
                    roots: tuple[PurePosixPath, ...]
                    if level:
                        for _index in range(level - 1):
                            base = base.parent
                        roots = (base,)
                    else:
                        roots = tuple(dict.fromkeys((current_dir, PurePosixPath("."))))
                    candidates: list[str] = []
                    for root in roots:
                        module_path = root.joinpath(*module_parts)
                        candidates.extend(
                            (
                                f"{module_path.as_posix()}.py",
                                (module_path / "__init__.py").as_posix(),
                            )
                        )
                    normalized = tuple(
                        WorkspaceService.normalize_path(path, allow_root=False)[0]
                        for path in dict.fromkeys(candidates)
                    )
                    identities = await self.runtime.workspace.batch_hash_files(
                        scope.thread_id, list(normalized)
                    )
                    local_path = next(
                        (
                            str(item.get("path"))
                            for item in identities
                            if isinstance(item, Mapping) and item.get("missing") is not True
                        ),
                        None,
                    )
                    if local_path is not None:
                        pending.append(local_path)
                    elif level:
                        unresolved[module_name] = normalized
                    else:
                        unresolved.setdefault(module_name.split(".", 1)[0], normalized)
            installed = (
                await self._installed_python_modules(
                    thread_id=scope.thread_id,
                    module_names=set(unresolved),
                )
                if unresolved
                else set()
            )
            missing = {
                module_name: candidates
                for module_name, candidates in unresolved.items()
                if module_name not in installed
            }
            if not missing:
                return None
            missing_paths = sorted({paths[0] for paths in missing.values()})
            return self._failure(
                ReportingError(
                    "report_analysis_dependency_missing",
                    "分析脚本存在缺失的工作区本地 Python 依赖，已拒绝执行。",
                    details={
                        "scriptPath": script_path,
                        "missingModules": sorted(missing),
                        "missingPaths": missing_paths,
                    },
                ),
                retryable=False,
            )
        except SyntaxError as error:
            return self._failure(
                ReportingError(
                    "report_analysis_python_syntax_invalid",
                    "待执行分析 Python 脚本语法无效，已拒绝执行。",
                    details={
                        "path": script_path,
                        "line": error.lineno,
                        "offset": error.offset,
                    },
                )
            )
        except (ReportingError, WorkspaceError) as error:
            return self._failure(error, retryable=False)

    async def complete_analysis_item(
        self,
        analysisId: str,
        summary: str,
        datasetIds: list[str],
        evidencePaths: list[str],
        citationIds: list[str],
        profileReadReceiptIds: list[str],
        warnings: list[str],
        chartIds: list[str] | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """把不可变固定事实直接绑定为 evidence，并结束对应的独立 Task。

        模型只在固定事实存在缺口时提交补充 evidencePaths；服务端始终追加当前 analysis
        的 deterministic fact 文件，并按路径、大小和 SHA-256 校验 durable artifact 账本。
        durable 游标已推进但 Task 收尾中断时，只允许相同 payload 在新 attempt 中幂等恢复，
        任何字段或文件身份变化都拒绝。
        """

        try:
            scope = await self.runtime.scope(run_context)
            _parameters, contract = self._phase_parameters(scope, "analysis")
            if contract.get("taskKind") != "analysis_item":
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "complete_analysis_item 只允许 analysis_item Task 调用。",
                )
            expected = contract.get("analysisIds")
            if not isinstance(expected, list) or expected != [analysisId]:
                raise ReportingError("report_analysis_item_unknown", "analysisId 不在冻结计划中。")
            durable_current = await self._durable_state(scope)
            analysis_items = durable_current.payload.get("analysisItems")
            durable_item = (
                analysis_items.get(analysisId) if isinstance(analysis_items, dict) else None
            )
            raw_plans = contract.get("analysisPlans")
            planned = raw_plans.get(analysisId) if isinstance(raw_plans, Mapping) else None
            planned_metrics = (
                list(
                    dict.fromkeys(
                        value for value in planned.get("metrics", ()) if isinstance(value, str)
                    )
                )
                if isinstance(planned, Mapping)
                else []
            )
            chart_ids = list(
                dict.fromkeys(value for value in (chartIds or ()) if isinstance(value, str))
            )
            if chartIds is not None and len(chart_ids) != len(chartIds):
                raise ReportingError(
                    "report_analysis_chart_invalid",
                    "chartIds 必须是不重复的字符串数组。",
                )
            self._require_analysis_output_paths(contract, evidencePaths)
            summary, comparability_warnings = _normalize_analysis_summary_comparability(summary)
            warnings = list(dict.fromkeys((*warnings, *comparability_warnings)))
            payload: dict[str, Any] = {
                "analysisId": analysisId,
                "summary": summary,
                "datasetIds": datasetIds,
                "evidencePaths": evidencePaths,
                "citationIds": citationIds,
                "profileReadReceiptIds": profileReadReceiptIds,
                "warnings": warnings,
            }
            if isinstance(planned, Mapping):
                payload["metrics"] = planned_metrics
            if chartIds is not None or isinstance(planned, Mapping):
                payload["chartIds"] = chart_ids
            deterministic_files = contract.get("deterministicFactFiles")
            deterministic_identity = (
                deterministic_files.get(analysisId)
                if isinstance(deterministic_files, dict)
                else None
            )
            if isinstance(deterministic_identity, dict):
                deterministic_path = deterministic_identity.get("path")
                if isinstance(deterministic_path, str) and deterministic_path:
                    evidencePaths = list(dict.fromkeys((*evidencePaths, deterministic_path)))
                    payload["evidencePaths"] = evidencePaths
            if not evidencePaths:
                raise ReportingError(
                    "report_analysis_evidence_missing",
                    "当前 analysis 缺少可绑定的不可变固定事实或补充 evidence。",
                )
            expected_datasets = contract.get("analysisDatasetIds")
            if isinstance(expected_datasets, dict):
                planned = expected_datasets.get(analysisId)
                if isinstance(planned, list) and set(datasetIds) != set(planned):
                    warnings.append("analysis Dataset 与冻结计划不一致，已保留实际提交归属。")
            authorized_dataset_ids = contract.get("authorizedDatasetIds")
            if isinstance(authorized_dataset_ids, list) and not set(datasetIds).issubset(
                set(item for item in authorized_dataset_ids if isinstance(item, str))
            ):
                warnings.append("analysis evidence Dataset 不属于授权 snapshot。")
            receipts = durable_current.payload.get("profileReadReceipts")
            receipt_by_id = {
                item.get("receiptId"): item
                for item in receipts or ()
                if isinstance(item, dict) and isinstance(item.get("receiptId"), str)
            }
            unknown_receipt_ids = set(profileReadReceiptIds) - set(receipt_by_id)
            if unknown_receipt_ids:
                raise ReportingError(
                    "report_profile_receipt_unknown",
                    "analysis item 引用了不存在的 ProfileReadReceipt。",
                )
            if any(
                receipt_by_id[receipt_id].get("datasetId") not in set(datasetIds)
                for receipt_id in profileReadReceiptIds
            ):
                raise ReportingError(
                    "report_profile_receipt_dataset_mismatch",
                    "analysis item 绑定的 ProfileReadReceipt 不属于其 Dataset 范围。",
                )
            identities = await self.runtime.workspace.batch_hash_files(
                scope.thread_id, evidencePaths
            )
            _durable, evidence_warnings = await self._ensure_registered_analysis_evidence(
                scope=scope, identities=identities
            )
            warnings.extend(evidence_warnings)
            payload["warnings"] = list(dict.fromkeys(warnings))
            payload["evidenceFiles"] = identities
            if isinstance(durable_item, dict):
                if durable_item != payload:
                    raise ReportingError(
                        "report_analysis_item_completion_conflict",
                        "analysisId 已绑定其他完成 payload，不能替换。",
                    )
                durable = durable_current
            else:
                durable = await self._apply_durable(
                    scope,
                    name="complete_analysis_item",
                    payload=payload,
                    command_id=f"analysis-item:{analysisId}:{_stable_digest(payload)}",
                )
            next_id = durable.payload.get("currentAnalysisId")
            self._complete_phase_plan(self._session_state(run_context))
            finish_result = await self.runtime.finish_task(
                f"分析项 {analysisId} 已提交冻结事实与证据。",
                [item["path"] for item in identities],
                None,
                [],
                run_context,
                self._finish_function,
                _scope=scope,
            )
            if finish_result.get("status") != "accepted":
                return finish_result
            return {
                "ok": True,
                "status": "accepted",
                "analysisId": analysisId,
                "readyToFinalize": next_id is None,
                "taskFinished": True,
            }
        except (ReportingError, WorkspaceError) as error:
            return self._failure(error)

    @staticmethod
    def _analysis_evidence_registration_status(
        *,
        durable: ReportingRunState,
        identities: list[dict[str, Any]],
    ) -> tuple[list[str], list[str], list[str]]:
        """返回缺失、未登记和身份变化的 evidence 路径。"""

        missing: list[str] = []
        for item in identities:
            path = item.get("path")
            if item.get("missing") is True and isinstance(path, str):
                missing.append(path)
        payload = durable.payload if isinstance(durable.payload, dict) else {}
        registered: list[dict[str, Any]] = []
        artifacts = payload.get("artifacts")
        if isinstance(artifacts, list):
            registered.extend(item for item in artifacts if isinstance(item, dict))
        intents = payload.get("writeIntents")
        if isinstance(intents, dict):
            for intent in intents.values():
                if not isinstance(intent, dict) or intent.get("status") != "committed":
                    continue
                committed = intent.get("artifacts")
                if isinstance(committed, list):
                    registered.extend(item for item in committed if isinstance(item, dict))

        registered_by_path = {
            item.get("path"): item for item in registered if isinstance(item.get("path"), str)
        }
        unregistered: list[str] = []
        changed: list[str] = []
        for identity in identities:
            if not isinstance(identity, dict) or not isinstance(identity.get("path"), str):
                continue
            path = identity["path"]
            expected = registered_by_path.get(path)
            if expected is None:
                unregistered.append(path)
            elif expected.get("size") != identity.get("size") or expected.get(
                "sha256"
            ) != identity.get("sha256"):
                changed.append(path)
        return missing, unregistered, changed

    @classmethod
    def _validate_registered_analysis_evidence(
        cls,
        *,
        durable: ReportingRunState,
        identities: list[dict[str, Any]],
    ) -> list[str]:
        """确认 evidence 可读取；身份漂移只记录 warning，不阻止发布。"""

        missing, unregistered, changed = cls._analysis_evidence_registration_status(
            durable=durable,
            identities=identities,
        )
        if missing:
            raise ReportingError(
                "report_analysis_evidence_missing",
                "analysis evidence 文件不存在。",
                details={"paths": missing},
            )
        warnings: list[str] = []
        if changed:
            warnings.append("analysis evidence 文件身份或 SHA-256 已变化，已按当前文件继续发布。")
        if unregistered:
            warnings.append("analysis evidence 文件未登记，已按当前文件继续发布。")
        return warnings

    async def _ensure_registered_analysis_evidence(
        self,
        *,
        scope: Any,
        identities: list[dict[str, Any]],
    ) -> tuple[ReportingRunState, list[str]]:
        """把 terminal 等工具已写出的 evidence 身份登记到唯一 durable 账本。"""

        durable = await self._durable_state(scope)
        missing, unregistered, changed = self._analysis_evidence_registration_status(
            durable=durable,
            identities=identities,
        )
        if missing:
            raise ReportingError(
                "report_analysis_evidence_missing",
                "analysis evidence 文件不存在。",
                details={"paths": missing},
            )
        warnings: list[str] = []
        if changed:
            warnings.append("analysis evidence 文件身份或 SHA-256 已变化，已按当前文件继续发布。")
        identities_by_path = {
            item["path"]: item
            for item in identities
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        for path in unregistered:
            identity = identities_by_path[path]
            try:
                durable = await self._apply_durable(
                    scope,
                    name="record_artifact",
                    payload={"artifact": identity},
                    command_id=f"analysis-evidence:{path}:{identity.get('sha256')}",
                )
            except ReportingError as error:
                if error.code != "report_artifact_identity_mismatch":
                    raise
                warnings.append("analysis evidence 登记身份发生变化，已按当前文件继续发布。")
        warnings.extend(
            self._validate_registered_analysis_evidence(
                durable=durable,
                identities=identities,
            )
        )
        return durable, list(dict.fromkeys(warnings))


def _require_dataset_id_sequence(value: object) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ReportingError("report_analysis_dataset_inconsistent", "Dataset ID 序列无效。")
    return list(value)
