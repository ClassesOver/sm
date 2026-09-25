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
_BLANK_GAP = re.compile(r"[ \t\r\n]*")


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
                marker_hint = ""
                while block := _EDIT_BLOCK.match(body, position):
                    if any(marker in text.split("\n") for text in (block["old"], block["new"])
                           for marker in _MARKERS):
                        marker_hint = _marker_hint(block["old"], block["new"], len(edits) + 1)
                        break
                    edits.append((block["old"], block["new"]))
                    position = block.end()
                    gap_end = _BLANK_GAP.match(body, position).end()
                    if gap_end == len(body) or body.startswith("<<<<<<< SEARCH", gap_end):
                        position = gap_end
                if edits and position == len(body):
                    return edits, match["sha"]
                details = {
                    **_invalid_details,
                    "reason": "trailing_text" if edits else (
                        "marker_in_block" if marker_hint else "no_valid_blocks"
                    ),
                    "blockIndex": len(edits) + 1 if marker_hint or position < len(body) else None,
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


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _reindent(text: str, add: str, remove: str) -> str | None:
    """按统一偏移调整非空行缩进；需去除的前缀不存在时返回 None。

    只按 LF 切行：textwrap.indent 会在 \u2028、\x0c 等处切分，改写字符串字面量。
    """

    lines = []
    for line in text.split("\n"):
        if not line.strip():
            lines.append(line)
        elif add:
            lines.append(add + line)
        elif line.startswith(remove):
            lines.append(line[len(remove):])
        else:
            return None
    return "\n".join(lines)


def _indent_shift(window: list[str], search: list[str]) -> tuple[str, str] | None:
    """源码窗口相对 SEARCH 的统一缩进偏移 (add, remove)；不一致或为零时返回 None。"""

    pairs = [(a, b) for a, b in zip(window, search, strict=True) if a.strip() or b.strip()]
    if not pairs or any(not a.strip() or not b.strip() for a, b in pairs):
        return None
    source_indent, search_indent = _indent(pairs[0][0]), _indent(pairs[0][1])
    if source_indent.startswith(search_indent):
        shift = (source_indent[len(search_indent):], "")
    elif search_indent.startswith(source_indent):
        shift = ("", search_indent[len(source_indent):])
    else:
        return None
    if shift == ("", ""):
        return None
    shifted = _reindent("\n".join(b for _, b in pairs), *shift)
    if shifted is None or any(
        a.rstrip() != b.rstrip() for (a, _), b in zip(pairs, shifted.split("\n"), strict=True)
    ):
        return None
    return shift


def _fuzzy_candidates(
    lines: list[str], offsets: list[int], old: str, new: str
) -> tuple[str, list[tuple[int, int, str]], str]:
    """精确匹配失败后的整行容错：先忽略行尾空白，再允许整块统一缩进偏移。

    lines/offsets 为源码按 LF 切分的行及其起点；返回 (匹配模式, 候选, 提示)。
    SEARCH 以换行结尾（协议中"分隔符前保留空行"的写法）时，匹配区域同样包含
    末行换行。
    """

    trailing_newline = old.endswith("\n")
    search = (old[:-1] if trailing_newline else old).split("\n")
    if not any(line.strip() for line in search):
        return "", [], ""
    count = len(search)
    trailing: list[tuple[int, int, str]] = []
    indented: list[tuple[int, int, str]] = []
    hint = ""
    last = len(lines) - count - (1 if trailing_newline else 0)
    for index in range(last + 1):
        window = lines[index:index + count]
        start = offsets[index]
        end = offsets[index + count - 1] + len(window[-1]) + (1 if trailing_newline else 0)
        if all(a.rstrip() == b.rstrip() for a, b in zip(window, search, strict=True)):
            trailing.append((start, end, new))
            continue
        shift = _indent_shift(window, search)
        if shift is None:
            continue
        if '"""' in new or "\'\'\'" in new:
            # 重排缩进会改变多行字符串字面量的值，不做自动对齐。
            hint = "SEARCH 按缩进偏移可唯一定位，但 REPLACE 含多行字符串，无法安全重排缩进；请按原文缩进逐字复制。"
            continue
        replacement = _reindent(new, *shift)
        if replacement is None:
            hint = "SEARCH 按缩进偏移可唯一定位，但 REPLACE 有行的缩进小于偏移量，无法对齐；请按原文缩进逐字复制。"
            continue
        indented.append((start, end, replacement))
    if trailing:
        return "trailing_whitespace", trailing, ""
    return ("indentation", indented, "") if indented else ("", [], hint)


def _starts_after_indent(source: str, position: int) -> bool:
    line_start = source.rfind("\n", 0, position) + 1
    prefix = source[line_start:position]
    return bool(prefix) and not prefix.strip(" \t")


def apply_edit_blocks(
    source: str, edits: list[tuple[str, str]]
) -> tuple[str, list[dict[str, object]]]:
    """所有块在同一原文中唯一定位，拒绝重叠和整份替换，再从后往前应用。

    精确匹配优先；失败时按整行容错定位（仍须唯一）。返回 (新源码, 容错定位的块
    [{blockIndex, matchMode}])。
    """
    line_table: tuple[list[str], list[int]] | None = None

    def split_lines() -> tuple[list[str], list[int]]:
        # 只在需要整行容错时切分源码；精确匹配的常见路径不付出这份开销。
        nonlocal line_table
        if line_table is None:
            lines = source.split("\n")
            offsets = [0]
            for line in lines[:-1]:
                offsets.append(offsets[-1] + len(line) + 1)
            line_table = (lines, offsets)
        return line_table

    replacements: list[tuple[int, int, str, int]] = []
    fuzzy: list[dict[str, object]] = []
    for index, (old, new) in enumerate(edits, 1):
        if old == new:
            raise _edit_error("unchanged", "SEARCH 与 REPLACE 文本不能相同。", index)
        start = source.find(old)
        if start >= 0:
            mode, hint = "", ""
            candidates = [(start, start + len(old), new)]
            if source.find(old, start + 1) >= 0:
                candidates.append(candidates[0])
            elif "\n" in new and _starts_after_indent(source, start):
                # SEARCH 从缩进之后开始、REPLACE 跨多行时，逐字插入会让后续行丢失
                # 缩进、悄悄改变代码块归属；整行缩进对齐的唯一候选覆盖同一位置时优先。
                aligned_mode, aligned, _ = _fuzzy_candidates(*split_lines(), old, new)
                if (
                    aligned_mode == "indentation"
                    and len(aligned) == 1
                    and aligned[0][0] <= start < aligned[0][1]
                ):
                    mode, candidates = aligned_mode, aligned
        else:
            mode, candidates, hint = _fuzzy_candidates(*split_lines(), old, new)
        if not candidates:
            error = _edit_error("not_found", "SEARCH 文本在原始脚本中不存在，请重新读取。", index)
            if hint:
                error.details["hint"] = hint
            raise error
        if len(candidates) > 1:
            raise _edit_error("ambiguous", "SEARCH 匹配多个位置，请增加上下文使其唯一。", index)
        replacements.append((*candidates[0], index))
        if mode:
            fuzzy.append({"blockIndex": index, "matchMode": mode})
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
