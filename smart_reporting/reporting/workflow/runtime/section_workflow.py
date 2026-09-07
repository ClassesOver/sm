"""章节证据读取与终态提交的固定执行链。"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agno.run import RunContext
from loguru import logger

from ...models import ReportingError
from ..checkpoint import SectionWorkItem
from .phase_models import (
    AnalysisReworkDecision,
    RenderSectionDecision,
    SectionDecision,
    SectionEvidenceBundle,
    SectionEvidenceFile,
)

ReadEvidence = Callable[[str, int, RunContext], Awaitable[Mapping[str, Any]]]
GenerateSection = Callable[[SectionEvidenceBundle, RunContext], Awaitable[SectionDecision]]
RecoverSection = Callable[[Mapping[str, Any], RunContext], Awaitable[SectionDecision]]
RenderSection = Callable[[RenderSectionDecision, RunContext], Awaitable[Mapping[str, Any]]]
RequestRework = Callable[[AnalysisReworkDecision, RunContext], Awaitable[Mapping[str, Any]]]

_NON_RECOVERABLE_CODES = frozenset(
    {
        "report_phase_artifact_changed",
        "report_capability_invalid",
        "report_task_lease_conflict",
        "report_task_cancelled",
        "report_task_timeout",
        "report_workspace_unavailable",
    }
)


def _section_recovery_diagnostic(error: Exception) -> dict[str, Any]:
    """保留服务端拒绝码与修复动作，避免 recovery Agent 只看到外层摘要。"""

    diagnostic: dict[str, Any] = {"message": str(error)[:2000]}
    if isinstance(error, ReportingError):
        diagnostic["code"] = error.code
        if isinstance(error.details, Mapping):
            diagnostic["details"] = dict(error.details)
    return diagnostic


@dataclass(frozen=True, slots=True)
class SectionWorkflowResult:
    status: str
    decision: SectionDecision
    recovery_used: bool = False


class SectionWorkflow:
    def __init__(
        self,
        *,
        read_evidence: ReadEvidence,
        generate: GenerateSection,
        recover: RecoverSection | None,
        render: RenderSection,
        rework: RequestRework,
    ) -> None:
        self.read_evidence = read_evidence
        self.generate = generate
        self.recover = recover
        self.render = render
        self.rework = rework

    async def _read_bundle(
        self, work_item: SectionWorkItem, context: RunContext
    ) -> SectionEvidenceBundle:
        identities_by_path: dict[str, object] = {}
        unique_identities: list[Any] = []
        for evidence in work_item.evidence:
            for identity in evidence.evidence_files:
                frozen_identity = identity.model_dump(mode="json", by_alias=True)
                previous = identities_by_path.get(identity.path)
                if previous is not None:
                    if previous != frozen_identity:
                        raise ReportingError(
                            "report_section_evidence_invalid",
                            "同一路径绑定了不同的冻结证据身份。",
                        )
                    continue
                identities_by_path[identity.path] = frozen_identity
                unique_identities.append(identity)
        files: list[SectionEvidenceFile] = []
        for identity in unique_identities:
            offset = 0
            chunks: list[str] = []
            while True:
                reply = await self.read_evidence(identity.path, offset, context)
                content = reply.get("content")
                if not isinstance(content, str) or not content:
                    raise ReportingError(
                        "report_section_evidence_invalid", "证据读取回执缺少有效 content。"
                    )
                if (
                    reply.get("path") != identity.path
                    or reply.get("offset") != offset
                    or reply.get("totalBytes") != identity.size
                    or reply.get("sha256") != identity.sha256
                ):
                    raise ReportingError(
                        "report_phase_artifact_changed",
                        "证据读取回执与冻结文件身份不一致。",
                    )
                chunks.append(content)
                if reply.get("hasMore") is False:
                    break
                next_offset = reply.get("nextOffset")
                if next_offset is None:
                    break
                if not isinstance(next_offset, int) or next_offset <= offset:
                    raise ReportingError(
                        "report_section_evidence_invalid", "证据续读 offset 无效。"
                    )
                offset = next_offset
            complete_content = "".join(chunks)
            complete_bytes = complete_content.encode("utf-8")
            if (
                len(complete_bytes) != identity.size
                or hashlib.sha256(complete_bytes).hexdigest() != identity.sha256
            ):
                raise ReportingError(
                    "report_phase_artifact_changed",
                    "证据正文与冻结文件身份不一致。",
                )
            files.append(SectionEvidenceFile(identity=identity, content=complete_content))
        if not files:
            raise ReportingError(
                "report_section_evidence_missing", "章节没有可授权 evidence 文件。"
            )
        return SectionEvidenceBundle(
            sectionCode=work_item.section_code,
            files=tuple(files),
            factSummaries=work_item.fact_summaries,
        )

    async def run(self, work_item: SectionWorkItem, context: RunContext) -> SectionWorkflowResult:
        bundle = await self._read_bundle(work_item, context)
        decision: SectionDecision | None = None
        recovery_used = False
        for attempt in range(2):
            try:
                if decision is None:
                    decision = await self.generate(bundle, context)
                if decision.section_code != work_item.section_code:
                    raise ReportingError(
                        "report_section_artifact_invalid", "章节决定没有绑定当前 sectionCode。"
                    )
                receipt = (
                    await self.render(decision, context)
                    if isinstance(decision, RenderSectionDecision)
                    else await self.rework(decision, context)
                )
                if receipt.get("status") != "accepted":
                    logger.bind(
                        section_code=work_item.section_code,
                        rejection_code=str(receipt.get("code", "report_section_submit_rejected")),
                    ).warning("report_section_submission_rejected")
                    raise ReportingError(
                        "report_section_submit_rejected",
                        "章节终态提交未被接受。",
                        details=dict(receipt),
                    )
                return SectionWorkflowResult("accepted", decision, recovery_used)
            except Exception as error:
                if isinstance(error, ReportingError) and error.code in _NON_RECOVERABLE_CODES:
                    raise
                if attempt == 1 or self.recover is None:
                    raise
                recovery_used = True
                decision = await self.recover(
                    {
                        "diagnostic": _section_recovery_diagnostic(error),
                    },
                    context,
                )
        raise RuntimeError("章节固定 Workflow 状态不可达")


__all__ = ["SectionWorkflow", "SectionWorkflowResult"]
