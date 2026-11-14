"""系统配置与格式偏好共用的事务、CAS、不可变版本和审计。"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import insert, select, update

from .models import ManagementError
from .repository import audit_events, configuration_drafts, configuration_versions


def configuration_hash(document: dict) -> str:
    return hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def document_changes(before: dict, after: dict, prefix: str = "") -> list[dict]:
    result = []
    for key in sorted(before.keys() | after.keys()):
        path = f"{prefix}.{key}" if prefix else key
        old, new = before.get(key), after.get(key)
        if isinstance(old, dict) and isinstance(new, dict):
            result.extend(document_changes(old, new, path))
        elif old != new:
            result.append({"path": path, "before": old, "after": new})
    return result


class ConfigurationVersionService:
    def __init__(self, auth, initial, *, kind, validator, action_prefix, invalid_code):
        self.auth, self.repository = auth, auth.repository
        self.kind, self.validator = kind, validator
        self.action_prefix, self.invalid_code = action_prefix, invalid_code
        self.initial = self._document(initial)

    def _document(self, document):
        try:
            return self.validator(document)
        except (ValidationError, ValueError, TypeError) as error:
            raise ManagementError(self.invalid_code, "配置无效，请检查对应字段。", 422) from error

    def _verified(self, document, digest):
        try:
            valid = configuration_hash(document) == digest
            valid = valid and self._document(document) == document
        except (TypeError, ValueError, ManagementError):
            valid = False
        if not valid:
            raise ManagementError("management_configuration_corrupt", "配置版本校验失败，请检查存储或恢复有效版本。", 409)
        return document

    async def _audit(self, connection, action, **details):
        await connection.execute(insert(audit_events).values(id=str(uuid4()), occurred_at=self.auth.clock(),
            actor="admin", action=action, details=details))

    async def _draft(self, connection, *, verify=True):
        row = (await connection.execute(select(configuration_drafts).where(
            configuration_drafts.c.kind == self.kind))).mappings().one_or_none()
        if row is None:
            digest = configuration_hash(self.initial)
            row = {"kind": self.kind, "version": 1, "document": self.initial, "content_hash": digest,
                "initial_document": self.initial, "initial_hash": digest, "updated_at": self.auth.clock()}
            await connection.execute(insert(configuration_drafts).values(**row))
            await self._audit(connection, f"{self.action_prefix}_initialized", version=1, contentHash=digest)
        if verify:
            self._verified(row["document"], row["content_hash"])
            self._verified(row["initial_document"], row["initial_hash"])
        return row

    @staticmethod
    def _expected(row, expected_version):
        if type(expected_version) is not int or row["version"] != expected_version:
            raise ManagementError("management_version_conflict", "配置已被其他操作更新，请回读后比较。", 409)

    def _version_payload(self, row):
        self._verified(row["document"], row["content_hash"])
        payload = {"revision": row["revision"], "draftVersion": row["draft_version"],
            "document": row["document"], "contentHash": row["content_hash"], "publishedAt": row["published_at"]}
        if row.get('preference_approval_id'):
            payload['approvalId'] = row['preference_approval_id']
        return payload

    async def _latest(self, connection):
        return (await connection.execute(select(configuration_versions).where(
            configuration_versions.c.kind == self.kind).order_by(
                configuration_versions.c.revision.desc()).limit(1))).mappings().one_or_none()

    async def _version(self, connection, revision):
        row = (await connection.execute(select(configuration_versions).where(
            configuration_versions.c.kind == self.kind, configuration_versions.c.revision == revision,
        ))).mappings().one_or_none()
        if row is None:
            raise ManagementError("management_configuration_version_not_found", "配置历史版本不存在。", 404)
        self._verified(row["document"], row["content_hash"])
        return row

    async def detail(self, raw_session):
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            draft = await self._draft(connection)
            published = await self._latest(connection)
            effective = self._version_payload(published) if published else None
            return {"draft": {"version": draft["version"], "document": draft["document"],
                "contentHash": draft["content_hash"], "updatedAt": draft["updated_at"]},
                "initial": draft["initial_document"], "effective": effective,
                "changes": document_changes(effective["document"] if effective else draft["initial_document"],
                    draft["document"])}

    async def _save(self, connection, row, document, action, **details):
        digest, version = configuration_hash(document), row["version"] + 1
        await connection.execute(update(configuration_drafts).where(
            configuration_drafts.c.kind == self.kind, configuration_drafts.c.version == row["version"],
        ).values(version=version, document=document, content_hash=digest, updated_at=self.auth.clock()))
        await self._audit(connection, action, version=version, contentHash=digest, **details)
        return {"version": version, "contentHash": digest}

    async def save_draft(self, raw_session, document, expected_version):
        document = self._document(document)
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            row = await self._draft(connection)
            self._expected(row, expected_version)
            return await self._save(connection, row, document, f"{self.action_prefix}_saved")

    async def publish(self, raw_session, expected_version):
        """内部版本操作；对外开放前须由实际生成/预览能力完成应用前检查。"""
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            row = await self._draft(connection)
            self._expected(row, expected_version)
            latest = await self._latest(connection)
            if latest:
                self._verified(latest["document"], latest["content_hash"])
                if latest["draft_version"] == row["version"]:
                    return self._version_payload(latest)
            return await self._publish_in_transaction(connection, row, latest)

    async def _publish_in_transaction(self, connection, row, latest, *, approval_id=None):
        """复用调用方当前事务；权限、CAS及批准由入口在同连接完成。"""
        record = {"kind": self.kind, "revision": latest["revision"] + 1 if latest else 1,
            "draft_version": row["version"], "document": row["document"],
            "content_hash": row["content_hash"], "published_at": self.auth.clock()}
        if approval_id is not None:
            record['preference_approval_id'] = approval_id
        await connection.execute(insert(configuration_versions).values(**record))
        await self._audit(connection, f"{self.action_prefix}_published", revision=record["revision"],
            version=row["version"], contentHash=row["content_hash"],
            **({'approvalId': approval_id} if approval_id else {}))
        return self._version_payload(record)

    async def version(self, raw_session, revision):
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            return self._version_payload(await self._version(connection, revision))

    async def history(self, raw_session, *, before=None, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100 or (before is not None and (
            type(before) is not int or before < 1
        )):
            raise ManagementError("management_input_invalid", "历史分页参数无效。", 422)
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            query = select(configuration_versions).where(configuration_versions.c.kind == self.kind)
            if before is not None:
                query = query.where(configuration_versions.c.revision < before)
            rows = (await connection.execute(query.order_by(configuration_versions.c.revision.desc()).limit(limit + 1))).mappings().all()
            items = [{key: value for key, value in self._version_payload(row).items() if key != "document"}
                for row in rows[:limit]]
            return {"items": items, "nextCursor": items[-1]["revision"] if len(rows) > limit else None}

    async def restore_draft(self, raw_session, revision, expected_version):
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            row = await self._draft(connection, verify=False)
            self._expected(row, expected_version)
            historical = await self._version(connection, revision)
            return await self._save(connection, row, historical["document"], f"{self.action_prefix}_restored",
                restoredRevision=revision)

    async def reset_draft(self, raw_session, expected_version):
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            row = await self._draft(connection, verify=False)
            self._expected(row, expected_version)
            self._verified(row["initial_document"], row["initial_hash"])
            return await self._save(connection, row, row["initial_document"], f"{self.action_prefix}_reset")
