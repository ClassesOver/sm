from __future__ import annotations

import asyncio
import hashlib
import io
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.service import ReportEditorContext, ReportEditorSession
from smart_reporting.report_editor.slides import ReportSlidesEditorService
from smart_reporting.reporting.models import ReportingError


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _context() -> ReportEditorContext:
    return ReportEditorContext(
        reportId="report-1",
        revision=1,
        jobId="job-1",
        workflowRunId="run-1",
        markdownPath="reports/report.md",
        job={"jobId": "job-1"},
        scope={
            "database": "db",
            "companyId": "company",
            "userId": "user",
            "sessionId": "session",
            "callerThreadId": "caller",
            "threadId": "workspace",
        },
        deliveryFormat="pptx",
        pptxPath="reports/report.pptx",
        pptxSize=12,
        pptxSha256="a" * 64,
    )


def _session(context: ReportEditorContext, **overrides: object) -> ReportEditorSession:
    values = {
        "report_id": context.report_id,
        "revision": context.revision,
        "workflow_run_id": context.workflow_run_id,
        "context_sha256": context.digest(),
        "expires_at": datetime.now(UTC),
        "capabilities": {"pptx_editor": True},
    }
    values.update(overrides)
    return ReportEditorSession(**values)


@pytest.mark.anyio
async def test_slides_editor_resolves_only_verified_pptx_context(monkeypatch):
    from smart_reporting.report_editor import slides

    monkeypatch.setattr(
        slides,
        "resolve_reporting_workflow_scope",
        lambda **_kwargs: SimpleNamespace(workspace_key="workspace"),
    )
    context = _context()
    workspace = SimpleNamespace(
        ahash_file=lambda _thread, _path: None,
    )

    async def hash_file(thread_id: str, path: str):
        assert thread_id == "workspace"
        assert path == context.pptx_path
        return {"missing": False, "size": context.pptx_size, "sha256": context.pptx_sha256}

    workspace.ahash_file = hash_file
    async def get_state(_run: str):
        return SimpleNamespace(payload={
            "reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}
        })

    service = ReportSlidesEditorService(
        state_repository=SimpleNamespace(get=get_state),
        workspace_registry=SimpleNamespace(resolve=lambda _scope: None),
        workspace=workspace,
    )

    resolved = await service.context_for_session(_session(context))

    assert resolved == context


@pytest.mark.anyio
async def test_slides_editor_rejects_document_capabilities_and_changed_identity(monkeypatch):
    from smart_reporting.report_editor import slides

    monkeypatch.setattr(
        slides,
        "resolve_reporting_workflow_scope",
        lambda **_kwargs: SimpleNamespace(workspace_key="workspace"),
    )
    context = _context()
    async def get_state(_run: str):
        return SimpleNamespace(payload={
            "reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}
        })

    service = ReportSlidesEditorService(
        state_repository=SimpleNamespace(get=get_state),
        workspace_registry=SimpleNamespace(resolve=lambda _scope: None),
        workspace=SimpleNamespace(ahash_file=lambda *_args: None),
    )

    with pytest.raises(ReportingError, match="编辑权限"):
        await service.context_for_session(_session(context, capabilities={"download_original": True}))

    async def changed_identity(_thread: str, _path: str):
        return {"missing": False, "size": context.pptx_size, "sha256": "b" * 64}

    service.workspace.ahash_file = changed_identity
    with pytest.raises(ReportingError, match="文件身份已变化"):
        await service.context_for_session(_session(context))


async def _editable_service(tmp_path: Path, monkeypatch, *, content: bytes = b"original-pptx"):
    from smart_reporting.report_editor import slides
    from smart_reporting.report_editor.service import ReportEditorService
    from smart_reporting.reporting.delivery.publishing import ReportDownloadGrantService
    from smart_reporting.reporting.host_workspace import HostReportingWorkspace
    from smart_reporting.reporting.workflow.state import ReportingRunState, apply

    monkeypatch.setattr(slides, "resolve_reporting_workflow_scope",
                        lambda **_kwargs: SimpleNamespace(workspace_key="workspace"))
    identity = SimpleNamespace(root=tmp_path)
    workspace = HostReportingWorkspace(identity)
    registry = SimpleNamespace(resolve=lambda _scope: identity, get=lambda _key: identity)
    context = _context().model_copy(update={
        "pptx_size": len(content), "pptx_sha256": hashlib.sha256(content).hexdigest(),
        "job": {"jobId": "job-1", "validation": {"ok": True, "issues": []}},
    })
    await workspace.awrite_bytes("workspace", context.pptx_path, content)
    state = ReportingRunState.initial(
        report_run_id="run-1", external_run_id="external-1", thread_id="caller",
        owner_user_id="user", payload={"reportEditorContexts": {
            "1": context.model_dump(mode="json", by_alias=True),
        }},
    )

    class StateRepository:
        fail_registration = False
        conflict_once = False

        async def get(self, _run):
            return self.state

        async def apply(self, _run, command, *, expected_version):
            from smart_reporting.reporting.workflow.state import ReportingStateConflict

            if self.fail_registration:
                raise OSError("状态登记暂不可用")
            if self.conflict_once:
                self.conflict_once = False
                self.state = apply(self.state, {
                    "name": "record_warnings", "commandId": "other-worker",
                    "payload": {"warnings": []},
                }).state
                raise ReportingStateConflict("状态已更新")
            self.state = apply(self.state, command, expected_version).state
            return self.state

    repository = StateRepository()
    repository.state = state
    stored = []

    class Persistence:
        async def persist_available(self, **values):
            for spec in values["artifacts"]:
                data = await workspace.read_limited_regular_file("workspace", spec.path,
                                                                 max_bytes=spec.size)
                assert len(data) == spec.size
                assert hashlib.sha256(data).hexdigest() == spec.sha256
                stored.append((values["revision"], spec, data))
            return values["artifacts"]

    class GrantRepository:
        async def replace(self, grant, *, now):
            self.grant = grant

        async def cleanup_expired(self, *, now):
            pass

        async def get(self, _hash):
            return self.grant

    locks = SimpleNamespace(_draft_locks={}, workspace_registry=registry)
    grants = ReportDownloadGrantService(GrantRepository())
    service = ReportSlidesEditorService(
        state_repository=repository, workspace_registry=registry, workspace=workspace,
        artifact_persistence=Persistence(), download_grants=grants,
        draft_lock=lambda item: ReportEditorService._draft_lock(locks, item),
    )
    return SimpleNamespace(service=service, context=context, session=_session(context),
                           workspace=workspace, repository=repository, stored=stored,
                           grants=grants, original=content)


def _fake_engine(monkeypatch, *, validation=None):
    from smart_reporting.report_editor import slides

    main_thread = threading.get_ident()

    def inspect(content):
        assert threading.get_ident() != main_thread
        return {"width": 1280, "height": 720, "slides": [{
            "index": 0, "title": content.decode(), "background": "#FFFFFF", "elements": [],
        }]}

    def edit(content, operations):
        assert threading.get_ident() != main_thread
        changed = content if not operations else content + operations[0].get("text", "-moved").encode()
        return changed, validation or {"ok": True, "issues": []}

    monkeypatch.setattr(slides, "inspect_pptx", inspect)
    monkeypatch.setattr(slides, "edit_pptx", edit)


def _set_source_validation(setup, validation, gate=None):
    job = {**setup.context.job, "validation": validation}
    if gate is not None:
        job["publicationGate"] = gate
    setup.context = setup.context.model_copy(update={"job": job})
    setup.session = _session(setup.context)
    setup.repository.state.payload["reportEditorContexts"]["1"] = setup.context.model_dump(
        mode="json", by_alias=True,
    )


@pytest.mark.anyio
async def test_slides_title_move_preserves_source_chart_warning_and_failed_publication_gate(
    tmp_path, monkeypatch,
):
    setup = await _editable_service(tmp_path, monkeypatch)
    _fake_engine(monkeypatch)
    chart_issue = {"code": "pptx_chart_unavailable", "message": "冻结图表无法读取。",
                   "details": {"chartId": "chart-original"}}
    gate = {"formalReleaseAllowed": False,
            "issues": [{"code": "source_review_failed", "message": "原发布来源需复核。"}]}
    _set_source_validation(setup, {"ok": False, "issues": [chart_issue, {
        "code": "pptx_layout_audit", "message": "原布局待复核。",
    }]}, gate)

    saved = await setup.service.save_draft_for_session(
        setup.session, expected_sha256=setup.context.pptx_sha256,
        operations=[{"op": "update", "slide": 0, "id": "title", "x": 20}],
    )

    assert saved["validation"] == {"ok": False, "issues": [chart_issue]}
    saved = await setup.service.save_draft_for_session(
        setup.session, expected_sha256=saved["sha256"],
        operations=[{"op": "update", "slide": 0, "id": "title", "x": 30}],
    )
    reopened = await setup.service.document_for_session(setup.session)
    result = await setup.service.export_for_session(
        setup.session, expected_sha256=saved["sha256"], base_url="https://reports.test",
    )

    assert saved["validation"] == reopened["validation"] == result["validation"] == {
        "ok": False, "issues": [chart_issue],
    }
    assert reopened["publicationGate"] == result["publicationGate"] == gate
    assert result["pptx"]["downloadUrl"]


@pytest.mark.anyio
async def test_slides_restores_source_warning_when_older_draft_record_claims_success(tmp_path, monkeypatch):
    setup = await _editable_service(tmp_path, monkeypatch)
    _fake_engine(monkeypatch)
    issue = {"code": "pptx_chart_unavailable", "message": "缺少原始冻结图表。"}
    _set_source_validation(setup, {"ok": False, "issues": [issue]})
    saved = await setup.service.save_draft_for_session(
        setup.session, expected_sha256=setup.context.pptx_sha256, operations=[{"text": "-old"}],
    )
    await setup.workspace.awrite_bytes(
        "workspace", setup.service._draft_path(setup.context) + ".validation.json",
        json.dumps({"sha256": saved["sha256"], "validation": {"ok": True, "issues": []}}).encode(),
        overwrite=True,
    )

    document = await setup.service.document_for_session(setup.session)
    result = await setup.service.export_for_session(
        setup.session, expected_sha256=saved["sha256"], base_url="https://reports.test",
    )

    assert document["validation"] == result["validation"] == {"ok": False, "issues": [issue]}


@pytest.mark.anyio
@pytest.mark.parametrize("code", [
    "pptx_layout_audit", "pptx_layout_warning", "pptx_audit_failed", "report_slides_validation_failed",
])
async def test_slides_refreshes_only_layout_validation_and_keeps_source_gate(tmp_path, monkeypatch, code):
    setup = await _editable_service(tmp_path, monkeypatch)
    _fake_engine(monkeypatch)
    gate = {"formalReleaseAllowed": False, "issues": [{"code": "source_gate_not_rechecked"}]}
    _set_source_validation(setup, {"ok": False, "issues": [{"code": code, "message": "旧版式问题"}]}, gate)

    saved = await setup.service.save_draft_for_session(
        setup.session, expected_sha256=setup.context.pptx_sha256, operations=[{"text": "-fixed"}],
    )
    result = await setup.service.export_for_session(
        setup.session, expected_sha256=saved["sha256"], base_url="https://reports.test",
    )

    assert saved["validation"] == result["validation"] == {"ok": True, "issues": []}
    assert result["publicationGate"] == gate
    assert result["pptx"]["downloadUrl"]


@pytest.mark.anyio
async def test_slides_keeps_unknown_source_failure_without_duplicate_issues(tmp_path, monkeypatch):
    setup = await _editable_service(tmp_path, monkeypatch)
    _fake_engine(monkeypatch)
    _set_source_validation(setup, {"ok": False, "issues": []})

    saved = await setup.service.save_draft_for_session(
        setup.session, expected_sha256=setup.context.pptx_sha256, operations=[{"text": "-first"}],
    )
    saved = await setup.service.save_draft_for_session(
        setup.session, expected_sha256=saved["sha256"], operations=[{"text": "-second"}],
    )
    result = await setup.service.export_for_session(
        setup.session, expected_sha256=saved["sha256"], base_url="https://reports.test",
    )

    assert saved["validation"] == result["validation"]
    assert result["validation"]["ok"] is False
    assert [issue["code"] for issue in result["validation"]["issues"]] == [
        "report_slides_source_validation_unknown",
    ]
    assert result["pptx"]["downloadUrl"]


@pytest.mark.anyio
async def test_slides_document_reads_verified_source_then_saved_draft_without_overwriting_source(
    tmp_path, monkeypatch,
):
    setup = await _editable_service(tmp_path, monkeypatch)
    _fake_engine(monkeypatch)

    original = await setup.service.document_for_session(setup.session)
    saved = await setup.service.save_draft_for_session(
        setup.session, expected_sha256=original["sha256"], operations=[{"text": "-edited"}],
    )
    reopened = await setup.service.document_for_session(setup.session)

    assert original["slides"][0]["title"] == "original-pptx"
    assert saved["slides"][0]["title"] == "original-pptx-edited"
    assert saved["sha256"] == reopened["sha256"] != original["sha256"]
    assert (saved["reportId"], saved["revision"]) == ("report-1", 1)
    assert await setup.workspace.read_limited_regular_file(
        "workspace", setup.context.pptx_path, max_bytes=1024,
    ) == b"original-pptx"


@pytest.mark.anyio
async def test_slides_stale_save_and_export_preserve_current_draft(tmp_path, monkeypatch):
    setup = await _editable_service(tmp_path, monkeypatch)
    _fake_engine(monkeypatch)
    first = await setup.service.save_draft_for_session(
        setup.session, expected_sha256=setup.context.pptx_sha256, operations=[{"text": "-first"}],
    )

    for action in (
        lambda: setup.service.save_draft_for_session(
            setup.session, expected_sha256=setup.context.pptx_sha256,
            operations=[{"text": "-stale"}],
        ),
        lambda: setup.service.export_for_session(
            setup.session, expected_sha256=setup.context.pptx_sha256, base_url="https://reports.test",
        ),
    ):
        with pytest.raises(ReportingError) as error:
            await action()
        assert error.value.code == "report_slides_conflict"
    assert (await setup.service.document_for_session(setup.session))["sha256"] == first["sha256"]
    assert setup.stored == []


@pytest.mark.anyio
async def test_slides_draft_never_bypasses_published_source_identity(tmp_path, monkeypatch):
    setup = await _editable_service(tmp_path, monkeypatch)
    _fake_engine(monkeypatch)
    await setup.service.save_draft_for_session(
        setup.session, expected_sha256=setup.context.pptx_sha256, operations=[{"text": "-first"}],
    )
    await setup.workspace.awrite_bytes("workspace", setup.context.pptx_path, b"changed", overwrite=True)

    with pytest.raises(ReportingError) as error:
        await setup.service.document_for_session(setup.session)
    assert error.value.code == "report_slides_identity_changed"


@pytest.mark.anyio
@pytest.mark.parametrize("register_failure", [False, True])
async def test_slides_export_issues_immutable_download_despite_validation_or_registration_failure(
    tmp_path, monkeypatch, register_failure,
):
    setup = await _editable_service(tmp_path, monkeypatch)
    _fake_engine(monkeypatch, validation={
        "ok": False, "issues": [{"code": "pptx_layout_warning", "message": "标题超出页边界"}],
    })
    setup.repository.fail_registration = register_failure
    draft = await setup.service.save_draft_for_session(
        setup.session, expected_sha256=setup.context.pptx_sha256, operations=[{"text": "-exported"}],
    )

    result = await setup.service.export_for_session(
        setup.session, expected_sha256=draft["sha256"], base_url="https://reports.test",
    )

    assert result["pptx"]["downloadUrl"].startswith("https://reports.test/reports/v1/download/")
    assert result["pptx"]["path"] != setup.context.pptx_path
    assert result["validation"]["ok"] is False
    codes = {item["code"] for item in result["validation"]["issues"]}
    assert "pptx_layout_warning" in codes
    assert ("report_slides_registration_failed" in codes) is register_failure
    assert setup.stored[0][2] == b"original-pptx-exported"
    raw = result["pptx"]["downloadUrl"].split("/")[-2]
    grant = await setup.grants.lookup(raw)
    assert grant.pptx_sha256 == result["pptx"]["sha256"]
    if not register_failure:
        registered = setup.repository.state.payload["reportEditorContexts"]["2"]
        assert registered["pptxSha256"] == result["pptx"]["sha256"]
        assert registered["deliveryFormat"] == "pptx"
        assert registered["markdownPath"] == setup.context.markdown_path

    second = await setup.service.export_for_session(
        setup.session, expected_sha256=draft["sha256"], base_url="https://reports.test",
    )
    assert second["pptx"]["path"] != result["pptx"]["path"]
    assert setup.stored[0][2] == b"original-pptx-exported"
    if not register_failure:
        assert second["revision"] == 3


@pytest.mark.anyio
async def test_slides_export_retries_state_version_conflict(tmp_path, monkeypatch):
    setup = await _editable_service(tmp_path, monkeypatch)
    _fake_engine(monkeypatch)
    setup.repository.conflict_once = True

    result = await setup.service.export_for_session(
        setup.session, expected_sha256=setup.context.pptx_sha256, base_url="https://reports.test",
    )

    assert result["revision"] == 2
    assert result["validation"]["ok"] is True
    assert "2" in setup.repository.state.payload["reportEditorContexts"]


@pytest.mark.anyio
async def test_slides_workers_share_draft_lock_and_reject_second_stale_save(tmp_path, monkeypatch):
    from smart_reporting.report_editor.service import ReportEditorService

    setup = await _editable_service(tmp_path, monkeypatch)
    _fake_engine(monkeypatch)
    other_locks = SimpleNamespace(_draft_locks={}, workspace_registry=setup.service.workspace_registry)
    worker = ReportSlidesEditorService(
        state_repository=setup.repository, workspace_registry=setup.service.workspace_registry,
        workspace=setup.workspace,
        draft_lock=lambda item: ReportEditorService._draft_lock(other_locks, item),
    )

    results = await asyncio.gather(*(
        service.save_draft_for_session(
            setup.session, expected_sha256=setup.context.pptx_sha256,
            operations=[{"text": suffix}],
        )
        for service, suffix in ((setup.service, "-worker-one"), (worker, "-worker-two"))
    ), return_exceptions=True)

    assert sum(isinstance(item, dict) for item in results) == 1
    rejected = next(item for item in results if isinstance(item, ReportingError))
    assert rejected.code == "report_slides_conflict"


@pytest.mark.anyio
@pytest.mark.parametrize("receipt", ["missing", None, {"ok": False, "issues": None}])
async def test_slides_invalid_validation_metadata_cannot_block_export(tmp_path, monkeypatch, receipt):
    setup = await _editable_service(tmp_path, monkeypatch)
    _fake_engine(monkeypatch)
    source = setup.repository.state.payload["reportEditorContexts"]["1"]
    job = {"jobId": "job-1"}
    if receipt != "missing":
        job["validation"] = receipt
    context = ReportEditorContext.model_validate({**source, "job": job})
    setup.repository.state.payload["reportEditorContexts"]["1"] = context.model_dump(mode="json", by_alias=True)

    result = await setup.service.export_for_session(
        _session(context), expected_sha256=context.pptx_sha256, base_url="https://reports.test",
    )

    assert result["pptx"]["downloadUrl"]
    assert result["validation"]["ok"] is False
    assert "report_slides_validation_unavailable" in {item["code"] for item in result["validation"]["issues"]}


@pytest.mark.anyio
async def test_slides_export_keeps_download_when_native_audit_raises(tmp_path, monkeypatch):
    from smart_reporting.report_editor import slides

    setup = await _editable_service(tmp_path, monkeypatch)
    _fake_engine(monkeypatch)

    def broken_audit(*_args):
        raise RuntimeError("pptx_audit_failed")

    monkeypatch.setattr(slides, "edit_pptx", broken_audit)
    result = await setup.service.export_for_session(
        setup.session, expected_sha256=setup.context.pptx_sha256, base_url="https://reports.test",
    )

    assert result["pptx"]["downloadUrl"]
    assert result["validation"]["ok"] is False
    assert result["validation"]["issues"][0]["code"] == "report_slides_validation_failed"
    assert setup.stored[0][2] == b"original-pptx"


@pytest.mark.anyio
async def test_slides_real_native_roundtrip_preserves_image_and_notes(tmp_path, monkeypatch):
    from PIL import Image
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    page = presentation.slides.add_slide(presentation.slide_layouts[6])
    page.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text = "原始标题"
    picture = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(picture, format="PNG")
    page.shapes.add_picture(io.BytesIO(picture.getvalue()), Inches(2), Inches(3))
    page.notes_slide.notes_text_frame.text = "备注必须保留"
    stream = io.BytesIO()
    presentation.save(stream)
    setup = await _editable_service(tmp_path, monkeypatch, content=stream.getvalue())

    original = await setup.service.document_for_session(setup.session)
    text = next(item for item in original["slides"][0]["elements"] if item.get("text") == "原始标题")
    saved = await setup.service.save_draft_for_session(
        setup.session, expected_sha256=original["sha256"],
        operations=[{"op": "update", "slide": 0, "id": text["id"], "text": "人工修订"}],
    )
    result = await setup.service.export_for_session(
        setup.session, expected_sha256=saved["sha256"], base_url="https://reports.test",
    )

    exported = Presentation(io.BytesIO(setup.stored[0][2]))
    assert any(shape.has_text_frame and shape.text == "人工修订" for shape in exported.slides[0].shapes)
    assert exported.slides[0].notes_slide.notes_text_frame.text == "备注必须保留"
    assert any(getattr(shape, "image", None) and shape.image.blob == picture.getvalue()
               for shape in exported.slides[0].shapes)
    assert result["pptx"]["sha256"] != original["sha256"]
