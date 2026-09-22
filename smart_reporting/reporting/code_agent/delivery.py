"""从任务绑定生成可跨上下文压缩保留的交付状态。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ...workspace import WorkspaceError
from ..models import ReportingError
from ..workflow.checkpoint import ChartVisualInspectionReceipt

if TYPE_CHECKING:
    from .toolkit import ReportingCodeModeToolkit

DELIVERY_STATE_MARKER = "REPORTING_CODE_DELIVERY_STATE"


def _visual_review_model_receipt(
    receipt: ChartVisualInspectionReceipt,
) -> dict[str, Any]:
    """将完整审计回执投影为最小模型可见结果。"""

    result: dict[str, Any] = {
        "sourcePath": receipt.source_path,
        "sha256": receipt.sha256,
        "visualReviewStatus": receipt.visual_review_status,
        "reviewed": receipt.reviewed,
        "requiresRevision": receipt.requires_revision,
    }
    critical_issues = [
        {
            "category": issue.category,
            "severity": issue.severity,
            "description": issue.description,
        }
        for issue in receipt.issues
        if issue.severity == "critical"
    ]
    if not receipt.requires_revision:
        result.update(
            {
                "warningCount": sum(
                    issue.severity == "warning" for issue in receipt.issues
                ),
                "message": "非阻断问题已记录，无需修改。",
            }
        )
        return result
    result["criticalIssues"] = critical_issues
    # suggestions 是独立的可选改进，没有 issue 关联；即使全部 issues
    # 都是 critical，也不能证明这些建议属于必需修复。完整内容保留在审计回执。
    return result


def merge_visual_failures(failures: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """合并跨图片完全相同的问题，给修复模型一次统一反馈。"""

    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for failure in failures:
        path = failure.get("path")
        issues = failure.get("issues")
        if not isinstance(path, str) or not isinstance(issues, list):
            continue
        normalized_issues = [
            issue for issue in issues
            if isinstance(issue, Mapping)
            and all(isinstance(issue.get(field), str) for field in ("category", "severity", "description"))
        ]
        key = tuple(
            (issue["category"], issue["severity"], issue["description"])
            for issue in normalized_issues
        )
        if not key:
            continue
        group = groups.get(key)
        if group is None:
            group = {
                "path": path,
                "paths": [],
                "summary": str(failure.get("summary", ""))[:256],
                "issues": normalized_issues[:3],
                "suggestions": [],
            }
            groups[key] = group
        if path not in group["paths"]:
            group["paths"].append(path)
        for suggestion in failure.get("suggestions", []):
            if isinstance(suggestion, str) and suggestion not in group["suggestions"]:
                group["suggestions"].append(suggestion[:256])
    return list(groups.values())


def _diagnostic_summary(diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    details = diagnostic.get("details")
    result = {
        "code": str(diagnostic.get("code", ""))[:128],
        "message": str(diagnostic.get("message", ""))[:512],
        "details": {
            key: str(details[key])[-limit:]
            for key, limit in (("reason", 256), ("errorType", 128), ("line", 12), ("column", 12),
                               ("traceback", 1024), ("stderr", 512), ("issueSummary", 1024),
                               ("sourceSha256", 64), ("sourceExcerpt", 1800),
                               ("sourceStartLine", 12), ("sourceEndLine", 12), ("errorLine", 12))
            if isinstance(details, Mapping) and details.get(key) is not None
        },
    }
    if isinstance(details, Mapping):
        for key in ("readRange", "allowedEditRegion"):
            region = details.get(key)
            if not isinstance(region, Mapping):
                continue
            start, end = region.get("startLine"), region.get("endLine")
            path = region.get("path")
            if (
                type(start) is int and type(end) is int and 1 <= start <= end
                and isinstance(path, str) and 0 < len(path) <= 1024
            ):
                result["details"][key] = {"path": path, "startLine": start, "endLine": end}
    return result


async def build_delivery_state(toolkit: ReportingCodeModeToolkit) -> dict[str, Any]:
    binding = toolkit.binding
    source_hash = await toolkit._source_sha256()
    receipt = binding.execution_receipt
    valid = bool(receipt and receipt.source_file.sha256 == source_hash)
    if valid:
        try:
            valid = await toolkit._declared_output_identities() == receipt.output_files
        except (ReportingError, WorkspaceError):
            valid = False
    pending = toolkit.pending_output_validation if valid else None
    reviews = [
        item.path for item in (receipt.output_files if receipt and valid else ())
        if binding.context.task_kind == "visualization"
        and not toolkit.has_current_visual_review(item.path)
    ]
    visual_failures = [
        review for path in reviews
        if (review := binding.visual_inspection_receipts.get(path)) is not None
        and receipt is not None
        and any(item.path == path and item.sha256 == review.sha256 for item in receipt.output_files)
    ]
    reviews = [path for path in reviews if all(item.source_path != path for item in visual_failures)]
    failure = toolkit.last_failure
    if failure and (failure["resolved"] or failure["sourceSha256"] != source_hash):
        failure = None
    submitted = valid and toolkit.submitted_receipt == receipt
    if submitted:
        next_tools, action = [], "当前产物已提交。"
    elif source_hash is None:
        next_tools, action = ["write_script"], "写入绑定脚本，然后运行。"
    elif pending:
        if binding.output_validation.status == "failed":
            next_tools = ["read_script", "edit_script", "run_script"]
            action = "修复输出结构预检指出的问题后重新运行。"
        else:
            next_tools, action = ["run_script"], "输出结构预检未获得可用结论，重新运行后检查结果。"
    elif not valid:
        if failure and failure["tool"] in {"write_script", "edit_script", "run_script"}:
            next_tools = ["read_script", "edit_script", "run_script"]
            action = "结合最近失败诊断修复脚本，再运行；不要原样重复失败操作。"
        else:
            next_tools, action = ["run_script"], "当前源码或输出尚无有效执行回执，运行绑定脚本。"
    elif visual_failures:
        next_tools = ["read_script", "edit_script", "run_script"]
        action = "根据 visualFailures 修复脚本后重新运行并审查新图片；重复查看当前图片只会返回缓存结论。"
    elif reviews:
        next_tools, action = ["view_image"], "只审查 nextReviewPaths 中尚未通过的当前图片，然后提交。"
    else:
        next_tools, action = ["submit_script"], "当前执行与审查已满足提交条件，直接提交，无需重复运行。"
    visual_failure_payloads = []
    for item in visual_failures[:3]:
        projected = _visual_review_model_receipt(item)
        visual_failure_payloads.append(
            {
                "path": item.source_path,
                # 视觉 summary/warnings 只保存在完整审计 receipt，不能重新
                # 注入模型上下文；critical issue 本身就是唯一修复上下文。
                "summary": "",
                "issues": projected.get("criticalIssues", []),
                "suggestions": projected.get("suggestions", []),
            }
        )
    return {
        "marker": DELIVERY_STATE_MARKER,
        "taskId": binding.context.task_id,
        "taskKind": binding.context.task_kind,
        "script": {"path": binding.context.script_path, "sha256": source_hash},
        "execution": {"runId": receipt.run_id, "valid": valid} if receipt else None,
        "outputValidation": binding.output_validation.status if valid else "not_checked",
        "validationFailure": (
            _diagnostic_summary(pending) if pending else None
        ),
        "lastFailure": (
            {"tool": failure["tool"], **_diagnostic_summary(failure)} if failure else None
        ),
        "visualFailures": merge_visual_failures(visual_failure_payloads),
        "pendingReviewCount": len(reviews),
        "nextReviewPaths": reviews[:5],
        "submitted": submitted,
        "nextTools": next_tools,
        "requiredAction": action,
    }
