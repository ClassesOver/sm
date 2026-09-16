from __future__ import annotations

import shutil
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
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
    _normalize_cjk_strong_markers,
    normalize_report_markdown_strong_spacing,
)
from smart_reporting.reporting.delivery.report_runtime.pdf import (
    DEFAULT_PAGE_LAYOUT,
    _apply_pdf_page_decorations,
    _page_number_context,
)
from smart_reporting.reporting.workspace import WorkspaceReportService, _report_runtime_digest
from smart_reporting.workspace import WorkspaceError


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


def test_cli_forwards_only_pdf_and_word_output_paths(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    captured: dict[str, object] = {}

    class FakeRuntime:
        def __init__(self, _workspace: Path) -> None:
            pass

        def render_markdown(self, *args: object) -> dict[str, object]:
            captured["args"] = args
            return {"status": "rendered", "wordPath": "reports/report.docx"}

    monkeypatch.setattr(runtime_cli, "ReportRuntime", FakeRuntime)
    assert (
        runtime_cli.main(
            [
                "render_markdown",
                '{"job": {}, "markdown_path": "report.md", "output_path": "report.pdf", '
                '"temporary_path": "/tmp/workspace-report-test/render.pdf", '
                '"word_output_path": "report.docx"}',
            ]
        )
        == 0
    )

    assert captured["args"][-1] == "report.docx"
    assert len(captured["args"]) == 6
    assert '"wordPath": "reports/report.docx"' in capsys.readouterr().out


def test_render_markdown_returns_only_pdf_and_word_artifact_identity(
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

    assert "html" not in result["render"]
    assert "htmlPath" not in result
    assert output.is_file()
    assert output.with_suffix(".docx").is_file()
    assert not output.with_suffix(".html").exists()


@pytest.mark.anyio
async def test_report_runtime_uploads_verified_package_for_fixed_python_entrypoint(
    tmp_path: Path,
) -> None:
    del tmp_path

    class Workspace:
        def __init__(self) -> None:
            self.writes: list[tuple[str, str, bytes]] = []
            self.commands: list[tuple[str, list[str], int, int]] = []
            self.deletes: list[tuple[str, str]] = []

        async def awrite_bytes(self, thread: str, path: str, content: bytes) -> None:
            self.writes.append((thread, path, content))

        async def arun_command(
            self, thread: str, args: list[str], *, timeout: int, tail: int
        ) -> str:
            self.commands.append((thread, args, timeout, tail))
            return '{"status":"ok"}\n{"__reportExitCode":0}'

        async def adelete_file(self, thread: str, path: str) -> None:
            self.deletes.append((thread, path))

    workspace = Workspace()
    report_workspace = WorkspaceReportService(workspace)  # type: ignore[arg-type]

    result = await report_workspace._run_report_runtime(
        "validate_pdf",
        {"job": {}},
        RunContext(run_id="report-runtime-run", session_id="report-runtime-package"),
    )

    assert len(workspace.commands) == 1
    thread, args, timeout, tail = workspace.commands[0]
    assert thread == "report-runtime-package"
    assert len(workspace.writes) == 1
    _thread, archive_path, archive = workspace.writes[0]
    assert archive_path.startswith(".workspace-report-runtime-")
    assert archive_path.endswith(f"-{_report_runtime_digest()}.zip")
    assert workspace.deletes == [(thread, archive_path)]
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
    script = args[2]
    assert args[1] == "-c"
    assert "from report_runtime.cli import main" in script
    assert "sys.path.insert(0" in script
    assert archive_path in script
    assert _report_runtime_digest() in script
    assert "报表运行时版本不匹配" in script
    assert "validate_pdf" in script
    assert timeout == 600
    assert tail == 200
    assert result == {"status": "ok"}


@pytest.mark.anyio
async def test_report_runtime_preserves_structured_error_before_stderr_warning(
    tmp_path: Path,
) -> None:
    del tmp_path

    class Workspace:
        async def awrite_bytes(self, *_args: object) -> None:
            return None

        async def arun_command(self, *_args: object, **_kwargs: object) -> str:
            return (
                '{"error":"Markdown 正式章节标识与已批准提纲不一致"}\n'
                '{"__reportExitCode":1}'
            )

        async def adelete_file(self, *_args: object) -> None:
            return None

    report_workspace = WorkspaceReportService(Workspace())  # type: ignore[arg-type]

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
