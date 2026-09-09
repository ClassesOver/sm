"""Reporting 分析结论的无状态规范化与耐久绑定。"""

# mypy: disable-error-code="attr-defined"
# 运行时由 toolkit 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any

from agno.run import RunContext
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from ...task_execution import abuild_workspace_changes, parse_unified_diff
from ...workspace import WorkspaceError, WorkspacePathConflict, WorkspaceService
from ..models import ReportingError
from ..workflow.checkpoint import (
    FileIdentity,
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
MAX_ANALYSIS_PYTHON_SOURCE_BYTES = 128 * 1024
MAX_ANALYSIS_PYTHON_LINE_BYTES = 8 * 1024
MAX_ANALYSIS_PYTHON_LITERAL_BYTES = 8 * 1024
MAX_ANALYSIS_PYTHON_LITERAL_ITEMS = 4096
MAX_ANALYSIS_WRITE_INTENT_BYTES = 4 * 1024 * 1024
_ANALYSIS_SUMMARY_PERIOD_PATTERN = re.compile(
    r"(?P<year>\d{4})年(?:(?P<full>全年)|(?P<start>\d{1,2})(?:[-—–至到](?P<end>\d{1,2}))?月)"
)
_ANALYSIS_SUMMARY_SENTENCE_PATTERN = re.compile(r"[^。！？\n]+[。！？]?|\n")
_INCOMPARABLE_YOY_WARNING = "摘要中的比较期间长度不一致，已将“同比”规范为“参考对比”。"
_FORBIDDEN_VISUALIZATION_MODULES = frozenset({"plotly", "kaleido", "seaborn"})


def _is_pyplot_import(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Import)
        and any(alias.name == "matplotlib.pyplot" for alias in node.names)
    ) or (
        isinstance(node, ast.ImportFrom)
        and (
            node.module == "matplotlib.pyplot"
            or (node.module == "matplotlib" and any(alias.name == "pyplot" for alias in node.names))
        )
    )


def _literal_dynamic_imported_module(node: ast.AST) -> str | None:
    if (
        not isinstance(node, ast.Call)
        or not node.args
        or not isinstance(node.args[0], ast.Constant)
        or not isinstance(node.args[0].value, str)
    ):
        return None
    if isinstance(node.func, ast.Name) and node.func.id == "__import__":
        return node.args[0].value.split(".")[0].lower()
    if (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "importlib"
        and node.func.attr == "import_module"
    ):
        return node.args[0].value.split(".")[0].lower()
    return None


def _valid_visualization_source(tree: ast.Module) -> bool:
    forbidden_names = {
        "__file__",
        "apply_analysis_patch",
        "null",
        "run_python_script",
        "submit_visualization_charts",
        "true",
        "false",
    }
    if any(
        isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in forbidden_names
        for node in ast.walk(tree)
    ):
        return False
    if any(
        module in _FORBIDDEN_VISUALIZATION_MODULES
        for node in ast.walk(tree)
        for module in (
            [alias.name.split(".")[0].lower() for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module.split(".")[0].lower()]
            if isinstance(node, ast.ImportFrom) and node.module
            else []
        )
    ) or any(
        _literal_dynamic_imported_module(node) in _FORBIDDEN_VISUALIZATION_MODULES
        for node in ast.walk(tree)
    ):
        return False
    if any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "write_image"
        for node in ast.walk(tree)
    ):
        return False

    matplotlib_imports = [
        index
        for index, node in enumerate(tree.body)
        if isinstance(node, ast.Import)
        and any(alias.name == "matplotlib" and alias.asname is None for alias in node.names)
    ]
    pyplot_imports = [index for index, node in enumerate(tree.body) if _is_pyplot_import(node)]
    agg_setups = [
        index
        for index, node in enumerate(tree.body)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "matplotlib"
        and node.value.func.attr == "use"
        and node.value.args
        and isinstance(node.value.args[0], ast.Constant)
        and node.value.args[0].value == "Agg"
    ]
    if (
        not matplotlib_imports
        or not pyplot_imports
        or not agg_setups
        or min(matplotlib_imports) >= min(agg_setups)
        or min(agg_setups) >= min(pyplot_imports)
    ):
        return False
    first_agg = tree.body[min(agg_setups)]
    if any(
        (node.lineno, node.col_offset) < (first_agg.lineno, first_agg.col_offset)
        for node in ast.walk(tree)
        if _is_pyplot_import(node)
    ):
        return False
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "savefig"
        for node in ast.walk(tree)
    )


def _reject_reporting_python_source(path: str, content: Any) -> None:
    if isinstance(content, str):
        try:
            raw_content = content.encode("utf-8")
        except UnicodeEncodeError:
            raw_content = b""
        lines = content.splitlines()
    elif isinstance(content, bytes):
        raw_content = content
        lines = []
    else:
        raw_content = b""
        lines = []
    raise ReportingError(
        "report_python_source_shape_invalid",
        "签发 Python 源码形状无效，已拒绝写入。",
        details={
            "path": path,
            "size": len(raw_content),
            "lineCount": len(lines),
            "maxLineLength": max(
                (len(line.encode("utf-8", errors="replace")) for line in lines),
                default=0,
            ),
        },
    )


def validate_reporting_python_source(
    *,
    path: str,
    content: Any,
    max_bytes: int,
    visualization: bool,
) -> dict[str, Any]:
    """以生产门禁验证 Reporting Python 源码并返回稳定指标。"""

    if not isinstance(content, str):
        _reject_reporting_python_source(path, content)
    try:
        raw_content = content.encode("utf-8")
    except UnicodeEncodeError:
        _reject_reporting_python_source(path, content)
    if len(raw_content) > max_bytes or "\r" in content or not content.endswith("\n"):
        _reject_reporting_python_source(path, content)
    lines = content.split("\n")
    source_line_count = len(content.splitlines())
    if source_line_count < 2:
        _reject_reporting_python_source(path, content)
    if any(len(line.encode("utf-8")) > MAX_ANALYSIS_PYTHON_LINE_BYTES for line in lines):
        _reject_reporting_python_source(path, content)
    try:
        tree = ast.parse(content, filename=path)
        compile(tree, path, "exec")
    except SyntaxError:
        _reject_reporting_python_source(path, content)
    if visualization and not _valid_visualization_source(tree):
        _reject_reporting_python_source(path, content)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            if (
                len(node.value if isinstance(node.value, bytes) else node.value.encode("utf-8"))
                > MAX_ANALYSIS_PYTHON_LITERAL_BYTES
            ):
                _reject_reporting_python_source(path, content)
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
            item_count = len(node.elts) if not isinstance(node, ast.Dict) else len(node.keys)
            if item_count > MAX_ANALYSIS_PYTHON_LITERAL_ITEMS:
                _reject_reporting_python_source(path, content)
    return {
        "path": path,
        "sourceLineCount": source_line_count,
        "sizeBytes": len(raw_content),
        "sha256": hashlib.sha256(raw_content).hexdigest(),
    }


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
    def _signed_analysis_script_contract(self, scope: Any) -> tuple[str, int, bool]:
        _parameters, contract = self._phase_parameters(scope, "analysis")
        workspace = contract.get("visualizationWorkspace")
        script_path = workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
        task_kind = contract.get("taskKind")
        if task_kind == "visualization_section":
            normalized = WorkspaceService.normalize_path(script_path, allow_root=False)[0]
            return normalized, MAX_VISUALIZATION_SCRIPT_BYTES, True
        if task_kind == "analysis_item":
            return (
                f"{self._analysis_output_root(contract)}/supplement.py",
                MAX_ANALYSIS_PYTHON_SOURCE_BYTES,
                False,
            )
        raise ReportingError(
            "report_phase_contract_invalid", "当前 analysis Task 缺少脚本签发契约。"
        )

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
        for operation in operations:
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

    async def _recover_recorded_analysis_write(
        self,
        *,
        scope: Any,
        tool_name: str,
        canonical: Mapping[str, Any],
        paths: tuple[str, ...],
        payload_bytes: int,
    ) -> dict[str, Any] | None:
        """在重建 patch 前恢复同一 durable 写入，避免旧 hunk 再次应用。"""

        durable = await self._durable_state(scope)
        intents = durable.payload.get("writeIntents")
        if not isinstance(intents, Mapping):
            return None
        for intent_id, intent in reversed(tuple(intents.items())):
            if not isinstance(intent, Mapping) or intent.get("toolName") != tool_name:
                continue
            if intent.get("affectedPaths") != list(paths):
                continue
            arguments = intent.get("arguments")
            if not isinstance(arguments, Mapping) or arguments.get("patch") != canonical.get(
                "patch"
            ):
                continue
            status = intent.get("status")
            if status == "pending":
                return await self._recover_pending_analysis_write(
                    scope=scope,
                    tool_name=tool_name,
                    canonical=arguments,
                    paths=paths,
                    intent_sha256=str(intent_id),
                    payload_bytes=payload_bytes,
                )
            if status != "committed":
                continue
            artifacts = intent.get("artifacts")
            if not isinstance(artifacts, list):
                raise ReportingError(
                    "report_analysis_write_intent_invalid", "已提交写入意图缺少文件身份。"
                )
            current = await self._analysis_write_hash_files(
                thread_id=scope.thread_id, paths=paths
            )
            if current != artifacts:
                raise ReportingError(
                    "report_analysis_write_identity_mismatch",
                    "已提交写入意图的文件身份发生变化。",
                )
            return {
                "ok": True,
                "status": "committed",
                "intentSha256": str(intent_id),
                "bytes": payload_bytes,
                "artifacts": artifacts,
                "recovered": True,
            }
        return None

    async def _preflight_analysis_python_write(
        self,
        *,
        scope: Any,
        tool_name: str,
        canonical: Mapping[str, Any],
    ) -> None:
        """在提交 Workspace mutation 前验证签发 Python 源码的形状。"""

        changes = list(canonical.get("operations", ()))
        normalized_script, max_bytes, visualization = self._signed_analysis_script_contract(scope)
        if len(changes) != 1:
            _reject_reporting_python_source(normalized_script, "")
        change = changes[0]
        path = change.get("path")
        content = change.get("content")
        if (
            change.get("operation") not in {"create", "update"}
            or path != normalized_script
            or not isinstance(content, str)
        ):
            _reject_reporting_python_source(
                path if isinstance(path, str) else normalized_script, content
            )
        validate_reporting_python_source(
            path=path,
            content=content,
            max_bytes=max_bytes,
            visualization=visualization,
        )

    def _analysis_patch_operation(self, scope: Any, patch: str) -> str:
        operations = parse_unified_diff(patch)
        normalized_script, _max_bytes, _visualization = (
            self._signed_analysis_script_contract(scope)
        )
        if len(operations) != 1:
            _reject_reporting_python_source(normalized_script, "")
        operation = operations[0]
        if operation.operation not in {"create", "update"} or operation.path != normalized_script:
            _reject_reporting_python_source(operation.path, "")
        return operation.operation

    async def _reject_create_for_existing_script(
        self, *, scope: Any, operations: Sequence[Mapping[str, Any]]
    ) -> None:
        change = operations[0]
        if change.get("operation") != "create":
            return
        path = str(change["path"])
        current = await self._analysis_write_hash_files(
            thread_id=scope.thread_id, paths=(path,)
        )
        if current and current[0].get("missing") is not True:
            raise ReportingError(
                "report_analysis_write_path_conflict",
                "create diff 的签发脚本已存在。",
                details={"paths": [path], "currentFiles": current},
            )

    async def recover_signed_analysis_script(
        self,
        path: str,
        run_context: RunContext | None,
    ) -> FileIdentity | None:
        """从 committed/pending write intent 恢复签发脚本身份。"""

        scope = await self.runtime.scope(run_context)
        normalized, _max_bytes, _visualization = self._signed_analysis_script_contract(scope)
        if path != normalized:
            raise ReportingError(
                "report_phase_artifact_changed", "恢复脚本路径与当前签发路径不一致。"
            )
        durable = await self._durable_state(scope)
        intents = durable.payload.get("writeIntents")
        if not isinstance(intents, Mapping):
            return None
        current_rows = await self._analysis_write_hash_files(
            thread_id=scope.thread_id, paths=(path,)
        )
        current = current_rows[0] if current_rows else {"path": path, "missing": True}
        for intent_id, intent in reversed(tuple(intents.items())):
            if not isinstance(intent, Mapping) or intent.get("toolName") != "apply_analysis_patch":
                continue
            if intent.get("affectedPaths") != [path]:
                continue
            arguments = intent.get("arguments")
            operations = arguments.get("operations") if isinstance(arguments, Mapping) else None
            if not isinstance(operations, list) or len(operations) != 1:
                raise ReportingError(
                    "report_analysis_write_intent_invalid", "脚本写入意图缺少唯一操作。"
                )
            change = operations[0]
            if (
                not isinstance(change, Mapping)
                or change.get("path") != path
                or change.get("operation") not in {"create", "update"}
                or not isinstance(change.get("content"), str)
            ):
                raise ReportingError(
                    "report_analysis_write_intent_invalid", "脚本写入意图操作无效。"
                )
            status = intent.get("status")
            if status == "committed":
                artifacts = intent.get("artifacts")
                if not isinstance(artifacts, list) or len(artifacts) != 1:
                    raise ReportingError(
                        "report_analysis_write_intent_invalid",
                        "已提交写入意图缺少唯一文件身份。",
                    )
                try:
                    expected = FileIdentity.model_validate(artifacts[0])
                except ValidationError as error:
                    raise ReportingError(
                        "report_analysis_write_intent_invalid",
                        "已提交写入意图的文件身份无效。",
                    ) from error
                if current == expected.model_dump():
                    return expected
                raise ReportingError(
                    "report_phase_artifact_changed",
                    "签发脚本身份与 durable write intent 不一致。",
                )
            if status != "pending":
                raise ReportingError(
                    "report_analysis_write_intent_invalid", "脚本写入意图状态无效。"
                )
            content = change["content"]
            desired = {
                "path": path,
                "size": len(content.encode("utf-8")),
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
            if current == desired:
                await self._apply_durable(
                    scope,
                    name="commit_write_intent",
                    payload={"intentId": intent_id, "artifacts": [desired]},
                    command_id=f"write-commit:{intent_id}",
                )
                return FileIdentity.model_validate(desired)
            if change.get("operation") == "create" and current.get("missing") is True:
                return None
            if (
                change.get("operation") == "update"
                and current.get("sha256") == change.get("expected_sha256")
            ):
                return None
            raise ReportingError(
                "report_phase_artifact_changed", "签发脚本身份与 durable write intent 不一致。"
            )
        return None

    async def apply_analysis_patch(
        self,
        patch: str,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """保存固定操作的写入意图、执行写入并返回文件身份。"""

        canonical_tool_name = "apply_analysis_patch"
        canonical_input = {"patch": patch}

        async def call(scope: Any) -> dict[str, Any]:
            _parameters, contract = self._phase_parameters(scope, "analysis")
            canonical, paths, expected_states, payload_bytes = (
                self._validate_analysis_write_arguments(canonical_tool_name, canonical_input)
            )
            operation = self._analysis_patch_operation(scope, canonical["patch"])
            if operation == "update":
                recovered = await self._recover_recorded_analysis_write(
                    scope=scope,
                    tool_name=canonical_tool_name,
                    canonical=canonical,
                    paths=paths,
                    payload_bytes=payload_bytes,
                )
                if recovered is not None:
                    return recovered
            raw_operations = await abuild_workspace_changes(
                self.runtime.workspace,
                scope.thread_id,
                canonical["patch"],
            )
            canonical["operations"] = raw_operations
            await self._preflight_analysis_python_write(
                scope=scope,
                tool_name=canonical_tool_name,
                canonical=canonical,
            )
            if operation == "create":
                recovered = await self._recover_recorded_analysis_write(
                    scope=scope,
                    tool_name=canonical_tool_name,
                    canonical=canonical,
                    paths=paths,
                    payload_bytes=payload_bytes,
                )
                if recovered is not None:
                    return recovered
            await self._reject_create_for_existing_script(
                scope=scope, operations=raw_operations
            )
            self._require_analysis_task_output_paths(contract, paths)
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
                    "patch",
                    None,
                    None,
                    None,
                    False,
                    canonical["patch"],
                    run_context,
                    _changes=raw_operations,
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

    async def _installed_python_modules(
        self,
        *,
        thread_id: str,
        module_names: set[str],
    ) -> set[str]:
        if not module_names:
            return set()
        try:
            return await self.runtime.workspace.probe_python_modules(thread_id, module_names)
        except WorkspaceError as error:
            raise ReportingError(
                "report_analysis_dependency_probe_failed",
                "无法确认分析脚本依赖是否完整，已拒绝执行脚本。",
            ) from error

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
        script_path: Any,
    ) -> dict[str, Any] | None:
        try:
            script_path = WorkspaceService.normalize_path(script_path, allow_root=False)[0]
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
        """确认 evidence 可读取；冻结身份漂移必须硬拒绝。"""

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
                "analysis evidence 文件身份或 SHA-256 已变化，拒绝继续发布。",
                details={"paths": changed},
            )
        return (
            ["analysis evidence 文件未登记，已由服务端登记到 durable 账本。"]
            if unregistered
            else []
        )

    async def _ensure_registered_analysis_evidence(
        self,
        *,
        scope: Any,
        identities: list[dict[str, Any]],
    ) -> tuple[ReportingRunState, list[str]]:
        """把执行工具已写出的 evidence 身份登记到唯一 durable 账本。"""

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
                "analysis evidence 文件身份或 SHA-256 已变化，拒绝继续发布。",
                details={"paths": changed},
            )
        warnings: list[str] = []
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
                    "analysis evidence 登记身份发生变化，拒绝继续发布。",
                    details={"path": path},
                ) from error
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
