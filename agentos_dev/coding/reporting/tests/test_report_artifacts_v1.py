from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from agentos_dev.coding.reporting.delivery.artifacts_v1 import (
    ArtifactFile,
    DocxArtifactManifest,
    build_authoritative_manifest,
)
from agentos_dev.coding.reporting.workflow.query_pipeline import DatasetLineage


def _manifest_validator_module():
    script = (
        Path(__file__).parents[1]
        / "builtin_skills"
        / "report-artifact"
        / "scripts"
        / "validate_manifest.py"
    )
    spec = importlib.util.spec_from_file_location("report_validate_manifest", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_word版式能力作为观测值不阻断产物清单() -> None:
    manifest = DocxArtifactManifest(
        reportId="report-1",
        revision=1,
        effectiveProfileHash="a" * 64,
        sourceMarkdownSha256="b" * 64,
        docx=ArtifactFile(
            path="reports/report.docx",
            mediaType="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size=1,
            sha256="c" * 64,
        ),
        convertedPageCount=1,
        sectionCount=1,
        tocEntryCount=0,
        sections=("executive_summary",),
    )

    assert manifest.section_count == 1
    assert manifest.toc_entry_count == 0


def test_manifest使用dataset血缘analysis和表格哈希() -> None:
    markdown = (
        "[[section:income]]\n## 收入分析\n"
        "医疗收入为100万元。[[citation:citation_001]][[analysis:analysis_001]]\n\n"
        "[[table:income-table]]\n**收入汇总**\n\n"
        "| 项目 | 本期值 |\n| --- | --- |\n| 医疗收入 | 100万元 |\n"
        "[[/table:income-table]]\n"
    )
    lineage = (
        DatasetLineage(
            datasetId="dataset-income",
            sourceId="operations",
            requirementId="income",
            sqlHash="a" * 64,
            rowCount=1,
            size=10,
            sha256="b" * 64,
        ),
    )
    manifest = build_authoritative_manifest(
        report_id="report-1",
        revision=1,
        coding_task_key="task-1",
        effective_profile_hash="c" * 64,
        markdown_path="reports/report.md",
        markdown=markdown,
        accepted_artifacts=[
            {"path": "reports/report.md", "size": len(markdown.encode()), "sha256": "d" * 64}
        ],
        lineage=lineage,
        sections=("income",),
    )

    assert manifest.citations[0].dataset_id == "dataset-income"
    assert manifest.citations[0].snapshot_hash == "b" * 64
    assert manifest.analysis_ids == ("analysis_001",)
    assert [item.table_id for item in manifest.tables] == ["income-table"]
    assert "factIds" not in manifest.model_dump(mode="json", by_alias=True)


def test_manifest_validator接受工作流生成的分析上下文和渲染契约(tmp_path) -> None:
    context = {
        "version": 1,
        "forbiddenVisibleTerms": [],
        "observedDataFacts": [],
        "prohibitDerivedValues": True,
        "expectedSections": ["income"],
        "expectedCitationBindings": [],
        "manifestSchema": {},
        "analysisContextFile": {
            "path": "contexts/analysis.json",
            "size": 1,
            "sha256": "0" * 64,
        },
        "renderContract": {"title": "运营报告", "sections": [], "citationIds": []},
    }
    content = json.dumps(context, ensure_ascii=False, separators=(",", ":")).encode()
    context_path = tmp_path / "validation.json"
    context_path.write_bytes(content)
    identity = {
        "path": "validation.json",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }

    loaded, error = _manifest_validator_module()._load_validation_context(
        str(tmp_path), identity
    )

    assert error is None
    assert loaded is not None
    assert loaded["analysisContextFile"]["path"] == "contexts/analysis.json"
    assert loaded["renderContract"]["title"] == "运营报告"
