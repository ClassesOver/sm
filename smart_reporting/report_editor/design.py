"""设计草稿：在既有草稿锁内保存，并与历史恢复的正文提交一起恢复。"""
from __future__ import annotations

import json
import secrets
from pathlib import PurePosixPath
from typing import Any

from ..reporting.delivery.report_design import ReportDesign, resolve_design
from ..reporting.models import ReportingError


class ReportEditorDesignService:
    def __init__(self, editor: Any):
        self.editor = editor

    @staticmethod
    def path(context) -> str:
        path = PurePosixPath(context.markdown_path)
        return str(path.parent / "draft" / ".report-design.json")

    async def _entry(self, context, markdown_sha: str) -> dict:
        path = self.path(context)
        if not await self.editor.workspace.apath_exists(context.scope["threadId"], path):
            return {"design": resolve_design(context.job).model_dump(mode="json", by_alias=True)}
        record = json.loads(await self.editor.workspace.aread_text(context.scope["threadId"], path))
        if record.get("contextSha256") != context.digest():
            raise ReportingError("report_editor_scope_mismatch", "设计草稿与报告版本不一致。")
        pending = record.get("pending")
        if pending and pending["markdownSha256"] == markdown_sha:
            return pending
        return {"design": record["active"], "source": record.get("source")}

    async def _read(self, context, markdown_sha: str) -> ReportDesign:
        return ReportDesign.model_validate((await self._entry(context, markdown_sha))["design"])

    async def source(self, context, markdown_sha: str):
        identity = (await self._entry(context, markdown_sha)).get("source")
        if not identity:
            return None
        candidates = await self.editor._candidate_revisions(context)
        selected = next((item for item in candidates if item.revision == identity["revision"]), None)
        if selected is None or selected.digest() != identity["contextSha256"]:
            raise ReportingError("snapshot_integrity_failed", "设计恢复记录的数据来源与报告版本不一致。")
        return selected

    async def _write(self, context, record: dict) -> None:
        path = self.path(context)
        exists = await self.editor.workspace.apath_exists(context.scope["threadId"], path)
        await self.editor.workspace.awrite_text(
            context.scope["threadId"], path,
            json.dumps({"contextSha256": context.digest(), **record}, ensure_ascii=False), overwrite=exists,
        )

    @staticmethod
    def payload(design: ReportDesign, context) -> dict[str, Any]:
        return {"design": design.model_dump(mode="json", by_alias=True), "designSha256": design.digest(),
                "documentContext": {key: context.job.get("_documentContext", {}).get(key, "") for key in
                                    ("title", "periodLabel", "organizationName", "generatedByLabel", "generatedDate", "watermarkText")}}

    async def read(self, expected) -> dict[str, Any]:
        context = await self.editor._restore(expected)
        async with self.editor._draft_lock(context):
            _, _, sha = await self.editor._read_revision_markdown(context)
            return self.payload(await self._read(context, sha), context)

    async def save(self, expected, design: ReportDesign, expected_design_sha256: str) -> dict[str, Any]:
        context = await self.editor._restore(expected)
        async with self.editor._draft_lock(context):
            _, _, sha = await self.editor._read_revision_markdown(context)
            current = await self._read(context, sha)
            self.check(current, expected_design_sha256)
            entry = await self._entry(context, sha)
            await self._write(context, {"active": design.model_dump(mode="json", by_alias=True), "source": entry.get("source")})
            return self.payload(design, context)

    @staticmethod
    def check(design: ReportDesign, expected_sha: str | None) -> None:
        if expected_sha is not None and not secrets.compare_digest(design.digest(), expected_sha):
            raise ReportingError("report_editor_design_conflict", "报告设计已在其他窗口修改，请重新载入后再保存。")

    async def settle(self, context, sha: str) -> None:
        # 崩溃后首次编辑正文前，将已生效的恢复设计转为 active，避免后续正文变更回退设计。
        path = self.path(context)
        if await self.editor.workspace.apath_exists(context.scope["threadId"], path):
            entry = await self._entry(context, sha)
            await self._write(context, {"active": entry["design"], "source": entry.get("source")})

    async def references(self, context) -> list[dict]:
        path = self.path(context)
        if not await self.editor.workspace.apath_exists(context.scope["threadId"], path):
            return []
        record = json.loads(await self.editor.workspace.aread_text(context.scope["threadId"], path))
        if record.get("contextSha256") != context.digest():
            raise ValueError("设计草稿身份不一致")
        return [identity for identity in (record.get("source"), (record.get("pending") or {}).get("source")) if identity]

    async def prepare_restore(self, context, current_sha: str, target_sha: str, design: ReportDesign, source=None) -> None:
        current = await self._entry(context, current_sha)
        active_source = await self.editor._draft_source(context, current_sha)
        def identity(selected):
            return {"revision": selected.revision, "contextSha256": selected.digest()}
        pending = {"markdownSha256": target_sha, "design": design.model_dump(mode="json", by_alias=True)}
        if source is not None:
            pending["source"] = identity(source)
        await self._write(context, {"active": current["design"], "source": identity(active_source), "pending": pending})
