"""Reporting 可视化工具能力。"""

# mypy: disable-error-code="attr-defined"
# 运行时由 toolkit 组合的多重继承提供公共状态与执行包装。

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from agno.run import RunContext
from pydantic import ValidationError

from ...workspace import WorkspaceError, WorkspaceService
from ..delivery.draft_v1 import ReportChartRegistration
from ..models import ReportingError
from ..workflow.checkpoint import ChartVisualInspectionReceipt, FileIdentity
from .validation import _stable_digest

MAX_VISUALIZATION_SCRIPT_BYTES = 64 * 1024
MIN_REPORT_CHART_WIDTH = 1200
MIN_REPORT_CHART_HEIGHT = 675
MIN_REPORT_CHART_EFFECTIVE_DPI = 150
# 174mm 来源于 A4 纸张宽度 210mm 减去现有左右各 18mm 页边距，仅作质量估算，不能作为发布门禁。
REPORT_BODY_WIDTH_INCHES = 174 / 25.4
_CJK_TEXT_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _missing_chinese_display_fields(registration: ReportChartRegistration) -> list[str]:
    """返回缺少中文用户可见文字的元数据字段。

    图像像素中的坐标轴和图例需要视觉或主题级校验，无法在提交工具中稳定识别；
    这里仅对服务端掌握的标题和图注做轻量门禁，避免英文元数据进入正式报告。
    """

    return [
        field_name
        for field_name, value in (("title", registration.title), ("altText", registration.alt_text))
        if not _CJK_TEXT_RE.search(value)
    ]


class RuntimeVisualizationMixin:
    """图表检查、登记与可视化终态提交。"""

    @staticmethod
    def _chart_output_root(contract: Mapping[str, Any]) -> str:
        workspace = contract.get("visualizationWorkspace")
        raw_root = workspace.get("chartOutputRoot") if isinstance(workspace, Mapping) else None
        try:
            return WorkspaceService.normalize_path(raw_root, allow_root=False)[0]
        except (TypeError, WorkspaceError) as error:
            raise ReportingError(
                "report_phase_contract_invalid",
                "visualization chartOutputRoot 无效。",
            ) from error

    @staticmethod
    def _section_chart_draft_catalog(
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        """读取 durable 章节图表草案；状态损坏或含重复身份时失败关闭，不猜测。"""

        raw_sections = payload.get("visualizationSections", {})
        if not isinstance(raw_sections, Mapping):
            raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
        charts_by_id: dict[str, dict[str, Any]] = {}
        files_by_path: dict[str, dict[str, Any]] = {}
        for section_code, section_draft in raw_sections.items():
            if not isinstance(section_code, str) or not isinstance(section_draft, Mapping):
                raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
            raw_charts = section_draft.get("charts", ())
            raw_files = section_draft.get("files", ())
            if not isinstance(raw_charts, list) or not isinstance(raw_files, list):
                raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
            for chart in raw_charts:
                if not isinstance(chart, Mapping) or not isinstance(chart.get("chartId"), str):
                    raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
                if chart["chartId"] in charts_by_id:
                    raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
                charts_by_id[chart["chartId"]] = dict(chart)
            for file in raw_files:
                if not isinstance(file, Mapping) or not isinstance(file.get("path"), str):
                    raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
                if file["path"] in files_by_path:
                    raise ReportingError("report_state_invalid", "visualizationSections 状态损坏。")
                files_by_path[file["path"]] = dict(file)
        return charts_by_id, files_by_path

    @staticmethod
    def _require_chart_output_path(path: str, output_root: str) -> str:
        try:
            normalized = WorkspaceService.normalize_path(path, allow_root=False)[0]
        except (TypeError, WorkspaceError) as error:
            raise ReportingError("report_chart_source_invalid", "图表源路径无效。") from error
        if not normalized.startswith(f"{output_root}/"):
            raise ReportingError(
                "report_chart_source_path_forbidden",
                "图表只能读取当前 visualization Task 的签发输出目录。",
            )
        return normalized

    async def _inspect_chart_file(
        self,
        *,
        thread_id: str,
        path: str,
    ) -> dict[str, Any]:
        return await self.runtime.workspace.inspect_chart_file(thread_id, path)

    async def _inspect_chart(
        self,
        *,
        thread_id: str,
        registration: ReportChartRegistration,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        file_identity = await self._inspect_chart_file(
            thread_id=thread_id,
            path=registration.source_path,
        )
        width = int(file_identity["width"])
        height = int(file_identity["height"])
        warnings: list[dict[str, Any]] = []
        if width < MIN_REPORT_CHART_WIDTH or height < MIN_REPORT_CHART_HEIGHT:
            warnings.append(
                {
                    "code": "chart_low_resolution",
                    "chartId": registration.chart_id,
                    "width": width,
                    "height": height,
                    "minimumWidth": MIN_REPORT_CHART_WIDTH,
                    "minimumHeight": MIN_REPORT_CHART_HEIGHT,
                    "message": "图表尺寸偏低，仅作为非阻断质量告警。",
                }
            )
        raw_effective_dpi = width / REPORT_BODY_WIDTH_INCHES
        if raw_effective_dpi < MIN_REPORT_CHART_EFFECTIVE_DPI:
            warnings.append(
                {
                    "code": "chart_low_effective_dpi",
                    "chartId": registration.chart_id,
                    "width": width,
                    "height": height,
                    "effectiveDpi": round(raw_effective_dpi, 1),
                    "minimumDpi": MIN_REPORT_CHART_EFFECTIVE_DPI,
                    "message": "按 A4 正文全宽估算的有效分辨率偏低，仅作为非阻断质量告警。",
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
                **file_identity,
            },
            warnings,
        )

    async def inspect_chart(
        self,
        path: str,
        detail: str = "high",
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        try:
            scope = await self.runtime.scope(run_context)
            self._require_phase_tool(
                scope,
                allowed=frozenset({"analysis"}),
                tool_name="inspect_chart",
                run_context=run_context,
                task_kinds=frozenset({"visualization_section"}),
            )
            if self._active_reporting_task_kind(scope) != "visualization_section":
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "inspect_chart 只允许 visualization_section Task 调用。",
                )
            if detail not in {"high", "original"}:
                raise ReportingError("report_chart_inspection_invalid", "图片 detail 无效。")
            _parameters, contract = self._phase_parameters(scope, "analysis")
            if contract.get("visualInspectionMode", "vision") != "vision":
                raise ReportingError(
                    "report_phase_tool_forbidden",
                    "deterministic 图表检查模式不允许调用 inspect_chart。",
                )
            output_root = self._chart_output_root(contract)
            source_path = self._require_chart_output_path(path, output_root)
            reviewer = self._vision_reviewer
            if reviewer is None:
                raise WorkspaceError("当前 Reporting Agent 未启用图片视觉审查。")
            identity = await self._inspect_chart_file(thread_id=scope.thread_id, path=source_path)
            receipt = ChartVisualInspectionReceipt.model_validate(
                await reviewer.review(scope.thread_id, source_path, detail=detail)
            )
            # 文件在像素检查和模型审查之间发生变化时，两份哈希会不一致。此时任何一份
            # 视觉结论都不能证明当前候选图表，必须失败关闭并要求重新检查。
            if receipt.sha256 != identity["sha256"]:
                raise ReportingError(
                    "report_chart_inspection_changed",
                    "图表在视觉审查期间发生变化，请重新检查最终文件。",
                )
            await self._apply_durable(
                scope,
                name="record_chart_inspection",
                payload={"receipt": receipt.model_dump(mode="json", by_alias=True)},
                command_id=(
                    f"chart-inspection:{identity['sha256']}:"
                    f"{_stable_digest(receipt.model_dump(mode='json', by_alias=True))}"
                ),
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)
        return {
            "ok": True,
            "status": "reviewed",
            "receipt": receipt.model_dump(mode="json", by_alias=True),
        }

    async def submit_visualization_charts(
        self,
        sectionCode: str,
        charts: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """提交当前章节图表草案（允许零图）并结束可视化 Task。"""

        try:
            scope = await self.runtime.scope(run_context)
            self._require_phase_tool(
                scope,
                allowed=frozenset({"analysis"}),
                tool_name="submit_visualization_charts",
                run_context=run_context,
                task_kinds=frozenset({"visualization_section"}),
            )
            _parameters, phase_contract = self._phase_parameters(scope, "analysis")
            contract_section_code = phase_contract.get("sectionCode")
            if not isinstance(contract_section_code, str) or contract_section_code != sectionCode:
                raise ReportingError(
                    "report_visualization_section_invalid",
                    "sectionCode 与当前章节 Task 契约不匹配。",
                )
            await self._ensure_visualization_terminal_settled(scope)
            output_root = self._chart_output_root(phase_contract)
            parsed = tuple(ReportChartRegistration.model_validate(item) for item in charts)
            serialized_charts = [
                registration.model_dump(mode="json", by_alias=True) for registration in parsed
            ]
            for registration in parsed:
                missing_fields = _missing_chinese_display_fields(registration)
                if missing_fields:
                    # 复用既有章节提交错误码，保持工具协议兼容；details 给出可直接修复的
                    # 字段，不把图片 OCR 引入发布门禁，也不改变成功回执结构。
                    raise ReportingError(
                        "report_visualization_section_invalid",
                        "图表用户可见标题和图注必须使用简体中文。",
                        details={
                            "chartId": registration.chart_id,
                            "missingFields": missing_fields,
                            "requiredActions": [
                                "仅修改 title 和 altText 的展示文字为简体中文后重新提交；"
                                "坐标轴、图例和注释应在绘图脚本中同步本地化。"
                            ],
                        },
                    )
            warnings = []
            for registration in parsed:
                if registration.comparability != "reference_only":
                    continue
                missing_fields = [
                    field_name
                    for field_name, value in (
                        ("title", registration.title),
                        ("altText", registration.alt_text),
                    )
                    if "参考" not in value
                ]
                if missing_fields:
                    warnings.append(
                        {
                            "code": "report_reference_only_marker_missing",
                            "message": "reference_only 图表标题或图注缺少“参考”标记。",
                            "details": {
                                "chartId": registration.chart_id,
                                "missingFields": missing_fields,
                            },
                        }
                    )
            durable = await self._durable_state(scope)
            durable_payload = getattr(durable, "payload", {})
            visualization_sections = (
                durable_payload.get("visualizationSections", {})
                if isinstance(durable_payload, dict)
                else {}
            )
            existing = (
                visualization_sections.get(sectionCode)
                if isinstance(visualization_sections, dict)
                else None
            )
            if isinstance(existing, dict) and existing.get("charts") != serialized_charts:
                raise ReportingError(
                    "report_visualization_section_conflict",
                    "当前章节已提交不同的图表事实。",
                )
            inspected: list[dict[str, Any]] = []
            files: list[dict[str, Any]] = []
            for registration in parsed:
                source_path = self._require_chart_output_path(registration.source_path, output_root)
                identity = await self._inspect_chart_file(
                    thread_id=scope.thread_id,
                    path=source_path,
                )
                inspected.append(registration.model_dump(mode="json", by_alias=True))
                files.append(
                    FileIdentity(
                        path=identity["sourcePath"],
                        size=identity["size"],
                        sha256=identity["sha256"],
                    ).model_dump(mode="json", by_alias=True)
                )
            if isinstance(existing, dict):
                if existing.get("files") != files:
                    raise ReportingError(
                        "report_visualization_section_conflict",
                        "当前章节图表文件身份与已提交事实不一致。",
                    )
                status = "already_committed"
            else:
                digest = _stable_digest({"charts": inspected, "files": files})
                durable_result = await self._apply_durable_command(
                    scope,
                    name="submit_visualization_charts",
                    payload={"sectionCode": sectionCode, "charts": list(inspected), "files": files},
                    command_id=f"viz-section:{durable.revision}:{sectionCode}:{digest}",
                )
                status = "already_committed" if durable_result.idempotent else "committed"
            self._complete_phase_plan(self._session_state(run_context))
            finish_result = await self.runtime.finish_task(
                f"图表章节 {sectionCode} 已提交 {len(inspected)} 张图表。",
                [file["path"] for file in files],
                None,
                [],
                run_context,
                self._finish_function,
                _scope=scope,
            )
            if finish_result.get("status") != "accepted":
                return finish_result
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)
        return {
            "ok": True,
            "status": status,
            "sectionCode": sectionCode,
            "chartCount": len(inspected),
            "taskFinished": True,
            "warnings": warnings,
        }


__all__ = ["RuntimeVisualizationMixin"]
