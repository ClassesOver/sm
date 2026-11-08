import subprocess
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
    assert "/runtime/reporting-slides-engine /opt/reporting-slides-engine" in dockerfile
    assert "/build/smart_reporting/report_editor/static /opt/report-editor-static" in dockerfile


def test_dockerfile_prebundles_office_engine_bridges():
    dockerfile = (Path(__file__).resolve().parents[3] / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("npm run bundle:bridges") == 3
    for engine in ("slides", "workbook", "pdf"):
        assert f"/runtime/reporting-{engine}-engine /opt/reporting-{engine}-engine" in dockerfile


def test_app_source_stage_removes_engine_development_files_but_retains_licenses(tmp_path):
    dockerfile = (Path(__file__).resolve().parents[3] / "Dockerfile").read_text(encoding="utf-8")
    source = tmp_path / "smart_reporting"
    for engine in ("slides_engine", "workbook_engine", "pdf_engine"):
        for name in ("LICENSE", "NOTICE", "SOURCE.md", "packages/vendor/LICENSE",
                     "bridge/cli.ts", "packages/tests/fixture.bin"):
            path = source / "reporting" / engine / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
    (source / "app.py").write_text("application")
    stage = dockerfile.split("FROM base AS app-source\n", 1)[1].split("\nFROM ", 1)[0]
    command = stage.split("\nRUN ", 1)[1].replace("\\\n", "").strip()

    subprocess.run(command.replace("/app/smart_reporting", str(source)), shell=True, check=True)

    assert (source / "app.py").read_text() == "application"
    for engine in ("slides_engine", "workbook_engine", "pdf_engine"):
        root = source / "reporting" / engine
        assert {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()} == {
            "LICENSE", "NOTICE", "SOURCE.md", "packages/vendor/LICENSE",
        }
