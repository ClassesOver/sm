from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.service import ReportEditorContext, ReportEditorSession
from smart_reporting.report_editor.slides import ReportSlidesEditorService
from smart_reporting.reporting.models import ReportingError
from smart_reporting.workspace import WorkspacePathConflict


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


@pytest.mark.anyio
async def test_slides_save_rejects_non_string_theme_values():
    context = _context()
    service = ReportSlidesEditorService(
        state_repository=None,
        workspace_registry=None,
        workspace=None,
    )

    async def current_context(_session):
        return context

    service.context_for_session = current_context
    with pytest.raises(ReportingError, match="主题无效"):
        await service.save_revision(
            _session(context),
            {"expectedSha256": context.pptx_sha256, "edits": [], "theme": {"x": 1}},
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "animation",
    [
        {"slideIndex": 0, "elementId": "shape-1", "effect": "unknown", "trigger": "onClick"},
        {"slideIndex": 0, "elementId": "shape-1", "effect": "zoom", "trigger": "onClick", "durationMs": -1},
        {"slideIndex": 0, "elementId": "shape-1", "effect": "zoom", "trigger": "onClick", "delayMs": 3_600_001},
    ],
)
async def test_slides_save_rejects_invalid_animation_parameters(animation):
    context = _context()
    service = ReportSlidesEditorService(
        state_repository=None,
        workspace_registry=None,
        workspace=None,
    )

    async def current_context(_session):
        return context

    service.context_for_session = current_context
    with pytest.raises(ReportingError, match="动画内容无效"):
        await service.save_revision(
            _session(context),
            {"expectedSha256": context.pptx_sha256, "edits": [], "animations": [animation]},
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    'fault', ['persistence', 'context', 'download_grant', 'editor_grant', 'preview', 'stale_revision'],
)
async def test_slides_save_commits_revision_and_keeps_download_when_persistence_fails(monkeypatch, fault):
    from smart_reporting.report_editor import slides

    monkeypatch.setattr(
        slides,
        "resolve_reporting_workflow_scope",
        lambda **_kwargs: SimpleNamespace(workspace_key="workspace"),
    )
    context = _context()
    source_bytes = b"verified-source"
    context = context.model_copy(update={
        "pptx_size": len(source_bytes),
        "pptx_sha256": hashlib.sha256(source_bytes).hexdigest(),
    })
    files = {context.pptx_path: source_bytes}
    contexts = {"1": context.model_dump(mode="json", by_alias=True)}
    if fault == 'stale_revision':
        # 修订 2 已存在（例如从首个编辑入口重新打开后再次保存）；新修订必须是 3 且不覆盖 r2。
        files["reports/report-r2.pptx"] = b"existing-revision-2"
        contexts["2"] = context.model_copy(update={"revision": 2, "pptx_path": "reports/report-r2.pptx"}).model_dump(
            mode="json", by_alias=True,
        )
    expected_revision = 3 if fault == 'stale_revision' else 2
    revision_path = re.compile(rf"reports/report-r{expected_revision}-[0-9a-f]{{12}}\.pptx")

    class Workspace:
        async def ahash_file(self, _thread, path):
            value = files.get(path)
            return {"missing": value is None, "size": len(value or b""), "sha256": hashlib.sha256(value or b"").hexdigest()}

        async def afile_bytes(self, _thread, path):
            return files[path], "application/vnd.openxmlformats-officedocument.presentationml.presentation"

        async def awrite_bytes(self, _thread, path, content, *, overwrite=False, **_kwargs):
            if path in files and not overwrite:
                raise WorkspacePathConflict("目标文件已经存在，请重新读取后再覆盖。")
            files[path] = content

    state = SimpleNamespace(
        payload={"reportEditorContexts": contexts},
        state_version=8,
    )
    applied = []

    async def get_state(_run):
        return state

    async def apply(_run, command, *, expected_version):
        if fault == 'context':
            raise OSError('context unavailable')
        applied.append((command, expected_version))

    class EditorGrants:
        async def issue(self, saved_context, *, capabilities):
            if fault == 'download_grant' and capabilities.get('pptx_download'):
                raise OSError('editor download grant unavailable')
            if fault == 'editor_grant' and capabilities.get('pptx_editor'):
                raise OSError('editor grant unavailable')
            return ("download-token" if "pptx_download" in capabilities else "editor-token", datetime.now(UTC))

    class FailingPersistence:
        async def persist_available(self, **_kwargs):
            if fault == 'persistence':
                raise RuntimeError("persistence unavailable")
            return _kwargs['artifacts']

    class DownloadGrants:
        async def issue(self, **kwargs):
            assert revision_path.fullmatch(kwargs['pptx_path'])
            assert kwargs['pptx_size'] == len(b'verified-revision')
            assert kwargs['pptx_sha256'] == hashlib.sha256(b'verified-revision').hexdigest()
            return 'artifact-download-token', SimpleNamespace(expires_at=datetime.now(UTC))

    service = ReportSlidesEditorService(
        state_repository=SimpleNamespace(get=get_state, apply=apply),
        workspace_registry=SimpleNamespace(resolve=lambda _scope: None),
        workspace=Workspace(),
        editor_grants=EditorGrants(),
        artifact_persistence=FailingPersistence(),
        public_base_url="https://reports.test",
    )
    monkeypatch.setattr(slides.ReportSlidesEditorService, "_run_engine", staticmethod(lambda *_args, **_kwargs: {"bytes": b"verified-revision", "issues": []}))
    service.download_grants = DownloadGrants()

    def render_pdf(_bytes):
        if fault == 'preview':
            raise OSError('preview unavailable')
        return b'%PDF-test'

    monkeypatch.setattr(slides.ReportSlidesEditorService, "_render_pdf", staticmethod(render_pdf))

    result = await service.save_revision(
        _session(context), {"expectedSha256": context.pptx_sha256, "edits": [], "order": [0]}
    )

    assert result["revision"] == expected_revision
    assert revision_path.fullmatch(result["pptx"]["path"])
    if fault == 'stale_revision':
        assert files["reports/report-r2.pptx"] == b"existing-revision-2"
        assert result["validation"]["ok"] is True
        return
    if fault in {'context', 'download_grant'}:
        assert result['pptx']['downloadUrl'].endswith('/reports/v1/download/artifact-download-token/pptx')
    else:
        assert result["pptx"]["downloadUrl"].endswith("/reports/v1/slides/download/download-token")
    if fault in {'context', 'editor_grant'}:
        assert 'editor' not in result
    else:
        assert result["editor"]["openUrl"].endswith("/reports/v1/slides/open/editor-token")
    assert result["validation"]["ok"] is False
    issue_code = {
        'persistence': 'report_pptx_persistence_failed',
        'context': 'report_slides_context_persistence_failed',
        'download_grant': 'report_pptx_download_grant_failed',
        'editor_grant': 'report_slides_editor_grant_failed',
        'preview': 'pptx_preview_render_failed',
    }[fault]
    assert any(issue['code'] == issue_code for issue in result['validation']['issues'])
    if fault != 'context':
        assert len(applied) == 1
        assert applied[0][1] == 8
        saved_context = applied[0][0].payload["context"]
        assert revision_path.fullmatch(saved_context["pptxPath"])


def _validating_service(context: ReportEditorContext) -> ReportSlidesEditorService:
    service = ReportSlidesEditorService(state_repository=None, workspace_registry=None, workspace=None)

    async def current_context(_session):
        return context

    service.context_for_session = current_context
    return service


_BOX = {"slideIndex": 0, "text": "内部资料", "geometry": {"x": 10, "y": 10, "width": 200, "height": 80}}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"backgrounds": [{"slideIndex": 0, "color": "red"}]}, "页面背景内容无效"),
        ({"backgrounds": [{"slideIndex": 0, "color": "#FFFFFF"}, {"slideIndex": 0, "color": "#000000"}]}, "只能设置一次背景"),
        ({"textBoxes": [{**_BOX, "geometry": {"x": 0, "y": 0, "width": 0, "height": 10}}]}, "新增文本框内容无效"),
        ({"textBoxes": [{**_BOX, "rotation": float("nan")}]}, "新增文本框内容无效"),
        ({"textBoxes": [{**_BOX, "script": "x"}]}, "新增文本框内容无效"),
        ({"deletions": [{"slideIndex": 0, "elementId": "s1"}, {"slideIndex": 0, "elementId": "s1"}]}, "删除对象重复"),
        ({"deletions": [{"slideIndex": 0, "elementId": "s1"}],
          "edits": [{"slideIndex": 0, "elementId": "s1", "text": "x"}]}, "不能同时修改"),
    ],
)
async def test_slides_save_rejects_invalid_structure_edits(extra, message):
    context = _context()
    with pytest.raises(ReportingError, match=message):
        await _validating_service(context).save_revision(
            _session(context), {"expectedSha256": context.pptx_sha256, "edits": [], **extra},
        )


@pytest.mark.anyio
async def test_slides_save_passes_structure_edits_to_engine(monkeypatch):
    from smart_reporting.report_editor import slides

    context = _context()
    service = _validating_service(context)
    captured: dict[str, object] = {}

    async def read_verified(_context):
        return b"source"

    def run_engine(_content, action, **kwargs):
        captured.update(kwargs, action=action)
        raise ReportingError("report_slides_engine_failed", "stop after engine")

    service._read_verified_pptx = read_verified
    monkeypatch.setattr(slides.ReportSlidesEditorService, "_run_engine", staticmethod(run_engine))
    payload = {
        "expectedSha256": context.pptx_sha256,
        "edits": [],
        "backgrounds": [{"slideIndex": 0, "color": "#F4F6F8"}],
        "textBoxes": [{**_BOX, "fontSize": 64, "color": "#DCE3EB", "rotation": -25}],
        "deletions": [{"slideIndex": 0, "elementId": "s2"}],
    }
    with pytest.raises(ReportingError, match="stop after engine"):
        await service.save_revision(_session(context), payload)

    assert captured["action"] == "edit"
    assert captured["backgrounds"] == payload["backgrounds"]
    assert captured["text_boxes"] == payload["textBoxes"]
    assert captured["deletions"] == payload["deletions"]
