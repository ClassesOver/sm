"""交互式 Coding Agent 的 Workspace 与执行身份工具。"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Mapping
from typing import Any, NoReturn
from uuid import uuid4

from agno.run import RunContext
from agno.tools import Function, Toolkit

from ...workspace import WorkspaceError, WorkspaceService
from ..code_mode import ReportingCodeModeRuntime
from ..knowledge import KnowledgeIndexError, ReportingKnowledgeIndex
from ..models import ReportingError
from ..vision import ReportVisionReviewer
from ..workflow.checkpoint import ChartVisualInspectionReceipt, FileIdentity
from .context import (
    ExecutionReceipt,
    ReportingCodingTaskBinding,
    ReportingCodingTaskContext,
)
from .lsp import ReportingWorkspaceLsp
from .lsp_process import ReportingLspProcessManager

MAX_PHYSICAL_LINE_BYTES = 8 * 1024
MAX_DIAGNOSTIC_BYTES = 8 * 1024
_FORBIDDEN_PATH_CALLS = frozenset(
    {
        "os.chdir",
        "os.fchdir",
        "os.getcwd",
        "os.getcwdb",
        "os.path.abspath",
        "os.path.dirname",
        "os.path.join",
        "os.path.normpath",
        "os.path.realpath",
        "os.path.relpath",
        "pathlib.Path.cwd",
    }
)
_PATH_ARGUMENT_CALLS = frozenset({"open", "io.open", "os.makedirs", "os.mkdir", "pathlib.Path"})
_PATH_ARGUMENT_METHODS = frozenset(
    {
        "imread",
        "imsave",
        "read_csv",
        "read_excel",
        "read_feather",
        "read_json",
        "read_parquet",
        "read_pickle",
        "savefig",
        "to_csv",
        "to_excel",
        "to_json",
        "to_parquet",
        "to_pickle",
    }
)
_PATH_ARGUMENT_KEYWORDS = frozenset(
    {"file", "filename", "filepath_or_buffer", "fname", "path", "path_or_buf"}
)


def _reject_source(message: str) -> NoReturn:
    raise ReportingError("report_code_source_invalid", message)


def validate_draft_source(context: ReportingCodingTaskContext, source: Any) -> bytes:
    if not isinstance(source, str) or not source or "\r" in source or not source.endswith("\n"):
        _reject_source("Python 源码形状无效。")
    try:
        raw = source.encode("utf-8")
    except UnicodeEncodeError:
        _reject_source("Python 源码必须是有效的 UTF-8 文本。")
    if len(raw) > context.max_source_bytes or any(
        len(line.encode("utf-8")) > MAX_PHYSICAL_LINE_BYTES for line in source.split("\n")
    ):
        _reject_source("Python 源码超过限制。")
    return raw


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                bound = item.asname or item.name.split(".", 1)[0]
                aliases[bound] = item.name if item.asname else bound
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                if item.name != "*":
                    aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _qualified_name(node: ast.AST, aliases: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        owner = _qualified_name(node.value, aliases)
        return f"{owner}.{node.attr}" if owner else node.attr
    return None


def _literal_bindings(tree: ast.AST) -> dict[str, ast.AST]:
    values: dict[str, ast.AST] = {}
    ambiguous: set[str] = set()
    for node in ast.walk(tree):
        target: ast.AST | None = None
        value: ast.AST | None = None
        if isinstance(node, (ast.Assign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if len(targets) == 1:
                target, value = targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and value is not None:
            if target.id in values:
                ambiguous.add(target.id)
            else:
                values[target.id] = value
    for name in ambiguous:
        values.pop(name, None)
    return values


def _literal_string(
    node: ast.AST,
    bindings: Mapping[str, ast.AST],
    seen: frozenset[str] = frozenset(),
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in bindings and node.id not in seen:
        return _literal_string(bindings[node.id], bindings, seen | {node.id})
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_string(node.left, bindings, seen)
        right = _literal_string(node.right, bindings, seen)
        return left + right if left is not None and right is not None else None
    return None


def _path_arguments(call: ast.Call, qualified_name: str) -> tuple[ast.AST, ...]:
    method_name = qualified_name.rsplit(".", 1)[-1]
    if qualified_name not in _PATH_ARGUMENT_CALLS and method_name not in _PATH_ARGUMENT_METHODS:
        return ()
    arguments = list(call.args[:1])
    arguments.extend(
        keyword.value for keyword in call.keywords if keyword.arg in _PATH_ARGUMENT_KEYWORDS
    )
    return tuple(arguments)


def _referenced_literal_paths(tree: ast.AST) -> set[str]:
    aliases = _import_aliases(tree)
    bindings = _literal_bindings(tree)
    paths: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        qualified_name = _qualified_name(node.func, aliases)
        if qualified_name is None:
            continue
        for argument in _path_arguments(node, qualified_name):
            literal = _literal_string(argument, bindings)
            if literal is not None:
                paths.add(literal)
    return paths


def compile_script_source(path: str, source: str, authorized_paths: frozenset[str]) -> None:
    try:
        tree = ast.parse(source, filename=path)
        aliases = _import_aliases(tree)
        forbidden = {
            qualified
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (qualified := _qualified_name(node.func, aliases)) in _FORBIDDEN_PATH_CALLS
        }
        if any(
            isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == "__file__"
            for node in ast.walk(tree)
        ):
            forbidden.add("__file__")
        unsigned = _referenced_literal_paths(tree) - set(authorized_paths)
        if forbidden or unsigned:
            raise ReportingError(
                "report_python_source_path_invalid",
                "脚本使用了未授权路径或目录推导操作。",
                details={
                    "path": path,
                    "unsignedPaths": sorted(unsigned)[:20],
                    "forbiddenPathOperations": sorted(forbidden),
                },
            )
        compile(tree, path, "exec")
    except ReportingError:
        raise
    except (SyntaxError, TypeError, ValueError) as error:
        raise ReportingError("report_code_source_invalid", "Python 源码无法编译。") from error


def validate_script_source(context: ReportingCodingTaskContext, source: str) -> bytes:
    raw = validate_draft_source(context, source)
    authorized = frozenset((*context.authorized_read_paths, *context.authorized_write_paths))
    compile_script_source(context.script_path, source, authorized)
    return raw


def _cell_field(cell: Any, name: str, default: Any = None) -> Any:
    if isinstance(cell, Mapping):
        return cell.get(name, default)
    return getattr(cell, name, default)


def _failure(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "status": "rejected", "code": code, "message": message}


def _bounded_failure(code: str, cell: Any) -> dict[str, Any]:
    remaining = MAX_DIAGNOSTIC_BYTES
    details: dict[str, str] = {}
    for name in ("stdout", "stderr", "traceback"):
        value = str(_cell_field(cell, name, "") or "").encode("utf-8")[:remaining]
        text = value.decode("utf-8", errors="ignore")
        details[name] = text
        remaining -= len(text.encode("utf-8"))
    return {
        **_failure(code, "Coding Agent 脚本执行失败。"),
        "details": details,
    }


def _reset_stop_after_tool_call(fc: Any) -> None:
    fc.function.stop_after_tool_call = False


def _stop_after_success(fc: Any) -> None:
    fc.function.stop_after_tool_call = bool(
        isinstance(fc.result, dict) and fc.result.get("ok") is True
    )


def _lsp_parameters(*, path_required: bool, include_position: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "path": {"type": "string", "minLength": 1},
        "expectedSourceSha256": {"type": "string", "minLength": 64, "maxLength": 64},
    }
    if include_position:
        properties.update(
            {
                "line": {"type": "integer", "minimum": 0},
                "character": {"type": "integer", "minimum": 0},
            }
        )
    required = ["path"] if path_required else []
    if include_position:
        required.extend(("line", "character"))
    return {"type": "object", "properties": properties, "required": required}


class ReportingCodeModeToolkit(Toolkit):
    """把固定 task binding 暴露为执行与只读代码理解工具。"""

    def __init__(
        self,
        binding: ReportingCodingTaskBinding,
        runtime: ReportingCodeModeRuntime,
        lsp_manager: ReportingLspProcessManager,
        knowledge_index: ReportingKnowledgeIndex | None = None,
        vision_reviewer: ReportVisionReviewer | None = None,
    ) -> None:
        self.binding = binding
        self.runtime = runtime
        self.knowledge_index = knowledge_index
        self.vision_reviewer = vision_reviewer
        self.lsp = ReportingWorkspaceLsp(binding, lsp_manager)
        self.submitted_receipt: ExecutionReceipt | None = None
        self.submitted_visual_receipts: tuple[ChartVisualInspectionReceipt, ...] = ()
        tools = [
            Function(
                name="write_script",
                description="将完整 Python 源码写入当前任务脚本。",
                parameters={
                    "type": "object",
                    "properties": {"source": {"type": "string"}},
                    "required": ["source"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.write_script,
            ),
            Function(name="read_script", entrypoint=self.read_script),
            Function(
                name="execute_code",
                description="在当前交互 Kernel 执行 Python 或 Shell cell。",
                parameters={
                    "type": "object",
                    "properties": {"code": {"type": "string"}},
                    "required": ["code"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.execute_code,
            ),
            Function(name="restart_code_mode", entrypoint=self.restart_code_mode),
            Function(name="run_script", entrypoint=self.run_script),
            Function(
                name="lsp_diagnostics",
                parameters=_lsp_parameters(path_required=False, include_position=False),
                entrypoint=self.lsp_diagnostics,
            ),
            Function(
                name="lsp_hover",
                parameters=_lsp_parameters(path_required=True, include_position=True),
                entrypoint=self.lsp_hover,
            ),
            Function(
                name="lsp_definition",
                parameters=_lsp_parameters(path_required=True, include_position=True),
                entrypoint=self.lsp_definition,
            ),
            Function(
                name="lsp_references",
                parameters=_lsp_parameters(path_required=True, include_position=True),
                entrypoint=self.lsp_references,
            ),
            Function(
                name="lsp_document_symbols",
                parameters=_lsp_parameters(path_required=True, include_position=False),
                entrypoint=self.lsp_document_symbols,
            ),
            Function(
                name="submit_script",
                entrypoint=self.submit_script,
                pre_hook=_reset_stop_after_tool_call,
                post_hook=_stop_after_success,
            ),
        ]
        if self.context.task_kind == "visualization":
            tools.append(
                Function(
                    name="view_image",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "detail": {
                                "type": "string",
                                "enum": ["high", "original"],
                            },
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                    strict=True,
                    entrypoint=self.view_image,
                )
            )
        if knowledge_index is not None:
            tools.append(
                Function(
                    name="search_knowledge",
                    description="检索当前 Workspace 可见的项目文档、规范和成功修复记录。",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "minLength": 1, "maxLength": 4096}
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                    strict=True,
                    entrypoint=self.search_knowledge,
                )
            )
        super().__init__(name="reporting_code_mode", tools=tools)

    @property
    def context(self) -> ReportingCodingTaskContext:
        return self.binding.context

    @property
    def workspace(self):
        return self.binding.workspace

    @property
    def tool_functions(self) -> tuple[Function, ...]:
        return tuple([*self.functions.values(), *self.async_functions.values()])

    async def read_script(self, run_context: RunContext | None = None) -> dict[str, Any]:
        del run_context
        if not await self.workspace.apath_exists(self.context.task_id, self.context.script_path):
            return {"ok": True, "exists": False, "path": self.context.script_path}
        raw = await self.workspace.read_limited_regular_file(
            self.context.task_id,
            self.context.script_path,
            max_bytes=self.context.max_source_bytes,
        )
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ReportingError(
                "report_code_source_invalid", "Python 脚本不是有效的 UTF-8 文本。"
            ) from error
        return {
            "ok": True,
            "exists": True,
            "path": self.context.script_path,
            "source": source,
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    async def search_knowledge(
        self, query: str, run_context: RunContext | None = None
    ) -> dict[str, Any]:
        del run_context
        if self.knowledge_index is None:
            return _failure("report_knowledge_unavailable", "知识索引未配置。")
        try:
            results = await self.knowledge_index.search(
                query,
                workspace_key=self.context.workspace_key,
            )
        except KnowledgeIndexError as error:
            return _failure(error.code, str(error))
        return {
            "ok": True,
            "results": [
                {
                    "identity": item.identity,
                    "kind": item.kind,
                    "snippet": item.snippet,
                    "score": item.score,
                    "contentSha256": item.content_sha256,
                }
                for item in results
            ],
        }

    async def write_script(
        self, source: str, run_context: RunContext | None = None
    ) -> dict[str, Any]:
        del run_context
        validate_draft_source(self.context, source)
        exists = await self.workspace.apath_exists(self.context.task_id, self.context.script_path)
        await self.workspace.awrite_text(
            self.context.task_id,
            self.context.script_path,
            source,
            overwrite=exists,
        )
        self.binding.clear_execution_state()
        self.submitted_receipt = None
        self.submitted_visual_receipts = ()
        return {
            "ok": True,
            **await self.workspace.ahash_file(self.context.task_id, self.context.script_path),
        }

    async def execute_code(
        self, code: str, run_context: RunContext | None = None
    ) -> dict[str, Any]:
        del run_context
        try:
            cell = await self.runtime.execute(
                self.context.code_mode_session_id,
                self.workspace,
                code,
                matplotlib_agg=self.context.task_kind == "visualization",
            )
        except ReportingError as error:
            return _failure(error.code, error.message)
        if _cell_field(cell, "status") != "ok":
            return _bounded_failure("report_code_mode_execution_failed", cell)
        return {
            "ok": True,
            "status": "completed",
            "stdout": _bounded_failure("", cell)["details"]["stdout"],
            "stderr": _bounded_failure("", cell)["details"]["stderr"],
        }

    async def restart_code_mode(self, run_context: RunContext | None = None) -> dict[str, Any]:
        del run_context
        self.binding.clear_execution_state()
        self.submitted_receipt = None
        self.submitted_visual_receipts = ()
        await self.runtime.shutdown(self.context.code_mode_session_id)
        return {"ok": True}

    async def view_image(
        self,
        path: str,
        detail: str = "high",
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        try:
            source_path = WorkspaceService.normalize_path(path, allow_root=False)[0]
        except WorkspaceError:
            return _failure(
                "report_code_visual_path_forbidden",
                "图片路径不属于当前 Coding task 的声明输出。",
            )
        if source_path not in self.context.declared_output_paths:
            return _failure(
                "report_code_visual_path_forbidden",
                "图片路径不属于当前 Coding task 的声明输出。",
            )
        execution = self.binding.execution_receipt
        if execution is None:
            return _failure(
                "report_code_visual_review_required_execution",
                "图片必须先由当前脚本成功执行生成。",
            )
        output = next(
            (item for item in execution.output_files if item.path == source_path),
            None,
        )
        if output is None:
            return _failure(
                "report_code_visual_path_forbidden",
                "图片不属于最近一次成功执行的输出。",
            )
        try:
            before = FileIdentity.model_validate(
                await self.workspace.ahash_file(self.context.task_id, source_path)
            )
        except (TypeError, ValueError, WorkspaceError):
            self.binding.visual_inspection_receipts.pop(source_path, None)
            return _failure(
                "report_code_visual_output_changed",
                "图片输出在执行或视觉审查后发生变化。",
            )
        if before != output:
            self.binding.visual_inspection_receipts.pop(source_path, None)
            return _failure(
                "report_code_visual_output_changed",
                "图片输出在执行或视觉审查后发生变化。",
            )
        cached = self.binding.visual_inspection_receipts.get(source_path)
        if cached is not None and cached.sha256 == output.sha256:
            return {
                "ok": True,
                "receipt": cached.model_dump(mode="json", by_alias=True),
            }
        if self.vision_reviewer is None:
            return _failure(
                "report_code_visual_review_unavailable",
                "独立视觉审查暂不可用，请稍后重试。",
            )
        try:
            reviewed = ChartVisualInspectionReceipt.model_validate(
                await self.vision_reviewer.review(
                    self.context.workspace_key,
                    source_path,
                    detail=detail,
                )
            )
        except Exception:
            return _failure(
                "report_code_visual_review_unavailable",
                "独立视觉审查暂不可用，请稍后重试。",
            )
        try:
            after = FileIdentity.model_validate(
                await self.workspace.ahash_file(self.context.task_id, source_path)
            )
        except (TypeError, ValueError, WorkspaceError):
            self.binding.visual_inspection_receipts.pop(source_path, None)
            return _failure(
                "report_code_visual_output_changed",
                "图片输出在执行或视觉审查后发生变化。",
            )
        if (
            reviewed.source_path != source_path
            or before.sha256 != reviewed.sha256
            or reviewed.sha256 != after.sha256
            or after != output
        ):
            self.binding.visual_inspection_receipts.pop(source_path, None)
            return _failure(
                "report_code_visual_output_changed",
                "图片输出在执行或视觉审查后发生变化。",
            )
        self.binding.visual_inspection_receipts[source_path] = reviewed
        return {
            "ok": True,
            "receipt": reviewed.model_dump(mode="json", by_alias=True),
        }

    async def lsp_diagnostics(
        self,
        path: str | None = None,
        expectedSourceSha256: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        return await self.lsp.diagnostics(
            path,
            expected_source_sha256=expectedSourceSha256,
        )

    async def lsp_hover(
        self,
        path: str,
        line: int,
        character: int,
        expectedSourceSha256: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        return await self.lsp.hover(
            path,
            line=line,
            character=character,
            expected_source_sha256=expectedSourceSha256,
        )

    async def lsp_definition(
        self,
        path: str,
        line: int,
        character: int,
        expectedSourceSha256: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        return await self.lsp.definition(
            path,
            line=line,
            character=character,
            expected_source_sha256=expectedSourceSha256,
        )

    async def lsp_references(
        self,
        path: str,
        line: int,
        character: int,
        expectedSourceSha256: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        return await self.lsp.references(
            path,
            line=line,
            character=character,
            expected_source_sha256=expectedSourceSha256,
        )

    async def lsp_document_symbols(
        self,
        path: str,
        expectedSourceSha256: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        return await self.lsp.document_symbols(
            path,
            expected_source_sha256=expectedSourceSha256,
        )

    async def _validated_source_identity(self) -> FileIdentity:
        raw = await self.workspace.read_limited_regular_file(
            self.context.task_id,
            self.context.script_path,
            max_bytes=self.context.max_source_bytes,
        )
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ReportingError(
                "report_code_source_invalid", "Python 脚本不是有效的 UTF-8 文本。"
            ) from error
        validate_script_source(self.context, source)
        return FileIdentity(
            path=self.context.script_path,
            size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
        )

    async def _clear_declared_outputs(self) -> None:
        for path in self.context.declared_output_paths:
            await self.workspace.adelete_file(self.context.task_id, path)

    async def _declared_output_identities(self) -> tuple[FileIdentity, ...]:
        identities: list[FileIdentity] = []
        for path in self.context.declared_output_paths:
            try:
                value = await self.workspace.ahash_file(self.context.task_id, path)
            except WorkspaceError as error:
                raise ReportingError(
                    "report_code_declared_output_missing",
                    "Coding Agent 声明输出不存在。",
                    details={"path": path},
                ) from error
            identities.append(FileIdentity.model_validate(value))
        return tuple(identities)

    async def run_script(self, run_context: RunContext | None = None) -> dict[str, Any]:
        del run_context
        self.binding.clear_execution_state()
        self.submitted_receipt = None
        self.submitted_visual_receipts = ()
        await self._clear_declared_outputs()
        try:
            source_before = await self._validated_source_identity()
            cell = await self.runtime.execute_script_process(
                self.context.code_mode_session_id,
                self.workspace,
                self.context.script_path,
                matplotlib_agg=self.context.task_kind == "visualization",
            )
            if _cell_field(cell, "status") != "ok":
                return _bounded_failure("report_code_mode_execution_failed", cell)
            source_after = await self._validated_source_identity()
            if source_after != source_before:
                return _failure(
                    "report_code_script_modified_during_execution",
                    "脚本在执行期间发生变化。",
                )
            outputs = await self._declared_output_identities()
        except WorkspaceError:
            return _failure(
                "report_code_source_missing",
                "Coding Agent 脚本不存在。",
            )
        except ReportingError as error:
            return _failure(error.code, error.message)
        receipt = ExecutionReceipt(
            runId=uuid4().hex,
            sourceFile=source_after,
            outputFiles=outputs,
        )
        self.binding.execution_receipt = receipt
        return {
            "ok": True,
            "executionReceipt": receipt.model_dump(mode="json", by_alias=True),
        }

    async def submit_script(self, run_context: RunContext | None = None) -> dict[str, Any]:
        del run_context
        receipt = self.binding.execution_receipt
        if receipt is None:
            return _failure(
                "report_code_submission_not_executed",
                "当前脚本内容尚未成功执行。",
            )
        try:
            source = await self._validated_source_identity()
            outputs = await self._declared_output_identities()
        except ReportingError as error:
            return _failure(error.code, error.message)
        if source != receipt.source_file:
            return _failure(
                "report_code_submission_not_executed",
                "当前脚本内容尚未成功执行。",
            )
        if outputs != receipt.output_files:
            return _failure(
                "report_code_output_modified_after_execution",
                "脚本输出在执行后发生变化。",
            )
        if self.context.task_kind == "visualization":
            output_by_path = {item.path: item for item in receipt.output_files}
            reviews = self.binding.visual_inspection_receipts
            if set(reviews) != set(output_by_path):
                return _failure(
                    "report_code_visual_review_required",
                    "每个当前图片输出都必须完成独立视觉审查。",
                )
            for path, output in output_by_path.items():
                reviewed = reviews[path]
                if reviewed.source_path != path:
                    return _failure(
                        "report_code_visual_review_required",
                        "每个当前图片输出都必须完成独立视觉审查。",
                    )
                if reviewed.sha256 != output.sha256:
                    return _failure(
                        "report_code_visual_output_changed",
                        "图片输出在执行或视觉审查后发生变化。",
                    )
                if not reviewed.reviewed or reviewed.visual_review_status != "passed":
                    return _failure(
                        "report_code_visual_review_required",
                        "每个当前图片输出都必须完成独立视觉审查。",
                    )
                if reviewed.requires_revision:
                    return _failure(
                        "report_code_visual_revision_required",
                        "独立视觉审查要求修订当前图片输出。",
                    )
            self.submitted_visual_receipts = tuple(
                reviews[path] for path in sorted(output_by_path)
            )
        self.submitted_receipt = receipt
        return {
            "ok": True,
            "executionReceipt": receipt.model_dump(mode="json", by_alias=True),
        }

    async def require_current_receipt(self, receipt: ExecutionReceipt) -> None:
        try:
            source = await self._validated_source_identity()
            outputs = await self._declared_output_identities()
        except (ReportingError, WorkspaceError) as error:
            raise ReportingError(
                "report_phase_artifact_changed",
                "Coding Agent 签发产物在阶段交接前发生变化。",
            ) from error
        if source != receipt.source_file or outputs != receipt.output_files:
            raise ReportingError(
                "report_phase_artifact_changed",
                "Coding Agent 签发产物在阶段交接前发生变化。",
            )


__all__ = [
    "ReportingCodeModeToolkit",
    "compile_script_source",
    "validate_draft_source",
    "validate_script_source",
]
