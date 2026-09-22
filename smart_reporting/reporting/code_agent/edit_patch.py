"""绑定脚本的多块 free-form 精确替换；统一定位后原子提交。"""

import re

from ..models import ReportingError

EDIT_PATCH_GRAMMAR = (
    'start: "*** Begin Edit" LF "*** SHA256: " SHA256 LF edit+ "*** End Edit" LF?\n'
    'edit: "<<<<<<< SEARCH" LF line+ "=======" LF line+ ">>>>>>> REPLACE" LF\n'
    'line: /[^\\n]+/ LF | LF\n'
    'SHA256: /[0-9a-f]{64}/\n'
    '%import common.LF'
)
_EDIT_PATCH = re.compile(
    r"\*\*\* Begin Edit\n\*\*\* SHA256: (?P<sha>[0-9a-f]{64})\n"
    r"(?P<body>.+)\*\*\* End Edit\n?",
    re.DOTALL,
)
_EDIT_BLOCK = re.compile(
    r"<<<<<<< SEARCH\n(?P<old>.+?)\n=======\n(?P<new>.*?)\n"
    r">>>>>>> REPLACE\n",
    re.DOTALL,
)
_MARKERS = ("*** Begin Edit", "<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE", "*** End Edit")


def parse_edit_patch(patch: str, max_source_bytes: int) -> tuple[list[tuple[str, str]], str]:
    """分隔符前的一个 LF 属于协议；块内字节（含 CRLF）原样保留。"""
    if isinstance(patch, str) and len(patch.encode("utf-8")) <= 2 * max_source_bytes + 256:
        match = _EDIT_PATCH.fullmatch(patch)
        if match:
            body = match["body"]
            edits: list[tuple[str, str]] = []
            position = 0
            while block := _EDIT_BLOCK.match(body, position):
                if any(marker in text.split("\n") for text in (block["old"], block["new"])
                       for marker in _MARKERS):
                    break
                edits.append((block["old"], block["new"]))
                position = block.end()
            if edits and position == len(body):
                return edits, match["sha"]
    raise ReportingError(
        "report_code_script_edit_invalid",
        "edit_script 需要一个含有效 SHA256 和一个或多个 SEARCH/REPLACE 块的原始补丁；"
        "SEARCH 不得为空，不接受 JSON、围栏、多份补丁或额外文字。"
        "标记独占一行并使用 LF；文本若需以换行结尾，请在分隔符前保留额外空行。",
        details={"nextTools": ["read_script", "edit_script"]},
    )


def apply_edit_blocks(source: str, edits: list[tuple[str, str]]) -> str:
    """所有块在同一原文中唯一定位，拒绝重叠和整份替换，再从后往前应用。"""
    replacements: list[tuple[int, int, str, int]] = []
    for index, (old, new) in enumerate(edits, 1):
        if old == new:
            raise _edit_error("unchanged", "SEARCH 与 REPLACE 文本不能相同。", index)
        start = source.find(old)
        if start < 0:
            raise _edit_error("not_found", "SEARCH 文本在原始脚本中不存在，请重新读取。", index)
        if source.find(old, start + 1) >= 0:
            raise _edit_error("ambiguous", "SEARCH 匹配多个位置，请增加上下文使其唯一。", index)
        replacements.append((start, start + len(old), new, index))
    replacements.sort()
    cursor = 0
    unchanged = []
    for start, end, _, index in replacements:
        if start < cursor:
            raise _edit_error("overlap", "SEARCH 块重叠，请合并为一个局部替换块。", index)
        unchanged.append(source[cursor:start])
        cursor = end
    unchanged.append(source[cursor:])
    if not "".join(unchanged).strip():
        raise _edit_error("not_local", "SEARCH 块合计覆盖整份脚本，请缩小到需要修改的局部。")
    for start, end, new, _ in reversed(replacements):
        source = source[:start] + new + source[end:]
    return source


def _edit_error(reason: str, message: str, block: int | None = None) -> ReportingError:
    return ReportingError(
        f"report_code_script_edit_{reason}", message,
        details={"nextTools": ["read_script", "edit_script"], "blockIndex": block},
    )
