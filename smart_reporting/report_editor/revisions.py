"""编辑器手动修订（幻灯片、工作簿）的编号与文件命名。

两类编辑器都可能从旧修订再次保存（完成消息中的编辑入口始终指向首个修订），也可能
有多个标签页同时保存，因此：

- 新修订号取已登记的最大修订号 + 1，不能用“当前修订 + 1”，否则会与已有修订撞号；
- 新文件名从原始文件名派生，并带随机后缀。若在上一修订文件名后继续追加后缀，
  文件名每次保存都会变长，最终超过文件系统 255 字节的单个文件名上限。
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from loguru import logger

# 以前的命名为 “-r{N}”（幻灯片）或 “-r{N}-{12 位十六进制}”（工作簿），可能已多次叠加。
_REVISION_SUFFIX = re.compile(r"(?:-r\d+(?:-[0-9a-f]{12})?)+$")


async def next_manual_revision(
    state_repository: Any, context: Any
) -> tuple[int, list[dict[str, str]]]:
    """返回新修订号；修订记录不可读时仍给出不与当前修订冲突的编号并附软告警。"""
    issues: list[dict[str, str]] = []
    contexts: Any = {}
    try:
        durable = await state_repository.get(context.workflow_run_id)
        if durable is not None:
            contexts = durable.payload.get("reportEditorContexts", {})
    except Exception as error:  # noqa: BLE001 - 编号回退到当前修订，文件名随机后缀保证不覆盖
        logger.warning(
            "report_editor_revision_lookup_failed report_id={} error_type={}",
            context.report_id,
            type(error).__name__,
        )
        issues.append({
            "code": "report_editor_revision_lookup_failed",
            "message": "修订记录暂不可读取，已为新文件保留独立身份。",
        })
    known = [int(key) for key in contexts if str(key).isdigit()] if isinstance(contexts, dict) else []
    return max([context.revision, *known]) + 1, issues


def revision_file_path(current_path: str, revision: int, *, suffix: str) -> str:
    """在原文件所在目录生成新修订文件路径，文件名长度不随保存次数增长。"""
    path = PurePosixPath(current_path)
    base = _REVISION_SUFFIX.sub("", path.stem) or path.stem
    return (path.parent / f"{base}-r{revision}-{uuid4().hex[:12]}{suffix}").as_posix()
