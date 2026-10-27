"""报告编辑器 AI 改图：登记侧车、可用性、任务生命周期与 asset 放行。

导出登记（改图进入新 revision 的 manifest 与追溯索引）及其非阻断故障注入
在 ``test_report_editor_lineage_export.py`` 中覆盖。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from smart_reporting.report_editor import (
    ReportEditorGrantService,
)
from smart_reporting.report_editor.chart_ai import (
    CHART_AI_STAGES,
    ChartAIEditRequest,
    ChartAIEditService,
    ChartEditPlan,
    ChartTemplateApplyRequest,
    chart_edit_image_src,
)
from smart_reporting.report_editor.chart_edits import (
    CHART_EDITS_REGISTRY_VERSION,
    ChartEditSkipped,
    _encode_registry_payload,
    chart_edits_registry_path,
    load_chart_edit_records,
    parse_chart_edit_records,
)
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile, ChartArtifact
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject
from smart_reporting.reporting.trace.contracts_v1 import (
    ChartTraceV1,
    FactRefV1,
    TraceFileRefV1,
    derive_resource_id,
)
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from smart_reporting.reporting.workflow.checkpoint import (
    ChartVisualInspectionIssue,
    ChartVisualInspectionReceipt,
)
from smart_reporting.reporting.workflow.state import ReportingCommand, ReportingRunState, apply

_SCRIPT_MARKER = "# chart-edit generated script\nPLOT = 'chart-001.chart-input.json'\n"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _png_bytes() -> bytes:
    # 非纯色：确定性检查会把空白图判定为 report_chart_blank。
    image = Image.new("RGB", (64, 48), (30, 64, 175))
    for x in range(64):
        for y in range(48):
            if (x // 8 + y // 8) % 2 == 0:
                image.putpixel((x, y), (240, 244, 250))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def _make_editor_with_chart(tmp_path: Path, *, template_ready: bool = False):
    """带登记图表（chart_001 + chart-input）的编辑器 fixture，结构对齐导出用例。"""

    editor, grants, original = await _make_editor_with_subject(tmp_path)
    thread_id = original.scope["threadId"]
    workspace = editor.workspace
    index = await editor.trace.load_index(original)
    assert index is not None
    chart_path = "reports/revision-1/chart-001.png"
    chart_bytes = _png_bytes()
    chart = ChartArtifact(
        path=chart_path,
        mediaType="image/png",
        size=len(chart_bytes),
        sha256=_sha(chart_bytes),
        chartId="chart_001",
        datasetIds=("dataset-url-abc0001",),
    )
    await workspace.awrite_bytes(thread_id, chart_path, chart_bytes)
    plot_path = "reports/revision-1/chart-001.chart-input.json"
    plot_bytes = (
        b'{"schema":"chart-input/v1","chartId":"chart_001","role":"measure",'
        b'"source":{"analysisId":"analysis_001","path":"reports/revision-1/x.json",'
        b'"dataPath":"/metrics/0"},'
        b'"columns":["period","revenue"],"rows":[["2025-09",3600]],"rowCount":1}'
    )
    await workspace.awrite_bytes(thread_id, plot_path, plot_bytes)
    header = (
        '# Revenue report\n\n<a id="report-section-section_002"></a>\n'
        "## 1 Report\n\n[[section:section_002]]\n[[analysis:analysis_001]]\n\n"
    )
    footer = "\n\n![Revenue](chart-001.png) [[citation:citation_001]]\n"
    markdown = header + "Revenue 3600 [[claim:claim-1]]" + footer
    markdown_file = ArtifactFile(
        path=original.markdown_path,
        mediaType="text/markdown",
        size=len(markdown.encode()),
        sha256=_sha(markdown.encode()),
    )
    await workspace.awrite_text(thread_id, original.markdown_path, markdown, overwrite=True)
    files = tuple(
        item.model_copy(update={"size": markdown_file.size, "sha256": markdown_file.sha256})
        if item.resource_id == index.markdown_file_resource_id
        else item
        for item in index.files
    )
    fact_entry = next(
        entry
        for entry in index.fact_files
        if entry.analysis_id == "analysis_001" and entry.content_kind == "deterministic_bundle"
    )
    fact_file = next(item for item in index.files if item.resource_id == fact_entry.file_resource_id)
    fact_payload = json.loads(await workspace.aread_text(thread_id, fact_file.path))
    metric_index, metric = next(
        (position, item)
        for position, item in enumerate(fact_payload["metrics"])
        if item.get("periodValues")
    )
    if template_ready:
        metric["periodValues"] = [
            {"period": "2025-07", "value": 1200.0},
            {"period": "2025-08", "value": 1500.0},
            {"period": "2025-09", "value": 1800.0},
        ]
        metric["total"] = 4500.0
        fact_bytes = json.dumps(
            fact_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        await workspace.awrite_bytes(thread_id, fact_file.path, fact_bytes, overwrite=True)
        fact_file = fact_file.model_copy(
            update={"size": len(fact_bytes), "sha256": _sha(fact_bytes)}
        )
        files = tuple(
            fact_file if item.resource_id == fact_file.resource_id else item for item in files
        )
    chart_fact_refs = (
        FactRefV1(
            analysisId="analysis_001",
            fileResourceId=fact_file.resource_id,
            jsonPointer=f"/metrics/{metric_index}",
            factKind="metric",
            factKey=metric["factId"],
        ),
    )
    index = index.model_copy(
        update={
            "files": (
                *files,
                TraceFileRefV1(
                    resourceId=derive_resource_id(chart_path),
                    path=chart_path,
                    mediaType="image/png",
                    size=chart.size,
                    sha256=chart.sha256,
                ),
                TraceFileRefV1(
                    resourceId=derive_resource_id(plot_path),
                    path=plot_path,
                    mediaType="application/json",
                    size=len(plot_bytes),
                    sha256=_sha(plot_bytes),
                ),
            ),
            "chart_traces": (
                ChartTraceV1(
                    chartId="chart_001",
                    imageFileResourceId=derive_resource_id(chart_path),
                    plotDataFileResourceIds=(derive_resource_id(plot_path),),
                    datasetIds=chart.dataset_ids,
                    factRefs=chart_fact_refs,
                ),
            ),
        }
    )
    await workspace.awrite_bytes(
        thread_id,
        "reports/revision-1/trace-index-v1.json",
        encode_trace_index(index),
        overwrite=True,
    )
    await workspace.adelete_file(thread_id, original.artifact_manifest.path)
    manifest_identity = await register_trace_manifest(workspace, thread_id, index)
    original = original.model_copy(update={"artifact_manifest": manifest_identity})
    manifest = await editor.trace.load_manifest(original)
    assert manifest is not None
    manifest = manifest.model_copy(update={"charts": (chart,)})
    manifest_bytes = manifest.model_dump_json(by_alias=True).encode()
    await workspace.awrite_bytes(thread_id, manifest_identity.path, manifest_bytes, overwrite=True)
    manifest_identity = manifest_identity.model_copy(
        update={"size": len(manifest_bytes), "sha256": _sha(manifest_bytes)}
    )
    job = {
        **original.job,
        "render": {
            "markdown": {
                "path": original.markdown_path,
                "size": markdown_file.size,
                "sha256": markdown_file.sha256,
            },
            "images": [{"path": chart_path, "size": chart.size, "sha256": chart.sha256}],
        },
    }
    context = original.model_copy(update={"job": job, "artifact_manifest": manifest_identity})
    durable = ReportingRunState.initial(
        report_run_id=context.workflow_run_id,
        external_run_id="external-1",
        thread_id="caller-thread",
        owner_user_id="user-1",
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}},
    )
    editor.state_repository = _StateRepository(durable)
    return SimpleNamespace(
        editor=editor,
        grants=grants,
        context=context,
        workspace=workspace,
        thread_id=thread_id,
        chart=chart,
        chart_bytes=chart_bytes,
        chart_path=chart_path,
        plot_path=plot_path,
        plot_bytes=plot_bytes,
        markdown=markdown,
    )


class _StateRepository:
    def __init__(self, durable: ReportingRunState) -> None:
        self.durable = durable

    async def get(self, _run_id: str):
        return self.durable

    async def apply(self, _run_id: str, command: ReportingCommand, *, expected_version: int):
        self.durable = apply(self.durable, command, expected_version=expected_version).state


class FakeRunner:
    """按任务边界写出脚本与新图的 runner 替身；vision_reviewer 必须非空。"""

    vision_reviewer = object()

    def __init__(
        self,
        png: bytes,
        *,
        gate: asyncio.Event | None = None,
        receipts: tuple[ChartVisualInspectionReceipt, ...] | None = None,
    ) -> None:
        self.png = png
        self.gate = gate
        self.receipts = receipts
        self.calls: list[tuple[object, dict, object]] = []

    async def run(self, task_context, workspace, task_facts, *, run_context, diagnostic=None):
        self.calls.append((task_context, dict(task_facts), diagnostic))
        if self.gate is not None:
            await asyncio.wait_for(self.gate.wait(), timeout=5)
        # 修复轮脚本与产物已存在，真实 write_script 支持覆盖；替身同样覆盖写。
        await workspace.awrite_bytes(
            task_context.workspace_key,
            task_context.script_path,
            _SCRIPT_MARKER.encode(),
            overwrite=True,
        )
        output = task_context.declared_output_paths[0]
        await workspace.awrite_bytes(task_context.workspace_key, output, self.png, overwrite=True)
        if self.receipts is None:
            receipt = ChartVisualInspectionReceipt(
                sourcePath=output,
                sha256=_sha(self.png),
                reviewed=True,
                requiresRevision=False,
                modelId="fake-vision-model",
            )
            receipts = (receipt,)
        else:
            receipts = self.receipts
        return SimpleNamespace(
            script_file={"path": task_context.script_path},
            execution_receipt=SimpleNamespace(output_files=()),
            visual_inspection_receipts=receipts,
            visual_repair_diagnostic=None,
        )


def _planner(
    level=("L1",),
    *,
    title="收入（横向）",
    alt_text="收入按期间横向对比",
    visual_form="横向条形图",
    skipped=(),
    data_bindings=(),
):
    async def plan(_request):
        return ChartEditPlan(
            level=level,
            title=title,
            altText=alt_text,
            visualForm=visual_form,
            drawInstruction="把柱状图改成横向条形图并按数值降序",
            dataBindings=data_bindings,
            skipped=skipped,
        )

    return plan


def _service(
    fixture: SimpleNamespace, runner: FakeRunner, planner=None, **kwargs
) -> ChartAIEditService:
    return ChartAIEditService(
        editor=fixture.editor,
        workspace_registry=fixture.editor.workspace_registry,
        planner=planner or _planner(),
        runner=runner,
        timeout_seconds=kwargs.pop("timeout_seconds", 15),
        **kwargs,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_template_runs_end_to_end_with_registered_fact_identity(
    tmp_path: Path,
) -> None:
    fixture = await _make_editor_with_chart(tmp_path, template_ready=True)
    runner = FakeRunner(fixture.chart_bytes)
    service = _service(fixture, runner)
    session = SimpleNamespace(capabilities=None)

    catalog = await service.templates(fixture.context, session, "chart_001")
    selected = next((item for item in catalog["templates"] if item["available"]), None)
    assert selected is not None, catalog
    started = await service.start_template(
        fixture.context,
        session,
        "chart_001",
        ChartTemplateApplyRequest(
            templateId=selected["templateId"],
            instruction="保持模板布局并标出数据标签",
            expectedSha256=fixture.chart.sha256,
        ),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == "succeeded", status
    records = await load_chart_edit_records(
        fixture.workspace, fixture.thread_id, fixture.context.markdown_path
    )
    record = records[-1]
    assert record.data_origin == "template"
    payload = await fixture.workspace.aread_text(
        fixture.thread_id, record.plot_data_files[0].path
    )
    source = json.loads(payload)["source"]
    assert source["factFilePath"] == source["path"]
    assert source["factFileSha256"]
    assert record.data_bindings
    index = await fixture.editor.trace.load_index(fixture.context)
    assert index is not None
    trace = next(item for item in index.chart_traces if item.chart_id == "chart_001")
    await fixture.editor._verify_chart_edit_plot_data(
        fixture.thread_id,
        record=record,
        trace=trace,
        index=index,
        data_origin="template",
    )
    tampered = record.model_copy(
        update={"data_bindings": ({**record.data_bindings[0], "dataPath": "/metrics/999"},)}
    )
    with pytest.raises(ReportingError, match="数据绑定"):
        await fixture.editor._verify_chart_edit_plot_data(
            fixture.thread_id,
            record=tampered,
            trace=trace,
            index=index,
            data_origin="template",
        )
    await service.aclose()


async def _await_edit(service: ChartAIEditService, context, chart_id: str, edit_id: str) -> dict:
    for _ in range(400):
        status = service.edit_status(context, chart_id, edit_id)
        if status["status"] in {"succeeded", "failed", "cancelled"}:
            return status
        await asyncio.sleep(0.02)
    raise AssertionError("改图任务未在预期时间内结束")


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_edit_history_and_visual_form_surface_in_sources(tmp_path: Path) -> None:
    """P3：改图后来源面板能看到历史与当前图形形态，供快捷指令按图形推荐。"""
    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes)
    service = _service(fixture, runner)
    session = SimpleNamespace(capabilities=None)

    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="改成横向条形图", baseTitle="收入", baseAltText="收入对比"),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == "succeeded"

    charts = await fixture.editor.trace.charts(fixture.context)
    chart = next(item for item in charts["charts"] if item["chartId"] == "chart_001")
    assert chart["editCount"] == 1
    assert chart["visualForm"] == "横向条形图"

    detail = await fixture.editor.trace.chart_source(fixture.context, "chart_001")
    assert [item["editId"] for item in detail["editHistory"]] == [started["editId"]]
    assert detail["editHistory"][0]["level"] == ["L1"]
    assert detail["editHistory"][0]["instruction"].startswith("改成横向条形图")

    # 无改图的图表面板不出现历史噪音。
    empty = await fixture.editor.trace._chart_edit_summaries(fixture.context)
    assert empty["chart_001"]["editCount"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_edit_happy_path_registers_record_and_serves_asset(tmp_path: Path) -> None:
    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes)
    service = _service(fixture, runner)
    session = SimpleNamespace(capabilities=None)

    availability = await service.availability(fixture.context, session, "chart_001")
    assert availability["available"] is True

    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(
            instruction="改成横向条形图并按金额降序",
            baseImagePath=fixture.chart_path,
            baseTitle="收入",
            baseAltText="收入对比",
            expectedSha256=_sha(fixture.chart_bytes),
        ),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == "succeeded"
    assert status["level"] == ["L1"]
    assert status["changes"]["plotDataUnchanged"] is True
    assert status["warnings"] == []

    records = await load_chart_edit_records(
        fixture.workspace, fixture.thread_id, fixture.context.markdown_path
    )
    assert [record.edit_id for record in records] == [started["editId"]]
    record = records[0]
    assert record.chart_id == "chart_001"
    assert record.base_image_path == fixture.chart_path
    assert record.image.path == f"reports/revision-1/chart-edits/{record.edit_id}/chart.png"
    assert record.script.path == f"reports/revision-1/chart-edits/{record.edit_id}/chart_edit.py"
    assert [item.path for item in record.plot_data_files] == [fixture.plot_path]
    assert record.chart.title == "收入（横向）"
    assert (
        chart_edit_image_src(fixture.context.markdown_path, record.edit_id)
        == f"chart-edits/{record.edit_id}/chart.png"
    )

    task_context, task_facts, diagnostic = runner.calls[0]
    assert diagnostic is None
    assert task_context.task_kind == "visualization"
    assert task_context.declared_output_paths == (record.image.path,)
    assert set(task_context.authorized_read_paths) == {
        fixture.plot_path,
        fixture.chart_path,
    }
    assert task_facts["visualizationMode"] == "static"
    assert task_facts["chartEdit"]["level"] == ["L1"]
    assert task_facts["chartInputs"][0]["columns"] == ["period", "revenue"]

    # 改图图片经登记身份放行；脚本与未登记路径不通过 asset 接口放行。
    content, media_type = await fixture.editor.read_asset(fixture.context, record.image.path)
    assert media_type == "image/png" and content == fixture.chart_bytes
    with pytest.raises(ReportingError, match="report_editor_asset_missing"):
        await fixture.editor.read_asset(fixture.context, record.script.path)
    with pytest.raises(ReportingError, match="report_editor_asset_missing"):
        await fixture.editor.read_asset(fixture.context, "reports/revision-1/chart-edits/other.png")

    # 底图被替换后（expectedSha256 与登记身份不一致）任务失败并返回原因。
    rejected = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(
            instruction="再改一次",
            baseImagePath=fixture.chart_path,
            expectedSha256="0" * 64,
        ),
    )
    rejected_status = await _await_edit(service, fixture.context, "chart_001", rejected["editId"])
    assert rejected_status["status"] == "failed"
    assert rejected_status["error"]["code"] == "report_editor_chart_ai_base_changed"
    # 失败的改图不产生登记记录。
    records_after = await load_chart_edit_records(
        fixture.workspace, fixture.thread_id, fixture.context.markdown_path
    )
    assert [record.edit_id for record in records_after] == [started["editId"]]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_edit_l3_requirements_are_skipped_with_reasons(tmp_path: Path) -> None:
    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes)
    skipped = (
        ChartEditSkipped(request="加入明年预测", reason="预测数据未登记，不作估算。"),
        ChartEditSkipped(
            request="按科室拆分", reason="该维度未拆分，可在重新生成报告时增加此分析。"
        ),
    )
    service = _service(fixture, runner, planner=_planner(level=(), skipped=skipped))
    session = SimpleNamespace(capabilities=None)

    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="加预测并按科室拆分"),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])

    assert status["status"] == "failed"
    assert status["error"]["code"] == "report_editor_chart_ai_skipped"
    assert {item["reason"] for item in status["error"]["skipped"]} == {
        item.reason for item in skipped
    }
    # 未产出任何改图登记，runner 未执行。
    assert runner.calls == []
    records = await load_chart_edit_records(
        fixture.workspace, fixture.thread_id, fixture.context.markdown_path
    )
    assert records == ()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_edit_l2_not_supported_is_reported_as_skip(tmp_path: Path) -> None:
    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes)
    # plan 仍给出 L1 可执行部分（换标题），L2 部分由服务端补跳过说明。
    service = _service(fixture, runner, planner=_planner(level=("L1", "L2")))
    session = SimpleNamespace(capabilities=None)

    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="换成按收入类型的维度"),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])

    assert status["status"] == "succeeded"
    assert status["level"] == ["L1"]
    assert len(status["skipped"]) == 1
    assert "换绑数据未使用" in status["skipped"][0]["reason"]
    # L1 仍执行：作图数据不变。
    task_context, task_facts, _ = runner.calls[0]
    assert [item["path"] for item in task_facts["chartInputs"]] == [fixture.plot_path]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_edit_l2_rebinds_registered_data_and_reports_change(tmp_path: Path) -> None:
    """L2 成功路径：planner 选中签发目录中的同分析绑定，物化新作图数据并如实登记。"""
    from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding

    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes)
    binding = ChartDataBinding(
        analysisId="analysis_001",
        factPath="报表/智能分析/report-1/facts/revision-1/analysis_001.json",
        dataPath="metrics[0].periodValues",
        fields=("period", "value"),
        role="main",
    )
    service = _service(
        fixture,
        runner,
        planner=_planner(level=("L2",), data_bindings=(binding,)),
    )
    session = SimpleNamespace(capabilities=None)

    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="换成按期间的月度趋势"),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == "succeeded", status
    assert status["level"] == ["L2"]
    assert status["skipped"] == []
    assert status["changes"]["plotDataUnchanged"] is False
    assert status["changes"]["dataBindingsAdded"][0]["dataPath"] == "metrics[0].periodValues"

    records = await load_chart_edit_records(
        fixture.workspace, fixture.thread_id, fixture.context.markdown_path
    )
    record = records[0]
    assert record.level == ("L2",)
    assert record.data_origin == "rebound"
    assert record.chart.dataset_ids == ("dataset-url-abc0001",)
    new_plot = record.plot_data_files[0]
    assert new_plot.path != fixture.plot_path
    stored, _ = await fixture.workspace.afile_bytes(fixture.thread_id, new_plot.path)
    import json as _json

    payload = _json.loads(stored)
    assert payload["schema"] == "chart-input/v1"
    assert payload["source"]["dataPath"] == "metrics[0].periodValues"
    assert payload["rows"] == [["2025-09", 3600.0]]
    # 授权读取路径包含新物化数据而不是原图作图数据。
    task_context, task_facts, _ = runner.calls[0]
    assert new_plot.path in task_context.authorized_read_paths
    assert fixture.plot_path not in task_context.authorized_read_paths
    assert [item["path"] for item in task_facts["chartInputs"]] == [new_plot.path]
    assert (
        task_facts["visualizationPlan"]["charts"][0]["dataBindings"][0]["dataPath"]
        == "metrics[0].periodValues"
    )

    # L2 后连续进行纯 L1 调整，后两轮都必须继承换绑数据，不能悄然回退原图数据。
    service.planner = _planner(level=("L1",))
    previous_edit_id = started["editId"]
    for _ in range(2):
        continued = await service.start_edit(
            fixture.context,
            session,
            "chart_001",
            ChartAIEditRequest(
                instruction="继续调整标签",
                previousEditId=previous_edit_id,
                expectedSha256=_sha(fixture.chart_bytes),
            ),
        )
        continued_status = await _await_edit(
            service, fixture.context, "chart_001", continued["editId"]
        )
        assert continued_status["status"] == "succeeded", continued_status
        previous_edit_id = continued["editId"]

    records = await load_chart_edit_records(
        fixture.workspace, fixture.thread_id, fixture.context.markdown_path
    )
    assert [item.data_origin for item in records] == ["rebound", "rebound", "rebound"]
    assert [item.level for item in records] == [("L2",), ("L1",), ("L1",)]
    assert all(item.plot_data_files[0].path == new_plot.path for item in records)
    assert all(item.chart.dataset_ids == ("dataset-url-abc0001",) for item in records)
    assert all(new_plot.path in call[0].authorized_read_paths for call in runner.calls[1:])


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_edit_l2_rejects_cross_analysis_and_unknown_bindings(tmp_path: Path) -> None:
    """跨分析或不在签发目录中的绑定不使用，按跳过说明返回且不执行绘图。"""
    from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding

    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes)
    forged = ChartDataBinding(
        analysisId="analysis_999",
        factPath="报表/智能分析/report-1/facts/revision-1/analysis_001.json",
        dataPath="metrics[0]",
        fields=("total", "unit"),
        role="main",
    )
    service = _service(fixture, runner, planner=_planner(level=("L2",), data_bindings=(forged,)))
    session = SimpleNamespace(capabilities=None)

    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="换成别的分析的数据"),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == "failed"
    assert status["error"]["code"] == "report_editor_chart_ai_skipped"
    assert "换绑数据未使用" in status["error"]["skipped"][0]["reason"]
    assert runner.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_edit_single_flight_busy_and_hourly_rate_limit(tmp_path: Path) -> None:
    fixture = await _make_editor_with_chart(tmp_path)
    gate = asyncio.Event()
    runner = FakeRunner(fixture.chart_bytes, gate=gate)
    service = _service(fixture, runner, hourly_limit=1)
    session = SimpleNamespace(capabilities=None)
    request = ChartAIEditRequest(instruction="改成横向条形图")

    first = await service.start_edit(fixture.context, session, "chart_001", request)
    status = service.edit_status(fixture.context, "chart_001", first["editId"])
    assert status["status"] == "running"
    assert status["stage"] in CHART_AI_STAGES

    with pytest.raises(ReportingError, match="report_editor_chart_ai_busy"):
        await service.start_edit(fixture.context, session, "chart_001", request)

    # 取消运行中的改图；原图与登记不受影响。
    cancelled = service.cancel_edit(fixture.context, "chart_001", first["editId"])
    assert cancelled["status"] == "cancelled"
    final = await _await_edit(service, fixture.context, "chart_001", first["editId"])
    assert final["status"] == "cancelled"
    records = await load_chart_edit_records(
        fixture.workspace, fixture.thread_id, fixture.context.markdown_path
    )
    assert records == ()
    await service.aclose()

    # 每小时次数上限按用户计数：第一次发起已计入窗口，重新发起受限。
    with pytest.raises(ReportingError, match="report_editor_chart_ai_rate_limited"):
        await service.start_edit(fixture.context, session, "chart_001", request)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_edit_timeout_returns_reason_and_keeps_original(tmp_path: Path) -> None:
    fixture = await _make_editor_with_chart(tmp_path)
    gate = asyncio.Event()
    runner = FakeRunner(fixture.chart_bytes, gate=gate)
    service = _service(fixture, runner, timeout_seconds=0.1)
    session = SimpleNamespace(capabilities=None)

    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="改成横向条形图"),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])

    assert status["status"] == "failed"
    assert status["error"]["code"] == "report_editor_chart_ai_timeout"
    records = await load_chart_edit_records(
        fixture.workspace, fixture.thread_id, fixture.context.markdown_path
    )
    assert records == ()
    # 超时后同图可再次发起（无遗留运行任务）。
    gate.set()
    retry = FakeRunner(fixture.chart_bytes)
    retry_service = _service(fixture, retry)
    again = await retry_service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="改成横向条形图"),
    )
    final = await _await_edit(retry_service, fixture.context, "chart_001", again["editId"])
    assert final["status"] == "succeeded"
    await retry_service.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_availability_reports_missing_plot_data_and_unknown_chart(
    tmp_path: Path,
) -> None:
    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes)
    service = _service(fixture, runner)
    session = SimpleNamespace(capabilities=None)

    unknown = await service.availability(fixture.context, session, "chart_404")
    assert unknown == {"available": False, "reason": "unknown_chart"}

    restricted = SimpleNamespace(capabilities={"download_original": False})
    read_only = await service.availability(fixture.context, restricted, "chart_001")
    assert read_only == {"available": False, "reason": "read_only"}

    with pytest.raises(ReportingError, match="report_editor_chart_ai_unavailable"):
        await service.start_edit(
            fixture.context,
            session,
            "chart_404",
            ChartAIEditRequest(instruction="改图"),
        )

    no_vision = ChartAIEditService(
        editor=fixture.editor,
        workspace_registry=fixture.editor.workspace_registry,
        planner=_planner(),
        runner=SimpleNamespace(vision_reviewer=None),
    )
    missing_vision = await no_vision.availability(fixture.context, session, "chart_001")
    assert missing_vision == {"available": False, "reason": "vision_missing"}


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_read_asset_rejects_changed_chart_edit_and_corrupt_registry(
    tmp_path: Path,
) -> None:
    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes)
    service = _service(fixture, runner)
    session = SimpleNamespace(capabilities=None)

    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="改成横向条形图"),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == "succeeded"
    records = await load_chart_edit_records(
        fixture.workspace, fixture.thread_id, fixture.context.markdown_path
    )
    image_path = records[0].image.path

    # 落盘文件被替换：哈希与登记身份不一致 → report_editor_asset_changed。
    await fixture.workspace.awrite_bytes(
        fixture.thread_id, image_path, fixture.chart_bytes + b"x", overwrite=True
    )
    with pytest.raises(ReportingError, match="report_editor_asset_changed"):
        await fixture.editor.read_asset(fixture.context, image_path)

    # 登记损坏：按未登记处理（404），不放大为 500。
    await fixture.workspace.awrite_bytes(
        fixture.thread_id,
        chart_edits_registry_path(fixture.context.markdown_path),
        b"not-json",
        overwrite=True,
    )
    with pytest.raises(ReportingError, match="report_editor_asset_missing"):
        await fixture.editor.read_asset(fixture.context, image_path)


def test_chart_edit_registry_roundtrip_rejects_duplicates_and_corruption() -> None:
    from smart_reporting.report_editor.chart_edits import (
        ChartEditChartMeta,
        ChartEditFileRef,
        ChartEditRecord,
    )

    record = ChartEditRecord(
        editId="cedit-0123456789abcdef",
        chartId="chart_001",
        baseImagePath="reports/revision-1/chart-001.png",
        baseImageSha256=_sha(b"base"),
        instruction="改成横向条形图",
        level=["L1"],
        image=ChartEditFileRef(
            path="reports/revision-1/chart-edits/cedit-0123456789abcdef/chart.png",
            size=3,
            sha256=_sha(b"abc"),
        ),
        script=ChartEditFileRef(
            path="reports/revision-1/chart-edits/cedit-0123456789abcdef/chart_edit.py",
            size=3,
            sha256=_sha(b"abc"),
        ),
        plotDataFiles=[
            ChartEditFileRef(
                path="reports/revision-1/chart-001.chart-input.json", size=3, sha256=_sha(b"abc")
            )
        ],
        chart=ChartEditChartMeta(
            title="收入",
            altText="收入对比",
            visualForm="横向条形图",
            datasetIds=["dataset-url-abc0001"],
        ),
        createdAt="2026-10-25T00:00:00+00:00",
        userId="user-1",
    )
    payload = {
        "version": CHART_EDITS_REGISTRY_VERSION,
        "records": [record.model_dump(mode="json", by_alias=True)],
        "tableEdits": [],
    }
    parsed = parse_chart_edit_records(_encode_registry_payload(payload))
    assert parsed == (record,)

    with pytest.raises(ValueError):
        parse_chart_edit_records(b"{not json")
    with pytest.raises(ValueError):
        parse_chart_edit_records(b'{"version": 99, "records": []}')
    payload["records"].append(payload["records"][0])
    duplicate = _encode_registry_payload(payload)
    with pytest.raises(ValueError):
        parse_chart_edit_records(duplicate)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_routes_require_csrf_and_map_status_codes() -> None:
    """API 冒烟：路由注册、写保护（CSRF/Origin）与任务状态错误码映射。"""

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor.api import create_report_editor_router
    from smart_reporting.report_editor.service import InMemoryReportEditorRepository

    class Editor:
        async def context_for_session(self, session):
            return SimpleNamespace(report_id=session.report_id, revision=session.revision)

    class ChartAI:
        def __init__(self) -> None:
            self.started: list[str] = []
            self.cancelled: list[str] = []

        async def availability(self, context, session, chart_id):
            return {"available": True, "chartId": chart_id}

        async def start_edit(self, context, session, chart_id, request):
            self.started.append(chart_id)
            return {"editId": "cedit-0123456789abcdef", "status": "queued"}

        def edit_status(self, context, chart_id, edit_id):
            if edit_id == "cedit-missing":
                raise ReportingError("report_editor_chart_ai_missing", "改图任务不存在或已过期。")
            return {"editId": edit_id, "chartId": chart_id, "status": "succeeded"}

        def cancel_edit(self, context, chart_id, edit_id):
            self.cancelled.append(edit_id)
            return {"editId": edit_id, "status": "cancelled"}

    repository = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(repository, secret="s" * 32)
    chart_ai = ChartAI()
    app = FastAPI()
    app.include_router(
        create_report_editor_router(
            grants,
            editor=Editor(),
            chart_ai=chart_ai,
            cookie_secure=False,
            allowed_origin="https://reports.example.com",
        )
    )
    base = "/reports/v1/editor/report-1/1/api/charts/chart_001/ai-edits"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://reports.example.com"
    ) as client:
        await client.get("/reports/v1/editor/open/nonexistent", follow_redirects=False)
        # 会话 cookie 指向 report-1/1 后再获取 CSRF。
        from datetime import UTC, datetime, timedelta

        from smart_reporting.report_editor.service import ReportEditorSession

        await repository.put_session(
            hashlib.sha256(b"session-1").hexdigest(),
            ReportEditorSession(
                report_id="report-1",
                revision=1,
                workflow_run_id="report-1",
                context_sha256="0" * 64,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
        )
        client.cookies.set("report_editor_session", "session-1")
        csrf = grants.csrf_token("session-1")

        availability = await client.get(f"{base}/availability")
        assert availability.status_code == 200
        assert availability.json() == {"available": True, "chartId": "chart_001"}

        # 写操作：缺 CSRF/Origin → 403；带齐 → 202。
        assert (await client.post(base, json={"instruction": "改成横向条形图"})).status_code == 403
        started = await client.post(
            base,
            json={"instruction": "改成横向条形图"},
            headers={"Origin": "https://reports.example.com", "X-CSRF-Token": csrf},
        )
        assert started.status_code == 202
        assert started.json()["editId"] == "cedit-0123456789abcdef"

        status = await client.get(f"{base}/cedit-0123456789abcdef")
        assert status.status_code == 200
        assert status.json()["status"] == "succeeded"
        missing = await client.get(f"{base}/cedit-missing")
        assert missing.status_code == 404

        cancelled = await client.post(
            f"{base}/cedit-0123456789abcdef/cancel",
            headers={"Origin": "https://reports.example.com", "X-CSRF-Token": csrf},
        )
        assert cancelled.status_code == 200
        assert cancelled.json() == {"editId": "cedit-0123456789abcdef", "status": "cancelled"}

    assert chart_ai.started == ["chart_001"]
    assert chart_ai.cancelled == ["cedit-0123456789abcdef"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_visual_issues_are_soft_warnings_and_trigger_one_repair(
    tmp_path: Path,
) -> None:
    """设计稿 §5.2/§8：视觉问题只出软告警不阻断；requiresRevision 触发一次自动修复，
    修复后仍有问题则带告警交付审阅。"""

    def receipt(requires_revision: bool) -> ChartVisualInspectionReceipt:
        return ChartVisualInspectionReceipt(
            sourcePath="reports/revision-1/chart-edits/x/chart.png",
            sha256=_sha(b"img"),
            inspectionMode="vision",
            visualReviewStatus="passed",
            modelId="fake-vision-model",
            reviewed=True,
            requiresRevision=requires_revision,
            issues=(
                ChartVisualInspectionIssue(
                    category="legend_occlusion",
                    severity="warning",
                    description="图例遮挡了柱体标签。",
                ),
            ),
        )

    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes, receipts=(receipt(True),))
    service = _service(fixture, runner)
    session = SimpleNamespace(capabilities=None)

    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="调整图例位置"),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])

    # 两次执行：首轮 requiresRevision → 一次自动修复（带诊断）；修复后仍带问题 → 交付。
    assert len(runner.calls) == 2
    assert runner.calls[0][2] is None
    assert runner.calls[1][2] == {
        "code": "report_visual_review_failed",
        "message": "视觉审查发现问题，请在不改变数据与输出路径的前提下修复图表。",
    }
    assert status["status"] == "succeeded"
    assert status["warnings"] == ["视觉审查（warning）：legend_occlusion - 图例遮挡了柱体标签。"]
    assert status["visualInspection"]["reviewed"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_previous_edit_id_must_belong_to_same_chart(tmp_path: Path) -> None:
    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes)
    service = _service(fixture, runner)
    session = SimpleNamespace(capabilities=None)

    # 用非法 previousEditId（不属于该图/不存在）发起：任务失败且不执行 runner。
    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="继续调整", previousEditId="cedit-doesnotexist1"),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == "failed"
    assert status["error"]["code"] == "report_editor_chart_ai_missing"
    assert runner.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_multi_round_edit_uses_previous_result_as_base(tmp_path: Path) -> None:
    """多轮调整：previousEditId 指向同图上一轮成功改图时，以其新图为底图继续。"""

    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes)
    service = _service(fixture, runner)
    session = SimpleNamespace(capabilities=None)

    first = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="改成横向条形图"),
    )
    first_status = await _await_edit(service, fixture.context, "chart_001", first["editId"])
    assert first_status["status"] == "succeeded"

    second = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(
            instruction="把数值标签放大",
            previousEditId=first["editId"],
            expectedSha256=_sha(fixture.chart_bytes),
        ),
    )
    second_status = await _await_edit(service, fixture.context, "chart_001", second["editId"])
    assert second_status["status"] == "succeeded"
    assert second_status["editId"] != first["editId"]

    records = await load_chart_edit_records(
        fixture.workspace, fixture.thread_id, fixture.context.markdown_path
    )
    assert [record.edit_id for record in records] == [first["editId"], second["editId"]]
    second_record = records[1]
    assert second_record.base_image_path == first_status["imagePath"]
    assert second_record.base_image_sha256 == records[0].image.sha256
    # 第二轮的授权读取以第一轮新图为底图，仍包含原作图数据。
    task_context = runner.calls[1][0]
    assert first_status["imagePath"] in task_context.authorized_read_paths
    assert fixture.plot_path in task_context.authorized_read_paths


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_keeps_visual_form_and_serves_relative_src_for_re_edit(
    tmp_path: Path,
) -> None:
    """不换图形的改图（计划未给 visualForm）照常登记；接受后正文相对引用可读，并能据登记找回图表。"""
    from smart_reporting.report_editor.chart_ai import _KEEP_VISUAL_FORM

    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes)
    service = _service(
        fixture, runner, planner=_planner(visual_form=None, title=None, alt_text=None)
    )
    session = SimpleNamespace(capabilities=None)
    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="在图上显示数值标签"),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == "succeeded"
    assert runner.calls[0][1]["visualizationPlan"]["charts"][0]["visualForm"] == _KEEP_VISUAL_FORM
    # 正文写入的是修订目录相对路径 chart-edits/<editId>/chart.png，浏览器按此请求资源。
    assert status["imageSrc"].startswith("chart-edits/")
    content, media_type = await fixture.editor.read_asset(fixture.context, status["imageSrc"])
    assert media_type == "image/png" and content == fixture.chart_bytes
    record = await service.edit_record(fixture.context, started["editId"])
    assert record == {
        "editId": started["editId"],
        "chartId": "chart_001",
        "imagePath": status["imagePath"],
    }


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chart_ai_failed_repair_keeps_first_result_and_internal_timeout_is_not_edit_timeout(
    tmp_path: Path,
) -> None:
    fixture = await _make_editor_with_chart(tmp_path)
    receipt = ChartVisualInspectionReceipt(
        sourcePath="reports/revision-1/chart-edits/x/chart.png",
        sha256=_sha(b"img"),
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="fake-vision-model",
        reviewed=True,
        requiresRevision=True,
    )

    class RepairFails(FakeRunner):
        async def run(self, task_context, workspace, task_facts, *, run_context, diagnostic=None):
            if diagnostic is not None:
                self.calls.append((task_context, dict(task_facts), diagnostic))
                await workspace.awrite_bytes(
                    task_context.workspace_key,
                    task_context.declared_output_paths[0],
                    b"partial",
                    overwrite=True,
                )
                raise RuntimeError("repair crashed")
            return await super().run(task_context, workspace, task_facts, run_context=run_context)

    runner = RepairFails(fixture.chart_bytes, receipts=(receipt,))
    service = _service(fixture, runner)
    session = SimpleNamespace(capabilities=None)
    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="调整图例"),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    # 修复失败：首轮产物写回，带告警交付，不让整次改图失败。
    assert status["status"] == "succeeded" and len(runner.calls) == 2
    assert any("自动修复未完成" in warning for warning in status["warnings"])
    content, _ = await fixture.editor.read_asset(fixture.context, status["imageSrc"])
    assert content == fixture.chart_bytes

    class InnerTimeout(FakeRunner):
        async def run(self, *args, **kwargs):
            raise TimeoutError("provider read timeout")

    service = _service(fixture, InnerTimeout(fixture.chart_bytes))
    started = await service.start_edit(
        fixture.context,
        session,
        "chart_001",
        ChartAIEditRequest(instruction="调整图例"),
    )
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["error"]["code"] == "report_editor_chart_ai_failed"


def test_caption_numbers_are_checked_against_all_rows_at_written_precision() -> None:
    from smart_reporting.report_editor.chart_ai import _caption_number_warnings

    rows = [[f"2025-{month:02d}", 3600 + month * 0.4] for month in range(1, 13)]
    content = (
        b'{"schema":"chart-input/v1","columns":["period","revenue"],"rows":'
        + str(rows).replace("'", '"').encode()
        + b"}"
    )
    files = [SimpleNamespace(content=content)]
    # 12 月的值（第 12 行）按图注写出的精度比较：3604.8 写作 3,605 与 3604.8 都可还原。
    assert _caption_number_warnings("12月收入3,605元，峰值3604.8元", files) == []
    assert _caption_number_warnings("收入达到9999元", files) == [
        "图注中的数字 9999 未在登记作图数据中找到，请人工核对。"
    ]
