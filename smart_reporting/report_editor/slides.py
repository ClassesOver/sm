from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ..reporting.delivery.publishing import ReportArtifactSpec, ReportDownloadScope
from ..reporting.models import ReportingError
from ..reporting.workflow.scope import resolve_reporting_workflow_scope
from ..reporting.workflow.state import ReportingCommand
from .service import ReportEditorContext, ReportEditorGrantService, ReportEditorSession

_SLIDE_ANIMATION_EFFECTS = {
    "appear", "fade", "flyIn", "wipe", "wipeDown", "splitIn", "bounce", "flipIn", "zoom",
    "pulse", "spin", "grow", "teeter", "disappear", "fadeOut", "flyOut", "wipeOut", "shrink",
    "zoomOut", "motionPath", "mediaPlay", "mediaPause", "mediaStop",
}
_SLIDE_ANIMATION_TRIGGERS = {"onClick", "withPrev", "afterPrev"}

class ReportSlidesEditorService:
    """读取并验证 PPTX 编辑授权所绑定的发布修订。"""

    def __init__(
        self,
        *,
        state_repository: Any,
        workspace_registry: Any,
        workspace: Any,
        editor_grants: ReportEditorGrantService | None = None,
        artifact_persistence: Any = None,
        public_base_url: str = "",
    ) -> None:
        self.state_repository = state_repository
        self.workspace_registry = workspace_registry
        self.workspace = workspace
        self.editor_grants = editor_grants
        self.artifact_persistence = artifact_persistence
        self.public_base_url = public_base_url.rstrip("/")

    async def context_for_session(self, session: ReportEditorSession) -> ReportEditorContext:
        return await self._context_for_capability(session, "pptx_editor")

    async def download_for_session(self, session: ReportEditorSession) -> tuple[ReportEditorContext, bytes]:
        context = await self._context_for_capability(session, "pptx_download")
        return context, await self._read_verified_pptx(context)

    async def _context_for_capability(
        self, session: ReportEditorSession, capability: str
    ) -> ReportEditorContext:
        capabilities = session.capabilities
        if not isinstance(capabilities, dict) or capabilities.get(capability) is not True:
            raise ReportingError("report_slides_permission_denied", "该会话没有幻灯片编辑权限。")
        durable = await self.state_repository.get(session.workflow_run_id)
        contexts = durable.payload.get("reportEditorContexts") if durable is not None else None
        raw = contexts.get(str(session.revision)) if isinstance(contexts, dict) else None
        try:
            context = ReportEditorContext.model_validate(raw)
        except Exception as error:
            raise ReportingError(
                "report_slides_context_missing", "幻灯片编辑上下文不存在。"
            ) from error
        if (
            context.delivery_format != "pptx"
            or context.report_id != session.report_id
            or context.revision != session.revision
            or context.workflow_run_id != session.workflow_run_id
            or not secrets.compare_digest(context.digest(), session.context_sha256)
        ):
            raise ReportingError("report_slides_scope_mismatch", "幻灯片编辑作用域不一致。")
        scope = resolve_reporting_workflow_scope(
            run_id=context.workflow_run_id,
            session_id=context.scope.get("sessionId", ""),
            user_id=context.scope.get("userId"),
            stored_scope=context.scope,
        )
        if scope.workspace_key != context.scope.get("threadId"):
            raise ReportingError("report_slides_scope_mismatch", "幻灯片工作区作用域不一致。")
        self.workspace_registry.resolve(scope)
        current = await self.workspace.ahash_file(scope.workspace_key, context.pptx_path)
        if (
            current.get("missing")
            or current.get("size") != context.pptx_size
            or current.get("sha256") != context.pptx_sha256
        ):
            raise ReportingError("report_slides_identity_changed", "PPTX 文件身份已变化。")
        return context

    async def deck_for_session(self, session: ReportEditorSession) -> dict[str, Any]:
        context = await self.context_for_session(session)
        pptx = await self._read_verified_pptx(context)
        deck = await asyncio.to_thread(self._run_engine, pptx, "inspect")
        return {
            **deck,
            "reportId": context.report_id,
            "revision": context.revision,
            "sha256": context.pptx_sha256,
        }

    async def preview_pdf(self, session: ReportEditorSession) -> bytes:
        context = await self.context_for_session(session)
        pptx = await self._read_verified_pptx(context)
        return await asyncio.to_thread(self._render_pdf, pptx)

    async def save_revision(
        self,
        session: ReportEditorSession,
        payload: Any,
        *,
        images: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        context = await self.context_for_session(session)
        if not isinstance(payload, dict) or payload.get("expectedSha256") != context.pptx_sha256:
            raise ReportingError("report_slides_conflict", "PPTX 已发生变化，请重新载入。")
        edits = payload.get("edits", [])
        order = payload.get("order")
        theme = payload.get("theme")
        if theme is not None and (
            not isinstance(theme, str) or theme not in {"executive", "clinical", "modern"}
        ):
            raise ReportingError("report_slides_edit_invalid", "幻灯片主题无效。")
        transitions = payload.get("transitions", [])
        animations = payload.get("animations", [])
        slide_layouts = payload.get("slideLayouts", [])
        if not isinstance(transitions, list) or len(transitions) > 500:
            raise ReportingError("report_slides_edit_invalid", "幻灯片转场内容无效。")
        if not isinstance(animations, list) or len(animations) > 500:
            raise ReportingError("report_slides_edit_invalid", "对象动画内容无效。")
        if not isinstance(slide_layouts, list) or len(slide_layouts) > 500:
            raise ReportingError("report_slides_edit_invalid", "幻灯片版式内容无效。")
        transition_kinds = {"none", "morph", "fade", "push", "wipe", "split", "circle", "cover", "pull", "dissolve", "zoom", "random"}
        if any(
            not isinstance(item, dict)
            or set(item) != {"slideIndex", "kind"}
            or not isinstance(item["slideIndex"], int)
            or isinstance(item["slideIndex"], bool)
            or item["slideIndex"] < 0
            or item["kind"] not in transition_kinds
            for item in transitions
        ):
            raise ReportingError("report_slides_edit_invalid", "幻灯片转场内容无效。")
        if any(
            not isinstance(item, dict)
            or not {"slideIndex", "elementId", "effect", "trigger"}.issubset(item)
            or not set(item).issubset({"slideIndex", "elementId", "effect", "trigger", "durationMs", "delayMs"})
            or not isinstance(item["slideIndex"], int)
            or isinstance(item["slideIndex"], bool)
            or item["slideIndex"] < 0
            or not isinstance(item["elementId"], str)
            or item["effect"] not in _SLIDE_ANIMATION_EFFECTS
            or item["trigger"] not in _SLIDE_ANIMATION_TRIGGERS
            or (
                "durationMs" in item
                and (
                    not isinstance(item["durationMs"], (int, float))
                    or isinstance(item["durationMs"], bool)
                    or not 0 <= item["durationMs"] <= 3_600_000
                )
            )
            or (
                "delayMs" in item
                and (
                    not isinstance(item["delayMs"], (int, float))
                    or isinstance(item["delayMs"], bool)
                    or not 0 <= item["delayMs"] <= 3_600_000
                )
            )
            for item in animations
        ):
            raise ReportingError("report_slides_edit_invalid", "对象动画内容无效。")
        if any(
            not isinstance(item, dict)
            or set(item) != {"slideIndex", "layoutPath"}
            or not isinstance(item["slideIndex"], int)
            or isinstance(item["slideIndex"], bool)
            or item["slideIndex"] < 0
            or not isinstance(item["layoutPath"], str)
            or not item["layoutPath"].startswith("ppt/slideLayouts/")
            or not item["layoutPath"].endswith(".xml")
            for item in slide_layouts
        ):
            raise ReportingError("report_slides_edit_invalid", "幻灯片版式内容无效。")
        if not isinstance(edits, list) or len(edits) > 500:
            raise ReportingError("report_slides_edit_invalid", "幻灯片修改内容无效。")
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("slideIndex"), int)
            or isinstance(item.get("slideIndex"), bool)
            or not isinstance(item.get("elementId"), str)
            or not (
                isinstance(item.get("text"), str)
                and len(item["text"]) <= 20_000
                or isinstance(item.get("geometry"), dict)
                and all(
                    isinstance(item["geometry"].get(key), (int, float))
                    and not isinstance(item["geometry"].get(key), bool)
                    and (0 < item["geometry"][key] <= 100_000 if key in {"width", "height"}
                         else 0 <= item["geometry"][key] <= 100_000)
                    for key in ("x", "y", "width", "height")
                )
            )
            for item in edits
        ):
            raise ReportingError("report_slides_edit_invalid", "幻灯片修改内容无效。")
        if order is not None and (
            not isinstance(order, list)
            or any(not isinstance(item, int) or isinstance(item, bool) for item in order)
        ):
            raise ReportingError("report_slides_edit_invalid", "幻灯片顺序无效。")

        source = await self._read_verified_pptx(context)
        engine_result = await asyncio.to_thread(
            self._run_engine,
            source,
            "edit",
            edits=edits,
            order=order,
            theme=theme,
            images=images,
            transitions=transitions,
            animations=animations,
            slide_layouts=slide_layouts,
        )
        revised = engine_result["bytes"]
        next_revision = context.revision + 1
        source_path = PurePosixPath(context.pptx_path or "report.pptx")
        revision_path = (source_path.parent / f"{source_path.stem}-r{next_revision}.pptx").as_posix()
        thread_id = context.scope["threadId"]
        await self.workspace.awrite_bytes(thread_id, revision_path, revised, overwrite=False)
        identity = await self.workspace.ahash_file(thread_id, revision_path)
        if identity.get("missing") or identity.get("size") != len(revised):
            raise ReportingError("report_slides_identity_unavailable", "新修订 PPTX 身份无法读取。")
        digest = str(identity.get("sha256", ""))
        if hashlib.sha256(revised).hexdigest() != digest:
            raise ReportingError("report_slides_identity_unavailable", "新修订 PPTX 身份无法核验。")

        next_job = deepcopy(context.job)
        next_job["revision"] = next_revision
        next_job["pptxPath"] = revision_path
        next_job["pptxSize"] = len(revised)
        next_job["pptxSha256"] = digest
        validation_issues = [
            {
                "code": "pptx_layout_audit",
                "message": f"第 {item['page']} 页：{item['message']}",
            }
            for item in engine_result.get("issues", [])
        ]
        try:
            await asyncio.to_thread(self._render_pdf, revised)
        except Exception:  # noqa: BLE001 - rendered file identity still gets published
            validation_issues.append({
                "code": "pptx_preview_render_failed",
                "message": "PPTX 已生成，但预览渲染失败。",
            })
        next_job["validation"] = {"ok": not validation_issues, "issues": validation_issues}
        next_context = ReportEditorContext(
            reportId=context.report_id,
            revision=next_revision,
            jobId=context.job_id,
            workflowRunId=context.workflow_run_id,
            markdownPath=context.markdown_path,
            artifactManifest=context.artifact_manifest,
            job=next_job,
            scope=context.scope,
            source="manual",
            createdAt=datetime.now(UTC),
            note="幻灯片编辑",
            deliveryFormat="pptx",
            pptxPath=revision_path,
            pptxSize=len(revised),
            pptxSha256=digest,
        )
        durable = await self.state_repository.get(context.workflow_run_id)
        if durable is None:
            raise ReportingError("report_editor_context_missing", "报告编辑上下文不存在。")
        await self.state_repository.apply(
            context.workflow_run_id,
            ReportingCommand(
                name="set_report_editor_context",
                payload={"context": next_context.model_dump(mode="json", by_alias=True)},
                commandId=f"editor-context:{next_revision}:{next_context.digest()}",
            ),
            expected_version=durable.state_version,
        )

        issues: list[dict[str, str]] = list(validation_issues)
        if self.artifact_persistence is not None:
            try:
                stored = await self.artifact_persistence.persist_available(
                    scope=self._download_scope(context),
                    report_id=context.report_id,
                    revision=next_revision,
                    artifacts=(ReportArtifactSpec(
                        artifact="pptx", path=revision_path, size=len(revised), sha256=digest
                    ),),
                )
                if not stored:
                    raise RuntimeError("artifact_not_persisted")
            except Exception:  # noqa: BLE001 - keep committed PPTX and report delivery issue
                issues.append({
                    "code": "report_pptx_persistence_failed",
                    "message": "PPTX 已保存，但下载副本暂不可用；请稍后重试。",
                })

        download_url = ""
        editor_url = ""
        if self.editor_grants is not None:
            try:
                raw_download, _expires = await self.editor_grants.issue(
                    next_context, capabilities={"pptx_download": True}
                )
                download_url = f"{self.public_base_url}/reports/v1/slides/download/{raw_download}"
            except Exception:  # noqa: BLE001 - saved PPTX stays available through its authenticated editor session
                issues.append({
                    "code": "report_pptx_download_grant_failed",
                    "message": "PPTX 已保存，但独立下载授权未能签发。",
                })
            try:
                raw_editor, _expires = await self.editor_grants.issue(
                    next_context, capabilities={"pptx_editor": True}
                )
                editor_url = f"{self.public_base_url}/reports/v1/slides/open/{raw_editor}"
            except Exception:  # noqa: BLE001 - editor access is advisory after save
                issues.append({
                    "code": "report_slides_editor_grant_failed",
                    "message": "PPTX 已保存，但新修订编辑入口未能签发。",
                })
        return {
            "reportId": context.report_id,
            "revision": next_revision,
            "pptx": {
                "path": revision_path,
                "size": len(revised),
                "sha256": digest,
                **({"downloadUrl": download_url} if download_url else {}),
            },
            **({"editor": {"openUrl": editor_url}} if editor_url else {}),
            "validation": {"ok": not issues, "issues": issues},
        }

    async def _read_verified_pptx(self, context: ReportEditorContext) -> bytes:
        try:
            content, _media_type = await self.workspace.afile_bytes(
                context.scope["threadId"], context.pptx_path or ""
            )
        except Exception as error:
            raise ReportingError("report_slides_identity_changed", "PPTX 文件无法读取。") from error
        if (
            len(content) != context.pptx_size
            or hashlib.sha256(content).hexdigest() != context.pptx_sha256
        ):
            raise ReportingError("report_slides_identity_changed", "PPTX 文件身份已变化。")
        return content

    @staticmethod
    def _download_scope(context: ReportEditorContext) -> ReportDownloadScope:
        return ReportDownloadScope(
            database=context.scope["database"],
            user_id=context.scope["userId"],
            company_id=context.scope["companyId"],
            session_id=context.scope["sessionId"],
            thread_id=context.scope["threadId"],
            workflow_run_id=context.workflow_run_id,
        )

    @staticmethod
    def _run_engine(
        content: bytes,
        action: str,
        *,
        edits: list[dict[str, Any]] | None = None,
        order: list[int] | None = None,
        theme: str | None = None,
        images: list[dict[str, Any]] | None = None,
        transitions: list[dict[str, Any]] | None = None,
        animations: list[dict[str, Any]] | None = None,
        slide_layouts: list[dict[str, Any]] | None = None,
    ) -> Any:
        engine = Path(os.environ.get(
            "AGENT_REPORTING_SLIDES_ENGINE_DIR",
            Path(__file__).parents[1] / "reporting" / "slides_engine",
        ))
        with tempfile.TemporaryDirectory(prefix="report-slides-edit-") as directory:
            root = Path(directory)
            source_path = root / "source.pptx"
            source_path.write_bytes(content)
            request_path = root / "request.json"
            request: dict[str, Any] = {"action": action, "input": str(source_path)}
            output_path = root / "output.pptx"
            if action == "edit":
                request.update({"output": str(output_path), "edits": edits or [], "order": order})
                if theme is not None:
                    request["theme"] = theme
                if images:
                    import base64

                    request["images"] = [
                        {
                            "slideIndex": image["slideIndex"],
                            "bytesBase64": base64.b64encode(image["bytes"]).decode("ascii"),
                            "extension": image["extension"],
                            "geometry": image["geometry"],
                            "descr": "AI 生成配图",
                        }
                        for image in images
                    ]
                if transitions:
                    request["transitions"] = transitions
                if animations:
                    request["animations"] = animations
                if slide_layouts:
                    request["slideLayouts"] = slide_layouts
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            process = subprocess.run(
                ["node_modules/.bin/tsx", "bridge/edit-pptx.ts", str(request_path)],
                cwd=engine,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if process.returncode:
                raise ReportingError(
                    "report_slides_engine_failed", process.stderr[-2000:] or "PPTX 编辑失败。"
                )
            try:
                receipt = json.loads(process.stdout.strip().splitlines()[-1])
            except (IndexError, json.JSONDecodeError) as error:
                raise ReportingError("report_slides_engine_receipt_invalid", "PPTX 引擎回执无效。") from error
            if action == "edit":
                return {"bytes": output_path.read_bytes(), "issues": receipt.get("issues", [])}
            return receipt

    @staticmethod
    def _render_pdf(content: bytes) -> bytes:
        with tempfile.TemporaryDirectory(prefix="report-slides-preview-") as directory:
            root = Path(directory)
            source = root / "preview.pptx"
            source.write_bytes(content)
            process = subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", str(root), str(source)],
                check=False,
                capture_output=True,
                timeout=90,
            )
            target = root / "preview.pdf"
            if process.returncode or not target.is_file():
                raise ReportingError("report_slides_preview_failed", "幻灯片预览暂不可用。")
            return target.read_bytes()
