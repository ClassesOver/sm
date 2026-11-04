from pathlib import Path


def test_runtime_image_checks_matplotlib_static_rendering_without_plotly():
    dockerfile = (Path(__file__).resolve().parents[3] / "Dockerfile").read_text(encoding="utf-8")

    assert "matplotlib-smoke.png" in dockerfile
    assert "plotly.graph_objects" not in dockerfile
    assert "kaleido-smoke.png" not in dockerfile


def test_editor_build_has_genoffice_sources_at_the_frontend_relative_path():
    dockerfile = (Path(__file__).resolve().parents[3] / "Dockerfile").read_text(encoding="utf-8")
    engine = "WORKDIR /build/smart_reporting/reporting/slides_engine"
    frontend = "WORKDIR /build/smart_reporting/report_editor/frontend"
    assert engine in dockerfile
    assert frontend in dockerfile
    engine_copy = dockerfile.index("COPY smart_reporting/reporting/slides_engine/packages ./packages")
    build = dockerfile.index("RUN npm run build && npm run build:slides")
    assert engine_copy < dockerfile.index(frontend) < build
    assert "/build/smart_reporting/reporting/slides_engine /opt/reporting-slides-engine" in dockerfile
    assert "/build/smart_reporting/report_editor/static /opt/report-editor-static" in dockerfile


def test_dockerfile_prebundles_office_engine_bridges():
    dockerfile = (Path(__file__).resolve().parents[3] / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("npm run bundle:bridges") == 2
