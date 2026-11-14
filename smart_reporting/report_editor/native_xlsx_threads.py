"""线程批注的新作者只取已授权的服务端作用域；历史作者由引擎保真。"""
from __future__ import annotations

import json
from io import BytesIO
from uuid import NAMESPACE_URL, uuid5
from zipfile import ZipFile
from xml.etree import ElementTree

from .native_models import NativeScope


def xlsx_thread_actor(scope: NativeScope) -> dict[str, str]:
    identity = json.dumps([scope.database, scope.company_id, scope.user_id], ensure_ascii=False, separators=(',', ':'))
    return {'personId': '{' + str(uuid5(NAMESPACE_URL, 'smart-reporting:xlsx-person:' + identity)).upper() + '}', 'author': scope.user_id}


def validate_xlsx_thread_actors(content: bytes, operations: list[dict], actor: dict[str, str] | None) -> None:
    threaded = [op for op in operations if op.get('kind') == 'patchThreadedComments']
    if not threaded:
        return
    if not actor or set(actor) != {'personId', 'author'} or not all(isinstance(v, str) and v for v in actor.values()):
        raise ValueError('native_xlsx_thread_actor_required')
    historical: dict[str, tuple[str | None, str | None]] = {}
    with ZipFile(BytesIO(content)) as package:
        for name in package.namelist():
            if name.startswith('xl/threadedComments/') and name.endswith('.xml'):
                xml = package.read(name)
                if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
                    raise ValueError('native_xlsx_thread_source_invalid')
                for node in ElementTree.fromstring(xml).iter():
                    if node.tag.rsplit('}', 1)[-1] == 'threadedComment':
                        historical[node.get('id', '')] = (node.get('personId'), node.get('dT'))
    for op in threaded:
        changes = op.get('changes')
        if not isinstance(changes, list):
            raise ValueError('native_xlsx_thread_changes_invalid')
        for change in changes:
            root = change.get('thread') if isinstance(change, dict) else None
            if root is None:
                continue
            if not isinstance(root, dict) or not isinstance(root.get('replies'), list):
                raise ValueError('native_xlsx_thread_changes_invalid')
            for entry in [root, *root['replies']]:
                if not isinstance(entry, dict):
                    raise ValueError('native_xlsx_thread_changes_invalid')
                before = historical.get(entry.get('id'))
                if before is not None:
                    if (entry.get('personId'), entry.get('dT')) != before:
                        raise ValueError('native_xlsx_thread_historical_actor_changed')
                elif any(entry.get(key) != value for key, value in actor.items()):
                    raise ValueError('native_xlsx_thread_actor_mismatch')
