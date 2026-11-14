"""Word chart DPI applies only to registered static chart media and is read from DOCX OOXML."""

import hashlib
import zipfile
from io import BytesIO

from docx import Document
from docx.shared import Inches
from PIL import Image

from smart_reporting.preferences.document_adapter import document_design
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.report_runtime.word_image_dpi import (
    apply_word_chart_image_dpi,
    read_word_chart_image_dpi,
    verify_word_chart_image_dpi,
)


def _png(size, color):
    image = Image.new("RGB", size, color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _image_parts(path):
    with zipfile.ZipFile(path) as package:
        return {name: package.read(name) for name in package.namelist()
            if name.startswith("word/media/")}


def test_word_dpi_creates_chart_only_derived_media_and_reads_effective_dpi(tmp_path):
    chart = _png((1200, 600), "navy")
    illustration = _png((320, 160), "green")
    chart_path = tmp_path / "chart.png"
    illustration_path = tmp_path / "illustration.png"
    chart_path.write_bytes(chart)
    illustration_path.write_bytes(illustration)

    document = Document()
    document.add_picture(str(chart_path), width=Inches(2))
    document.add_picture(str(illustration_path), width=Inches(2))
    output = tmp_path / "report.docx"
    document.save(output)
    before = _image_parts(output)
    chart_sha = hashlib.sha256(chart).hexdigest()

    receipt = apply_word_chart_image_dpi(output, target_dpi=150, chart_source_sha256s={chart_sha})

    after = _image_parts(output)
    assert receipt["status"] == "applied"
    assert len(receipt["images"]) == 1
    assert receipt["images"][0]["sourceSha256"] == chart_sha
    assert receipt["images"][0]["sourcePixels"] == {"width": 1200, "height": 600}
    assert receipt["images"][0]["outputPixels"] == {"width": 300, "height": 150}
    assert receipt["images"][0]["effectiveDpi"] == {"x": 150.0, "y": 150.0}
    assert any(value == chart for value in after.values())
    assert any(value == illustration for value in after.values())
    derived = [value for value in after.values() if value not in before.values()]
    assert len(derived) == 1
    readback = read_word_chart_image_dpi(output)
    row = next(item for item in readback
        if item["relationshipId"] == receipt["images"][0]["relationshipId"])
    assert row["outputPixels"] == receipt["images"][0]["outputPixels"]
    assert row["effectiveDpi"] == receipt["images"][0]["effectiveDpi"]


def test_word_dpi_does_not_upsample_or_rewrite_unregistered_chart_media(tmp_path):
    chart = _png((240, 120), "navy")
    chart_path = tmp_path / "chart.png"
    chart_path.write_bytes(chart)
    document = Document()
    document.add_picture(str(chart_path), width=Inches(2))
    output = tmp_path / "report.docx"
    document.save(output)
    before = _image_parts(output)

    receipt = apply_word_chart_image_dpi(output, target_dpi=300,
        chart_source_sha256s={hashlib.sha256(chart).hexdigest(), "unmatched-source"})

    assert receipt["status"] == "unchanged"
    assert receipt["images"] == []
    assert _image_parts(output) == before
    rows = read_word_chart_image_dpi(output)
    assert rows == [{
        "relationshipId": rows[0]["relationshipId"],
        "mediaSha256": hashlib.sha256(chart).hexdigest(),
        "outputPixels": {"width": 240, "height": 120},
        "extentEmu": {"width": 1828800, "height": 914400},
        "effectiveDpi": {"x": 120.0, "y": 120.0},
    }]


def test_word_dpi_skips_media_shared_with_a_non_document_part(tmp_path):
    chart = _png((1200, 600), "navy")
    chart_path = tmp_path / "chart.png"
    chart_path.write_bytes(chart)
    document = Document()
    document.add_picture(str(chart_path), width=Inches(2))
    header = document.sections[0].header
    header.paragraphs[0].add_run().add_picture(str(chart_path), width=Inches(1))
    output = tmp_path / "report.docx"
    document.save(output)
    before = _image_parts(output)

    receipt = apply_word_chart_image_dpi(output, target_dpi=150,
        chart_source_sha256s={hashlib.sha256(chart).hexdigest()})

    assert receipt == {"status": "unchanged", "images": [],
        "issues": ["chart_media_reused_ambiguously"]}
    assert _image_parts(output) == before


def test_word_dpi_reaches_real_report_export_and_is_returned_from_final_package(tmp_path):
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
    from smart_reporting.reporting.tests.test_report_runtime_full_render import (
        _IMAGE_RENDER_TEMPORARY_PDF_PATH,
        _build_image_workspace,
    )

    workspace = tmp_path / "workspace"
    state = _build_image_workspace(workspace)
    chart = workspace / "reports/r1/chart.png"
    chart.write_bytes(_png((1920, 800), "navy"))
    preferences = FormatPreferences.model_validate({
        "common": {"signer": "DPI 验证"},
        "word": {"cover": False, "toc": False, "sources": False,
            "headerFooter": {"enabled": False, "pageNumbers": False},
            "watermark": {"enabled": False}, "charts": {"imageDpi": 150}},
    })
    resolved = resolve_format_preferences(preferences, "word")
    state["_formatPreferences"] = {"word": resolved}
    state["_formatDesigns"] = {"word": document_design(resolved).compact()}

    result = ReportRuntime(workspace).render_markdown(state,
        "reports/r1/revision-1/draft/report.md", "reports/r1/revision-1/report.pdf",
        _IMAGE_RENDER_TEMPORARY_PDF_PATH)

    assert result["status"] == "rendered"
    dpi = result["render"]["wordStructure"]["chartImageDpi"]
    assert dpi["status"] == "applied" and len(dpi["images"]) == 1
    row = dpi["images"][0]
    assert row["sourceSha256"] == hashlib.sha256(chart.read_bytes()).hexdigest()
    readback = read_word_chart_image_dpi(workspace / "reports/r1/revision-1/report.docx")
    actual = next(item for item in readback if item["relationshipId"] == row["relationshipId"])
    assert actual["mediaSha256"] == row["derivedSha256"]
    assert actual["outputPixels"] == row["outputPixels"]
    assert actual["extentEmu"] == row["extentEmu"]
    assert actual["effectiveDpi"] == row["effectiveDpi"]
    assert verify_word_chart_image_dpi(workspace / "reports/r1/revision-1/report.docx", dpi)
    corrupted = {**dpi, "images": [{**row, "derivedSha256": "0" * 64}]}
    assert not verify_word_chart_image_dpi(workspace / "reports/r1/revision-1/report.docx", corrupted)
