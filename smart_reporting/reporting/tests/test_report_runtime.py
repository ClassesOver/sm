from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from agno.run import RunContext

from smart_reporting.reporting.delivery.report_runtime import cli as runtime_cli
from smart_reporting.reporting.delivery.report_runtime import docx as docx_module
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
from smart_reporting.reporting.delivery.report_runtime.validation import (
    ReportFailure,
    _temporary_pdf_path,
    _validation_directory,
)
from smart_reporting.reporting.workspace import WorkspaceReportService, _report_runtime_digest
from smart_reporting.workspace import WorkspaceError


def test_render_docx_uses_libreoffice_when_pandoc_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "render.docx"
    calls: list[list[str]] = []

    monkeypatch.setattr(
        docx_module.shutil,
        "which",
        lambda name: "/usr/bin/libreoffice" if name == "libreoffice" else None,
    )

    def fake_run(command, **_kwargs):
        calls.append(command)
        Path(command[command.index("--outdir") + 1], output.name).write_bytes(
            b"PK\x03\x04fake-docx"
        )
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(docx_module.subprocess, "run", fake_run)
    monkeypatch.setattr(docx_module, "_postprocess_docx", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(docx_module, "_validate_docx_structure", lambda *_args, **_kwargs: {})

    result = docx_module._render_docx(
        "<html><body>报告</body></html>",
        source_parent=tmp_path,
        output=output,
        context={"sections": [], "headingNumbers": []},
        layout={},
    )

    assert result == {}
    assert calls and calls[0][0] == "/usr/bin/libreoffice"
    assert calls[0][1].startswith("-env:UserInstallation=file://")
    assert calls[0][2:6] == ["--headless", "--convert-to", "docx:MS Word 2007 XML", "--outdir"]
    assert "--outdir" in calls[0]
    assert output.is_file()


@pytest.mark.parametrize("kind", ["render", "validate"])
def test_report_temporary_paths_are_private_workspace_directories(tmp_path: Path, kind: str):
    relative = f".reporting-tmp/workspace-report-test-{kind}"
    create = _temporary_pdf_path if kind == "render" else _validation_directory
    value = relative + "/render.pdf" if kind == "render" else relative
    path = create(tmp_path, value)
    directory = path.parent if kind == "render" else path
    assert directory == tmp_path / relative
    assert directory.is_dir()
    assert directory.stat().st_mode & 0o777 == 0o700
    with pytest.raises(ReportFailure):
        create(tmp_path, value)


@pytest.mark.parametrize("kind", ["render", "validate"])
@pytest.mark.parametrize("prefix", ["/tmp", "../outside", "reports", ".reporting-tmp/nested"])
def test_report_temporary_paths_reject_unscoped_directories(tmp_path: Path, kind: str, prefix: str):
    create = _temporary_pdf_path if kind == "render" else _validation_directory
    value = f"{prefix}/workspace-report-test-{kind}"
    if kind == "render":
        value += "/render.pdf"
    with pytest.raises(ReportFailure):
        create(tmp_path, value)


@pytest.mark.parametrize("kind", ["render", "validate"])
def test_report_temporary_paths_reject_symlink_root(tmp_path: Path, kind: str):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".reporting-tmp").symlink_to(outside, target_is_directory=True)
    create = _temporary_pdf_path if kind == "render" else _validation_directory
    value = f".reporting-tmp/workspace-report-test-{kind}"
    if kind == "render":
        value += "/render.pdf"
    with pytest.raises(ReportFailure):
        create(tmp_path, value)
    assert list(outside.iterdir()) == []


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
                '"temporary_path": ".reporting-tmp/workspace-report-test-render/render.pdf", '
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

    temporary_root = tmp_path / ".reporting-tmp" / f"workspace-report-{uuid.uuid4().hex}-render"
    try:
        result = runtime_module.ReportRuntime(tmp_path).render_markdown(
            state,
            "report.md",
            "revision/report.pdf",
            str((temporary_root / "render.pdf").relative_to(tmp_path)),
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
    assert len(workspace.writes) == 2
    (_thread, payload_path, payload), (_thread, archive_path, archive) = workspace.writes
    assert payload_path.endswith("-payload.json")
    assert payload == b'{"job":{}}'
    assert archive_path.startswith(".workspace-report-runtime-")
    assert archive_path.endswith(f"-{_report_runtime_digest()}.zip")
    assert workspace.deletes == [(thread, archive_path), (thread, payload_path)]
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
    assert payload_path in script
    assert timeout == 600
    assert tail == 200
    assert result == {"status": "ok"}


@pytest.mark.anyio
async def test_report_runtime_passes_large_payload_without_argv_limit(tmp_path: Path) -> None:
    import subprocess

    class Workspace:
        async def awrite_bytes(self, _thread: str, path: str, content: bytes) -> None:
            (tmp_path / path).write_bytes(content)

        async def arun_command(
            self, _thread: str, args: list[str], *, timeout: int, tail: int
        ) -> str:
            del tail
            process = subprocess.run(
                args, cwd=tmp_path, capture_output=True, text=True, timeout=timeout, check=False
            )
            return process.stdout

        async def adelete_file(self, _thread: str, path: str) -> None:
            (tmp_path / path).unlink(missing_ok=True)

    # 真实渲染回执与产物清单可超过 Linux 单个命令行参数的 128 KiB 上限。
    payload = {"job": {"notes": ["引用覆盖说明" * 20] * 800}}
    assert len(json.dumps(payload, ensure_ascii=False).encode()) > 128 * 1024

    with pytest.raises(WorkspaceError) as caught:
        await WorkspaceReportService(Workspace())._run_report_runtime(  # type: ignore[arg-type]
            "validate_pdf",
            payload,
            RunContext(run_id="report-runtime-run", session_id="report-runtime-package"),
        )

    # 进程成功启动并由 runtime 返回结构化业务错误，而不是 Argument list too long。
    assert "Argument list too long" not in str(caught.value)
    assert "报表运行时返回无效结果" not in str(caught.value)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.anyio
async def test_report_runtime_preserves_structured_error_before_stderr_warning(
    tmp_path: Path,
) -> None:
    del tmp_path

    class Workspace:
        async def awrite_bytes(self, *_args: object) -> None:
            return None

        async def arun_command(self, *_args: object, **_kwargs: object) -> str:
            return '{"error":"Markdown 正式章节标识与已批准提纲不一致"}\n{"__reportExitCode":1}'

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


def _png(path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4), "white").save(path)


def _image_tokens(markdown: str) -> list[Any]:
    from markdown_it import MarkdownIt

    return MarkdownIt("commonmark").parse(markdown)


def _draft_state(*paths: str) -> dict[str, Any]:
    return {"render": {"images": [{"path": path} for path in paths]}}


def test_draft_images_fall_back_to_render_manifest(tmp_path: Path) -> None:
    _png(tmp_path / "reports/r1/chart.png")
    draft = tmp_path / "reports/r1/revision-2/draft/report.md"
    runtime = runtime_module.ReportRuntime(tmp_path)

    images = runtime._images(
        draft, _image_tokens("![图](chart.png)"), _draft_state("reports/r1/chart.png")
    )

    assert images == {(tmp_path / "reports/r1/chart.png").resolve()}
    body = '<p><img src="chart.png" alt="图"></p>'
    inlined = runtime._inline_images(body, draft.parent, images, runtime._image_sources)
    assert "data:image/png;base64," in inlined


def test_manifest_fallback_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "reports/r1/draft").mkdir(parents=True)
    _png(tmp_path / "outside/chart.png")
    draft = workspace / "reports/r1/draft/report.md"
    runtime = runtime_module.ReportRuntime(workspace)

    with pytest.raises(ReportFailure, match="不存在或格式不受支持"):
        runtime._images(
            draft, _image_tokens("![图](chart.png)"), _draft_state("../outside/chart.png")
        )


def test_manifest_fallback_prefers_ancestor_and_rejects_ambiguity(tmp_path: Path) -> None:
    _png(tmp_path / "reports/r1/chart.png")
    _png(tmp_path / "reports/r2/chart.png")
    runtime = runtime_module.ReportRuntime(tmp_path)
    state = _draft_state("reports/r2/chart.png", "reports/r1/chart.png")

    images = runtime._images(
        tmp_path / "reports/r1/revision-2/draft/report.md",
        _image_tokens("![图](chart.png)"),
        state,
    )
    assert images == {(tmp_path / "reports/r1/chart.png").resolve()}

    with pytest.raises(ReportFailure, match="多个同名候选"):
        runtime._images(
            tmp_path / "other/draft/report.md", _image_tokens("![图](chart.png)"), state
        )


@pytest.mark.parametrize(
    ("physical_page", "body_start_page", "expected"),
    [(1, 1, (1, 5)), (5, 1, (5, 5)), (1, 2, ("i", "i")), (2, 2, (1, 4))],
)
def test_page_number_context_without_cover_numbers_from_first_page(
    physical_page: int, body_start_page: int, expected: tuple[str | int, str | int]
) -> None:
    assert (
        _page_number_context(
            physical_page,
            body_start_page=body_start_page,
            physical_page_count=5,
            first_numbered_page=1,
        )
        == expected
    )


def test_pdf_decorations_without_cover_cover_every_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pypdf

    path = tmp_path / "report.pdf"
    writer = pypdf.PdfWriter()
    for _index in range(2):
        writer.add_blank_page(width=595.276, height=841.89)
    with path.open("wb") as stream:
        writer.write(stream)
    monkeypatch.setattr(
        "smart_reporting.reporting.delivery.report_runtime.pdf._pdf_section_pages",
        lambda _reader, _sections: {"section_001": 1},
    )

    _apply_pdf_page_decorations(
        path,
        context={
            "title": "Report",
            "organizationName": "Org",
            "watermarkText": "Internal",
            "sections": [{"code": "section_001"}],
        },
        layout=DEFAULT_PAGE_LAYOUT,
        include_cover=False,
    )

    texts = [page.extract_text() or "" for page in pypdf.PdfReader(str(path)).pages]
    assert all("Internal" in text for text in texts)


@pytest.mark.parametrize(
    ("include_cover", "include_toc"), [(False, True), (True, False), (False, False)]
)
def test_postprocess_docx_follows_cover_and_toc_export_settings(
    tmp_path: Path, include_cover: bool, include_toc: bool
) -> None:
    docx = pytest.importorskip("docx")
    from smart_reporting.reporting.delivery.report_runtime.markdown import _WORD_MARKERS

    context = {
        **_docx_postprocess_context(),
        "headingNumbers": [
            {
                "level": 2,
                "number": "1",
                "title": "经营概览",
                "sectionCode": "overview",
                "anchor": "report-heading-overview",
            }
        ],
    }
    document = docx.Document()
    texts = [
        *(["测试报告"] if include_cover else []),
        _WORD_MARKERS["cover_end"],
        *(["目录"] if include_toc else []),
        _WORD_MARKERS["toc_field_start"],
        *(["1. 经营概览"] if include_toc else []),
        _WORD_MARKERS["toc_field_end"],
        _WORD_MARKERS["toc_end"],
        _WORD_MARKERS["body_start"],
        *([] if include_cover else ["测试报告"]),
        "1. 经营概览",
        "测试机构",
        "2026-08-17",
    ]
    for text in texts:
        document.add_paragraph(text)
    path = tmp_path / "report.docx"
    document.save(path)

    _postprocess_docx(
        path,
        context=context,
        layout=DEFAULT_PAGE_LAYOUT,
        include_cover=include_cover,
        include_toc=include_toc,
    )

    processed = docx.Document(path)
    assert len(processed.sections) == 1 + include_cover + include_toc
    paragraph_texts = [item.text for item in processed.paragraphs]
    assert not any(marker in paragraph_texts for marker in _WORD_MARKERS.values())
    # 无封面时首个分节即带页眉页脚；有封面时封面分节不带页面元素。
    first_header = processed.sections[0].header
    assert first_header.is_linked_to_previous is include_cover
    with zipfile.ZipFile(path) as package:
        document_xml = package.read("word/document.xml").decode()
    assert ('TOC \\o "1-3"' in document_xml) is include_toc


def test_semantic_documents_without_cover_keep_title_in_body() -> None:
    from smart_reporting.reporting.delivery.report_runtime.markdown import (
        _WORD_MARKERS,
        _semantic_documents,
    )

    context = {
        **_docx_postprocess_context(),
        "headingNumbers": [
            {
                "level": 2,
                "number": "1",
                "title": "经营概览",
                "sectionCode": "overview",
                "anchor": "report-heading-overview",
            }
        ],
    }
    pdf_document, word_document = _semantic_documents(
        "<h2>1 经营概览</h2>",
        context=context,
        layout=DEFAULT_PAGE_LAYOUT,
        include_cover=False,
        include_toc=False,
    )

    assert 'class="report-cover"' not in pdf_document
    assert 'class="report-toc"' not in pdf_document
    assert '<h1 class="report-title">测试报告</h1>' in pdf_document
    assert all(marker in word_document for marker in _WORD_MARKERS.values())
    assert "<h1>目录</h1>" not in word_document
    body = word_document.split(_WORD_MARKERS["body_start"], 1)[1]
    assert "<h1>测试报告</h1>" in body


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("output", "message"),
    [
        ("Error: command timed out after 600 seconds", "报表运行时执行超时"),
        ("Error (exit 137): Killed", "报表运行时进程异常退出"),
    ],
)
async def test_report_runtime_classifies_process_failures(output: str, message: str) -> None:
    class Workspace:
        async def awrite_bytes(self, *_args: object) -> None:
            return None

        async def arun_command(self, *_args: object, **_kwargs: object) -> str:
            return output

        async def adelete_file(self, *_args: object) -> None:
            return None

    with pytest.raises(WorkspaceError, match=message):
        await WorkspaceReportService(Workspace())._run_report_runtime(  # type: ignore[arg-type]
            "render_markdown",
            {"job": {}},
            RunContext(run_id="report-runtime-run", session_id="report-runtime-package"),
        )
