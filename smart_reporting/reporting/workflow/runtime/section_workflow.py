"""章节证据读取与终态提交的固定执行链。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agno.run import RunContext

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
        files: list[SectionEvidenceFile] = []
        for evidence in work_item.evidence:
            for identity in evidence.evidence_files:
                offset = 0
                chunks: list[str] = []
                while True:
                    reply = await self.read_evidence(identity.path, offset, context)
                    content = reply.get("content")
                    if not isinstance(content, str) or not content:
                        raise ReportingError(
                            "report_section_evidence_invalid", "证据读取回执缺少有效 content。"
                        )
                    returned_sha = reply.get("sha256")
                    if returned_sha is not None and returned_sha != identity.sha256:
                        raise ReportingError(
                            "report_phase_artifact_changed",
                            "证据文件 SHA-256 与冻结身份不一致。",
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
                files.append(SectionEvidenceFile(identity=identity, content="".join(chunks)))
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
        decision = await self.generate(bundle, context)
        recovery_used = False
        for attempt in range(2):
            try:
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
                        "evidence": bundle.model_dump(mode="json", by_alias=True),
                        "diagnostic": str(error)[:2000],
                    },
                    context,
                )
        raise RuntimeError("章节固定 Workflow 状态不可达")


__all__ = ["SectionWorkflow", "SectionWorkflowResult"]
