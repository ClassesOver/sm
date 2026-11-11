"""Agno PgVector适配：验证完整构建，故障不解释成无匹配。

索引是派生资源；回执须由管理服务绑定到已授权的不可变发布集合，
不能接受浏览器自行提交的回执作为授权。
"""

from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from hashlib import sha256
from math import isfinite
from typing import TYPE_CHECKING

from agno.filters import EQ, IN
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.document import Document
from agno.vectordb.search import SearchType
from pydantic import Field
from sqlalchemy import event, select, text

from ...async_utils import complete_cleanup
from ..contract import SHA256_PATTERN
from ..semantics.models import Identity, Revision, SemanticModel
from .models import DocumentLocator, ParsedDocument

if TYPE_CHECKING:
    from agno.vectordb.pgvector import PgVector


class EvidenceIndexUnavailable(RuntimeError):
    """索引、embedding或完整性校验不可用；消息不包含正文或连接信息。"""


class EvidenceIndexConflict(RuntimeError):
    """相同构建身份已经用于其他内容。"""


class IndexDocument(SemanticModel):
    document_id: Identity
    revision: Revision
    parsed: ParsedDocument


class IndexChunk(SemanticModel):
    key: str
    document_key: str
    metadata_hash: str = Field(pattern=SHA256_PATTERN)


class IndexBuildReceipt(SemanticModel):
    scope_id: Identity
    build_id: Identity
    embedding_identity: str = Field(min_length=1, max_length=256)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    chunks: tuple[IndexChunk, ...] = Field(min_length=1)

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


class IndexHit(SemanticModel):
    document_id: Identity
    revision: Revision
    source_hash: str = Field(pattern=SHA256_PATTERN)
    locator: DocumentLocator
    quote: str = Field(min_length=1, max_length=1200)


class LocatedChunking(FixedSizeChunking):
    """沿用Agno分块边界，保留可逐字核对的原文空白。"""

    def clean_text(self, value: str) -> str:
        return value


def _digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class AgnoEvidenceIndex:
    def __init__(self, store: PgVector, *, embedding_identity: str):
        if store.search_type != SearchType.vector or store.reranker is not None:
            raise ValueError("当前适配仅支持已验证的向量检索配置")
        self.store = store
        self.embedding_identity = embedding_identity
        self.chunker = LocatedChunking(chunk_size=1200, overlap=0)
        self._search_state: ContextVar[list[tuple[str, int]] | None] = ContextVar("evidence_search", default=None)
        event.listen(store.db_engine, "after_cursor_execute", self._searched)
        event.listen(store.db_engine, "handle_error", self._failed)

    def _searched(self, connection, cursor, statement, parameters, context, executemany):
        state = self._search_state.get()
        if state is not None and "ORDER BY" in statement and "embedding" in statement:
            state.append(("searched", cursor.rowcount))

    def _failed(self, context):
        state = self._search_state.get()
        if state is not None:
            state.append(("failed", -1))

    def close(self) -> None:
        for name, callback in (("after_cursor_execute", self._searched), ("handle_error", self._failed)):
            if event.contains(self.store.db_engine, name, callback):
                event.remove(self.store.db_engine, name, callback)

    def _prepare(self, scope_id, build_id, documents):
        ordered = sorted(documents, key=lambda item: (item.document_id, item.revision))
        if not ordered or len({(doc.document_id, doc.revision) for doc in ordered}) != len(ordered):
            raise ValueError("构建必须包含非重复的文档修订")
        manifest = _digest({
            "scope": scope_id, "build": build_id, "embedding": self.embedding_identity,
            "chunking": "agno-fixed-1200-overlap0-preserve-whitespace-v1",
            "documents": [doc.model_dump(mode="json") for doc in ordered],
        })
        records, chunks = [], []
        for doc in ordered:
            if doc.parsed.status != "parsed":
                raise ValueError("未完整解析文档不能建立可用索引")
            for number, fragment in enumerate(doc.parsed.fragments):
                fragment_key = f"{doc.document_id}:{doc.revision}:{number}"
                for chunk in self.chunker.chunk(Document(id=fragment_key, content=fragment.text, meta_data={})):
                    payload = {
                        "document_id": doc.document_id, "revision": doc.revision,
                        "source_hash": doc.parsed.original_hash,
                        "locator": fragment.locator.model_dump(mode="json"), "quote": chunk.content,
                    }
                    metadata = {
                        "scope_id": scope_id, "build_id": build_id, "manifest_hash": manifest,
                        "chunk_key": chunk.id, "document_key": f"{doc.document_id}:{doc.revision}",
                        "source": payload,
                    }
                    chunk.meta_data = metadata
                    records.append(chunk)
                    chunks.append(IndexChunk(key=chunk.id, document_key=metadata["document_key"], metadata_hash=_digest(metadata)))
        receipt = IndexBuildReceipt(scope_id=scope_id, build_id=build_id, embedding_identity=self.embedding_identity, manifest_hash=manifest, chunks=tuple(chunks))
        return receipt, records

    def _rows(self, scope_id, build_id, document_keys=None):
        table = self.store.table
        statement = select(table.c.meta_data, table.c.content, table.c.embedding).where(
            table.c.meta_data.contains({"scope_id": scope_id, "build_id": build_id}),
        )
        if document_keys is not None:
            statement = statement.where(table.c.meta_data["document_key"].astext.in_(sorted(document_keys)))
        with self.store.db_engine.connect() as connection:
            return connection.execute(statement).all()

    def _verify(self, receipt, document_keys=None):
        if receipt.embedding_identity != self.embedding_identity:
            raise EvidenceIndexUnavailable("index_embedding_identity_mismatch")
        rows = self._rows(receipt.scope_id, receipt.build_id, document_keys)
        expected = {chunk.key: chunk.metadata_hash for chunk in receipt.chunks
                    if document_keys is None or chunk.document_key in document_keys}
        actual = {}
        for row in rows:
            metadata = row.meta_data
            if row.embedding is None or len(row.embedding) != self.store.embedder.dimensions or not all(isfinite(value) for value in row.embedding) or not any(row.embedding):
                raise EvidenceIndexUnavailable("index_embedding_mismatch")
            if row.content != metadata.get("source", {}).get("quote"):
                raise EvidenceIndexUnavailable("index_content_mismatch")
            actual[metadata.get("chunk_key")] = _digest(metadata)
        if len(rows) != len(expected) or actual != expected:
            raise EvidenceIndexUnavailable("index_manifest_mismatch")

    async def build(self, scope_id: str, build_id: str, documents: tuple[IndexDocument, ...]) -> IndexBuildReceipt:
        receipt, records = self._prepare(scope_id, build_id, documents)
        # 会话级锁只串行同一构建，不占用管理事务等待embedding。
        key = int.from_bytes(sha256(f"{self.store.table.fullname}:{scope_id}:{build_id}".encode()).digest()[:8], signed=True)
        connection = None
        try:
            connection = self.store.db_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
            while True:
                attempt = asyncio.create_task(asyncio.to_thread(
                    connection.scalar, text("SELECT pg_try_advisory_lock(:key)"), {"key": key},
                ))
                try:
                    acquired = await asyncio.shield(attempt)
                except asyncio.CancelledError:
                    # 查询线程结束后才能使用同一连接释放锁。
                    await complete_cleanup(attempt)
                    raise
                if acquired:
                    break
                await asyncio.sleep(0.05)
            rows = await asyncio.to_thread(self._rows, scope_id, build_id)
            if any(row.meta_data.get("manifest_hash") != receipt.manifest_hash for row in rows):
                raise EvidenceIndexConflict("index_build_conflict")
            if len(rows) == receipt.chunk_count:
                await asyncio.to_thread(self._verify, receipt)
                return receipt
            await self.store.async_upsert(content_hash=receipt.manifest_hash, documents=records)
            await asyncio.to_thread(self._verify, receipt)
            return receipt
        except (EvidenceIndexConflict, EvidenceIndexUnavailable):
            raise
        except Exception:
            raise EvidenceIndexUnavailable("index_build_unavailable") from None
        finally:
            if connection is not None:
                def release():
                    try:
                        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    finally:
                        connection.close()
                await complete_cleanup(asyncio.to_thread(release))

    async def search(self, receipt: IndexBuildReceipt, query: str, *, document_keys: tuple[str, ...], limit: int = 5) -> tuple[IndexHit, ...]:
        if not 1 <= limit <= 5 or not query.strip():
            raise ValueError("检索需要非空问题，最多返回5条")
        allowed = set(document_keys) & {chunk.document_key for chunk in receipt.chunks}
        state: list[tuple[str, int]] = []
        token = self._search_state.set(state)
        try:
            if not allowed:
                return ()
            await asyncio.to_thread(self._verify, receipt, allowed)
            # Agno过滤DSL在同一SQL的排序/LIMIT之前限制组织、集合和文档。
            found = await self.store.async_search(query, limit=limit, filters=[
                EQ("scope_id", receipt.scope_id), EQ("build_id", receipt.build_id),
                EQ("manifest_hash", receipt.manifest_hash), IN("document_key", sorted(allowed)),
            ])
            searches = [count for status, count in state if status == "searched"]
            if any(status == "failed" for status, _ in state) or searches != [len(found)]:
                raise EvidenceIndexUnavailable("index_search_unavailable")
            await asyncio.to_thread(self._verify, receipt, allowed)
            expected = {chunk.key: chunk.metadata_hash for chunk in receipt.chunks}
            result = []
            for hit in sorted(found, key=lambda item: item.meta_data.get("similarity_score", 0), reverse=True)[:limit]:
                metadata = dict(hit.meta_data)
                metadata.pop("similarity_score", None)
                # Agno可能增加存储时间元数据；只核对我们登记的字段。
                metadata = {key: metadata[key] for key in ("scope_id", "build_id", "manifest_hash", "chunk_key", "document_key", "source")}
                if _digest(metadata) != expected.get(metadata["chunk_key"]) or metadata["document_key"] not in allowed:
                    raise EvidenceIndexUnavailable("index_hit_mismatch")
                result.append(IndexHit.model_validate(metadata["source"]))
            return tuple(result)
        except EvidenceIndexUnavailable:
            raise
        except Exception:
            raise EvidenceIndexUnavailable("index_search_unavailable") from None
        finally:
            self._search_state.reset(token)
