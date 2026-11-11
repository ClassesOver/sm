"""Word 审阅阅读证据：评论仅全文授权，修订仅完整授权块。"""
from __future__ import annotations

import json
import math
from copy import deepcopy


class NativeWordReviewReader:
    def __init__(self, model: dict, *, selection: bool, selected_cells: dict,
                 authorized_blocks: set[str], events: list[dict]):
        self.events = events
        self.limitations = []
        self._items = {'comments': [], 'revisions': []}
        self._blocks = authorized_blocks
        if selection:
            self.limitations.append('当前引擎未提供可核验的批注正文锚点；选区阅读不返回批注或线程。')
        else:
            # 线程投影包含原始评论身份及回复关系；只从实际引擎字段建立快照。
            threads = model.get('commentThreads', {})
            comments = model.get('comments', {})
            targets = threads.get('targets') or comments.get('commentTargets', [])
            for target in targets:
                if (not all(isinstance(target.get(key), str) and target[key]
                            for key in ('sourceId', 'targetId')) or
                        not isinstance(target.get('text'), str)):
                    continue
                identity = f"comment:{target['sourceId']}:{target['targetId']}"
                self._items['comments'].append({'reviewId': identity, 'kind': 'comment',
                    **deepcopy({key: target.get(key) for key in (
                        'sourceId', 'targetId', 'originalCommentId', 'author', 'date',
                        'text', 'parentId', 'done')})})
            reason = threads.get('readOnlyReason') or comments.get('commentReadOnlyReason')
            if reason:
                self.limitations.append('批注投影存在引擎限制，不能宣称覆盖所有批注：' + str(reason))
        self._revision_labels = {}
        for block_number, block in enumerate(model['blocks'], 1):
            block_id = block['blockId']
            if block_id not in authorized_blocks:
                continue
            if selected_cells.get(block_id) is not None:
                self.limitations.append('单元格选区不扩张至整块修订，未读取其块级修订。')
                continue
            reason = block.get('revisionReadOnlyReason')
            if reason:
                self.limitations.append('仅支持引擎已解析的简单正文插入/删除修订；此块修订不可读：' + str(reason))
                continue
            for ordinal, target in enumerate(block.get('reviewTargets', []), 1):
                span = target.get('sourceRange', {})
                if (target.get('blockId') != block_id or
                        not isinstance(target.get('revisionId'), str) or
                        target.get('type') not in {'insertion', 'deletion'} or
                        not isinstance(span.get('text'), str)):
                    self.limitations.append('存在未提供可信身份或正文投影的修订，不能完整读取。')
                    continue
                identity = f"revision:{block_id}:{target['revisionId']}"
                kind_label = '插入' if target['type'] == 'insertion' else '删除'
                self._revision_labels[identity] = f'第{block_number}块：{kind_label}修订{ordinal}'
                self._items['revisions'].append({'reviewId': identity, 'kind': 'revision',
                    'blockId': block_id, 'revisionId': target['revisionId'],
                    'type': target['type'], 'author': target.get('author'),
                    'date': target.get('date'), 'text': span['text']})
        self._read_ids = set()
        self._spans = {}

    def _serialize(self, kind: str, block_ids: list[str] | None = None) -> str:
        return json.dumps([item for item in self._items[kind]
                           if block_ids is None or item.get('blockId') in block_ids], ensure_ascii=False)

    def read(self, kind: str, offset: int, block_ids: list[str] | None = None) -> dict:
        if (block_ids is not None and (not isinstance(block_ids, list) or not block_ids or
                any(not isinstance(item, str) or item not in self._blocks for item in block_ids) or
                len(set(block_ids)) != len(block_ids))):
            raise ValueError('native_word_ai_review_selection_mismatch')
        content = self._serialize(kind, block_ids)
        if type(offset) is not int or not 0 <= offset < len(content):
            raise ValueError('native_word_ai_review_offset_invalid')
        end = min(offset + 24000, len(content))
        key = (kind, tuple(sorted(block_ids)) if block_ids is not None else None)
        spans = self._spans.setdefault(key, [])
        spans.append((offset, end))
        covered = 0
        for start, stop in sorted(spans):
            if start > covered:
                break
            covered = max(covered, stop)
        if covered == len(content):
            self._read_ids.update(item['reviewId'] for item in json.loads(content))
        tool = 'read_comments' if kind == 'comments' else 'read_revisions'
        self.events.append({'tool': tool, 'offset': offset, 'endOffset': end,
                            **({'blockIds': list(block_ids)} if block_ids is not None else {})})
        return {'content': content[offset:end], 'offset': offset,
                'nextOffset': end if end < len(content) else None, 'totalCharacters': len(content),
                'limitations': list(self.limitations), 'reviewCoverage': self.coverage()}

    def coverage(self) -> dict:
        return {kind: {'totalItems': len(items),
                'fullyReadIds': [item['reviewId'] for item in items if item['reviewId'] in self._read_ids],
                'readComplete': all(item['reviewId'] in self._read_ids for item in items)}
                for kind, items in self._items.items()}

    def tool_call_budget(self) -> int:
        return sum(math.ceil(len(self._serialize(kind)) / 24000) for kind in self._items)

    def has_read_evidence(self) -> bool:
        return bool(self._read_ids)

    def citations(self, identities: list[str]) -> tuple[list[dict], list[dict]]:
        known = {item['reviewId']: item for items in self._items.values() for item in items}
        verified, issues = [], []
        for identity in dict.fromkeys(identities):
            if identity not in self._read_ids:
                issues.append({'code': 'native_word_ai_unread_review_citation',
                               'message': '已丢弃未完整读取或未授权的Word审阅引用。'})
                continue
            item = known[identity]
            label = ('批注 ' + item['originalCommentId'] if item['kind'] == 'comment' and
                     isinstance(item.get('originalCommentId'), str) else
                     self._revision_labels.get(identity, '批注'))
            verified.append({'kind': item['kind'], 'id': identity, 'label': label,
                             **({'blockId': item['blockId']} if 'blockId' in item else {})})
        return verified, issues
