"""Load a server-registered, current overview for first publication rendering."""

from __future__ import annotations

import hashlib

from ..delivery.artifacts_v1 import ReportArtifactManifest
from ..trace.contracts_v1 import RevisionTraceIndexV1
from ..trace.quality_bundle import QUALITY_FILENAME, SEMANTIC_RULE_VERSIONS, QualityBundle
from .management_overview import ManagementOverview, build_management_overview


async def registered_management_overview(workspace, thread_id: str, manifest: ReportArtifactManifest,
                                         authorization_scope_hash: str) -> ManagementOverview:
    """Manifest is server-authoritative; hashes alone do not grant authority."""
    async def read(file):
        if file.size > 16 * 1024 * 1024:
            raise ValueError("overview input exceeds budget")
        raw = await workspace.read_limited_regular_file(thread_id, file.path, max_bytes=16 * 1024 * 1024)
        if len(raw) != file.size or hashlib.sha256(raw).hexdigest() != file.sha256:
            raise ValueError("overview input identity changed")
        return raw

    if manifest.trace_index is None:
        raise ValueError("overview trace index unavailable")
    index = RevisionTraceIndexV1.model_validate_json(await read(manifest.trace_index))
    if (index.report_id != manifest.report_id or index.revision != manifest.revision
            or index.profile_hash != manifest.effective_profile_hash):
        raise ValueError("overview index identity mismatch")
    files = {file.resource_id: file for file in index.files}
    markdown = files[index.markdown_file_resource_id]
    if (markdown.path, markdown.size, markdown.sha256) != (manifest.markdown.path, manifest.markdown.size, manifest.markdown.sha256):
        raise ValueError("overview markdown registration mismatch")
    await read(markdown)
    records = [file for file in index.files if file.path.endswith("/" + QUALITY_FILENAME)]
    if len(records) != 1:
        raise ValueError("overview quality identity unavailable")
    quality = QualityBundle.model_validate_json(await read(records[0]))
    if (quality.report_id != index.report_id or quality.revision != index.revision
            or quality.markdown_sha256 != markdown.sha256
            or quality.semantic_rule_versions != SEMANTIC_RULE_VERSIONS):
        raise ValueError("overview quality snapshot mismatch")
    overview = build_management_overview(quality)
    assertion_ids = {evidence.assertion_id for row in overview.rows for evidence in row.evidence}
    selected = [assertion for assertion in quality.assertions if assertion.assertion_id in assertion_ids]
    if any(assertion.profile_hash != index.profile_hash
           or assertion.authorization_scope_hash != authorization_scope_hash
           for assertion in selected):
        raise ValueError("overview assertion provenance mismatch")
    required_subjects = {subject for row in overview.rows for evidence in row.evidence for subject in evidence.subject_ids}
    required_files = {ref.file_resource_id for subject in index.subject_bindings
                      if subject.subject_id in required_subjects for ref in subject.fact_refs}
    if required_subjects - {subject.subject_id for subject in index.subject_bindings}:
        raise ValueError("overview subject identity unavailable")
    needed_hashes = {digest for assertion in selected for digest in assertion.source_hashes}
    for digest in needed_hashes:
        matches = [fact.file_resource_id for fact in index.fact_files if files[fact.file_resource_id].sha256 == digest]
        if not matches:
            raise ValueError("overview source registration unavailable")
        if not any(resource in required_files for resource in matches):
            required_files.add(matches[0])
    budget = 64 * 1024 * 1024
    for resource in sorted(required_files):
        file = files[resource]
        budget -= file.size
        if budget < 0:
            raise ValueError("overview source budget exceeded")
        await read(file)
    return overview
