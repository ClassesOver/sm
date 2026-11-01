from pathlib import Path


def test_runtime_image_checks_matplotlib_static_rendering_without_plotly():
    dockerfile = (Path(__file__).resolve().parents[3] / "Dockerfile").read_text(encoding="utf-8")

    assert "matplotlib-smoke.png" in dockerfile
    assert "plotly.graph_objects" not in dockerfile
    assert "kaleido-smoke.png" not in dockerfile