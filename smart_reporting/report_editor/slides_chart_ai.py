"""PPTX 已登记数据图表的候选预览与图片替换边界。

对象只按嵌入图片字节身份关联 manifest/trace，绝不按名称猜测。绘图仍由
ChartAIEditService 执行，其冻结事实、L1/L2、Matplotlib 和侧车登记规则不变。
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from ..reporting.delivery.office_engine import run_bridge, run_office_engine
from ..reporting.models import ReportingError
from .chart_ai import ChartAIEditRequest, _chart_artifact_for_trace
from .chart_edits import ChartEditRecord, load_chart_edit_records
from .service import ReportEditorContext, ReportEditorSession


def _run_picture_bridge(content: bytes, replacements: list[dict[str, Any]] | None = None) -> Any:
    with tempfile.TemporaryDirectory(prefix="report-slides-chart-") as directory:
        root = Path(directory)
        source, output, request_path = (
            root / "source.pptx",
            root / "output.pptx",
            root / "request.json",
        )
        source.write_bytes(content)
        request: dict[str, Any] = {
            "action": "inspect" if replacements is None else "replace",
            "input": str(source),
        }
        if replacements is not None:
            request.update(
                output=str(output),
                replacements=[
                    {
                        **{
                            key: item[key]
                            for key in (
                                "slideIndex",
                                "elementId",
                                "slidePath",
                                "shapeId",
                                "expectedSha256",
                                "expectedSize",
                                "extension",
                            )
                            if key in item
                        },
                        "bytesBase64": base64.b64encode(item["bytes"]).decode("ascii"),
                    }
                    for item in replacements
                ],
            )
        request_path.write_text(json.dumps(request), encoding="utf-8")
        result = run_bridge("slides", "replace-picture", request_path)
        if result.returncode:
            raise ReportingError(
                "report_slides_chart_bridge_failed", "图表图片替换失败，原 PPTX 保持不变。"
            )
        if replacements is not None:
            return output.read_bytes()
        return json.loads(result.stdout)["pictures"]


def inspect_pptx_pictures(content: bytes) -> list[dict[str, Any]]:
    return _run_picture_bridge(content)


def replace_pptx_pictures(content: bytes, replacements: list[dict[str, Any]]) -> bytes:
    if not replacements:
        return content
    return _run_picture_bridge(content, replacements)


@dataclass
class _ChartCandidate:
    context_sha256: str
    source: ReportEditorContext
    chart_id: str
    picture: dict[str, Any]
    base_image_path: str
    base_image_sha256: str
    created_at: datetime


class ReportSlidesChartAIService:
    def __init__(self, slides: Any, *, chart_ai: Any) -> None:
        self.slides = slides
        self.chart_ai = chart_ai
        self.editor = chart_ai.editor
        self._candidates: dict[str, _ChartCandidate] = {}

    async def _registered_charts(
        self, context: ReportEditorContext
    ) -> tuple[ReportEditorContext, list[Any]]:
        source = await self.editor._source_context(context)
        manifest, index = await self.editor.trace.load_manifest_and_index(source)
        charts = []
        if manifest is not None and index is not None:
            for trace in index.chart_traces:
                chart = _chart_artifact_for_trace(manifest, index, trace)
                if chart is not None and chart.media_type in {"image/png", "image/jpeg"}:
                    # 发布清单会重编号；图片身份核验后，改图操作仍使用冻结 trace 的编号。
                    charts.append(chart.model_copy(update={"chart_id": trace.chart_id}))
        return source, charts

    async def _frozen_source(
        self,
        context: ReportEditorContext,
        *,
        revision: int | None = None,
        digest: str | None = None,
    ) -> ReportEditorContext:
        durable = await self.slides.state_repository.get(context.workflow_run_id)
        contexts = durable.payload.get("reportEditorContexts", {}) if durable else {}
        for raw in contexts.values():
            source = ReportEditorContext.model_validate(raw)
            if (
                source.report_id != context.report_id
                or source.workflow_run_id != context.workflow_run_id
                or source.scope != context.scope
                or source.markdown_path != context.markdown_path
            ):
                continue
            if revision is not None:
                if source.revision == revision and source.digest() == digest:
                    return await self.editor._source_context(source)
            elif source.artifact_manifest == context.artifact_manifest:
                try:
                    restored = await self.editor._source_context(source)
                    await self.editor.trace.load_manifest_and_index(restored)
                    return restored
                except ReportingError:
                    continue
        raise ReportingError("report_slides_chart_source_missing", "图表冻结来源上下文无法核验。")

    async def _bindings(
        self, session: ReportEditorSession
    ) -> tuple[ReportEditorContext, ReportEditorContext, list[dict[str, Any]]]:
        context = await self.slides.context_for_session(session)
        content = await self.slides._read_verified_pptx(context)
        pictures = await run_office_engine(inspect_pptx_pictures, content)
        try:
            source = await self._frozen_source(context)
            source, charts = await self._registered_charts(source)
        except ReportingError as error:
            logger.warning(
                "report_slides_chart_source_unavailable report_id={} code={}",
                context.report_id,
                error.code,
            )
            source, charts = context, []
        result = []
        accepted = context.job.get("pptxChartEdits", [])
        accepted = accepted if isinstance(accepted, list) else []
        for picture in pictures:
            saved = [
                item
                for item in accepted
                if isinstance(item, dict)
                and (item.get("slidePath"), item.get("shapeId"))
                == (picture["slidePath"], picture["shapeId"])
            ]
            if saved:
                try:
                    if len(saved) != 1:
                        raise ValueError("duplicate_chart_binding")
                    item = saved[0]
                    registered_source = await self._frozen_source(
                        context, revision=item["sourceRevision"], digest=item["sourceContextSha256"]
                    )
                    _, registered_charts = await self._registered_charts(registered_source)
                    record = ChartEditRecord.model_validate(item["record"])
                    if (
                        record.edit_id != item["editId"]
                        or record.chart_id != item["chartId"]
                        or record.image.as_identity() != item["image"]
                        or [ref.as_identity() for ref in record.plot_data_files]
                        != item["plotDataFiles"]
                    ):
                        raise ValueError("saved_chart_binding_changed")
                    if not any(chart.chart_id == record.chart_id for chart in registered_charts):
                        raise ValueError("saved_chart_unregistered")
                    candidate = _ChartCandidate(
                        context.digest(),
                        registered_source,
                        record.chart_id,
                        picture,
                        record.base_image_path,
                        record.base_image_sha256,
                        datetime.now(UTC),
                    )
                    registered, _, _ = await self._record_image(candidate, record.edit_id)
                    if registered != record or (record.image.size, record.image.sha256) != (
                        picture["size"],
                        picture["sha256"],
                    ):
                        raise ValueError("saved_chart_image_changed")
                    result.append(
                        {
                            **picture,
                            "chartId": record.chart_id,
                            "baseImagePath": record.image.path,
                            "previousEditId": record.edit_id,
                            "_source": registered_source,
                        }
                    )
                except (ReportingError, ValueError, KeyError, TypeError) as error:
                    logger.warning(
                        "report_slides_chart_binding_unavailable report_id={} error_type={}",
                        context.report_id,
                        type(error).__name__,
                    )
                continue
            matches = [
                chart
                for chart in charts
                if (chart.size, chart.sha256) == (picture["size"], picture["sha256"])
            ]
            if len(matches) == 1:
                chart = matches[0]
                result.append(
                    {
                        **picture,
                        "chartId": chart.chart_id,
                        "baseImagePath": chart.path,
                        "_source": source,
                    }
                )
        return context, source, result

    async def list_charts(self, session: ReportEditorSession) -> dict[str, Any]:
        _, _, bindings = await self._bindings(session)
        # PPTX 专用会话先经 context_for_session 的能力与身份校验，再委托完整编辑权限。
        delegate = replace(session, capabilities=None)
        charts = []
        for binding in bindings:
            source = binding["_source"]
            availability = await self.chart_ai.availability(source, delegate, binding["chartId"])
            charts.append(
                {
                    **availability,
                    **{key: value for key, value in binding.items() if key != "_source"},
                }
            )
        return {"charts": charts}

    async def start_edit(
        self, session: ReportEditorSession, slide_index: int, element_id: str, instruction: str
    ) -> dict[str, Any]:
        context, source, bindings = await self._bindings(session)
        if not isinstance(instruction, str) or not instruction.strip():
            raise ReportingError("report_slides_chart_instruction_required", "请输入图表调整要求。")
        if len(instruction) > 2000:
            raise ReportingError(
                "report_slides_chart_instruction_too_large", "图表调整要求过长，请缩短后重试。"
            )
        if isinstance(slide_index, bool) or not isinstance(slide_index, int):
            raise ReportingError("report_slides_chart_target_invalid", "图表对象无效。")
        binding = next(
            (
                item
                for item in bindings
                if item["slideIndex"] == slide_index and item["elementId"] == element_id
            ),
            None,
        )
        if binding is None:
            raise ReportingError(
                "report_slides_chart_unregistered", "该图片没有唯一的已登记图表来源，原图保持不变。"
            )
        source = binding["_source"]
        request = ChartAIEditRequest(
            instruction=instruction.strip(),
            baseImagePath=binding["baseImagePath"],
            expectedSha256=binding["sha256"],
            previousEditId=binding.get("previousEditId"),
        )
        started = await self.chart_ai.start_edit(
            source, replace(session, capabilities=None), binding["chartId"], request
        )
        cutoff = datetime.now(UTC) - timedelta(hours=1)
        self._candidates = {
            key: value for key, value in self._candidates.items() if value.created_at >= cutoff
        }
        self._candidates[started["editId"]] = _ChartCandidate(
            context.digest(),
            source,
            binding["chartId"],
            binding,
            binding["baseImagePath"],
            binding["sha256"],
            datetime.now(UTC),
        )
        return {**started, "candidateId": started["editId"]}

    async def _candidate(
        self, session: ReportEditorSession, candidate_id: str
    ) -> tuple[ReportEditorContext, _ChartCandidate]:
        context = await self.slides.context_for_session(session)
        candidate = self._candidates.get(candidate_id)
        if (
            candidate is None
            or candidate.created_at < datetime.now(UTC) - timedelta(hours=1)
            or not secrets.compare_digest(candidate.context_sha256, context.digest())
        ):
            raise ReportingError(
                "report_slides_chart_candidate_missing", "图表候选已失效，请重新生成。"
            )
        return context, candidate

    async def _record_image(
        self, candidate: _ChartCandidate, edit_id: str
    ) -> tuple[ChartEditRecord, bytes, str]:
        records = await load_chart_edit_records(
            self.editor.workspace,
            candidate.source.scope["threadId"],
            candidate.source.markdown_path,
        )
        record = next((item for item in records if item.edit_id == edit_id), None)
        if (
            record is None
            or record.chart_id != candidate.chart_id
            or record.base_image_path != candidate.base_image_path
            or record.base_image_sha256 != candidate.base_image_sha256
            or record.user_id != candidate.source.scope["userId"]
        ):
            raise ReportingError(
                "report_slides_chart_candidate_changed", "图表候选登记身份不一致。"
            )
        if len(record.pages) > 1:
            raise ReportingError(
                "report_slides_chart_candidate_multipage", "候选含多页图表，请生成单张图表后采纳。"
            )
        for ref in (record.image, record.script, *record.plot_data_files):
            identity = await self.editor.workspace.ahash_file(
                candidate.source.scope["threadId"], ref.path
            )
            if (
                identity.get("missing")
                or identity.get("size") != ref.size
                or identity.get("sha256") != ref.sha256
            ):
                raise ReportingError(
                    "report_slides_chart_candidate_changed",
                    "图表候选或作图数据身份已变化，原图保持不变。",
                )
        content, media_type = await self.editor.workspace.afile_bytes(
            candidate.source.scope["threadId"], record.image.path
        )
        if (
            len(content) != record.image.size
            or hashlib.sha256(content).hexdigest() != record.image.sha256
            or media_type not in {"image/png", "image/jpeg"}
        ):
            raise ReportingError("report_slides_chart_candidate_changed", "候选静态图身份已变化。")
        return record, content, media_type

    async def edit_status(
        self, session: ReportEditorSession, candidate_id: str, *, wait_ms: int = 0
    ) -> dict[str, Any]:
        _, candidate = await self._candidate(session, candidate_id)
        status = await self.chart_ai.wait_edit_status(
            candidate.source, candidate.chart_id, candidate_id, wait_ms=wait_ms
        )
        result = {
            **status,
            "candidateId": candidate_id,
            "slideIndex": candidate.picture["slideIndex"],
            "elementId": candidate.picture["elementId"],
            "accepted": False,
        }
        if status["status"] == "succeeded":
            record, content, media_type = await self._record_image(candidate, candidate_id)
            result.update(
                imagePath=record.image.path,
                previewDataUrl=f"data:{media_type};base64,{base64.b64encode(content).decode('ascii')}",
            )
        return result

    async def cancel_edit(self, session: ReportEditorSession, candidate_id: str) -> dict[str, Any]:
        _, candidate = await self._candidate(session, candidate_id)
        return self.chart_ai.cancel_edit(candidate.source, candidate.chart_id, candidate_id)

    async def resolve_for_session(
        self, session: ReportEditorSession, edits: Any
    ) -> list[dict[str, Any]]:
        if (
            not isinstance(edits, list)
            or len(edits) > 50
            or any(
                not isinstance(item, dict)
                or set(item) != {"candidateId"}
                or not isinstance(item["candidateId"], str)
                for item in edits
            )
        ):
            raise ReportingError("report_slides_chart_edit_invalid", "图表候选列表无效。")
        _, _, bindings = await self._bindings(session)
        result, used = [], set()
        for edit in edits:
            candidate_id = edit["candidateId"]
            _, candidate = await self._candidate(session, candidate_id)
            picture = candidate.picture
            key = (picture["slidePath"], picture["shapeId"])
            binding = next(
                (
                    item
                    for item in bindings
                    if (item["slidePath"], item["shapeId"]) == key
                    and item["chartId"] == candidate.chart_id
                    and item["sha256"] == candidate.base_image_sha256
                ),
                None,
            )
            status = self.chart_ai.edit_status(candidate.source, candidate.chart_id, candidate_id)
            if key in used or binding is None or status["status"] != "succeeded":
                raise ReportingError(
                    "report_slides_chart_candidate_invalid", "图表候选不可采纳，原图保持不变。"
                )
            record, content, media_type = await self._record_image(candidate, candidate_id)
            used.add(key)
            result.append(
                {
                    **{
                        key: picture[key]
                        for key in ("slideIndex", "elementId", "slidePath", "shapeId")
                    },
                    "candidateId": candidate_id,
                    "expectedSha256": picture["sha256"],
                    "expectedSize": picture["size"],
                    "bytes": content,
                    "extension": "png" if media_type == "image/png" else "jpg",
                    "binding": {
                        "chartId": candidate.chart_id,
                        "editId": candidate_id,
                        "sourceRevision": candidate.source.revision,
                        "sourceContextSha256": candidate.source.digest(),
                        "image": record.image.as_identity(),
                        "plotDataFiles": [ref.as_identity() for ref in record.plot_data_files],
                        "record": record.model_dump(mode="json", by_alias=True),
                    },
                }
            )
        return result

    async def discard_candidates(
        self, session: ReportEditorSession, candidate_ids: list[str]
    ) -> None:
        for candidate_id in candidate_ids:
            await self._candidate(session, candidate_id)
        for candidate_id in candidate_ids:
            self._candidates.pop(candidate_id, None)
