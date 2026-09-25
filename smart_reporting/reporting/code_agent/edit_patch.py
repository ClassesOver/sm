"""绑定脚本的多块 free-form 精确替换；统一定位后原子提交。"""

import re
from dataclasses import dataclass
from typing import Literal

from ..models import ReportingError

EDIT_PATCH_GRAMMAR = (
    "start: edit_envelope | patch_envelope\n"
    'edit_envelope: "*** Begin Edit" LF "*** SHA256: " SHA256 LF (edit+ | hunks) "*** End Edit" LF?\n'
    'patch_envelope: "*** Begin Patch" LF ("*** SHA256: " SHA256 LF)? '
    '"*** Update File: " PATH LF hunks "*** End Patch" LF?\n'
    'edit: "<<<<<<< SEARCH" LF line+ "=======" LF line+ ">>>>>>> REPLACE" LF\n'
    "hunks: hunk+ (\"*** End of File\" LF)?\n"
    "hunk: hunk_header? change_line+\n"
    'hunk_header: "@@" TEXT? LF\n'
    "TEXT: /[^\\n]+/\n"
    "change_line: /[ +\\-][^\\n]*/ LF | LF\n"
    'line: /[^\\n]+/ LF | LF\n'
    "PATH: /[^\\n]+/\n"
    'SHA256: /[0-9a-f]{64}/\n'
    '%import common.LF'
)
_EDIT_PATCH = re.compile(
    r"\*\*\* Begin Edit\n\*\*\* SHA256: (?P<sha>[0-9a-f]{64})\n"
    r"(?P<body>.+)\*\*\* End Edit\n?",
    re.DOTALL,
)
# 空 REPLACE（删除）允许 ======= 后直接跟 >>>>>>> REPLACE；中间保留一个空行的
# 旧写法仍解析为空文本，两种写法语义一致。
_EDIT_BLOCK = re.compile(
    r"<<<<<<< SEARCH\n(?P<old>.+?)\n=======\n(?:(?P<new>.*?)\n)?"
    r">>>>>>> REPLACE\n",
    re.DOTALL,
)
_MARKERS = ("*** Begin Edit", "<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE", "*** End Edit")

_invalid_details = {"nextTools": ["read_script", "edit_script"]}
# 块间与 End Edit 之后只含空白的多余内容不承载任何源码，按协议噪声容忍。
_BLANK_GAP = re.compile(r"[ \t\r\n]*")


_SHA_LINE = re.compile(r"\*\*\* SHA256:[ \t]*([0-9A-Fa-f]{64})[ \t]*")


def _normalize_patch(patch: str) -> str:
    """只消除无歧义的格式噪声：整份 CRLF、首部空行、标记行尾空白与 SHA 大小写。

    信封行本身为 CRLF 说明整份补丁被换行转换，统一回 LF；信封为 LF 时块内字节
    （含 CRLF）原样保留。缺少 *** End Edit 多见于输出截断，可能丢失后续块，
    仍按无效补丁拒绝。
    """

    patch = patch.lstrip(" \t\r\n")
    if patch.startswith("*** Begin Edit\r\n"):
        patch = patch.replace("\r\n", "\n")
    lines = patch.split("\n")
    normalized = []
    for line in lines:
        stripped = line.rstrip(" \t")
        if stripped in _MARKERS:
            normalized.append(stripped)
        elif sha := _SHA_LINE.fullmatch(line):
            normalized.append(f"*** SHA256: {sha[1].lower()}")
        else:
            normalized.append(line)
    return "\n".join(normalized)


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
            patch = _normalize_patch(patch)
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
                    replacement = block["new"] or ""
                    if any(marker in text.split("\n") for text in (block["old"], replacement)
                           for marker in _MARKERS):
                        marker_hint = _marker_hint(block["old"], replacement, len(edits) + 1)
                        break
                    edits.append((block["old"], replacement))
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


PatchFormat = Literal["search_replace", "apply_patch", "edit_envelope_hunks"]


@dataclass(frozen=True, slots=True)
class ScriptPatch:
    """edit_script 输入的统一解析结果；各格式都归一为 (SEARCH, REPLACE) 块。"""

    edits: list[tuple[str, str]]
    sha256: str | None
    patch_format: PatchFormat
    path: str | None = None


_APPLY_PATCH_ENVELOPE = re.compile(
    r"\*\*\* Begin Patch\n(?:\*\*\* SHA256: (?P<sha>[0-9a-f]{64})\n)?"
    r"(?P<body>.*?)\*\*\* End Patch\n?",
    re.DOTALL,
)
_UPDATE_FILE = "*** Update File: "
_UNSUPPORTED_FILE_OPERATIONS = ("*** Add File: ", "*** Delete File: ", "*** Move to: ")
_HUNK_LINE = re.compile(r"^(?:@@.*|[ +\-].*|)$")


def _apply_patch_error(reason: str, message: str, **details: object) -> ReportingError:
    return ReportingError(
        "report_code_script_edit_invalid",
        message,
        details={**_invalid_details, "reason": reason, "patchFormat": "apply_patch", **details},
    )


def _parse_hunks(body: str) -> list[tuple[str, str]]:
    """把 Codex apply_patch 的 hunk（@@ / 空格 / - / + 行）转换为 SEARCH/REPLACE 块。

    上下文与删除行组成 SEARCH，上下文与新增行组成 REPLACE；@@ 只作 hunk 分隔，
    定位仍由唯一匹配决定，歧义时要求补充上下文。纯新增 hunk 没有定位锚点，拒绝。
    """

    lines = body.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if lines and lines[-1] == "*** End of File":
        lines.pop()
    hunks: list[list[str]] = [[]]
    for number, line in enumerate(lines, 1):
        if line.startswith("@@"):
            if hunks[-1]:
                hunks.append([])
            continue
        if line.startswith("*** "):
            raise _apply_patch_error(
                "apply_patch_operation_unsupported",
                "edit_script 只支持对当前绑定脚本的单个 *** Update File；"
                "不支持新增、删除、移动文件或多文件补丁。",
                line=number,
            )
        if not _HUNK_LINE.match(line):
            raise _apply_patch_error(
                "apply_patch_line_prefix_missing",
                f"补丁第 {number} 行缺少行首标记：上下文行以一个空格开头，删除行以 -、"
                "新增行以 + 开头。",
                line=number,
            )
        hunks[-1].append(line)
    edits: list[tuple[str, str]] = []
    for index, hunk in enumerate((item for item in hunks if item), 1):
        old = [line[1:] for line in hunk if line[:1] in {" ", "-", ""}]
        new = [line[1:] for line in hunk if line[:1] in {" ", "+", ""}]
        if not any(line[:1] in {"+", "-"} for line in hunk):
            raise _apply_patch_error(
                "apply_patch_hunk_without_change",
                f"第 {index} 个 hunk 没有 - 或 + 行。",
                blockIndex=index,
            )
        if not any(line.strip() for line in old):
            raise _apply_patch_error(
                "apply_patch_hunk_without_context",
                f"第 {index} 个 hunk 只有新增行，无法定位插入位置；请带上至少一行原文上下文"
                "（以空格开头）。",
                blockIndex=index,
            )
        edits.append(("\n".join(old), "\n".join(new)))
    if not edits:
        raise _apply_patch_error("apply_patch_empty", "补丁不包含任何 hunk。")
    return edits


def _looks_like_hunk_body(body: str) -> bool:
    lines = [line for line in body.split("\n") if line]
    if lines and lines[0].startswith(_UPDATE_FILE):
        lines = lines[1:]
    return bool(lines) and any(line[:1] in {"+", "-"} for line in lines) and all(
        _HUNK_LINE.match(line) or line == "*** End of File" for line in lines
    )


def parse_script_patch(patch: str, max_source_bytes: int) -> ScriptPatch:
    """edit_script 统一入口：SEARCH/REPLACE、Codex apply_patch 及二者混合信封。

    观测到弱模型常把 apply_patch hunk 写进 *** Begin Edit 信封（candidate-19/27/28 的
    no_valid_blocks 早停族）；这里按原生格式确定性转换，最终仍由同一唯一匹配、
    语法护栏与预检校验，不放宽任何提交约束。
    """

    if isinstance(patch, str) and len(patch.encode("utf-8")) <= 2 * max_source_bytes + 256:
        normalized = _normalize_patch(patch)
        if normalized.startswith("*** Begin Patch\n"):
            match = _APPLY_PATCH_ENVELOPE.fullmatch(normalized.rstrip() + "\n")
            if match is None:
                raise _apply_patch_error(
                    "apply_patch_envelope_invalid",
                    "apply_patch 补丁必须以 *** Begin Patch 开头、*** End Patch 结尾，"
                    "中间只含一个 *** Update File: <脚本路径> 及其 hunk。",
                )
            body = match["body"]
            if any(body.startswith(item) for item in _UNSUPPORTED_FILE_OPERATIONS):
                raise _apply_patch_error(
                    "apply_patch_operation_unsupported",
                    "edit_script 只支持对当前绑定脚本的单个 *** Update File。",
                )
            if not body.startswith(_UPDATE_FILE):
                raise _apply_patch_error(
                    "apply_patch_update_missing",
                    "apply_patch 补丁缺少 *** Update File: <脚本路径> 行。",
                )
            header, _, hunk_body = body.partition("\n")
            return ScriptPatch(
                edits=_parse_hunks(hunk_body),
                sha256=match["sha"],
                patch_format="apply_patch",
                path=header[len(_UPDATE_FILE):].strip(),
            )
        envelope = _EDIT_PATCH.fullmatch(normalized.rstrip() + "\n")
        if envelope is not None and "<<<<<<< SEARCH" not in envelope["body"]:
            body = envelope["body"]
            if _looks_like_hunk_body(body):
                path = None
                if body.startswith(_UPDATE_FILE):
                    header, _, body = body.partition("\n")
                    path = header[len(_UPDATE_FILE):].strip()
                return ScriptPatch(
                    edits=_parse_hunks(body),
                    sha256=envelope["sha"],
                    patch_format="edit_envelope_hunks",
                    path=path,
                )
    edits, sha256 = parse_edit_patch(patch, max_source_bytes)
    return ScriptPatch(edits=edits, sha256=sha256, patch_format="search_replace")


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


def _is_identifier_char(character: str) -> bool:
    # 只看 ASCII：脚本标识符几乎都是 ASCII，中文多出现在字符串字面量里，
    # 允许对其中的词做子串替换。
    return character == "_" or (character.isascii() and character.isalnum())


def _cuts_identifier(source: str, start: int, end: int) -> bool:
    """匹配边界是否落在标识符中间，例如 SEARCH `x = 1` 命中 `max = 1` 的尾部。"""

    return (
        start > 0
        and _is_identifier_char(source[start - 1])
        and _is_identifier_char(source[start])
    ) or (
        end < len(source)
        and _is_identifier_char(source[end - 1])
        and _is_identifier_char(source[end])
    )


def _exact_candidates(source: str, old: str) -> tuple[list[int], int]:
    """返回不切断标识符的精确匹配起点（最多 2 个）与被排除的切断匹配数。

    行内子串替换（如 figsize 参数）仍然允许；只排除边界落在标识符内部的命中，
    否则 SEARCH 写错一行时会静默改写另一个变量，或把本可唯一定位的块误判为歧义。
    """

    starts: list[int] = []
    cut = 0
    position = source.find(old)
    while position >= 0 and len(starts) < 2:
        if _cuts_identifier(source, position, position + len(old)):
            cut += 1
        else:
            starts.append(position)
        position = source.find(old, position + 1)
    return starts, cut


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
        starts, cut_matches = _exact_candidates(source, old)
        if starts:
            start = starts[0]
            mode, hint = "", ""
            candidates = [(start, start + len(old), new)]
            if len(starts) > 1:
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
            if cut_matches > 1:
                # 多处只能切断标识符命中（如 "aa" 之于 'aaa'）：无法判断意图，按歧义拒绝。
                raise _edit_error(
                    "ambiguous", "SEARCH 匹配多个位置，请增加上下文使其唯一。", index
                )
            mode, candidates, hint = _fuzzy_candidates(*split_lines(), old, new)
            if not candidates and cut_matches:
                hint = (
                    "SEARCH 只在标识符中间匹配到（例如 x = 1 命中 max = 1），已拒绝以免改错"
                    "变量；请从 read_script 原样复制完整的源码行。"
                )
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
