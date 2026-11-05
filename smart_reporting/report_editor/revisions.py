"""编辑器手动修订（幻灯片、工作簿）的编号与文件命名。

两类编辑器都可能从旧修订再次保存（完成消息中的编辑入口始终指向首个修订），也可能
有多个标签页同时保存，因此：

- 新修订号通过状态 CAS 预留，超过已登记及已预留编号；失败保存可留下编号空缺；
- 新文件名从原始文件名派生，并带随机后缀。若在上一修订文件名后继续追加后缀，
  文件名每次保存都会变长，最终超过文件系统 255 字节的单个文件名上限。
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from loguru import logger

from ..reporting.workflow.state import ReportingCommand, ReportingStateConflict

# 以前的命名为 “-r{N}”（幻灯片）或 “-r{N}-{12 位十六进制}”（工作簿），可能已多次叠加。
_REVISION_SUFFIX = re.compile(r"(?:-r\d+(?:-[0-9a-f]{12})?)+$")


async def apply_editor_command(
    state_repository: Any, run_id: str, command: ReportingCommand, *, state: Any = None,
) -> Any:
    """只重试状态版本冲突；调用方保留非阻断的交付失败处理。"""
    for attempt in range(16):
        if state is None:
            state = await state_repository.get(run_id)
        try:
            return await state_repository.apply(run_id, command, expected_version=state.state_version)
        except ReportingStateConflict:
            if attempt == 15:
                raise
            state = None


async def next_manual_revision(
    state_repository: Any, context: Any
) -> tuple[int, list[dict[str, str]]]:
    """通过状态 CAS 预留编号；状态不可用时保留独立文件并附软告警。"""
    issues: list[dict[str, str]] = []
    contexts: Any = {}
    try:
        durable = await state_repository.get(context.workflow_run_id)
        if durable is not None:
            contexts = durable.payload.get("reportEditorContexts", {})
        result = await apply_editor_command(
            state_repository, context.workflow_run_id,
            ReportingCommand(
                name="reserve_report_editor_revision",
                payload={"minimumRevision": context.revision},
                commandId=f"editor-revision:{uuid4().hex}",
            ),
            state=durable,
        )
        return result.state.payload["reportEditorRevisionCounter"], issues
    except Exception as error:  # noqa: BLE001 - 编号回退到当前修订，文件名随机后缀保证不覆盖
        logger.warning(
            "report_editor_revision_lookup_failed report_id={} error_type={}",
            context.report_id,
            type(error).__name__,
        )
        issues.append({
            "code": "report_editor_revision_lookup_failed",
            "message": "修订编号暂无法预留，已为新文件保留独立身份。",
        })
    known = [int(key) for key in contexts if str(key).isdigit()] if isinstance(contexts, dict) else []
    return max([context.revision, *known]) + 1, issues


def revision_file_path(current_path: str, revision: int, *, suffix: str) -> str:
    """在原文件所在目录生成新修订文件路径，文件名长度不随保存次数增长。"""
    path = PurePosixPath(current_path)
    base = _REVISION_SUFFIX.sub("", path.stem) or path.stem
    return (path.parent / f"{base}-r{revision}-{uuid4().hex[:12]}{suffix}").as_posix()
