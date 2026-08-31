from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

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

    async def replace(self, grant: ReportDownloadGrant, *, now: datetime) -> None:
        active = [
            current
            for current in self.records.values()
            if current.report_id == grant.report_id
            and current.scope == grant.scope
            and current.revoked_at is None
            and current.expires_at > now
        ]
        if active and max(current.revision for current in active) > grant.revision:
            raise ReportingError(
                "report_download_revision_stale",
                "不能用较低修订替换当前报告下载授权。",
            )
        for key, current in tuple(self.records.items()):
            if (
                current.report_id == grant.report_id
                and current.scope == grant.scope
                and current.revoked_at is None
                and current.revision <= grant.revision
            ):
                self.records[key] = replace(current, revoked_at=now)
        self.records[grant.grant_hash] = grant

    async def cleanup_expired(self, *, now: datetime) -> None:
        self.records = {key: grant for key, grant in self.records.items() if grant.expires_at > now}

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

    async def resolve(
        self,
        *,
        scope: ReportDownloadScope,
        report_id: str,
        revision: int,
        artifact: Literal["pdf", "word", "html"],
    ) -> StoredReportArtifact | None:
        matches = [
            item
            for item in self.records.values()
            if item.scope == scope
            and item.report_id == report_id
            and item.revision == revision
            and item.artifact == artifact
        ]
        if len(matches) > 1:
            raise ReportingError("report_artifact_invalid", "持久化报告产物无效。")
        return matches[0] if matches else None

    async def touch(self, artifact_key: str, *, now: datetime) -> None:
        artifact = self.records.get(artifact_key)
        if artifact is not None:
            self.records[artifact_key] = replace(artifact, created_at=now)

    async def stream(self, artifact_key: str) -> AsyncIterator[bytes]:
        for chunk in self.chunks.get(artifact_key, ()):
            yield chunk
