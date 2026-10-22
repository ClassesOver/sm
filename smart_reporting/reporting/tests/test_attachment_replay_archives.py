"""Complete workspace exports retain immutable resource paths across formats."""

import io
import tarfile
import zipfile

import pytest

from scripts.replay_table_derivation_references import _discover, _read_archive


@pytest.mark.parametrize("format", ["zip", "tar.xz"])
@pytest.mark.parametrize("prefix", ["workspace/", ""])
def test_workspace_archive_with_metadata_prefers_selected_revision_chart(tmp_path, format, prefix):
    base = "报表/智能分析/run"
    files = {
        f"{prefix}{base}/report-revision-1.manifest.json": b"{}",
        f"{prefix}{base}/trace-index-v1.json": b"{}",
        f"{prefix}{base}/facts/revision-1/analysis_001.json": b'{"analysisId":"analysis_001"}',
        f"{prefix}{base}/chart-001--1.chart-input.json": b'{"rows":[[1]]}',
        f"{prefix}{base}/revision-2/chart-001--1.chart-input.json": b'{"rows":[[1]]}',
        "metadata/workspace-manifest.json": b"[]",
        "README.md": b"export metadata",
    }
    path = tmp_path / f"attachment.{format}"
    if format == "zip":
        with zipfile.ZipFile(path, "w") as archive:
            for name, raw in files.items():
                archive.writestr(name, raw)
    else:
        with tarfile.open(path, "w:xz") as archive:
            for name, raw in files.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(raw)
                archive.addfile(entry, io.BytesIO(raw))
    members = _read_archive(path)
    expected = ({name.removeprefix(prefix): raw for name, raw in files.items()
                 if name.startswith(prefix)} if prefix else files)
    assert members == expected
    manifest, _, _, facts, _, charts = _discover(members)
    assert manifest == f"{base}/report-revision-1.manifest.json"
    assert len(facts) == 1
    assert charts == [f"{base}/chart-001--1.chart-input.json"]
