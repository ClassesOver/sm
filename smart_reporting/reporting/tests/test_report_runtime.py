from __future__ import annotations

import hashlib
import shutil
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agno.run import RunContext

from smart_reporting.reporting.delivery.report_runtime import cli as runtime_cli
from smart_reporting.reporting.delivery.report_runtime import runtime as runtime_module
from smart_reporting.reporting.delivery.report_runtime.docx import (
    _WORD_PAGE_FIELDS,
    _fit_image_dimensions,
    _postprocess_docx,
)
from smart_reporting.reporting.delivery.report_runtime.markdown import (
    _html_document,
    _normalize_cjk_strong_markers,
    normalize_report_markdown_strong_spacing,
)
from smart_reporting.reporting.delivery.report_runtime.pdf import (
    DEFAULT_PAGE_LAYOUT,
    _apply_pdf_page_decorations,
    _page_number_context,
)
from smart_reporting.reporting.tests.workspace_fakes import (
    AsyncFakeClient,
    AsyncMemoryRegistry,
    service,
)
from smart_reporting.reporting.workspace import WorkspaceReportService, _report_runtime_digest
from smart_reporting.sandbox import ExecutionStatus, RunPythonScriptResult
from smart_reporting.workspace import WORKSPACE_ROOT, WorkspaceError, WorkspaceService


@pytest.mark.parametrize(
    ("width", "height", "maximum_width", "maximum_height", "expected"),
    [
        (2_000, 1_000, 1_000, 1_500, (1_000, 500)),
        (1_000, 2_000, 1_500, 1_000, (500, 1_000)),
        (1_000, 500, 1_500, 1_000, (1_000, 500)),
    ],
)
def test_fit_image_dimensions_preserves_aspect_ratio_within_bounds(
    width: int,
    height: int,
    maximum_width: int,
    maximum_height: int,
    expected: tuple[int, int],
) -> None:
    assert _fit_image_dimensions(width, height, maximum_width, maximum_height) == expected


def test_pdf_page_decorations_are_merged_above_report_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pypdf

    path = tmp_path / "report.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=595.276, height=841.89)
    writer.add_blank_page(width=595.276, height=841.89)
    with path.open("wb") as stream:
        writer.write(stream)

    monkeypatch.setattr(
        "smart_reporting.reporting.delivery.report_runtime.pdf._pdf_section_pages",
        lambda _reader, _sections: {"section_001": 2},
    )
    merge_layers: list[bool] = []
    original_merge_page = pypdf.PageObject.merge_page

    def track_merge_page(self, page2, expand=False, over=True):
        merge_layers.append(over)
        return original_merge_page(self, page2, expand=expand, over=over)

    monkeypatch.setattr(pypdf.PageObject, "merge_page", track_merge_page)

    _apply_pdf_page_decorations(
        path,
        context={
            "title": "测试报告",
            "organizationName": "测试机构",
            "watermarkText": "内部资料",
            "sections": [{"code": "section_001"}],
        },
        layout=DEFAULT_PAGE_LAYOUT,
    )

    assert merge_layers == [True]


def test_html_document_is_static_and_self_contained() -> None:
    document = _html_document(
        '<p>正文</p><img src="data:image/png;base64,AAAA">',
        context={
            "title": "测试报告",
            "periodLabel": "2026 年",
            "organizationName": "测试机构",
            "generatedByLabel": "Reporting Agent",
            "watermarkText": "内部资料",
            "generatedDate": "2026-08-17",
            "sections": [{"code": "overview", "title": "经营概览", "sectionNumber": "1"}],
            "sectionNumbers": ["1"],
            "headingNumbers": [
                {
                    "level": 2,
                    "number": "1",
                    "title": "经营概览",
                    "sectionCode": "overview",
                    "anchor": "report-heading-overview",
                }
            ],
        },
        layout=DEFAULT_PAGE_LAYOUT,
    )

    assert document.startswith("<!doctype html>")
    assert "<html lang='zh-CN'>" in document
    assert "<style>" in document
    assert "<script" not in document.lower()
    assert "<form" not in document.lower()
    assert "http://" not in document
    assert "https://" not in document
    assert "data:image/png;base64,AAAA" in document


@pytest.mark.parametrize(
    "href", ["https://example.com", "//example.com", "report.md", "mailto:a@example.com"]
)
def test_html_rejects_markdown_links(href: str) -> None:
    from markdown_it import MarkdownIt

    body = MarkdownIt("commonmark", {"html": False}).render(f"[链接]({href})")

    with pytest.raises(ValueError, match="不允许外部或工作区链接"):
        runtime_module.ReportRuntime._reject_html_links(body)


def test_cli_forwards_optional_html_output_path(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeRuntime:
        def __init__(self, _workspace: Path) -> None:
            pass

        def render_markdown(self, *args: object) -> dict[str, object]:
            captured["args"] = args
            return {"status": "rendered", "htmlPath": "reports/report.html"}

    monkeypatch.setattr(runtime_cli, "ReportRuntime", FakeRuntime)
    assert (
        runtime_cli.main(
            [
                "render_markdown",
                '{"job": {}, "markdown_path": "report.md", "output_path": "report.pdf", '
                '"temporary_path": "/tmp/workspace-report-test/render.pdf", '
                '"html_output_path": "report.html"}',
            ]
        )
        == 0
    )

    assert captured["args"][-1] == "report.html"
    assert '"htmlPath": "reports/report.html"' in capsys.readouterr().out


def test_render_markdown_returns_html_artifact_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "report.md"
    source.write_text(
        "# 测试报告\n\n## 1. 经营概览\n\n[[section:overview]]\n正文。\n",
        encoding="utf-8",
    )
    output = tmp_path / "revision" / "report.pdf"
    output.parent.mkdir()
    state = {
        "jobId": "job-1",
        "sources": [],
        "_documentContext": {
            "title": "测试报告",
            "periodLabel": "2026 年",
            "organizationName": "测试机构",
            "generatedByLabel": "Reporting Agent",
            "watermarkText": "内部资料",
            "generatedDate": "2026-08-17",
            "sections": [{"code": "overview", "sectionNumber": "1", "title": "经营概览"}],
            "sectionNumbers": ["1"],
            "headingNumbers": [
                {
                    "level": 2,
                    "number": "1",
                    "title": "经营概览",
                    "sectionCode": "overview",
                    "anchor": "report-heading-overview",
                }
            ],
        },
    }
    monkeypatch.setattr(runtime_module.ReportRuntime, "_validate_datasets", lambda *_: None)
    monkeypatch.setattr(runtime_module.ReportRuntime, "_images", lambda *_: set())
    monkeypatch.setattr(
        runtime_module, "_apply_pdf_page_decorations", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        runtime_module,
        "_render_docx",
        lambda *_args, **kwargs: kwargs["output"].write_bytes(b"docx") or {},
    )
    monkeypatch.setattr(runtime_module, "_validate_docx_structure", lambda *_args, **_kwargs: {})
    html_capture: dict[str, bytes] = {}
    original_sha256 = runtime_module._sha256

    def capture_sha256(path: Path) -> str:
        digest = original_sha256(path)
        if path.name == "render.html":
            html_capture["bytes"] = path.read_bytes()
        return digest

    monkeypatch.setattr(runtime_module, "_sha256", capture_sha256)
    monkeypatch.setattr(
        Path,
        "replace",
        lambda *_args, **_kwargs: pytest.fail("私有 /tmp 与 workspace 之间不得使用 rename"),
    )

    temporary_root = Path(f"/tmp/workspace-report-{uuid.uuid4().hex}")
    try:
        result = runtime_module.ReportRuntime(tmp_path).render_markdown(
            state,
            "report.md",
            "revision/report.pdf",
            str(temporary_root / "render.pdf"),
        )
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)

    html_bytes = html_capture["bytes"]
    assert result["render"]["html"]["path"] == "revision/report.html"
    assert result["htmlSize"] == len(html_bytes)
    assert result["htmlSha256"] == hashlib.sha256(html_bytes).hexdigest()
    assert html_bytes.startswith(b"<!doctype html>")
    assert output.is_file()
    assert output.with_suffix(".docx").is_file()
    assert output.with_suffix(".html").read_bytes() == html_bytes


@pytest.mark.anyio
async def test_report_runtime_uploads_verified_package_for_fixed_python_entrypoint(
    tmp_path: Path,
) -> None:
    current = service(tmp_path)
    workspace = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    report_workspace = WorkspaceReportService(workspace)

    class Execution:
        def __init__(self) -> None:
            self.requests = []

        async def run_python_script(self, request):
            self.requests.append(request)
            return RunPythonScriptResult(
                status=ExecutionStatus.SUCCEEDED,
                exit_code=0,
                stdout='{"status":"ok"}\n',
                script_hash=hashlib.sha256(request.script.encode()).hexdigest(),
            )

    class Process:
        async def exec(self, *_args, **_kwargs):
            raise AssertionError("报表运行时不得使用任意 Shell")

    class FileSystem:
        def __init__(self) -> None:
            self.uploads: list[tuple[bytes, str]] = []
            self.deleted: list[str] = []

        async def upload_file(self, content: bytes, path: str) -> None:
            assert path.startswith(f"{WORKSPACE_ROOT}/")
            self.uploads.append((content, path))

        async def delete_file(self, path: str) -> None:
            self.deleted.append(path)

    execution = Execution()
    filesystem = FileSystem()

    async def sandbox_for(_client, _thread):
        return SimpleNamespace(execution=execution, process=Process(), fs=filesystem)

    workspace._asandbox_for = sandbox_for  # type: ignore[method-assign]

    result = await report_workspace._run_report_runtime(
        "validate_pdf",
        {"job": {}},
        RunContext(run_id="report-runtime-run", session_id="report-runtime-package"),
    )

    assert len(execution.requests) == 1
    request = execution.requests[0]
    assert len(filesystem.uploads) == 1
    archive, archive_path = filesystem.uploads[0]
    assert archive_path.startswith(f"{WORKSPACE_ROOT}/.workspace-report-runtime-")
    assert archive_path.endswith(f"-{_report_runtime_digest()}.zip")
    assert filesystem.deleted == [archive_path]
    with zipfile.ZipFile(BytesIO(archive)) as package:
        assert set(package.namelist()) == {
            "report_runtime/__init__.py",
            "report_runtime/cli.py",
            "report_runtime/docx.py",
            "report_runtime/markdown.py",
            "report_runtime/pdf.py",
            "report_runtime/runtime.py",
            "report_runtime/validation.py",
        }
    assert "from report_runtime.cli import main" in request.script
    assert "sys.path.insert(0" in request.script
    assert archive_path not in request.script
    assert archive_path.removeprefix(f"{WORKSPACE_ROOT}/") in request.script
    assert _report_runtime_digest() in request.script
    assert "报表运行时版本不匹配" in request.script
    assert "validate_pdf" in request.script
    assert request.timeout_ms == 600_000
    assert result == {"status": "ok"}


@pytest.mark.anyio
async def test_report_runtime_preserves_structured_error_before_stderr_warning(
    tmp_path: Path,
) -> None:
    current = service(tmp_path)
    workspace = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    report_workspace = WorkspaceReportService(workspace)

    class Execution:
        async def run_python_script(self, request):
            return RunPythonScriptResult(
                status=ExecutionStatus.FAILED,
                exit_code=1,
                stdout='{"error":"Markdown 正式章节标识与已批准提纲不一致"}\n',
                stderr="Fontconfig warning: ignored invalid cache\n",
                script_hash=hashlib.sha256(request.script.encode()).hexdigest(),
            )

    class FileSystem:
        async def upload_file(self, _content: bytes, _path: str) -> None:
            return None

        async def delete_file(self, _path: str) -> None:
            return None

    async def sandbox_for(_client, _thread):
        return SimpleNamespace(execution=Execution(), fs=FileSystem())

    workspace._asandbox_for = sandbox_for  # type: ignore[method-assign]

    with pytest.raises(
        WorkspaceError,
        match="Markdown 正式章节标识与已批准提纲不一致",
    ):
        await report_workspace._run_report_runtime(
            "validate_pdf",
            {"job": {}},
            RunContext(run_id="report-runtime-run", session_id="report-runtime-package"),
        )


def test_normalize_cjk_strong_markers_supports_chinese_punctuation() -> None:
    from markdown_it import MarkdownIt

    markdown = "呈**“年初低位—3月跳升”**形态"

    normalized = _normalize_cjk_strong_markers(markdown)
    rendered = MarkdownIt("commonmark", {"html": False}).render(normalized)

    assert normalized == "呈 **“年初低位—3月跳升”** 形态"
    assert "<strong>“年初低位—3月跳升”</strong>" in rendered
    assert "**" not in rendered


def test_normalize_cjk_strong_markers_preserves_unmatched_stars() -> None:
    markdown = "数量增长 * 2，备注 **未闭合"

    assert _normalize_cjk_strong_markers(markdown) == markdown


def test_normalize_spaced_strong_markers_renders_budget_values() -> None:
    from markdown_it import MarkdownIt

    markdown = "预算为 ** 131.73 亿元 **，执行率 ** 95.14% **。"

    normalized = _normalize_cjk_strong_markers(markdown)
    rendered = MarkdownIt("commonmark", {"html": False}).render(normalized)

    assert normalized == "预算为 **131.73 亿元**，执行率 **95.14%**。"
    assert "<strong>131.73 亿元</strong>" in rendered
    assert "<strong>95.14%</strong>" in rendered
    assert "**" not in rendered


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("由** 总部院区**、", "由**总部院区**、"),
        ("由**总部院区 **、", "由**总部院区**、"),
        ("由** 总部院区 **、", "由**总部院区**、"),
        ("由**总部院区**、", "由**总部院区**、"),
        ("** 总部院区**", "**总部院区**"),
    ],
)
def test_normalize_spaced_chinese_strong_markers(source: str, expected: str) -> None:
    from markdown_it import MarkdownIt

    normalized = normalize_report_markdown_strong_spacing(source)
    rendered = MarkdownIt("commonmark", {"html": False}).render(normalized)

    assert normalized == expected
    assert "<strong>总部院区</strong>" in rendered
    assert "**" not in rendered


@pytest.mark.parametrize(
    "markdown",
    [
        "说明 `由** 总部院区**、`。",
        "```markdown\n** 总部院区**\n```",
        "~~~~\n** 总部院区**\n~~~~",
        "    ** 总部院区**",
    ],
)
def test_normalize_strong_markers_does_not_change_code(markdown: str) -> None:
    assert normalize_report_markdown_strong_spacing(markdown) == markdown
    assert _normalize_cjk_strong_markers(markdown) == markdown


def test_normalize_strong_markers_preserves_math_stars() -> None:
    markdown = "幂运算 2 ** 3，未格式化 ** 2 **。"

    assert _normalize_cjk_strong_markers(markdown) == markdown


@pytest.mark.parametrize(
    ("physical_page", "body_start_page", "physical_page_count", "expected"),
    [
        (2, 3, 25, ("i", "i")),
        (2, 4, 25, ("i", "ii")),
        (3, 4, 25, ("ii", "ii")),
        (3, 3, 25, (1, 23)),
        (25, 3, 25, (23, 23)),
    ],
)
def test_page_number_context_uses_section_page_count(
    physical_page: int,
    body_start_page: int,
    physical_page_count: int,
    expected: tuple[str | int, str | int],
) -> None:
    assert (
        _page_number_context(
            physical_page,
            body_start_page=body_start_page,
            physical_page_count=physical_page_count,
        )
        == expected
    )


def _docx_postprocess_fixture(docx: Any) -> Any:
    document = docx.Document()
    for text in (
        "测试报告",
        "__REPORT_COVER_END__",
        "目录",
        "__REPORT_TOC_FIELD_START__",
        "__REPORT_TOC_FIELD_END__",
        "__REPORT_TOC_END__",
        "__REPORT_BODY_START__",
        "经营概览",
        "测试机构",
        "2026-08-17",
    ):
        document.add_paragraph(text)
    return document


def _docx_postprocess_context() -> dict[str, Any]:
    return {
        "title": "测试报告",
        "periodLabel": "2025 年",
        "organizationName": "测试机构",
        "generatedByLabel": "Reporting Agent",
        "watermarkText": "内部资料",
        "generatedDate": "2026-08-17",
        "sections": [{"code": "overview", "title": "经营概览"}],
        "headingNumbers": [],
    }


def test_postprocess_docx_uses_section_page_count_field(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")

    path = tmp_path / "report.docx"
    document = _docx_postprocess_fixture(docx)
    document.save(path)

    _postprocess_docx(
        path,
        context=_docx_postprocess_context(),
        layout=DEFAULT_PAGE_LAYOUT,
    )

    with zipfile.ZipFile(path) as package:
        footer_xml = "\n".join(
            package.read(name).decode("utf-8")
            for name in package.namelist()
            if name.startswith("word/footer") and name.endswith(".xml")
        )

    assert "SECTIONPAGES" in footer_xml
    assert "NUMPAGES" not in footer_xml


def test_postprocess_docx_scales_tall_image_within_page_bounds(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")
    from docx.shared import Mm
    from PIL import Image

    image_path = tmp_path / "tall.png"
    Image.new("RGB", (600, 1800), "white").save(image_path)
    path = tmp_path / "report.docx"
    document = _docx_postprocess_fixture(docx)
    document.add_picture(str(image_path))
    document.save(path)

    _postprocess_docx(
        path,
        context=_docx_postprocess_context(),
        layout=DEFAULT_PAGE_LAYOUT,
    )

    processed = docx.Document(path)
    assert len(processed.inline_shapes) == 1
    shape = processed.inline_shapes[0]
    assert shape.width <= Mm(174)
    assert shape.height <= Mm(180)
    assert abs(shape.width / shape.height - 1 / 3) < 0.001


def test_word_page_fields_use_section_page_count() -> None:
    assert _WORD_PAGE_FIELDS == {"page": "PAGE", "pages": "SECTIONPAGES"}
