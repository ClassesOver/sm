"""Word 注释工具只使用明确授权的注释或插入锚点，身份由来源模型恢复。"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from ..reporting.models import ReportingError

NOTE_OPERATION_FIELDS = {
    'insertNote': ('noteKind', 'blockId', 'expectedObjectSha256', 'offset', 'text'),
    'updateNote': ('noteKind', 'noteId', 'expectedNoteSha256', 'text'),
    'deleteNote': ('noteKind', 'noteId', 'expectedNoteSha256', 'expectedReferences'),
}
NOTE_SELECTION_KINDS = {'note', 'noteAnchor'}


def invalid(message: str, code: str = 'native_ai_selection_mismatch'):
    return ReportingError(code, message)


def notes_selection(selection: list[dict]) -> bool:
    return any(isinstance(item, dict) and (item.get('selectionKind') in NOTE_SELECTION_KINDS
               or 'noteKind' in item or 'noteId' in item) for item in selection)


def notes_mode(selected: list[dict]) -> bool:
    return any(item.get('selectionKind') in NOTE_SELECTION_KINDS for item in selected)


def checked_note_text(value: Any) -> str:
    if (not isinstance(value, str) or any(ord(char) < 32 and char not in '\t\n'
            or 0xd800 <= ord(char) <= 0xdfff or ord(char) in (0xfffe, 0xffff) for char in value)
            or len(value.encode('utf-16-le')) // 2 > 20000):
        raise invalid('注释文字须为有效文本，最多20000个UTF-16码元。', 'native_ai_schema_invalid')
    return value


def checked_note_operation(operation: dict) -> dict:
    kind = operation.get('kind')
    if (kind not in NOTE_OPERATION_FIELDS or set(operation) - {'kind', *NOTE_OPERATION_FIELDS[kind]}
            or operation.get('noteKind') not in {'footnote', 'endnote'}):
        raise invalid('注释操作字段或类型无效。', 'native_ai_schema_invalid')
    identity = 'blockId' if kind == 'insertNote' else 'noteId'
    if not isinstance(operation.get(identity), str) or not operation[identity]:
        raise invalid('注释来源身份无效。', 'native_ai_schema_invalid')
    if kind != 'deleteNote':
        checked_note_text(operation.get('text'))
    if kind == 'insertNote' and (type(operation.get('offset')) is not int or operation['offset'] < 0):
        raise invalid('注释插入位置须为非负UTF-16偏移。', 'native_ai_schema_invalid')
    return deepcopy(operation)


def selected_note_objects(model: dict, operations: list[dict], selection: list[dict]) -> list[dict]:
    notes = model.get('notes')
    if not isinstance(notes, dict):
        raise invalid('当前来源的脚注尾注结构暂不可编辑。', 'native_ai_selection_invalid')
    refs = {item['blockId']: item for item in notes.get('referenceBlocks', [])}
    known = {(kind, note['id']): note for kind in ('footnote', 'endnote')
             for note in notes.get(kind + 's', [])}
    selected, seen = [], set()
    for item in selection:
        if not isinstance(item, dict):
            raise invalid('注释授权身份无效。', 'native_ai_selection_invalid')
        if item.get('selectionKind') == 'noteAnchor' and set(item) == {'selectionKind', 'blockId'}:
            anchor = refs.get(item.get('blockId'))
            if anchor is None or anchor.get('editable') is not True or not isinstance(anchor.get('text'), str):
                raise invalid('该段落没有可靠的注释插入锚点。', 'native_ai_selection_invalid')
            if any(op.get('blockId') == anchor['blockId'] or op.get('kind') == 'deleteNote'
                   and any(ref.get('blockId') == anchor['blockId'] for ref in op.get('expectedReferences', []))
                   for op in operations):
                raise invalid('所选注释插入段已有正文或引用标记草稿修改，请先保存并重新选择。', 'native_ai_selection_invalid')
            snapshot = {**deepcopy(anchor), 'selectionKind': 'noteAnchor',
                        'noteTargetId': 'anchor:' + anchor['blockId'], 'allowedOperations': ['insertNote']}
        elif (item.get('selectionKind') == 'note' and set(item) == {'selectionKind', 'noteKind', 'noteId'}
              and item.get('noteKind') in {'footnote', 'endnote'}):
            key = (item['noteKind'], item.get('noteId'))
            note = known.get(key)
            if note is None:
                raise invalid('注释来源身份已失效。', 'native_ai_selection_invalid')
            touched = [op for op in operations if op.get('noteKind') == key[0] and op.get('noteId') == key[1]]
            if any(op.get('kind') != 'updateNote' for op in touched) or len(touched) > 1:
                raise invalid('所选注释已删除或存在冲突草稿，请先保存并重新选择。', 'native_ai_selection_invalid')
            allowed = ['updateNote'] if note.get('editable') is True else []
            references = note.get('references', [])
            if all(refs.get(ref['blockId'], {}).get('editable') is True and
                   not any(op.get('blockId') == ref['blockId'] for op in operations) for ref in references):
                allowed.append('deleteNote')
            snapshot = {**deepcopy(note), 'text': touched[-1]['text'] if touched else note['text'],
                        'selectionKind': 'note', 'noteKind': key[0], 'noteId': key[1],
                        'noteTargetId': f'note:{key[0]}:{key[1]}', 'allowedOperations': allowed}
        else:
            raise invalid('注释不能与正文或审阅混合授权。', 'native_ai_selection_invalid')
        if snapshot['noteTargetId'] in seen:
            raise invalid('注释授权目标重复。', 'native_ai_selection_invalid')
        seen.add(snapshot['noteTargetId'])
        selected.append(snapshot)
    return selected


def note_identity(operation: dict) -> str:
    return ('anchor:' + operation['blockId'] if operation['kind'] == 'insertNote' else
            f"note:{operation['noteKind']}:{operation['noteId']}")


def note_candidate(candidate: list[dict], selected: list[dict]) -> list[dict]:
    known = {item['noteTargetId']: item for item in selected}
    anchors = {item['blockId']: item['text'] for item in selected if item['selectionKind'] == 'noteAnchor'}
    result, seen, deleted_blocks = [], set(), set()
    for raw in candidate:
        if raw.get('kind') not in NOTE_OPERATION_FIELDS:
            raise invalid('注释选区不授权修改正文、批注或修订。')
        op = checked_note_operation(raw)
        identity = note_identity(op)
        target = known.get(identity)
        if target is None or op['kind'] not in target['allowedOperations']:
            raise invalid('注释候选超出明确授权身份或开放能力。')
        trusted = ({'expectedObjectSha256': target['expectedObjectSha256']} if op['kind'] == 'insertNote'
                   else {'expectedNoteSha256': target['expectedNoteSha256']})
        if op['kind'] == 'deleteNote':
            trusted['expectedReferences'] = deepcopy(target['references'])
            deleted_blocks.update(ref['blockId'] for ref in target['references'])
        if any(key in op and op[key] != value for key, value in trusted.items()):
            raise invalid('注释候选来源摘要或引用身份被改写。')
        if op['kind'] == 'insertNote':
            text = anchors[op['blockId']]
            offsets = {0: 0}
            size = 0
            for index, char in enumerate(text):
                size += len(char.encode('utf-16-le')) // 2
                offsets[size] = index + 1
            if op['offset'] not in offsets:
                raise invalid('注释位置越界或切断Unicode字符。')
            at = offsets[op['offset']]
            anchors[op['blockId']] = text[:at] + '\ufffc' + text[at:]
        elif identity in seen:
            raise invalid('同一注释在一次候选中只能更新或删除一次。')
        seen.add(identity)
        result.append({**op, **trusted})
    if deleted_blocks & {op['blockId'] for op in result if op['kind'] == 'insertNote'}:
        raise invalid('同一段的删除注释与插入注释请分别生成并采纳。')
    return result


class NativeWordNoteTools:
    def __init__(self, owner):
        self.owner = owner

    def read_notes(self, offset: int = 0) -> dict:
        """分页读取明确授权的脚注尾注和插入段落；nextOffset非空时须继续读取。"""
        selected = self.owner.selected
        if not notes_mode(selected):
            raise invalid('当前正文或审阅授权不包含脚注尾注。')
        data = json.dumps(selected, ensure_ascii=False)
        if type(offset) is not int or not 0 <= offset < len(data):
            raise ValueError('native_ai_read_offset_invalid')
        end = min(offset + 24000, len(data))
        spans = self.owner._read_spans.setdefault(('notes',), [])
        spans.append((offset, end))
        cursor = 0
        for start, stop in sorted(spans):
            if start > cursor:
                break
            cursor = max(cursor, stop)
        if cursor == len(data):
            self.owner.read_ids.update(item['noteTargetId'] for item in selected)
        return {'content': data[offset:end], 'offset': offset,
                'nextOffset': end if end < len(data) else None, 'totalCharacters': len(data)}

    def _insert(self, kind: str, block_id: str, text: str, after_text: str | None) -> dict:
        target = next((item for item in self.owner.selected
                       if item.get('noteTargetId') == 'anchor:' + block_id), None)
        if target is None:
            raise invalid('只能在明确授权段落插入脚注或尾注。')
        current = target['text']
        # 每次工具调用使用已有候选的引用标记投影，后续插入偏移保持顺序语义。
        for op in self.owner.operations:
            if op['kind'] == 'insertNote' and op['blockId'] == block_id:
                raw = current.encode('utf-16-le')
                current = (raw[:op['offset'] * 2] + '\ufffc'.encode('utf-16-le') + raw[op['offset'] * 2:]).decode('utf-16-le')
        if after_text is None:
            before = current
        elif not isinstance(after_text, str) or not after_text or current.count(after_text) != 1:
            raise invalid('after_text须在授权段落中精确且唯一匹配。')
        else:
            before = current[:current.index(after_text) + len(after_text)]
        op = {'kind': 'insertNote', 'noteKind': kind, 'blockId': block_id,
              'offset': len(before.encode('utf-16-le')) // 2, 'text': text}
        return self.owner.propose_operations('插入脚注' if kind == 'footnote' else '插入尾注', [op])

    def insert_footnote(self, block_id: str, text: str, after_text: str | None = None) -> dict:
        """在明确授权段落after_text之后插入脚注；省略after_text则位于段尾，等待预览及采纳。"""
        return self._insert('footnote', block_id, text, after_text)

    def insert_endnote(self, block_id: str, text: str, after_text: str | None = None) -> dict:
        """在明确授权段落after_text之后插入尾注；省略after_text则位于段尾，等待预览及采纳。"""
        return self._insert('endnote', block_id, text, after_text)

    def edit_note(self, id: str, find: str, replace: str, kind: str | None = None, match_case: bool = True) -> dict:
        """精确替换已授权注释中所有find；kind仅footnote/endnote，同id有歧义时必填。"""
        target = self._target(id, kind)
        if not isinstance(find, str) or not find or not isinstance(replace, str) or type(match_case) is not bool:
            raise invalid('注释查找替换参数无效。', 'native_ai_schema_invalid')
        text, count = re.subn(re.escape(find), lambda _match: replace, target['text'], flags=0 if match_case else re.IGNORECASE)
        if count == 0:
            raise invalid('授权注释没有匹配文字，原文未改变。')
        return self.owner.propose_operations('修改脚注或尾注', [{'kind': 'updateNote',
            'noteKind': target['noteKind'], 'noteId': target['noteId'], 'text': text}])

    def _target(self, id: str, kind: str | None) -> dict:
        if kind is not None and kind not in {'footnote', 'endnote'}:
            raise invalid('注释类型仅支持footnote或endnote。')
        targets = [item for item in self.owner.selected if item.get('selectionKind') == 'note'
                   and item['noteId'] == id and (kind is None or item['noteKind'] == kind)]
        if len(targets) != 1:
            raise invalid('注释身份未授权或脚注尾注同id有歧义；请明确kind。')
        return targets[0]

    def delete_note(self, kind: str, id: str) -> dict:
        """删除明确授权的脚注或尾注及全部引用标记；保留未授权注释，等待预览及采纳。"""
        target = self._target(id, kind)
        return self.owner.propose_operations('删除脚注或尾注', [{'kind': 'deleteNote',
            'noteKind': target['noteKind'], 'noteId': target['noteId']}])
