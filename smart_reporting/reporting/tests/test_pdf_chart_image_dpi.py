import hashlib

import pytest
from PIL import Image

from smart_reporting.reporting.delivery.report_runtime.chart_image_dpi import (
    ChartImageSource,
    derive_chart_image,
    verify_chart_image_sources,
)


def _image(path, size):
    Image.new("RGB", size, (20, 80, 140)).save(path, format="PNG")
    content = path.read_bytes()
    return ChartImageSource("chart-1", path.name, len(content), hashlib.sha256(content).hexdigest())


def test_chart_sources_require_manifest_identity_and_markdown_membership(tmp_path):
    chart_path = tmp_path / "chart.png"
    chart = _image(chart_path, (800, 400))
    other_path = tmp_path / "photo.png"
    other = _image(other_path, (800, 400))

    verified = verify_chart_image_sources(tmp_path, [
        {"chartId": chart.chart_id, "path": chart.path, "size": chart.size, "sha256": chart.sha256},
        {"path": other.path, "size": other.size, "sha256": "0" * 64},
        {"path": "../outside.png", "size": other.size, "sha256": other.sha256},
    ], {chart_path, other_path})

    assert verified == {chart_path.resolve(): chart}


def test_chart_derivation_preserves_source_and_never_upsamples(tmp_path):
    path = tmp_path / "chart.png"
    source = _image(path, (800, 400))
    original = path.read_bytes()

    derived = derive_chart_image(path, source, display_width_css_px=96, display_height_css_px=48, target_dpi=150)
    assert derived is not None
    assert (derived.width, derived.height) == (150, 75)
    assert derived.source_sha256 == source.sha256
    assert derived.derived_sha256 == hashlib.sha256(derived.data).hexdigest()
    assert path.read_bytes() == original

    lower_resolution = _image(path, (90, 45))
    assert derive_chart_image(path, lower_resolution, display_width_css_px=96, display_height_css_px=48,
        target_dpi=150) is None


def test_chart_derivation_rejects_source_drift(tmp_path):
    path = tmp_path / "chart.png"
    source = _image(path, (800, 400))
    path.write_bytes(b"changed")

    assert derive_chart_image(path, source, display_width_css_px=96, display_height_css_px=48,
        target_dpi=150) is None


@pytest.mark.parametrize("image_format,extension", [("PNG", ".png"), ("JPEG", ".jpg")])
def test_actual_pdf_chart_images_are_resampled_and_read_back(tmp_path, image_format, extension):
    from pypdf import PdfReader

    from smart_reporting.reporting.delivery.report_runtime.report_design import ReportDesign
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime

    root = tmp_path / image_format.lower()
    root.mkdir()
    chart_path = root / f"chart{extension}"
    image = Image.effect_noise((2400, 1200), 90).convert("RGB")
    image.save(chart_path, format=image_format, quality=95)
    chart_bytes = chart_path.read_bytes()
    chart = ChartImageSource("chart-1", chart_path.name, len(chart_bytes), hashlib.sha256(chart_bytes).hexdigest())
    data_path = root / "data.csv"
    data_path.write_text("value\n1\n", encoding="utf-8")
    markdown = root / "report.md"
    markdown.write_text(
        "# DPI 验证报告\n\n[[section:overview]]\n\n## 1. 经营概览\n\n![图表](chart" + extension + ")\n",
        encoding="utf-8",
    )
    dpi = 150
    state = {
        "jobId": "pdf-chart-image-dpi",
        "sources": [{"path": data_path.name, "size": data_path.stat().st_size,
            "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest()}],
        "_documentContext": {
            "title": "DPI 验证报告", "periodLabel": "2026年", "organizationName": "验证编制",
            "generatedByLabel": "", "watermarkText": "", "generatedDate": "2026-11-13",
            "sectionNumbers": ["1"],
            "sections": [{"code": "overview", "sectionNumber": "1", "title": "经营概览"}],
            "headingNumbers": [{"level": 2, "number": "1", "title": "经营概览",
                "sectionCode": "overview", "anchor": "report-section-overview"}],
        },
        "_editorExportSettings": {"cover": False, "toc": False, "sources": False},
        "_formatDesigns": {"pdf": ReportDesign().model_dump(mode="json", by_alias=True)},
        "_formatPreferences": {"pdf": {"common": {"signer": "验证编制", "generatedByLabel": ""},
            "charts": {"imageDpi": dpi}}},
    }
    result = ReportRuntime(root).render_markdown(
        state, markdown.name, "revision/report.pdf", ".reporting-tmp/workspace-report-dpi-test-render/render.pdf",
        chart_images=[{"chartId": chart.chart_id, "path": chart.path,
            "size": chart.size, "sha256": chart.sha256}],
    )

    assert result["status"] == "rendered"
    assert chart_path.read_bytes() == chart_bytes
    assert not any(issue["code"] == "pdf_chart_image_dpi_unverified" for issue in result["renderIssues"])
    pdf_path = root / "revision/report.pdf"
    evidence = result["render"]["chartImageDpi"]
    assert len(evidence) == 1 and evidence[0]["chartId"] == chart.chart_id, result["renderIssues"]
    assert evidence[0]["sourceSha256"] == chart.sha256
    assert evidence[0]["derivedSha256"] != chart.sha256
    assert len(evidence[0]["draws"]) == 1
    assert max(evidence[0]["draws"][0]["widthDpi"], evidence[0]["draws"][0]["heightDpi"]) <= dpi + 0.05
    assert PdfReader(pdf_path).pages
