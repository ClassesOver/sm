from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

from ...workspace import MAX_DOWNLOAD_BYTES
from ..delivery.publishing import (
    ReportDownloadGrant,
    ReportDownloadScope,
    StoredReportArtifact,
)
from ..models import ReportingError


class InMemoryDownloadGrantRepository:
    def __init__(self) -> None:
        self.records: dict[str, ReportDownloadGrant] = {}

    async def put(self, grant: ReportDownloadGrant) -> None:
        self.records[grant.grant_hash] = grant

    async def get(self, grant_hash: str) -> ReportDownloadGrant | None:
        return self.records.get(grant_hash)

    async def revoke_report(
        self,
        report_id: str,
        *,
        scope: ReportDownloadScope,
        before_revision: int | None = None,
    ) -> None:
        now = datetime.now(UTC)
        for key, grant in tuple(self.records.items()):
            if (
                grant.report_id == report_id
                and grant.scope == scope
                and (before_revision is None or grant.revision < before_revision)
            ):
                self.records[key] = replace(grant, revoked_at=now)


class InMemoryReportArtifactRepository:
    def __init__(self) -> None:
        self.records: dict[str, StoredReportArtifact] = {}
        self.chunks: dict[str, tuple[bytes, ...]] = {}

    async def put(
        self,
        artifact: StoredReportArtifact,
        chunks: AsyncIterator[bytes],
    ) -> None:
        stored: list[bytes] = []
        digest = hashlib.sha256()
        total = 0
        async for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise ReportingError("report_artifact_changed", "报告文件已变化。")
            if not chunk:
                continue
            total += len(chunk)
            if total > artifact.size or total > MAX_DOWNLOAD_BYTES:
                raise ReportingError("report_artifact_changed", "报告文件已变化。")
            digest.update(chunk)
            stored.append(chunk)
        if total != artifact.size or digest.hexdigest() != artifact.sha256:
            raise ReportingError("report_artifact_changed", "报告文件已变化。")
        self.records[artifact.artifact_key] = artifact
        self.chunks[artifact.artifact_key] = tuple(stored)

    async def get(self, artifact_key: str) -> StoredReportArtifact | None:
        return self.records.get(artifact_key)

    async def stream(self, artifact_key: str) -> AsyncIterator[bytes]:
        for chunk in self.chunks.get(artifact_key, ()):
            yield chunk
