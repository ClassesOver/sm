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

_invalid_details = {"nextTools": ["read_script", "edit_script"]}
# 块间与 End Edit 之后只含空白的多余内容不承载任何源码，按协议噪声容忍。
_BLANK_GAP = re.compile(r"[ \t\r]*(?:\n[ \t\r]*)*")


def _marker_hint(old: str, new: str, block_index: int) -> str:
    """定位被混入块内的协议标记，说明缺的是哪一行，而不只报 marker_in_block。"""

    old_lines, new_lines = old.split("\n"), new.split("\n")
    if "<<<<<<< SEARCH" in new_lines or "*** End Edit" in new_lines:
        return f"第 {block_index} 块 REPLACE 后缺少独占一行的 >>>>>>> REPLACE。"
    if "=======" in new_lines:
        return f"第 {block_index} 块含两个 ======= 分隔行；SEARCH 与 REPLACE 之间只能有一个。"
    if ">>>>>>> REPLACE" in old_lines or "<<<<<<< SEARCH" in old_lines:
        return f"第 {block_index} 块 SEARCH 后缺少独占一行的 =======。"
    return f"第 {block_index} 块的 SEARCH/REPLACE 文本中含有协议标记行。"


def parse_edit_patch(patch: str, max_source_bytes: int) -> tuple[list[tuple[str, str]], str]:
    """分隔符前的一个 LF 属于协议；块内字节（含 CRLF）原样保留。"""
    details = _invalid_details
    if isinstance(patch, str):
        patch_bytes = len(patch.encode("utf-8"))
        if patch_bytes > 2 * max_source_bytes + 256:
            details = {**_invalid_details, "reason": "oversized_patch",
                       "actualBytes": patch_bytes, "limitBytes": max_source_bytes}
        else:
            match = _EDIT_PATCH.fullmatch(patch.rstrip() + "\n") if patch.strip() else None
            if match is None:
                if _EDIT_PATCH.match(patch):
                    details = {**_invalid_details, "reason": "trailing_text"}
                else:
                    details = {**_invalid_details, "reason": "missing_envelope"}
            else:
                body = match["body"]
                edits: list[tuple[str, str]] = []
                position = 0
                marker_contaminated = False
                marker_hint = ""
                while block := _EDIT_BLOCK.match(body, position):
                    if any(marker in text.split("\n") for text in (block["old"], block["new"])
                           for marker in _MARKERS):
                        marker_contaminated = True
                        marker_hint = _marker_hint(block["old"], block["new"], len(edits) + 1)
                        break
                    edits.append((block["old"], block["new"]))
                    position = block.end()
                    gap = _BLANK_GAP.match(body, position)
                    if gap is not None and (
                        gap.end() == len(body) or body.startswith("<<<<<<< SEARCH", gap.end())
                    ):
                        position = gap.end()
                if edits and position == len(body):
                    return edits, match["sha"]
                details = {
                    **_invalid_details,
                    "reason": "trailing_text" if edits else (
                        "marker_in_block" if marker_contaminated else "no_valid_blocks"
                    ),
                    "blockIndex": len(edits) + 1 if marker_contaminated or position < len(body) else None,
                }
                if details["blockIndex"] is None:
                    details.pop("blockIndex")
                if marker_hint:
                    details["hint"] = marker_hint
    raise ReportingError(
        "report_code_script_edit_invalid",
        "edit_script 需要一个含有效 SHA256 和一个或多个 SEARCH/REPLACE 块的原始补丁；"
        "SEARCH 不得为空，不接受 JSON、围栏、apply-patch 差异、多份补丁或额外文字。"
        "标记独占一行并使用 LF；文本若需以换行结尾，请在分隔符前保留额外空行。"
        "逐行复制此模板（\\n 表示真实换行）："
        "*** Begin Edit\\n*** SHA256: <read_script 回执的 64 位十六进制>\\n"
        "<<<<<<< SEARCH\\n<原样复制要修改的源码行>\\n=======\\n<替换后的行>\\n"
        ">>>>>>> REPLACE\\n*** End Edit",
        details=details,
    )


def _line_spans(source: str) -> list[tuple[int, int]]:
    """每行 (起点, 不含换行符的终点)。"""

    spans: list[tuple[int, int]] = []
    position = 0
    for line in source.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        spans.append((position, position + len(content)))
        position += len(line)
    return spans


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _reindent(new: str, add: str, remove: str) -> str | None:
    lines = new.split("\n")
    result = []
    for line in lines:
        if not line.strip():
            result.append(line)
        elif remove:
            if not line.startswith(remove):
                return None
            result.append(line[len(remove):])
        else:
            result.append(add + line)
    return "\n".join(result)


def _fuzzy_candidates(
    source: str, old: str, new: str
) -> tuple[str, list[tuple[int, int, str]]]:
    """精确匹配失败后的整行容错：先忽略行尾空白，再允许整块统一缩进偏移。

    只在 SEARCH 由完整行构成时生效；返回 (匹配模式, [(起点, 终点, 替换文本)])。
    """

    search = old.split("\n")
    if not any(line.strip() for line in search):
        return "", []
    spans = _line_spans(source)
    lines = [source[a:b] for a, b in spans]
    count = len(search)
    trailing: list[tuple[int, int, str]] = []
    indented: list[tuple[int, int, str]] = []
    for index in range(len(lines) - count + 1):
        window = lines[index:index + count]
        start, end = spans[index][0], spans[index + count - 1][1]
        if all(a.rstrip() == b.rstrip() for a, b in zip(window, search, strict=True)):
            trailing.append((start, end, new))
            continue
        pairs = [
            (a, b) for a, b in zip(window, search, strict=True) if a.strip() or b.strip()
        ]
        if not pairs or any(not a.strip() or not b.strip() for a, b in pairs):
            continue
        source_indent, search_indent = _indent(pairs[0][0]), _indent(pairs[0][1])
        if source_indent.startswith(search_indent):
            add, remove = source_indent[len(search_indent):], ""
        elif search_indent.startswith(source_indent):
            add, remove = "", search_indent[len(source_indent):]
        else:
            continue
        if not add and not remove:
            continue
        if all(
            a.rstrip() == (add + b.rstrip() if add else b.rstrip()[len(remove):])
            and (add or b.startswith(remove))
            for a, b in pairs
        ):
            replacement = _reindent(new, add, remove)
            if replacement is not None:
                indented.append((start, end, replacement))
    if trailing:
        return "trailing_whitespace", trailing
    return ("indentation", indented) if indented else ("", [])


def apply_edit_blocks(source: str, edits: list[tuple[str, str]]) -> str:
    """所有块在同一原文中唯一定位，拒绝重叠和整份替换，再从后往前应用。"""
    return apply_edit_blocks_with_modes(source, edits)[0]


def apply_edit_blocks_with_modes(
    source: str, edits: list[tuple[str, str]]
) -> tuple[str, list[dict[str, object]]]:
    """同 apply_edit_blocks，并返回使用了容错定位的块（blockIndex, matchMode）。"""
    replacements: list[tuple[int, int, str, int]] = []
    fuzzy: list[dict[str, object]] = []
    for index, (old, new) in enumerate(edits, 1):
        if old == new:
            raise _edit_error("unchanged", "SEARCH 与 REPLACE 文本不能相同。", index)
        start = source.find(old)
        if start < 0:
            mode, candidates = _fuzzy_candidates(source, old, new)
            if not candidates:
                raise _edit_error("not_found", "SEARCH 文本在原始脚本中不存在，请重新读取。", index)
            if len(candidates) > 1:
                raise _edit_error("ambiguous", "SEARCH 匹配多个位置，请增加上下文使其唯一。", index)
            fuzzy_start, fuzzy_end, fuzzy_new = candidates[0]
            replacements.append((fuzzy_start, fuzzy_end, fuzzy_new, index))
            fuzzy.append({"blockIndex": index, "matchMode": mode})
            continue
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
    return source, fuzzy


def _edit_error(reason: str, message: str, block: int | None = None) -> ReportingError:
    return ReportingError(
        f"report_code_script_edit_{reason}", message,
        details={"nextTools": ["read_script", "edit_script"], "blockIndex": block},
    )
