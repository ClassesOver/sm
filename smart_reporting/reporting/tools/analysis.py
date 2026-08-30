"""Reporting 分析结论的无状态规范化与耐久绑定。"""

# mypy: disable-error-code="attr-defined"
# 运行时由 toolkit 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import re
import shlex
from collections.abc import Mapping
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any

from agno.run import RunContext
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from ...task_execution.changes import (
    build_workspace_changes,
    create_files_patch,
    parse_unified_diff,
)
from ...workspace import WORKSPACE_ROOT, WorkspaceError, WorkspacePathConflict, WorkspaceService
from ..models import ReportingError
from ..workflow.checkpoint import (
    AnalysisArtifact,
    AnalysisChart,
    AnalysisDatasetSemantics,
    AnalysisEvidence,
    AnalysisEvidenceManifest,
    FileIdentity,
    MetricDefinition,
    ProfileReadReceipt,
    ReportBrief,
)
from ..workflow.state import ReportingRunState
from .phase_output import REPORT_PHASE_OUTPUT_STATE_KEY
from .validation import (
    ANALYSIS_WRITE_TOOL_NAMES,
    _analysis_write_operation_arguments,
    _canonical_analysis_write_call,
    _jsonschema_error_message,
    _stable_digest,
)

MAX_ANALYSIS_PYTHON_DEPENDENCIES = 100
MAX_ANALYSIS_PYTHON_SOURCE_BYTES = 2 * 1024 * 1024
MAX_ANALYSIS_WRITE_INTENT_BYTES = 4 * 1024 * 1024
MAX_VISUALIZATION_SCRIPT_BYTES = 64 * 1024

_ANALYSIS_SUMMARY_PERIOD_PATTERN = re.compile(
    r"(?P<year>\d{4})年(?:(?P<full>全年)|(?P<start>\d{1,2})(?:[-—–至到](?P<end>\d{1,2}))?月)"
)
_ANALYSIS_SUMMARY_SENTENCE_PATTERN = re.compile(r"[^。！？\n]+[。！？]?|\n")
_INCOMPARABLE_YOY_WARNING = "摘要中的比较期间长度不一致，已将“同比”规范为“参考对比”。"


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
        """复用原工具 JSON Schema 与原生补丁解析器，冻结完整写入身份。"""

        function = self.async_functions.get(tool_name)
        if tool_name not in ANALYSIS_WRITE_TOOL_NAMES or function is None:
            raise ReportingError(
                "report_analysis_write_intent_invalid", "暂存工具不支持该写入类型。"
            )
        raw = deepcopy(dict(arguments))
        if tool_name == "create_files" and isinstance(raw.get("files"), list):
            if len(raw["files"]) != 1:
                raise ReportingError(
                    "report_analysis_write_intent_invalid",
                    "create_files 每次只能提交一个文件；单个完整长脚本可在一次调用中提交。",
                )
        try:
            Draft202012Validator(function.parameters).validate(raw)
        except JsonSchemaValidationError as error:
            path = "arguments"
            for part in error.absolute_path:
                path += f"[{part}]" if isinstance(part, int) else f".{part}"
            expected_fields = sorted(function.parameters.get("properties", {}).keys())
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
        if tool_name == "replace_text":
            raw.setdefault("replace_all", False)

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

        if tool_name in {"overwrite_file", "replace_text"}:
            add_path(raw["path"], "present")
        elif tool_name == "create_files":
            for item in raw["files"]:
                add_path(item["path"], "present")
        else:
            try:
                operations = parse_unified_diff(raw["patch"])
            except WorkspaceError as error:
                raise ReportingError("report_analysis_write_intent_invalid", str(error)) from error
            for operation in operations:
                if operation.operation == "delete":
                    add_path(operation.path, "absent")
                else:
                    add_path(operation.path, "present")

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
        if tool_name == "create_files":
            contents = {
                item["path"]: item["content"]
                for item in canonical.get("files", ())
                if isinstance(item, Mapping)
                and isinstance(item.get("path"), str)
                and isinstance(item.get("content"), str)
            }
        elif tool_name == "overwrite_file":
            path = canonical.get("path")
            content = canonical.get("content")
            if isinstance(path, str) and isinstance(content, str):
                contents[path] = content
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

        return await self.kernel.service.abatch_hash_files(thread_id, list(paths))

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

        if tool_name == "create_files":
            changes = [
                {
                    "operation": "create",
                    "path": WorkspaceService.normalize_path(item["path"], allow_root=False)[0],
                    "content": item["content"],
                }
                for item in canonical["files"]
            ]
        elif tool_name == "overwrite_file":
            changes = [
                {
                    "operation": "update",
                    "path": WorkspaceService.normalize_path(canonical["path"], allow_root=False)[0],
                    "content": canonical["content"],
                }
            ]
        elif tool_name == "replace_text":

            def replacement() -> list[dict[str, Any]]:
                path = WorkspaceService.normalize_path(canonical["path"], allow_root=False)[0]
                content, _mime = self.kernel.service.file_bytes(scope.thread_id, path)
                try:
                    original = content.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise WorkspaceError("replace 模式只支持 UTF-8 文本文件。") from error
                count = original.count(canonical["old_string"])
                if count == 0:
                    raise ReportingError(
                        "report_replace_target_not_found",
                        "old_string 在目标文件中不存在。",
                        details={
                            "path": path,
                            "matchCount": 0,
                            "preview": original[:200],
                        },
                    )
                if count != 1 and not canonical["replace_all"]:
                    raise ReportingError(
                        "report_replace_target_ambiguous",
                        "old_string 在目标文件中不唯一；请扩大上下文或启用 replace_all。",
                        details={
                            "path": path,
                            "matchCount": count,
                            "preview": original[:200],
                        },
                    )
                return [
                    {
                        "operation": "update",
                        "path": path,
                        "content": original.replace(
                            canonical["old_string"],
                            canonical["new_string"],
                            -1 if canonical["replace_all"] else 1,
                        ),
                    }
                ]

            changes = await asyncio.to_thread(replacement)
        else:
            changes = await asyncio.to_thread(
                build_workspace_changes,
                self.kernel.service,
                scope.thread_id,
                canonical["patch"],
            )

        # Kernel patch 的实际提交发生在这之后；预检只使用同一候选文本，保证语法错误时
        # Workspace 与 write intent 都不产生可恢复但无效的中间状态。
        _parameters, contract = self._phase_parameters(scope, "analysis")
        workspace = contract.get("visualizationWorkspace")
        script_path = workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
        normalized_script = (
            WorkspaceService.normalize_path(script_path, allow_root=False)[0]
            if contract.get("taskKind") == "visualization"
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

    async def write_analysis_files(
        self,
        operation: str,
        path: str | None = None,
        content: str | None = None,
        expected_sha256: str | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
        replace_all: bool | None = None,
        patch: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """在单次调用内保存写入意图、执行写入并返回文件身份。"""

        requested_arguments = _analysis_write_operation_arguments(
            operation,
            {
                "path": path,
                "content": content,
                "expected_sha256": expected_sha256,
                "old_string": old_string,
                "new_string": new_string,
                "replace_all": replace_all,
                "patch": patch,
            },
        )
        canonical_tool_name, canonical_input = _canonical_analysis_write_call(
            operation, requested_arguments
        )

        async def call(scope: Any) -> dict[str, Any]:
            _parameters, contract = self._phase_parameters(scope, "analysis")
            canonical, paths, expected_states, payload_bytes = (
                self._validate_analysis_write_arguments(canonical_tool_name, canonical_input)
            )
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
                if canonical_tool_name == "overwrite_file":
                    result = await self.kernel.patch(
                        "overwrite",
                        canonical["path"],
                        None,
                        None,
                        False,
                        None,
                        run_context,
                        content=canonical["content"],
                        expected_sha256=canonical["expected_sha256"],
                        _scope=scope,
                    )
                elif canonical_tool_name == "replace_text":
                    result = await self.kernel.patch(
                        "replace",
                        canonical["path"],
                        canonical["old_string"],
                        canonical["new_string"],
                        canonical["replace_all"],
                        None,
                        run_context,
                        _scope=scope,
                    )
                else:
                    patch = (
                        create_files_patch(canonical["files"])
                        if canonical_tool_name == "create_files"
                        else canonical["patch"]
                    )
                    result = await self.kernel.patch(
                        "patch",
                        None,
                        None,
                        None,
                        False,
                        patch,
                        run_context,
                        _scope=scope,
                    )
            except WorkspacePathConflict as error:
                try:
                    current_files = await self._analysis_write_hash_files(
                        thread_id=scope.thread_id,
                        paths=paths,
                    )
                except Exception:
                    current_files = []
                recovery_operation = (
                    "overwrite_file"
                    if canonical_tool_name in {"create_files", "overwrite_file"}
                    else "apply_patch"
                )
                raise ReportingError(
                    "report_analysis_write_path_conflict",
                    "写入目标文件已存在或内容身份已变化。",
                    details={
                        "paths": list(paths),
                        "currentFiles": current_files,
                        "recoveryOperation": recovery_operation,
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
                return await self.kernel.bound_tool_result(
                    scope, response, run_context, retain=True
                )
            return response

        try:
            external_run_id = self.kernel.bound_external_run_id(run_context)
            async with self.kernel.task_scheduler(external_run_id) as scheduler, scheduler.write():
                scope = await self.kernel.scope(run_context)
                self._require_phase_tool(
                    scope,
                    allowed=frozenset({"analysis"}),
                    tool_name="write_analysis_files",
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
        async with self.kernel.service._async_client() as client:
            sandbox = await self.kernel.service._asandbox_for(client, thread_id)
            result = await sandbox.process.exec(command, cwd=WORKSPACE_ROOT, timeout=30)
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
        relative, remote = WorkspaceService.normalize_path(path, allow_root=False)
        async with self.kernel.service._async_client() as client:
            sandbox = await self.kernel.service._asandbox_for(client, thread_id)
            await self.kernel.service._avalidate_existing_path(sandbox, relative)
            info = await self.kernel.service._ainfo(sandbox, remote)
            if not self.kernel.service._is_regular_file(info):
                raise WorkspaceError("分析脚本依赖必须是普通文件。")
            if int(getattr(info, "size", 0) or 0) > MAX_ANALYSIS_PYTHON_SOURCE_BYTES:
                raise WorkspaceError("单个分析脚本依赖不能超过 2 MiB。")
            return await self.kernel.service._adownload_file(
                sandbox,
                remote,
                MAX_ANALYSIS_PYTHON_SOURCE_BYTES,
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
                    identities = await self.kernel.service.abatch_hash_files(
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

    async def finalize_report_analysis(
        self,
        reportBrief: dict[str, Any],
        datasetSemantics: list[dict[str, Any]],
        metricDefinitions: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """冻结全局分析事实；后续章节只能消费该产物，不继承本 run 消息。"""

        state = self._session_state(run_context)
        try:
            scope = await self.kernel.scope(run_context)
            self._require_phase_tool(
                scope,
                allowed=frozenset({"analysis"}),
                tool_name="finalize_report_analysis",
                run_context=run_context,
                task_kinds=frozenset({"visualization"}),
            )
            durable = await self._durable_state(scope)
            parameters, contract = self._phase_parameters(scope, "analysis")
            output_path = parameters.get("analysisOutputPath")
            expected_analysis_ids = contract.get("analysisIds")
            known_dataset_ids = contract.get("datasetIds")
            known_citation_ids = contract.get("citationIds")
            if (
                not isinstance(output_path, str)
                or not isinstance(expected_analysis_ids, list)
                or not isinstance(known_dataset_ids, list)
                or not isinstance(known_citation_ids, list)
            ):
                raise ReportingError(
                    "report_phase_contract_invalid", "Analysis Task 缺少冻结注册表。"
                )
            submitted = durable.payload.get("analysisItems")
            if not isinstance(submitted, dict) or any(
                not isinstance(submitted.get(item), dict) for item in expected_analysis_ids
            ):
                raise ReportingError(
                    "report_analysis_evidence_invalid", "耐久分析账本未完整覆盖全部 analysisId。"
                )
            # complete_analysis_item 已冻结 Dataset、fact 文件、Profile receipt、citation
            # 与 chart。Finalize 只按批准顺序从耐久账本派生，不接受模型重新提交 evidence。
            evidence = [
                {
                    **submitted[item],
                    "evidencePaths": [
                        entry.get("path")
                        for entry in submitted[item].get("evidenceFiles", ())
                        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
                    ],
                }
                for item in expected_analysis_ids
            ]
            metricDefinitions = metricDefinitions or []
            warnings = warnings or []
            parsed_dataset_semantics = tuple(
                AnalysisDatasetSemantics.model_validate(item) for item in datasetSemantics
            )
            if {item.dataset_id for item in parsed_dataset_semantics} != set(known_dataset_ids):
                raise ReportingError(
                    "report_analysis_dataset_semantics_incomplete",
                    "Dataset 语义必须精确覆盖全部授权 Dataset。",
                )

            receipts = tuple(
                ProfileReadReceipt.model_validate(item)
                for item in (durable.payload.get("profileReadReceipts", ()))
            )
            receipt_ids = {item.receipt_id for item in receipts}
            receipts_by_id = {item.receipt_id: item for item in receipts}
            chart_registry = {
                item["chartId"]: item
                for item in durable.payload.get("charts", ())
                if isinstance(item, dict) and isinstance(item.get("chartId"), str)
            }

            parsed_evidence: list[AnalysisEvidence] = []
            for item in evidence:
                if not isinstance(item, dict):
                    raise ReportingError(
                        "report_analysis_evidence_invalid", "analysis evidence 必须是对象。"
                    )
                allowed = {
                    "analysisId",
                    "summary",
                    "datasetIds",
                    "evidencePaths",
                    "citationIds",
                    "chartIds",
                    "profileReadReceiptIds",
                    "warnings",
                    "evidenceFiles",
                }
                if set(item) - allowed:
                    raise ReportingError(
                        "report_analysis_evidence_invalid", "analysis evidence 包含未注册字段。"
                    )
                analysis_id = item.get("analysisId")
                durable_item = (
                    submitted.get(analysis_id)
                    if isinstance(submitted, dict) and isinstance(analysis_id, str)
                    else None
                )
                if isinstance(durable_item, dict):
                    # CompleteAnalysisItem 已在 CAS 聚合中冻结 Dataset、引用、Profile
                    # receipt 和文件身份。Dataset coverage 不等于分布事实被结论使用，
                    # Finalize 因此只保留单项显式提交的 receipt，不按 Dataset 自动补齐。
                    item = _derive_durable_analysis_binding(durable_item)
                paths = item.get("evidencePaths")
                supplied_identities = item.get("evidenceFiles")
                if not paths and isinstance(supplied_identities, list):
                    paths = [
                        entry.get("path")
                        for entry in supplied_identities
                        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
                    ]
                if (
                    not isinstance(paths, list)
                    or not paths
                    or len(paths) > 50
                    or len(paths) != len(set(paths))
                    or any(not isinstance(path, str) or not path for path in paths)
                ):
                    raise ReportingError(
                        "report_analysis_evidence_invalid",
                        "每项 analysis 必须绑定 1 至 50 个不重复 evidencePaths。",
                    )
                identities = await asyncio.gather(
                    *(self.kernel.service.ahash_file(scope.thread_id, path) for path in paths)
                )
                if any(identity.get("missing") for identity in identities):
                    raise ReportingError(
                        "report_analysis_evidence_missing", "analysis evidence 文件不存在。"
                    )
                if isinstance(supplied_identities, list) and supplied_identities != identities:
                    raise ReportingError(
                        "report_analysis_evidence_identity_mismatch",
                        "analysis evidence 文件身份在单项完成后发生变化。",
                        details={"paths": paths},
                    )
                parsed = AnalysisEvidence.model_validate(
                    {
                        **{
                            key: value
                            for key, value in item.items()
                            if key not in {"evidencePaths", "evidenceFiles"}
                        },
                        "evidenceFiles": identities,
                    }
                )
                if set(parsed.dataset_ids) - set(known_dataset_ids):
                    raise ReportingError(
                        "report_analysis_dataset_unknown",
                        "analysis evidence 引用了未授权 Dataset。",
                    )
                if set(parsed.citation_ids) - set(known_citation_ids):
                    raise ReportingError(
                        "report_analysis_citation_unknown",
                        "analysis evidence 引用了未注册 citation。",
                    )
                if set(parsed.chart_ids) - set(chart_registry):
                    raise ReportingError(
                        "report_analysis_chart_unknown", "analysis evidence 引用了未登记图表。"
                    )
                if set(parsed.profile_read_receipt_ids) - receipt_ids:
                    raise ReportingError(
                        "report_profile_receipt_unknown",
                        "analysis evidence 引用了不存在的 ProfileReadReceipt。",
                    )
                if any(
                    receipts_by_id[receipt_id].dataset_id not in parsed.dataset_ids
                    for receipt_id in parsed.profile_read_receipt_ids
                ):
                    raise ReportingError(
                        "report_profile_receipt_dataset_mismatch",
                        "analysis evidence 绑定的 ProfileReadReceipt 不属于其 Dataset 范围。",
                    )
                parsed_evidence.append(parsed)
            if [item.analysis_id for item in parsed_evidence] != expected_analysis_ids:
                raise ReportingError(
                    "report_analysis_evidence_incomplete",
                    "analysis evidence 必须按冻结顺序精确覆盖全部 analysisId。",
                )
            bound_profile_receipt_ids = {
                receipt_id
                for item in parsed_evidence
                for receipt_id in item.profile_read_receipt_ids
            }
            # Profile receipt 只有被 analysis 显式绑定时才能证明实际使用；Dataset 相同只
            # 能证明曾经读取，不能由服务端推断归属。图表仍可按 citation 交集确定性绑定，
            # 无法证明归属的图表保持未使用并由 finalize 排除。
            bound_chart_ids = {chart_id for item in parsed_evidence for chart_id in item.chart_ids}
            for chart_id, chart in chart_registry.items():
                if chart_id in bound_chart_ids or not isinstance(chart, dict):
                    continue
                raw_citation_ids = chart.get("citationIds")
                if not isinstance(raw_citation_ids, (list, tuple)):
                    continue
                chart_citation_ids = {
                    value for value in raw_citation_ids if isinstance(value, str) and value
                }
                selected_index: int | None = None
                selected_overlap = 0
                for index, candidate_evidence in enumerate(parsed_evidence):
                    overlap = len(chart_citation_ids.intersection(candidate_evidence.citation_ids))
                    if overlap > selected_overlap:
                        selected_index = index
                        selected_overlap = overlap
                if selected_index is None:
                    continue
                selected = parsed_evidence[selected_index]
                parsed_evidence[selected_index] = selected.model_copy(
                    update={"chart_ids": (*selected.chart_ids, chart_id)}
                )
                bound_chart_ids.add(chart_id)

            parsed_charts: list[AnalysisChart] = []
            for chart_id, chart in chart_registry.items():
                if not isinstance(chart, dict):
                    raise ReportingError("report_analysis_chart_invalid", "图表登记状态无效。")
                source_path = chart.get("sourcePath")
                if not isinstance(source_path, str):
                    raise ReportingError("report_analysis_chart_invalid", "图表缺少源路径。")
                current = await self.kernel.service.ahash_file(scope.thread_id, source_path)
                if (
                    current.get("missing")
                    or current.get("size") != chart.get("size")
                    or current.get("sha256") != chart.get("sha256")
                ):
                    raise ReportingError(
                        "report_analysis_chart_changed", f"图表 {chart_id} 在冻结前发生变化。"
                    )
                parsed_charts.append(
                    AnalysisChart.model_validate(
                        {
                            "chartId": chart_id,
                            "sourceFile": current,
                            "title": chart.get("title"),
                            "altText": chart.get("altText"),
                            "citationIds": chart.get("citationIds"),
                            "metricCodes": chart.get("metricCodes"),
                            "currentPeriod": chart.get("currentPeriod"),
                            "comparisonPeriod": chart.get("comparisonPeriod"),
                            "comparisonType": chart.get("comparisonType"),
                            "sourceDatasetId": chart.get("sourceDatasetId"),
                            "aggregationGrain": chart.get("aggregationGrain"),
                            "comparability": chart.get("comparability"),
                            "visualInspectionReceipt": chart.get("visualInspectionReceipt"),
                        }
                    )
                )

            deterministic_chart_ids = [
                item.chart_id
                for item in parsed_charts
                if item.visual_inspection_receipt is not None
                and item.visual_inspection_receipt.inspection_mode == "deterministic"
            ]
            if deterministic_chart_ids:
                warning = "图表仅通过确定性图片文件检查，未运行模型视觉审查：" + "、".join(
                    deterministic_chart_ids
                )
                if warning not in warnings:
                    if len(warnings) >= 500:
                        warnings = warnings[:499]
                    warnings.append(warning)

            artifact = AnalysisArtifact(
                reportBrief=ReportBrief.model_validate(reportBrief),
                evidenceManifest=AnalysisEvidenceManifest(
                    evidence=tuple(parsed_evidence),
                    metricDefinitions=tuple(
                        MetricDefinition.model_validate(item) for item in metricDefinitions
                    ),
                    charts=tuple(parsed_charts),
                    datasetSemantics=parsed_dataset_semantics,
                    warnings=tuple(warnings),
                ),
                profileReadReceipts=tuple(
                    receipt
                    for receipt in receipts
                    if receipt.receipt_id in bound_profile_receipt_ids
                ),
            )
            serialized = artifact.model_dump(mode="json", by_alias=True)
            phase_state = (
                state.get(REPORT_PHASE_OUTPUT_STATE_KEY) if isinstance(state, dict) else None
            )
            if isinstance(phase_state, dict):
                if (
                    phase_state.get("phase") != "analysis"
                    or phase_state.get("payload") != serialized
                ):
                    raise ReportingError(
                        "report_analysis_already_submitted",
                        "当前 analysis run 已冻结阶段产物，不能替换。",
                    )
                identity = FileIdentity.model_validate(phase_state.get("artifactFile")).model_dump(
                    mode="json", by_alias=True
                )
            else:
                identity = await self._write_phase_json(
                    scope=scope,
                    path=output_path,
                    payload=serialized,
                    run_context=run_context,
                )
                if state is not None:
                    state[REPORT_PHASE_OUTPUT_STATE_KEY] = {
                        "phase": "analysis",
                        "payload": serialized,
                        "artifactFile": identity,
                    }
            return await self._finish_phase_task(
                scope=scope,
                phase="analysis",
                identity=identity,
                summary="全局分析、证据清单和指标口径已冻结。",
                state=state,
                run_context=run_context,
                extra={
                    "analysisCount": len(parsed_evidence),
                    "profileReadReceiptCount": len(receipts),
                },
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)

    async def complete_analysis_item(
        self,
        analysisId: str,
        summary: str,
        datasetIds: list[str],
        evidencePaths: list[str],
        citationIds: list[str],
        profileReadReceiptIds: list[str],
        warnings: list[str],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """把不可变固定事实直接绑定为 evidence，并结束对应的独立 Task。

        模型只在固定事实存在缺口时提交补充 evidencePaths；服务端始终追加当前 analysis
        的 deterministic fact 文件，并按路径、大小和 SHA-256 校验 durable artifact 账本。
        durable 游标已推进但 Task 收尾中断时，只允许相同 payload 在新 attempt 中幂等恢复，
        任何字段或文件身份变化都拒绝。
        """

        try:
            scope = await self.kernel.scope(run_context)
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
                    raise ReportingError(
                        "report_analysis_dataset_mismatch",
                        "analysis item 必须精确绑定服务端计划中的 Dataset。",
                    )
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
            identities = await self.kernel.service.abatch_hash_files(scope.thread_id, evidencePaths)
            await self._ensure_registered_analysis_evidence(scope=scope, identities=identities)
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
            finish_function = self.async_functions.get("finish_task")
            if finish_function is None:
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "Reporting Worker 缺少底层 finish_task。",
                )
            finish_result = await self.kernel.finish_task(
                f"分析项 {analysisId} 已提交冻结事实与证据。",
                [item["path"] for item in identities],
                None,
                [],
                run_context,
                finish_function,
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
    ) -> None:
        """确认 evidence 当前身份与 durable 写入登记逐项一致。"""

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
        if changed:
            raise ReportingError(
                "report_analysis_evidence_identity_mismatch",
                "analysis evidence 文件身份已变化，请按当前 SHA-256 重新登记。",
                details={"paths": changed},
            )
        if unregistered:
            raise ReportingError(
                "report_analysis_evidence_not_registered",
                "analysis evidence 必须先通过 write_analysis_files 登记。",
                details={
                    "paths": unregistered,
                    "missingRegistration": unregistered,
                },
            )

    async def _ensure_registered_analysis_evidence(
        self,
        *,
        scope: Any,
        identities: list[dict[str, Any]],
    ) -> ReportingRunState:
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
        if changed:
            raise ReportingError(
                "report_analysis_evidence_identity_mismatch",
                "analysis evidence 文件身份已变化，请按当前 SHA-256 重新登记。",
                details={"paths": changed},
            )
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
                raise ReportingError(
                    "report_analysis_evidence_identity_mismatch",
                    "analysis evidence 文件身份已变化，请按当前 SHA-256 重新登记。",
                    details={"paths": [path]},
                ) from error
        self._validate_registered_analysis_evidence(
            durable=durable,
            identities=identities,
        )
        return durable
