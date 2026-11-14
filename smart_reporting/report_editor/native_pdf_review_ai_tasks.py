"""批注处理任务：私有候选经真实预览，显式采纳只返回草稿操作。"""

from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from time import monotonic, time
from uuid import uuid4

from loguru import logger

from ..reporting.models import ReportingError
from .agent_event_streams import bind_agent_event_log, event_stream_response
from .native_ai import _copy_operations
from .native_models import native_digest
from .native_pdf_ai_tasks import NativePDFReadService, _ReadJob
from .native_pdf_review_ai import NativePDFReviewReader, pending_note_target


class NativePDFReviewService(NativePDFReadService):
    def __init__(self, editor, *, planner, enabled=False, timeout_seconds=180):
        super().__init__(editor, planner=planner, enabled=enabled, timeout_seconds=timeout_seconds)
        self._closed = False

    async def start(
        self, session, *, client_request_id, expected_sha256, operations, instruction=""
    ):
        context = await self._context(session)
        if self._closed:
            raise ReportingError("native_ai_closed", "批注处理服务已关闭。")
        self.editor.require_enabled("pdf")
        if not self.editor.pdf_text_enabled:
            raise ReportingError(
                "native_ai_pdf_text_disabled", "PDF 原位文字编辑尚未开放，不能处理批注。"
            )
        request_id = self._request_id(client_request_id)
        if expected_sha256 != context.source_file.sha256:
            raise ReportingError("native_ai_snapshot_changed", "PDF 来源已变化，请重新打开。")
        if not isinstance(instruction, str) or len(instruction) > 2000:
            raise ReportingError("native_ai_instruction_invalid", "批注处理要求无效。")
        base = _copy_operations(operations)
        snapshot = native_digest(
            {
                "context": context.digest(),
                "operations": base,
                "instruction": instruction,
                "action": "processNotes",
            }
        )
        self._prune()
        key = (context.digest(), request_id)
        previous = self._jobs.get(key)
        if previous:
            if previous.snapshot_sha256 is not None and previous.snapshot_sha256 != snapshot:
                raise ReportingError(
                    "native_ai_snapshot_changed", "相同 AI 请求内容已变化，请重新发起。"
                )
            return self._serialize(previous)
        self._reserve()
        job = _ReadJob(uuid4().hex, request_id, context.digest(), monotonic(), snapshot)
        job.base = deepcopy(base)
        self._jobs[key] = job
        job.task = asyncio.create_task(self._run_review(job, session, context, base, instruction))
        return self._serialize(job)

    @staticmethod
    def _receipt(receipt, source_sha, operation_count):
        content = receipt.get("content")
        applied, skipped = receipt.get("appliedOperationIndices"), receipt.get("skippedOperations")
        digest = receipt.get("previewDigest")
        if (
            not isinstance(content, bytes)
            or receipt.get("sourceSha256") != source_sha
            or receipt.get("size") != len(content)
            or receipt.get("sha256") != hashlib.sha256(content).hexdigest()
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or not isinstance(applied, list)
            or any(type(i) is not int for i in applied)
            or not isinstance(skipped, list)
            or any(
                not isinstance(i, dict) or type(i.get("operationIndex")) is not int for i in skipped
            )
            or sorted(applied + [i["operationIndex"] for i in skipped])
            != list(range(operation_count))
        ):
            raise ReportingError("native_ai_preview_invalid", "真实预览身份或执行回执不完整。")
        return {
            key: deepcopy(receipt[key])
            for key in ("previewDigest", "appliedOperationIndices", "skippedOperations")
        }

    async def _run_review(self, job, session, context, base, instruction):
        deadline = monotonic() + self.timeout_seconds
        try:
            async with asyncio.timeout(self.timeout_seconds):
                content = await self.editor.read_file(context)
                receipt = None
                if base:
                    receipt = await self.editor.preview_file(
                        context, expected_sha256=context.source_file.sha256, operations=base
                    )
                if job.status != "running":
                    return
                reader = await NativePDFReviewReader.from_bytes(
                    context, content, operations=base, draft_receipt=receipt
                )
                if job.status != "running":
                    return
                await job.event_log.emit("phase", label="正在处理批注")
                async with bind_agent_event_log(job.event_log):
                    result = await self.planner(
                        reader=reader,
                        instruction=instruction or "逐条处理全部批注。",
                        session_id=f"native-pdf-review:{job.task_id}",
                        user_id=context.scope.user_id,
                    )
                if job.status != "running":
                    return
                if monotonic() >= deadline:
                    raise TimeoutError
                if (
                    not isinstance(result, dict)
                    or not isinstance(result.get("answer"), str)
                    or not result["answer"].strip()
                ):
                    raise ReportingError("native_ai_output_empty", "未生成有效批注处理结果。")
                additions = _copy_operations(result.get("operations"))
                if any(op.get("kind") not in {"replaceText", "addMarkup", "removeMarkup"} for op in additions):
                    raise ReportingError(
                        "native_ai_schema_invalid", "批注处理只接受原位改字、文字标注、删除标注与可信回复候选。"
                    )
                removed = result.get("removedBaseOperationIndices", [])
                allowed = {mapping["operationIndex"] for mapping in
                           (reader.projection or {}).get("pendingMarkupMapping", [])}
                if (not isinstance(removed, list) or any(type(index) is not int or index not in allowed for index in removed)
                        or len(set(removed)) != len(removed)):
                    raise ReportingError("native_ai_schema_invalid", "撤销标注必须绑定已核验的草稿新增操作。")
                retained_base = [deepcopy(op) for index, op in enumerate(base) if index not in removed]
                base_mapping = {old: new for new, old in enumerate(index for index in range(len(base)) if index not in removed)}
                operations = [*retained_base, *additions]
                notes = deepcopy(result.get("notes", []))
                replies = result.get("replies", [])
                if not isinstance(notes, list) or not isinstance(replies, list):
                    raise ReportingError("native_ai_schema_invalid", "逐批注处理清单无效。")
                for note in notes:
                    deleted = note.get("removedBaseOperationIndices", [])
                    if not isinstance(deleted, list) or any(type(index) is not int or index not in removed for index in deleted):
                        raise ReportingError("native_ai_schema_invalid", "批注与草稿标注撤销映射无效。")
                    indices = note.get("operationIndices")
                    if not isinstance(indices, list) or any(
                        type(i) is not int or not 0 <= i < len(additions) for i in indices
                    ):
                        raise ReportingError("native_ai_schema_invalid", "批注与改字候选映射无效。")
                    note["operationIndices"] = [len(retained_base) + i for i in indices]
                if sorted(index for note in notes for index in note.get("removedBaseOperationIndices", [])) != sorted(removed):
                    raise ReportingError("native_ai_schema_invalid", "撤销草稿标注必须逐条且唯一追溯到批注。")
                if sorted(i for note in notes for i in note["operationIndices"]) != list(
                    range(len(retained_base), len(retained_base) + len(additions))
                ):
                    raise ReportingError(
                        "native_ai_schema_invalid", "新增正文操作必须逐条且唯一追溯到批注。"
                    )
                created_ms = int(time() * 1000)
                for reply in replies:
                    owners = [n for n in notes if n.get("reply") == reply]
                    if (
                        len(owners) != 1
                        or reply.get("author") != "AI Assistant"
                        or reply.get("intent") not in {"change", "clarify"}
                        or reply.get("intent") == "change"
                        and not (owners[0]["operationIndices"] or owners[0].get("removedBaseOperationIndices"))
                    ):
                        raise ReportingError(
                            "native_ai_schema_invalid", "批注回复身份或来源映射无效。"
                        )
                    owners[0]["replyOperationIndex"] = len(operations)
                    pending = pending_note_target(reader, owners[0].get("annotationId"))
                    if "parentOperationIndex" in reply:
                        if pending is None or any(reply.get(k) != v for k, v in pending.items()):
                            raise ReportingError(
                                "native_ai_schema_invalid", "待保存回复与原草稿归属不一致。"
                            )
                        root_index = base_mapping[pending["parentOperationIndex"]]
                        operations[root_index] = {
                            **operations[root_index],
                            "localId": pending["parentLocalId"],
                        }
                    elif pending is not None:
                        raise ReportingError(
                            "native_ai_schema_invalid", "新增便签不得伪造已保存来源身份。"
                        )
                    operations.append(
                        {
                            "kind": "replyPendingNote" if pending is not None else "replyNote",
                            "pageId": reply["pageId"],
                            **(
                                {"parentLocalId": pending["parentLocalId"]}
                                if pending is not None
                                else {
                                    "annotationId": reply["annotationId"],
                                    "expectedAnnotationSha256": reply["expectedAnnotationSha256"],
                                }
                            ),
                            "contents": reply["contents"],
                            "author": "AI Assistant",
                            "createdMs": created_ms,
                        }
                    )
                preview = await self.editor.preview_file(
                    context, expected_sha256=context.source_file.sha256, operations=operations
                )
                if job.status != "running":
                    return
                manifest = self._receipt(preview, context.source_file.sha256, len(operations))
                # 改字被真实引擎跳过时，不附加声称改字成功的回复。
                skipped = {i["operationIndex"] for i in manifest["skippedOperations"]}
                drop = {
                    n["replyOperationIndex"]
                    for n in notes
                    if (n.get("reply") or {}).get("intent") == "change"
                    and "replyOperationIndex" in n
                    and any(i in skipped for i in n["operationIndices"])
                }
                if drop:
                    mapping = {
                        old: new
                        for new, old in enumerate(
                            i for i in range(len(operations)) if i not in drop
                        )
                    }
                    operations = [op for i, op in enumerate(operations) if i not in drop]
                    for index, original in enumerate(retained_base):
                        if (
                            original.get("kind") == "addTextAnnotation"
                            and "localId" not in original
                            and not any(
                                op.get("kind") == "replyPendingNote"
                                and op.get("parentLocalId") == operations[index].get("localId")
                                for op in operations
                            )
                        ):
                            operations[index] = deepcopy(original)
                    for note in notes:
                        note["operationIndices"] = [mapping[i] for i in note["operationIndices"]]
                        if note.get("replyOperationIndex") in drop:
                            note.pop("replyOperationIndex")
                            note["replyOmittedReason"] = (
                                "关联改字实际跳过，未写入声称已修改的回复。"
                            )
                            note["reply"]["status"] = "omitted"
                        elif "replyOperationIndex" in note:
                            note["replyOperationIndex"] = mapping[note["replyOperationIndex"]]
                    preview = await self.editor.preview_file(
                        context, expected_sha256=context.source_file.sha256, operations=operations
                    )
                    if job.status != "running":
                        return
                    manifest = self._receipt(preview, context.source_file.sha256, len(operations))
                current = await self.editor.context_for_session(session)
                if current.digest() != job.context_sha256:
                    raise ReportingError("native_ai_snapshot_changed", "PDF 会话来源已变化。")
                if monotonic() >= deadline:
                    raise TimeoutError
                applied = set(manifest["appliedOperationIndices"])
                for note in notes:
                    note["appliedOperationIndices"] = [
                        i for i in note["operationIndices"] if i in applied
                    ]
                    note["skippedOperationIndices"] = [
                        i for i in note["operationIndices"] if i not in applied
                    ]
                    if note.get("status") != "skipped":
                        indices = [
                            *note["operationIndices"],
                            *(
                                [note["replyOperationIndex"]]
                                if "replyOperationIndex" in note
                                else []
                            ),
                        ]
                        note["status"] = (
                            "previewApplied"
                            if (indices or note.get("removedBaseOperationIndices")) and all(i in applied for i in indices)
                            else "skipped"
                        )
                if job.status == "running":
                    job.result = {
                        "answer": result["answer"],
                        "operations": operations,
                        "removedBaseOperationIndices": removed,
                        "notes": notes,
                        **manifest,
                        "coverage": reader.coverage(),
                        "issues": deepcopy(result.get("issues", [])),
                        "sourceSha256": context.source_file.sha256,
                        "baseSnapshotSha256": native_digest(base),
                        "toolEvents": deepcopy(reader.tool_events),
                        **(
                            {"projection": deepcopy(reader.projection)}
                            if reader.projection is not None
                            else {}
                        ),
                        "needsVerification": True,
                    }
                    job.status = "succeeded"
        except asyncio.CancelledError:
            job.status, job.result = "cancelled", None
            raise
        except Exception as error:
            if job.status == "cancelled":
                return
            code, message = (
                (error.code, error.message)
                if isinstance(error, ReportingError)
                else (
                    ("native_ai_timeout", "批注处理超时，请重试。")
                    if isinstance(error, TimeoutError)
                    else ("native_ai_review_failed", "批注处理失败，来源与草稿保持原样。")
                )
            )
            logger.warning(
                "native_pdf_review_failed edit_id={} error_type={}",
                job.task_id,
                type(error).__name__,
            )
            job.status, job.result, job.error = "failed", None, {"code": code, "message": message}
        finally:
            await job.event_log.finish(job.status)

    async def accept(self, session, edit_id, *, expected_sha256, operations, snapshot_sha256,
                     revalidate_session=None):
        context = await self._context(session)
        self._prune()
        base = _copy_operations(operations)
        job = next(
            (
                j
                for (digest, _), j in self._jobs.items()
                if digest == context.digest() and j.task_id == edit_id
            ),
            None,
        )
        if job is None:
            raise ReportingError("native_ai_job_missing", "批注处理任务不存在或已过期。")
        if (
            expected_sha256 != context.source_file.sha256
            or snapshot_sha256 != job.snapshot_sha256
            or base != getattr(job, "base", None)
        ):
            raise ReportingError("native_ai_snapshot_changed", "完整草稿或来源已变化，请重新处理。")
        proposal = job.result
        if job.status != "succeeded" or proposal is None or self._closed:
            raise ReportingError("native_ai_candidate_unavailable", "候选已取消或尚不可采纳。")
        preview = await self.editor.preview_file(
            context,
            expected_sha256=expected_sha256,
            operations=deepcopy(proposal["operations"]),
            expected_preview_digest=proposal["previewDigest"],
        )
        manifest = self._receipt(preview, expected_sha256, len(proposal["operations"]))
        current = await self.editor.context_for_session(session)
        await self.editor.read_file(current)
        # HTTP callers re-read the registered grant after the last external await.
        # Direct service callers retain their existing trusted-session contract.
        if revalidate_session is not None:
            registered = await revalidate_session()
            if (registered.report_id, registered.revision, registered.workflow_run_id,
                    registered.context_sha256, registered.capabilities) != (
                    session.report_id, session.revision, session.workflow_run_id,
                    session.context_sha256, session.capabilities):
                raise ReportingError("native_permission_denied", "编辑会话身份已变化。")
        if snapshot_sha256 != job.snapshot_sha256 or base != getattr(job, "base", None):
            raise ReportingError("native_ai_snapshot_changed", "完整草稿快照已变化。")
        if job.status != "succeeded" or job.result is not proposal or self._closed:
            raise ReportingError("native_ai_candidate_unavailable", "候选已取消，不能采纳。")
        if current.digest() != job.context_sha256 or manifest != {
            key: proposal[key] for key in manifest
        }:
            raise ReportingError("native_ai_preview_changed", "实际预览已变化，请重新处理。")
        return {
            "operations": deepcopy(proposal["operations"]),
            **manifest,
            "notes": deepcopy(proposal["notes"]),
            "needsVerification": True,
        }

    async def event_stream(self, session, edit_id, after=0):
        context = await self._context(session)
        self._prune()
        job = next((job for (digest, _), job in self._jobs.items()
                    if digest == context.digest() and job.task_id == edit_id), None)
        if job is None:
            raise ReportingError("native_ai_job_missing", "批注处理任务不存在或已过期。")
        return event_stream_response(job.event_log, after)

    @staticmethod
    def _serialize(job):
        return {
            "editId": job.task_id,
            "clientRequestId": job.client_request_id,
            "status": job.status,
            "snapshotSha256": job.snapshot_sha256,
            **({"proposal": deepcopy(job.result)} if job.result is not None else {}),
            **({"error": deepcopy(job.error)} if job.error else {}),
        }

    async def aclose(self):
        self._closed = True
        tasks = []
        for job in self._jobs.values():
            if job.task and not job.task.done():
                job.status, job.result = "cancelled", None
                tasks.append(job.task)
            elif job.status == "succeeded":
                job.status, job.result = "cancelled", None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for job in self._jobs.values():
            if job.status == "cancelled":
                await job.event_log.finish(job.status)
