"""Registered manifest fixtures for editor source tests."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

from smart_reporting.reporting.delivery.artifacts_v1 import (
    ArtifactFile,
    Citation,
    ReportArtifactManifest,
)
from smart_reporting.reporting.delivery.draft_v1 import HeadingNumber
from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1, canonical_json_bytes


async def register_trace_manifest(workspace, thread_id: str, index: RevisionTraceIndexV1, *, overwrite: bool = False) -> ArtifactFile:
    files = {item.resource_id: item for item in index.files}
    markdown = files[index.markdown_file_resource_id]
    index_path = PurePosixPath(markdown.path).with_name("trace-index-v1.json").as_posix()
    index_bytes = canonical_json_bytes(index.model_dump(mode="json", by_alias=True))
    manifest = ReportArtifactManifest(
        reportId=index.report_id,
        revision=index.revision,
        codingTaskKey="trace-test-task",
        datasetSnapshotHash="a" * 64,
        effectiveProfileHash="b" * 64,
        markdown=ArtifactFile(path=markdown.path, mediaType="text/markdown", size=markdown.size, sha256=markdown.sha256),
        citations=tuple(
            Citation(citationId=f"citation_{position:03d}", datasetId=dataset.dataset_id,
                     requirementId=dataset.requirement_id, snapshotHash=files[dataset.file_resource_id].sha256)
            for position, dataset in enumerate(index.datasets, start=1)
        ),
        sections=("section_002",),
        sectionNumbers=("1",),
        headingNumbers=(HeadingNumber(level=2, number="1", title="Report", sectionCode="section_002", anchor="report-section-section_002"),),
        traceIndex=ArtifactFile(path=index_path, mediaType="application/json", size=len(index_bytes), sha256=hashlib.sha256(index_bytes).hexdigest()),
    )
    content = canonical_json_bytes(manifest.model_dump(mode="json", by_alias=True))
    manifest_path = PurePosixPath(markdown.path).with_name("report.manifest.json").as_posix()
    await workspace.awrite_bytes(thread_id, manifest_path, content, overwrite=overwrite)
    return ArtifactFile(path=manifest_path, mediaType="application/json", size=len(content), sha256=hashlib.sha256(content).hexdigest())
