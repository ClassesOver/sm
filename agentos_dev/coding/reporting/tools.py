"""Report worker 工具装配。"""

from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import PurePosixPath
from typing import Any

from agno.run import RunContext
from agno.tools import Function, Toolkit
from jsonpatch import JsonPatch, JsonPatchException
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from ...agent_control import AGENT_PLAN_STATE_KEY, validated_agent_plan
from ...task_execution.execution import (
    DEFAULT_TERMINAL_TIMEOUT,
    WorkspaceTaskToolkit,
    normalize_function_call_arguments,
)
from ...workspace import WorkspaceError, WorkspaceService
from .acceptance import REPORT_ARTIFACT_VALIDATOR_ID
from .draft_v1 import (
    ReportChartInput,
    ReportChartRegistration,
    ReportDraft,
    ReportSectionDefinition,
)
from .draft_v1 import render_report_draft as render_structured_draft
from .models import ReportingError
from .repair_guard import REPORT_REPAIR_STATE_KEY, ReportRepairGuard

REPORT_DRAFT_STATE_KEY = "agentos_reporting_structured_draft"
REPORT_CHART_STATE_KEY = "agentos_reporting_registered_charts"
REPORT_TOOL_ARGUMENT_AUTOFIX_STATE_KEY = "agentos_reporting_tool_argument_autofixes"
MAX_REPORT_CHART_BYTES = 10 * 1024 * 1024
_MISSING_PERIOD_LANGUAGE = re.compile(
    r"(?:无记录|没有记录|缺失|未提供|未出数|无数据|没有数据|数据为空)"
)
_PERIOD_REPAIR_REPLACEMENTS = (
    ("没有记录", "按有效观测处理"),
    ("无记录", "按有效观测处理"),
    ("数据缺失", "数据存在有效观测记录"),
    ("未提供", "按有效观测处理"),
    ("未出数", "已有有效观测"),
    ("没有数据", "存在有效观测记录"),
    ("无数据", "有有效观测记录"),
    ("数据为空", "数据存在有效观测记录"),
    ("缺失", "存在有效观测记录"),
)


def _stable_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def normalize_reporting_function_call_arguments(
    fc: Any,
    run_context: RunContext | None = None,
) -> None:
    """在 Agno 2.8.2 建立工具执行链前按 strict schema 规范化 JSON 参数。"""
    normalize_function_call_arguments(
        fc,
        run_context,
        state_key=REPORT_TOOL_ARGUMENT_AUTOFIX_STATE_KEY,
        autofix_code="report_tool_arguments_unwrapped",
    )


class ReportWorkspaceTaskToolkit(WorkspaceTaskToolkit):
    """Report Worker 的专用工具门禁；底层锁、租约和审计复用通用 Kernel。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._report_repair_guard = ReportRepairGuard()
        self.register(
            Function(
                name="register_report_charts",
                description=(
                    "登记工作区中的报告图表源文件；服务端校验身份并决定发布路径。"
                    '示例：{"charts":[{"chartId":"income_trend","sourcePath":'
                    '"analysis/charts/income.png","title":"医疗收入月度趋势",'
                    '"altText":"2025年医疗收入月度变化","citationIds":["citation_001"]}]}'
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "charts": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 100,
                            "items": ReportChartRegistration.model_json_schema(by_alias=True),
                        }
                    },
                    "required": ["charts"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.register_report_charts,
            )
        )
        self.register(
            Function(
                name="render_report_draft",
                description=(
                    "提交一次完整结构化中文报告草稿，由服务端生成最终 Markdown。"
                    "每个 block 的 text 必须是非空正文或图表题注，图表 block 也不得传空字符串。"
                    '示例：{"draft":{"title":"报告标题","sections":[{"sectionCode":'
                    '"executive_summary","blocks":[{"blockId":"income_chart",'
                    '"text":"图表题注","citationIds":["citation_001"],'
                    '"chartIds":["income_trend"]}]}]}}'
                ),
                parameters={
                    "type": "object",
                    "properties": {"draft": ReportDraft.model_json_schema(by_alias=True)},
                    "required": ["draft"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.render_report_draft,
            )
        )
        self.register(
            Function(
                name="resume_report_draft",
                description=(
                    "图表登记或归档异常修复后，恢复当前 Attempt 已保存的报告草稿。示例：{}"
                ),
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                strict=True,
                entrypoint=self.resume_report_draft,
            )
        )
        self.register(
            Function(
                name="verify_report_draft",
                description=("使用服务端固定 validator 和当前已保存产物执行正式报告验收。示例：{}"),
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                strict=True,
                entrypoint=self.verify_report_draft,
            )
        )
        self.register(
            Function(
                name="repair_report_draft",
                description=(
                    "仅按首次验收返回的 issueId 定点修复服务端保存的结构化草稿。"
                    '示例：{"changes":[{"issueId":"period_claim_abc",'
                    '"newText":"2025年11月收入100万元按有效观测处理。"}]}'
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "changes": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 50,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "issueId": {"type": "string", "minLength": 1},
                                    "newText": {"type": "string", "minLength": 1},
                                },
                                "required": ["issueId", "newText"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["changes"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.repair_report_draft,
            )
        )
        for function in (*self.functions.values(), *self.async_functions.values()):
            if function.pre_hook is None:
                function.pre_hook = normalize_reporting_function_call_arguments

    async def _state_admission_rejection(
        self,
        scope: Any,
        tool_name: str,
        arguments: dict[str, Any],
        state: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        rejection = await super()._state_admission_rejection(scope, tool_name, arguments, state)
        if rejection is not None:
            return rejection
        return self._report_repair_guard.admission_rejection(tool_name, arguments, state)

    async def verify(
        self,
        command: str | None = None,
        validator_id: str | None = None,
        artifact_paths: list[str] | None = None,
        run_context: RunContext | None = None,
        *,
        timeout: int = DEFAULT_TERMINAL_TIMEOUT,
    ) -> dict[str, Any]:
        if validator_id == REPORT_ARTIFACT_VALIDATOR_ID:
            return {
                "ok": False,
                "status": "rejected",
                "code": "report_verify_tool_forbidden",
                "message": "报告正式验收只允许调用零参数 verify_report_draft。",
                "expectedCallShape": {},
                "correctCallExample": {
                    "name": "verify_report_draft",
                    "arguments": {},
                },
                "requiredActions": ["调用 verify_report_draft()。"],
                "retryable": True,
            }
        return await super().verify(
            command=command,
            validator_id=validator_id,
            artifact_paths=artifact_paths,
            run_context=run_context,
            timeout=timeout,
        )

    async def _invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        call: Any,
        run_context: Any,
    ) -> Any:
        result = await super()._invoke(tool_name, arguments, call, run_context)
        state = self._session_state(run_context)
        if (
            tool_name == "verify"
            and arguments.get("validator_id") == REPORT_ARTIFACT_VALIDATOR_ID
            and isinstance(result, dict)
        ):
            self._bind_repair_targets(result, state)
        self._report_repair_guard.record_result(
            tool_name,
            arguments,
            result,
            state,
        )
        return result

    @staticmethod
    def _session_state(run_context: RunContext | None) -> dict[str, Any] | None:
        if run_context is not None and isinstance(run_context.session_state, dict):
            return run_context.session_state
        return None

    @staticmethod
    def _render_contract(scope: Any) -> tuple[str, str, tuple[Any, ...], tuple[str, ...]]:
        acceptance_contract = scope.task.acceptance_contract
        requirements = (
            acceptance_contract.get("requirements")
            if isinstance(acceptance_contract, dict)
            else None
        )
        requirement = (
            requirements[0] if isinstance(requirements, list) and len(requirements) == 1 else None
        )
        parameters = requirement.get("parameters") if isinstance(requirement, dict) else None
        expected = parameters.get("expectedIdentity") if isinstance(parameters, dict) else None
        contract = parameters.get("renderContract") if isinstance(parameters, dict) else None
        if not isinstance(expected, dict) or not isinstance(contract, dict):
            raise ReportingError(
                "report_draft_contract_missing", "当前 Reporting Task 缺少服务端渲染契约。"
            )
        title = contract.get("title")
        markdown_path = expected.get("markdownPath")
        raw_sections = contract.get("sections")
        raw_citations = contract.get("citationIds")
        if (
            not isinstance(title, str)
            or not isinstance(markdown_path, str)
            or not isinstance(raw_sections, list)
            or not isinstance(raw_citations, list)
        ):
            raise ReportingError(
                "report_draft_contract_invalid", "当前 Reporting Task 的服务端渲染契约无效。"
            )
        sections = tuple(ReportSectionDefinition.model_validate(item) for item in raw_sections)
        if any(not isinstance(item, str) for item in raw_citations):
            raise ReportingError(
                "report_draft_contract_invalid", "当前 Reporting Task 的 citation 注册表无效。"
            )
        return title, markdown_path, sections, tuple(raw_citations)

    @staticmethod
    def _failure(error: Exception, *, retryable: bool = True) -> dict[str, Any]:
        validation_errors: list[dict[str, str]] = []
        if isinstance(error, ReportingError):
            code = error.code
            message = error.message
        elif isinstance(error, ValidationError):
            code = "report_draft_invalid"
            message = "结构化报告参数不符合严格 schema。"
            # 只返回定位修复所需的稳定结构，不回显 input、ctx 或文档 URL，避免把整份
            # Draft 和内部校验细节再次塞回模型上下文。错误数量也必须有界。
            for item in error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )[:20]:
                path = "draft"
                for part in item["loc"]:
                    path += f"[{part}]" if isinstance(part, int) else f".{part}"
                validation_errors.append(
                    {
                        "path": path,
                        "code": str(item["type"]),
                        "message": str(item["msg"])[:300],
                    }
                )
            validation_errors = [
                item
                for item in validation_errors
                if not any(
                    other["path"].startswith((f"{item['path']}.", f"{item['path']}["))
                    for other in validation_errors
                    if other is not item
                )
            ]
        elif isinstance(error, (WorkspaceError, UnidentifiedImageError, OSError)):
            code = "report_draft_workspace_error"
            message = str(error)[:1000]
        else:
            code = "report_draft_workspace_error"
            message = "报告草稿处理失败。"
        result = {
            "ok": False,
            "status": "rejected",
            "code": code,
            "message": message,
            "requiredActions": ["按服务端错误反馈修正后重试。"],
            "retryable": retryable,
        }
        if validation_errors:
            result["validationErrors"] = validation_errors
            result["requiredActions"] = [
                "仅修正 validationErrors 指向的字段后重新调用 render_report_draft。"
            ]
        return result

    @staticmethod
    def _attempt_state(
        state: dict[str, Any] | None,
        key: str,
        attempt_no: int,
    ) -> dict[str, Any]:
        if state is None:
            raise ReportingError("report_draft_state_missing", "当前工具缺少可持久化会话状态。")
        value = state.get(key)
        if not isinstance(value, dict) or value.get("attemptNo") != attempt_no:
            value = {"attemptNo": attempt_no}
            state[key] = value
        return value

    async def _inspect_chart(
        self,
        *,
        thread_id: str,
        registration: ReportChartRegistration,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        source_path, remote = self.kernel.service.normalize_path(
            registration.source_path, allow_root=False
        )
        async with self.kernel.service._async_client() as client:
            sandbox = await self.kernel.service._asandbox_for(client, thread_id)
            await self.kernel.service._avalidate_existing_path(sandbox, source_path)
            info = await self.kernel.service._ainfo(sandbox, remote)
            if not self.kernel.service._is_regular_file(info):
                raise ReportingError("report_chart_source_invalid", "图表源路径必须指向普通文件。")
            size = int(getattr(info, "size", 0) or 0)
            if not 0 < size <= MAX_REPORT_CHART_BYTES:
                raise ReportingError(
                    "report_chart_source_invalid", "单张图表必须大于 0 且不超过 10 MiB。"
                )
            content = await self.kernel.service._adownload_file(
                sandbox, remote, MAX_REPORT_CHART_BYTES
            )
        digest = hashlib.sha256(content).hexdigest()
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.load()
                image_format = str(image.format or "").upper()
                width, height = image.size
                colors = image.convert("RGBA").getcolors(maxcolors=2)
        except (UnidentifiedImageError, OSError) as error:
            raise ReportingError(
                "report_chart_source_invalid", "图表源文件无法解码或图片签名无效。"
            ) from error
        suffix = PurePosixPath(source_path).suffix.lower()
        if image_format == "PNG" and suffix == ".png":
            media_type = "image/png"
            extension = ".png"
        elif image_format == "JPEG" and suffix in {".jpg", ".jpeg"}:
            media_type = "image/jpeg"
            extension = ".jpg"
        else:
            raise ReportingError(
                "report_chart_source_invalid", "图表仅允许签名与扩展名一致的 PNG 或 JPEG。"
            )
        if width < 1 or height < 1 or (colors is not None and len(colors) <= 1):
            raise ReportingError("report_chart_blank", "图表图片完全空白，不能登记。")
        warnings: list[dict[str, Any]] = []
        if width < 800 or height < 450:
            warnings.append(
                {
                    "code": "chart_low_resolution",
                    "chartId": registration.chart_id,
                    "width": width,
                    "height": height,
                    "message": "图表分辨率偏低，已进入发布质量审核。",
                }
            )
        ratio = width / height
        if ratio > 4 or ratio < 0.25:
            warnings.append(
                {
                    "code": "chart_extreme_aspect_ratio",
                    "chartId": registration.chart_id,
                    "width": width,
                    "height": height,
                    "message": "图表宽高比极端，已进入发布质量审核。",
                }
            )
        return (
            {
                **registration.model_dump(mode="json", by_alias=True),
                "sourcePath": source_path,
                "size": len(content),
                "sha256": digest,
                "format": image_format,
                "mediaType": media_type,
                "extension": extension,
                "width": width,
                "height": height,
            },
            warnings,
        )

    async def register_report_charts(
        self,
        charts: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        state = self._session_state(run_context)
        rejection = self._report_repair_guard.admission_rejection(
            "register_report_charts", {"charts": charts}, state
        )
        if rejection is not None:
            return rejection
        try:
            scope = await self.kernel.scope(run_context)
            _title, _path, _sections, citation_ids = self._render_contract(scope)
            parsed = tuple(ReportChartRegistration.model_validate(item) for item in charts)
            if len({item.chart_id for item in parsed}) != len(parsed):
                raise ReportingError(
                    "report_chart_registration_duplicate", "同一次登记的 chartId 不能重复。"
                )
            if any(set(item.citation_ids) - set(citation_ids) for item in parsed):
                raise ReportingError("report_draft_citation_unknown", "图表引用了未注册 citation。")
            registry_state = self._attempt_state(
                state, REPORT_CHART_STATE_KEY, int(getattr(scope, "attempt_no", 0))
            )
            registry = registry_state.setdefault("charts", {})
            warnings: list[dict[str, Any]] = []
            registered: list[dict[str, Any]] = []
            for registration in parsed:
                identity, chart_warnings = await self._inspect_chart(
                    thread_id=scope.thread_id,
                    registration=registration,
                )
                existing = registry.get(registration.chart_id)
                if isinstance(existing, dict):
                    comparable_keys = {
                        "sourcePath",
                        "title",
                        "altText",
                        "citationIds",
                        "size",
                        "sha256",
                        "format",
                        "width",
                        "height",
                    }
                    if any(existing.get(key) != identity.get(key) for key in comparable_keys):
                        raise ReportingError(
                            "report_chart_registration_conflict",
                            f"chartId {registration.chart_id} 已绑定不同图表身份。",
                        )
                    identity = existing
                else:
                    registry[registration.chart_id] = identity
                warnings.extend(chart_warnings)
                registered.append(
                    {
                        "chartId": identity["chartId"],
                        "sourcePath": identity["sourcePath"],
                        "size": identity["size"],
                        "sha256": identity["sha256"],
                        "format": identity["format"],
                        "width": identity["width"],
                        "height": identity["height"],
                    }
                )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)
        return {
            "ok": True,
            "status": "completed",
            "charts": registered,
            "warnings": warnings,
            "mutation_sequence": getattr(scope.task, "mutation_sequence", 0),
        }

    @staticmethod
    def _draft_chart_ids(draft: ReportDraft) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                chart_id
                for section in draft.sections
                for block in section.blocks
                for chart_id in block.chart_ids
            )
        )

    @staticmethod
    def _placeholder_charts(draft: ReportDraft) -> tuple[ReportChartInput, ...]:
        bindings: dict[str, set[str]] = {}
        for section in draft.sections:
            for block in section.blocks:
                for chart_id in block.chart_ids:
                    if chart_id in bindings:
                        bindings[chart_id].intersection_update(block.citation_ids)
                    else:
                        bindings[chart_id] = set(block.citation_ids)
        if any(not values for values in bindings.values()):
            raise ReportingError(
                "report_draft_chart_citation_invalid",
                "同一图表在全部正文块中必须具有共同 citation 绑定。",
            )
        return tuple(
            ReportChartInput(
                chartId=chart_id,
                fileName=f"chart-{hashlib.sha256(chart_id.encode()).hexdigest()[:16]}.png",
                title="待登记图表",
                altText="待登记图表",
                citationIds=tuple(sorted(citations)),
            )
            for chart_id, citations in bindings.items()
        )

    def _validate_and_store_draft(
        self,
        *,
        scope: Any,
        state: dict[str, Any] | None,
        draft: dict[str, Any],
    ) -> tuple[ReportDraft, str, tuple[Any, ...], tuple[str, ...], dict[str, Any]]:
        attempt_no = int(getattr(scope, "attempt_no", 0))
        draft_state = self._attempt_state(state, REPORT_DRAFT_STATE_KEY, attempt_no)
        if draft_state.get("submitted") is True:
            raise ReportingError(
                "report_draft_already_submitted",
                "当前 Attempt 已提交过完整 ReportDraft；请使用 resume_report_draft 恢复。",
            )
        title, markdown_path, sections, citation_ids = self._render_contract(scope)
        parsed = ReportDraft.model_validate(draft)
        # 这里先用服务端占位图表完成标题、章节、正文 citation 与协议注入校验；
        # 图表真实身份随后由登记表校验，因此机械归档失败不会迫使模型重传完整 Draft。
        render_structured_draft(
            parsed,
            expected_title=title,
            markdown_path=markdown_path,
            sections=sections,
            citation_ids=citation_ids,
            charts=self._placeholder_charts(parsed),
        )
        serialized = parsed.model_dump(mode="json", by_alias=True)
        draft_id = _stable_digest(serialized)
        draft_state.update(
            {
                "submitted": True,
                "status": "validated",
                "draftId": draft_id,
                "draft": serialized,
                "markdownPath": markdown_path,
            }
        )
        return parsed, markdown_path, sections, citation_ids, draft_state

    @staticmethod
    def _archived_chart_input(identity: dict[str, Any]) -> ReportChartInput:
        target_name = (
            f"chart-{hashlib.sha256(str(identity['chartId']).encode()).hexdigest()[:16]}"
            f"{identity['extension']}"
        )
        return ReportChartInput(
            chartId=identity["chartId"],
            fileName=target_name,
            title=identity["title"],
            altText=identity["altText"],
            citationIds=identity["citationIds"],
        )

    async def _write_rendered_draft(
        self,
        *,
        scope: Any,
        markdown_path: str,
        markdown: str,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        current = (await self.kernel.service.abatch_hash_files(scope.thread_id, [markdown_path]))[0]
        mode = "create" if current.get("missing") is True else "overwrite"
        return await self.kernel.patch(
            mode,
            markdown_path,
            None,
            None,
            False,
            None,
            run_context,
            content=markdown,
            expected_sha256=current.get("sha256") if mode == "overwrite" else None,
            _scope=scope,
        )

    @staticmethod
    def _render_repair_warnings(markdown: str, warnings: Any) -> tuple[str, list[dict[str, Any]]]:
        if not isinstance(warnings, list) or not warnings:
            return markdown, []
        parts = [markdown, "## 发布审核提示"]
        rendered_warnings: list[dict[str, Any]] = []
        for item in warnings:
            if not isinstance(item, dict):
                continue
            validator_issue_id = item.get("validatorIssueId")
            if (
                not isinstance(validator_issue_id, str)
                or re.fullmatch(r"period_claim_[a-f0-9]{16}", validator_issue_id) is None
            ):
                continue
            raw_citation_ids = item.get("citationIds")
            citation_ids = (
                [value for value in raw_citation_ids if isinstance(value, str)]
                if isinstance(raw_citation_ids, list)
                else []
            )
            markers = "".join(f"[[citation:{value}]]" for value in citation_ids)
            parts.append(
                f"<!-- repair-warning:{validator_issue_id} -->\n"
                "> 正文中有一处期间覆盖表述未能自动修复，请在发布前结合对应数据来源人工核对。"
                f"{markers}"
            )
            rendered_warnings.append(
                {
                    "code": "unresolved_repair_issue",
                    "issueId": validator_issue_id,
                    "message": "期间覆盖表述未能自动修复，已写入发布审核提示。",
                }
            )
        return "\n\n".join(parts), rendered_warnings

    async def _resume_saved_draft(
        self,
        *,
        scope: Any,
        state: dict[str, Any] | None,
        draft_state: dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        title, markdown_path, sections, citation_ids = self._render_contract(scope)
        parsed = ReportDraft.model_validate(draft_state.get("draft"))
        attempt_no = int(getattr(scope, "attempt_no", 0))
        chart_state = self._attempt_state(state, REPORT_CHART_STATE_KEY, attempt_no)
        registry = chart_state.get("charts")
        registry = registry if isinstance(registry, dict) else {}
        referenced = self._draft_chart_ids(parsed)
        missing = [chart_id for chart_id in referenced if chart_id not in registry]
        if missing:
            raise ReportingError(
                "report_draft_chart_unregistered",
                "草稿引用了尚未登记的图表：" + ", ".join(missing),
            )
        chart_inputs = tuple(
            self._archived_chart_input(identity)
            for identity in registry.values()
            if isinstance(identity, dict)
        )
        rendered = render_structured_draft(
            parsed,
            expected_title=title,
            markdown_path=markdown_path,
            sections=sections,
            citation_ids=citation_ids,
            charts=chart_inputs,
        )
        rendered_markdown, repair_warnings = self._render_repair_warnings(
            rendered.markdown,
            draft_state.get("repairWarnings"),
        )
        input_by_id = {item.chart_id: item for item in chart_inputs}
        report_parent = PurePosixPath(markdown_path).parent
        copies = []
        for chart_id in referenced:
            identity = registry[chart_id]
            destination = report_parent.joinpath(input_by_id[chart_id].file_name).as_posix()
            copies.append(
                {
                    "source": identity["sourcePath"],
                    "destination": destination,
                    "expected_sha256": identity["sha256"],
                    "expected_size": identity["size"],
                }
            )
        copy_result = (
            await self.kernel.batch_copy_files(copies, run_context, _scope=scope)
            if copies
            else {
                "ok": True,
                "files": [],
                "mutation_sequence": getattr(scope.task, "mutation_sequence", 0),
                "execution_id": None,
            }
        )
        if copy_result.get("ok") is not True:
            return copy_result
        mutation = await self._write_rendered_draft(
            scope=scope,
            markdown_path=markdown_path,
            markdown=rendered_markdown,
            run_context=run_context,
        )
        if mutation.get("ok") is not True:
            return mutation
        markdown_sha256 = hashlib.sha256(rendered_markdown.encode("utf-8")).hexdigest()
        draft_state.update(
            {
                "status": "rendered",
                "markdownSha256": markdown_sha256,
                "artifactPaths": [markdown_path, *rendered.chart_paths],
                "archiveReceipt": copy_result.get("files", []),
            }
        )
        if state is not None:
            self._report_repair_guard.record_draft_rendered(
                state,
                markdown_path=markdown_path,
                markdown_sha256=markdown_sha256,
            )
        return {
            "ok": True,
            "status": "completed",
            "draftId": draft_state["draftId"],
            "markdownPath": markdown_path,
            "markdownSha256": markdown_sha256,
            "artifactPaths": [markdown_path, *rendered.chart_paths],
            "warnings": [*rendered.warnings, *repair_warnings],
            "autoFixes": list(rendered.auto_fixes),
            "archiveReceipts": copy_result.get("files", []),
            "execution_id": mutation.get("execution_id"),
            "mutation_sequence": mutation.get("mutation_sequence"),
        }

    async def render_report_draft(
        self,
        draft: dict[str, Any],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        state = self._session_state(run_context)
        rejection = self._report_repair_guard.admission_rejection(
            "render_report_draft", {"draft": draft}, state
        )
        if rejection is not None:
            return rejection
        try:
            scope = await self.kernel.scope(run_context)
            _parsed, _path, _sections, _citations, draft_state = self._validate_and_store_draft(
                scope=scope,
                state=state,
                draft=draft,
            )
            return await self._resume_saved_draft(
                scope=scope,
                state=state,
                draft_state=draft_state,
                run_context=run_context,
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)

    async def resume_report_draft(
        self,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        state = self._session_state(run_context)
        rejection = self._report_repair_guard.admission_rejection("resume_report_draft", {}, state)
        if rejection is not None:
            return rejection
        try:
            scope = await self.kernel.scope(run_context)
            draft_state = self._attempt_state(
                state, REPORT_DRAFT_STATE_KEY, int(getattr(scope, "attempt_no", 0))
            )
            if draft_state.get("submitted") is not True:
                raise ReportingError(
                    "report_draft_state_missing", "当前 Attempt 没有已保存的结构化草稿。"
                )
            if draft_state.get("status") == "rendered":
                raise ReportingError(
                    "report_draft_already_rendered", "当前结构化草稿已经成功渲染。"
                )
            return await self._resume_saved_draft(
                scope=scope,
                state=state,
                draft_state=draft_state,
                run_context=run_context,
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)

    async def verify_report_draft(
        self,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        state = self._session_state(run_context)
        stored = state.get(REPORT_DRAFT_STATE_KEY) if isinstance(state, dict) else None
        trusted_paths = stored.get("artifactPaths") if isinstance(stored, dict) else None
        if not isinstance(trusted_paths, list) or any(
            not isinstance(path, str) or not path for path in trusted_paths
        ):
            return self._failure(
                ReportingError(
                    "report_draft_state_missing",
                    "正式验收前必须先由服务端生成结构化报告草稿。",
                )
            )
        result = await WorkspaceTaskToolkit.verify(
            self,
            validator_id=REPORT_ARTIFACT_VALIDATOR_ID,
            artifact_paths=list(trusted_paths),
            run_context=run_context,
        )
        acceptance = result.get("acceptance") if isinstance(result, dict) else None
        requirements = acceptance.get("requirements") if isinstance(acceptance, dict) else None
        if isinstance(requirements, list):
            warnings = [
                warning
                for requirement in requirements
                if isinstance(requirement, dict)
                for warning in (requirement.get("details") or {}).get("warnings", [])
                if isinstance(warning, dict)
            ]
            auto_fixes = [
                item
                for requirement in requirements
                if isinstance(requirement, dict)
                for item in (requirement.get("details") or {}).get("autoFixes", [])
                if isinstance(item, dict)
            ]
            result["warnings"] = warnings
            result["autoFixes"] = auto_fixes
        if isinstance(result, dict) and result.get("ok") is True:
            # Workspace verify 的 ok=True 是正式验收的唯一事实依据。仅在该结果成立后，
            # 服务端才结束本 Attempt 的计划并签发下一次调用；产物路径取自已保存 Draft，
            # 不接受模型重填。finish_task 本身仍按原发布契约真实执行，不能由这里绕过。
            plan = validated_agent_plan(state.get(AGENT_PLAN_STATE_KEY)) if state else None
            if plan is not None and state is not None:
                state[AGENT_PLAN_STATE_KEY] = {
                    "plan": [
                        {"step": item["step"], "status": "completed"} for item in plan["plan"]
                    ],
                    "explanation": plan["explanation"],
                }
            draft = stored.get("draft") if isinstance(stored, dict) else None
            title = draft.get("title") if isinstance(draft, dict) else None
            summary = (
                f"报告《{title}》已通过服务端正式验收。"
                if isinstance(title, str) and title
                else "结构化报告已通过服务端正式验收。"
            )
            result["nextToolCall"] = {
                "name": "finish_task",
                "arguments": {
                    "summary": summary,
                    "artifact_paths": list(trusted_paths),
                },
            }
        return result

    @staticmethod
    def _period_repair_example(claim: str) -> str:
        for original, replacement in _PERIOD_REPAIR_REPLACEMENTS:
            if original in claim:
                return claim.replace(original, replacement, 1)
        return claim

    def _bind_repair_targets(
        self,
        result: dict[str, Any],
        state: dict[str, Any] | None,
    ) -> None:
        """把 validator 问题绑定到服务端 Draft 的唯一 JSON Pointer。"""
        stored = state.get(REPORT_DRAFT_STATE_KEY) if isinstance(state, dict) else None
        if not isinstance(stored, dict) or not isinstance(stored.get("draftId"), str):
            return
        try:
            draft_payload = ReportDraft.model_validate(stored.get("draft")).model_dump(
                mode="json", by_alias=True
            )
        except ValidationError:
            return
        if _stable_digest(draft_payload) != stored["draftId"]:
            return

        failures = result.get("failedRequirements")
        if not isinstance(failures, list):
            return
        candidates = [
            {
                "sectionIndex": section_index,
                "blockIndex": block_index,
                "sectionCode": section["sectionCode"],
                "blockId": block["blockId"],
                "block": block,
                "pointer": f"/sections/{section_index}/blocks/{block_index}/text",
            }
            for section_index, section in enumerate(draft_payload["sections"])
            for block_index, block in enumerate(section["blocks"])
        ]
        used_pointers: set[str] = set()
        repair_changes: list[dict[str, str]] = []
        output_issue_bindings: list[tuple[str, str, dict[str, Any]]] = []
        issue_ordinal = 0
        for failure in failures:
            details = failure.get("details") if isinstance(failure, dict) else None
            issues = details.get("contradictoryPeriodClaims") if isinstance(details, dict) else None
            if not isinstance(issues, list):
                continue
            for issue in issues:
                if not isinstance(issue, dict) or not isinstance(issue.get("claim"), str):
                    continue
                issue_ordinal += 1
                claim = issue["claim"]
                validator_issue_id = str(issue.get("issueId") or "period_claim")
                raw_citation_ids = issue.get("citationIds")
                citation_ids = (
                    {value for value in raw_citation_ids if isinstance(value, str)}
                    if isinstance(raw_citation_ids, list)
                    else set()
                )
                matches = [
                    candidate
                    for candidate in candidates
                    if candidate["pointer"] not in used_pointers
                    and candidate["block"]["text"].count(claim) == 1
                    and (
                        not citation_ids
                        or citation_ids.issubset(set(candidate["block"]["citationIds"]))
                    )
                ]
                target = matches[0] if matches else None
                binding_identity = (
                    target["pointer"] if target is not None else f"unbound:{issue_ordinal}"
                )
                issue_id = (
                    "period_claim_"
                    + _stable_digest(
                        {
                            "validatorIssueId": validator_issue_id,
                            "binding": binding_identity,
                            "claim": claim,
                        }
                    )[:16]
                )
                suggested_text = self._period_repair_example(claim)
                issue.update(
                    {
                        "issueId": issue_id,
                        "validatorIssueId": validator_issue_id,
                        "suggestedText": suggested_text,
                        "draftId": stored["draftId"],
                    }
                )
                if target is None:
                    issue["targetBindingError"] = "claim_not_bound_to_structured_draft"
                else:
                    used_pointers.add(target["pointer"])
                    block_text = target["block"]["text"]
                    issue.update(
                        {
                            "sectionCode": target["sectionCode"],
                            "blockId": target["blockId"],
                            "targetPointer": target["pointer"],
                            "targetTextSha256": hashlib.sha256(
                                block_text.encode("utf-8")
                            ).hexdigest(),
                        }
                    )
                output_issue_bindings.append((validator_issue_id, claim, dict(issue)))
                repair_changes.append({"issueId": issue_id, "newText": suggested_text})
        self._rewrite_validator_output_issues(result, output_issue_bindings)
        if repair_changes:
            result["repairCallExample"] = {
                "name": "repair_report_draft",
                "arguments": {"changes": repair_changes},
            }

    @staticmethod
    def _rewrite_validator_output_issues(
        result: dict[str, Any],
        bindings: list[tuple[str, str, dict[str, Any]]],
    ) -> None:
        """让模型可见的 validator 输出与服务端 repair issue 使用同一稳定 ID。"""
        output = result.get("output")
        if not bindings or not isinstance(output, str):
            return
        try:
            requirements = json.loads(output)
        except (TypeError, ValueError):
            return
        if not isinstance(requirements, list):
            return
        remaining = list(bindings)
        changed = False
        for requirement in requirements:
            details = requirement.get("details") if isinstance(requirement, dict) else None
            issues = details.get("contradictoryPeriodClaims") if isinstance(details, dict) else None
            if not isinstance(issues, list):
                continue
            for issue in issues:
                if not isinstance(issue, dict) or not isinstance(issue.get("claim"), str):
                    continue
                key = (str(issue.get("issueId") or "period_claim"), issue["claim"])
                match_index = next(
                    (
                        index
                        for index, (validator_issue_id, claim, _bound) in enumerate(remaining)
                        if (validator_issue_id, claim) == key
                    ),
                    None,
                )
                if match_index is None:
                    continue
                _validator_issue_id, _claim, bound = remaining.pop(match_index)
                issue.update(bound)
                changed = True
        if changed:
            result["output"] = json.dumps(
                requirements,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )

    async def repair_report_draft(
        self,
        changes: list[dict[str, str]],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        arguments = {"changes": changes}
        state = self._session_state(run_context)
        rejection = self._report_repair_guard.admission_rejection(
            "repair_report_draft", arguments, state
        )
        if rejection is not None:
            return rejection
        stored = state.get(REPORT_DRAFT_STATE_KEY) if isinstance(state, dict) else None
        repair_state = state.get(REPORT_REPAIR_STATE_KEY) if isinstance(state, dict) else None
        if not isinstance(stored, dict) or not isinstance(repair_state, dict):
            return self._failure(
                ReportingError("report_draft_state_missing", "服务端没有可修复的结构化草稿。")
            )
        try:
            scope = await self.kernel.scope(run_context)
            if stored.get("attemptNo") != int(getattr(scope, "attempt_no", 0)):
                raise ReportingError(
                    "report_draft_state_missing", "已保存草稿不属于当前 Coding Attempt。"
                )
            issues = {
                item["issueId"]: item
                for item in repair_state.get("requiredIssues", [])
                if isinstance(item, dict) and isinstance(item.get("issueId"), str)
            }
            draft_payload = ReportDraft.model_validate(stored.get("draft")).model_dump(
                mode="json", by_alias=True
            )
            if _stable_digest(draft_payload) != stored.get("draftId"):
                raise ReportingError(
                    "report_draft_repair_target_invalid",
                    "结构化草稿在 issue 绑定后发生变化，拒绝应用修复。",
                )
            patch_receipts: list[dict[str, Any]] = []
            auto_fixes: list[dict[str, Any]] = []
            repair_warnings: list[dict[str, Any]] = []
            for change in changes:
                issue = issues[change["issueId"]]
                claim = issue["claim"]
                suggested_text = issue.get("suggestedText")
                target_pointer = issue.get("targetPointer")
                if (
                    issue.get("targetBindingError") is not None
                    or not isinstance(target_pointer, str)
                    or not isinstance(suggested_text, str)
                ):
                    repair_warnings.append(
                        {
                            "issueId": change["issueId"],
                            "validatorIssueId": issue.get("validatorIssueId"),
                            "citationIds": issue.get("citationIds", []),
                            "reason": "target_not_bound",
                        }
                    )
                    continue
                target_match = re.fullmatch(r"/sections/(\d+)/blocks/(\d+)/text", target_pointer)
                if target_match is None or issue.get("draftId") != stored.get("draftId"):
                    raise ReportingError(
                        "report_draft_repair_target_invalid",
                        "issueId 没有绑定合法的服务端 Draft text 路径。",
                    )
                section_index, block_index = (int(value) for value in target_match.groups())
                try:
                    section = draft_payload["sections"][section_index]
                    block = section["blocks"][block_index]
                except (IndexError, TypeError):
                    raise ReportingError(
                        "report_draft_repair_target_invalid",
                        "issueId 对应的服务端 Draft text 路径已经失效。",
                    ) from None
                current_text = block["text"]
                if (
                    section["sectionCode"] != issue.get("sectionCode")
                    or block["blockId"] != issue.get("blockId")
                    or current_text.count(claim) != 1
                    or hashlib.sha256(current_text.encode("utf-8")).hexdigest()
                    != issue.get("targetTextSha256")
                ):
                    raise ReportingError(
                        "report_draft_repair_target_invalid",
                        "issueId 绑定的 block 身份或原文已经变化。",
                    )
                requested_text = change["newText"].strip()
                use_suggestion = _MISSING_PERIOD_LANGUAGE.search(requested_text) is not None
                new_text = suggested_text if use_suggestion else requested_text
                if new_text == claim or _MISSING_PERIOD_LANGUAGE.search(new_text) is not None:
                    repair_warnings.append(
                        {
                            "issueId": change["issueId"],
                            "validatorIssueId": issue.get("validatorIssueId"),
                            "citationIds": issue.get("citationIds", []),
                            "reason": "safe_replacement_unavailable",
                        }
                    )
                    continue
                replacement_text = current_text.replace(claim, new_text, 1)
                try:
                    draft_payload = JsonPatch(
                        [
                            {"op": "test", "path": target_pointer, "value": current_text},
                            {"op": "replace", "path": target_pointer, "value": replacement_text},
                        ]
                    ).apply(draft_payload, in_place=False)
                except JsonPatchException as error:
                    raise ReportingError(
                        "report_draft_repair_target_invalid",
                        "受限 JSON Patch 无法应用到已绑定的 Draft text。",
                    ) from error
                patch_receipts.append(
                    {
                        "issueId": change["issueId"],
                        "op": "replace",
                        "path": target_pointer,
                        "beforeSha256": hashlib.sha256(current_text.encode("utf-8")).hexdigest(),
                        "afterSha256": hashlib.sha256(replacement_text.encode("utf-8")).hexdigest(),
                    }
                )
                if use_suggestion:
                    auto_fixes.append(
                        {
                            "code": "repair_text_replaced_by_server_suggestion",
                            "issueId": change["issueId"],
                            "message": "模型修复文本仍包含缺失表述，已使用服务端建议文本。",
                        }
                    )
            parsed = ReportDraft.model_validate(draft_payload)
            stored.update(
                {
                    "draft": parsed.model_dump(mode="json", by_alias=True),
                    "status": "validated",
                    "repairPatches": patch_receipts,
                    "repairWarnings": repair_warnings,
                }
            )
            result = await self._resume_saved_draft(
                scope=scope,
                state=state,
                draft_state=stored,
                run_context=run_context,
            )
        except (KeyError, ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)
        if isinstance(result, dict) and result.get("ok") is True:
            result["repairPatches"] = patch_receipts
            result["autoFixes"] = [*result.get("autoFixes", []), *auto_fixes]
        self._report_repair_guard.record_result("repair_report_draft", arguments, result, state)
        return result


def build_report_worker_tools(
    workspace_service: WorkspaceService,
    task_repository: Any,
    validator_registry: Any = None,
    *,
    run_context: RunContext | None = None,
    agent: Any | None = None,
    enable_vision: bool = False,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
) -> list[Toolkit]:
    """Report Worker 只执行 Coding 分析，不持有数据库或 SQL 工具。"""
    toolkit = ReportWorkspaceTaskToolkit(
        workspace_service,
        task_repository,
        validator_registry=validator_registry,
    )
    if not enable_vision:
        toolkit.functions.pop("view_image", None)
        toolkit.async_functions.pop("view_image", None)
    return [toolkit]
