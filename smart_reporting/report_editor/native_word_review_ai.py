"""Word AI 审阅授权和候选身份；实际写入沿用原生引擎。"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from ..reporting.models import ReportingError

REVIEW_OPERATION_FIELDS = {
    'replyComment': ('sourceId', 'targetId', 'text', 'expectedCommentsSha256',
                     'expectedObjectSha256', 'author', 'date', 'clientId'),
    'resolveComment': ('sourceId', 'targetId', 'done', 'expectedCommentsSha256', 'expectedObjectSha256'),
    'resolveTextRevision': ('blockId', 'revisionId', 'action', 'expectedObjectSha256'),
}


def _invalid(message: str, code: str = 'native_ai_selection_mismatch'):
    return ReportingError(code, message)


def review_selection(selection: list[dict]) -> bool:
    return any(isinstance(item, dict) and bool(set(item) & {'sourceId', 'targetId', 'revisionId'})
               for item in selection)


def checked_review_operation(operation: dict) -> dict:
    kind = operation.get('kind')
    fields = REVIEW_OPERATION_FIELDS[kind]
    identity = ('blockId', 'revisionId') if kind == 'resolveTextRevision' else ('sourceId', 'targetId')
    if (set(operation) - {'kind', *fields} or
            any(not isinstance(operation.get(key), str) or not operation[key] for key in identity)):
        raise _invalid('审阅操作身份或字段无效。', 'native_ai_schema_invalid')
    if kind == 'replyComment' and (not isinstance(operation.get('text'), str) or
            not operation['text'].strip() or len(operation['text'].encode('utf-16-le')) // 2 > 65536):
        raise _invalid('批注回复必须包含有效文字。', 'native_ai_schema_invalid')
    if kind == 'resolveComment' and type(operation.get('done')) is not bool:
        raise _invalid('批注解决状态必须为布尔值。', 'native_ai_schema_invalid')
    if kind == 'resolveTextRevision' and operation.get('action') not in {'accept', 'reject'}:
        raise _invalid('修订仅支持接受或拒绝。', 'native_ai_schema_invalid')
    return deepcopy(operation)


def selected_review_objects(model: dict, operations: list[dict], selection: list[dict]) -> list[dict]:
    if operations:
        raise _invalid('审阅操作不能与已有草稿合批，请先保存并重新打开。', 'native_ai_selection_invalid')
    replies = {(t['sourceId'], t['targetId']): t for t in model.get('commentReplies', {}).get('targets', [])}
    threads = {(t['sourceId'], t['targetId']): t for t in model.get('commentThreads', {}).get('targets', [])}
    selected, seen = [], set()
    for item in selection:
        if not isinstance(item, dict):
            raise _invalid('审阅选区身份无效。', 'native_ai_selection_invalid')
        if set(item) == {'sourceId', 'targetId'}:
            if any(not isinstance(item[key], str) for key in item):
                raise _invalid('批注选区身份无效。', 'native_ai_selection_invalid')
            key = (item['sourceId'], item['targetId'])
            reply, thread = replies.get(key), threads.get(key)
            allowed = []
            if (reply and not model.get('commentReplies', {}).get('readOnlyReason') and
                    reply.get('canReply') is True and reply.get('parentId') is None):
                allowed.append('replyComment')
            if (thread and not model.get('commentThreads', {}).get('readOnlyReason') and
                    thread.get('canResolve') is True and thread.get('parentId') is None):
                allowed.append('resolveComment')
            target = reply if 'replyComment' in allowed else thread
            if not allowed or target is None:
                raise _invalid('仅能明确选择支持操作的根批注线程。', 'native_ai_selection_invalid')
            if (any(not isinstance(target.get(key), str) or not target[key]
                    for key in ('expectedCommentsSha256', 'expectedObjectSha256')) or
                    not isinstance(target.get('text'), str)):
                raise _invalid('批注来源身份或正文不可读取。', 'native_ai_selection_invalid')
            identity = f"comment:{item['sourceId']}:{item['targetId']}"
            snapshot = {'selectionKind': 'comment', 'reviewId': identity, 'allowedOperations': allowed,
                **{key: deepcopy(target.get(key)) for key in ('sourceId', 'targetId',
                    'expectedCommentsSha256', 'expectedObjectSha256', 'text', 'author', 'date')},
                'parentId': target.get('parentId'),
                'done': thread.get('done') if thread else None,
                'replyMetadata': {'author': 'AI Assistant',
                    'date': datetime.now(UTC).isoformat(timespec='seconds').replace('+00:00', 'Z'),
                    'clientId': uuid4().hex}}
        elif set(item) == {'blockId', 'revisionId'}:
            block = next((b for b in model['blocks'] if b['blockId'] == item['blockId']), None)
            target = next((t for t in (block or {}).get('reviewTargets', [])
                           if t.get('revisionId') == item['revisionId']), None)
            if (block is None or block.get('revisionReadOnlyReason') or target is None or
                    target.get('blockId') != block['blockId'] or
                    not isinstance(target.get('expectedObjectSha256'), str) or
                    not target['expectedObjectSha256'] or
                    target.get('type') not in {'insertion', 'deletion'} or
                    not isinstance(target.get('sourceRange', {}).get('text'), str)):
                raise _invalid('修订选区失效或不属于可操作的简单增删修订。', 'native_ai_selection_invalid')
            identity = f"revision:{item['blockId']}:{item['revisionId']}"
            snapshot = {'selectionKind': 'revision', 'reviewId': identity,
                'allowedOperations': ['resolveTextRevision'],
                **{key: deepcopy(target.get(key)) for key in (
                    'blockId', 'revisionId', 'expectedObjectSha256', 'author', 'date', 'type')},
                'text': target['sourceRange']['text']}
        else:
            raise _invalid('审阅选区不能与普通正文混合或携带额外字段。', 'native_ai_selection_invalid')
        if identity in seen:
            raise _invalid('审阅选区不能重复。', 'native_ai_selection_invalid')
        if selected and selected[0]['selectionKind'] != snapshot['selectionKind']:
            raise _invalid('批注与修订必须分批处理。', 'native_ai_selection_invalid')
        seen.add(identity)
        selected.append(snapshot)
    return selected


def review_candidate(candidate: list[dict], selected: list[dict]) -> list[dict]:
    if len({operation.get('kind') for operation in candidate}) != 1:
        raise _invalid('审阅操作必须按回复、解决状态或修订分别生成候选。')
    known = {item['reviewId']: item for item in selected}
    result, seen = [], set()
    for raw in candidate:
        if raw.get('kind') not in REVIEW_OPERATION_FIELDS:
            raise _invalid('审阅选区不授权普通正文修改。')
        operation = checked_review_operation(raw)
        kind = operation['kind']
        identity = (f"revision:{operation['blockId']}:{operation['revisionId']}" if kind == 'resolveTextRevision'
                    else f"comment:{operation['sourceId']}:{operation['targetId']}")
        target = known.get(identity)
        if target is None or kind not in target['allowedOperations'] or identity in seen:
            raise _invalid('审阅候选超出明确授权身份、能力或重复操作同一目标。')
        trusted = {key: target[key] for key in (
            ('blockId', 'revisionId', 'expectedObjectSha256') if kind == 'resolveTextRevision' else
            ('sourceId', 'targetId', 'expectedCommentsSha256', 'expectedObjectSha256'))}
        if kind == 'replyComment':
            trusted.update(target['replyMetadata'])
        for key, value in trusted.items():
            if key in operation and operation[key] != value:
                raise _invalid('审阅候选来源身份或服务端作者、日期、请求身份被改写。')
        seen.add(identity)
        result.append({**operation, **trusted})
    return result
