"""编辑器手动修订的编号与文件命名。"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.revisions import next_manual_revision, revision_file_path

_TITLE_PATH = "报表/智能分析/run-1/revision-1/2025年度某某市第一人民医院门急诊及住院医疗服务运营效率与成本结构综合分析报告_2025-01-01_2025-12-31"


@pytest.mark.parametrize("suffix", [".pptx", ".xlsx"])
def test_revision_file_name_does_not_grow_with_each_save(suffix):
    path = f"{_TITLE_PATH}{suffix}"
    original_bytes = len(path.rsplit("/", 1)[1].encode())
    for revision in range(2, 200):
        path = revision_file_path(path, revision, suffix=suffix)
    name = path.rsplit("/", 1)[1]

    assert path.startswith("报表/智能分析/run-1/revision-1/")
    assert re.fullmatch(r".+_2025-12-31-r199-[0-9a-f]{12}" + re.escape(suffix), name)
    assert len(name.encode()) <= original_bytes + len("-r199-") + 12
    assert len(name.encode()) <= 255


@pytest.mark.parametrize(
    "legacy",
    ["reports/report-r2-r3-r4.pptx", "reports/report-r2-0123456789ab-r3-abcdef012345.xlsx"],
)
def test_revision_file_name_drops_previously_stacked_suffixes(legacy):
    suffix = legacy[legacy.rindex("."):]
    assert re.fullmatch(r"reports/report-r5-[0-9a-f]{12}" + re.escape(suffix), revision_file_path(legacy, 5, suffix=suffix))


def test_revision_file_names_are_distinct_for_concurrent_saves():
    assert revision_file_path("reports/report.pptx", 2, suffix=".pptx") != revision_file_path(
        "reports/report.pptx", 2, suffix=".pptx"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_next_revision_skips_revisions_created_from_other_sessions(anyio_backend):
    async def get(_run_id):
        return SimpleNamespace(payload={"reportEditorContexts": {"1": {}, "2": {}, "4": {}, "draft": {}}})

    revision, issues = await next_manual_revision(
        SimpleNamespace(get=get), SimpleNamespace(workflow_run_id="run-1", report_id="r", revision=1),
    )

    assert (revision, issues) == (5, [])


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_next_revision_falls_back_with_soft_issue_when_lookup_fails(anyio_backend):
    async def get(_run_id):
        raise OSError("state store unavailable")

    revision, issues = await next_manual_revision(
        SimpleNamespace(get=get), SimpleNamespace(workflow_run_id="run-1", report_id="r", revision=3),
    )

    assert revision == 4
    assert [issue["code"] for issue in issues] == ["report_editor_revision_lookup_failed"]
