"""SQLite/FTS5 驱动的 Reporting Coding Agent 最小知识索引。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loguru import logger

_DYNAMIC_KIND = "repair"
_STATIC_KIND = "static"
_MAX_RESULTS = 5
_MAX_SNIPPET_BYTES = 1200
_MAX_REPAIR_SUMMARY_BYTES = 4096


class KnowledgeIndexError(RuntimeError):
    """知识索引不可用时暴露给工具层的稳定错误。"""

    code = "report_knowledge_unavailable"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bounded_utf8(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", errors="ignore")


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} 不能为空")
    return normalized


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """一个可检索知识文档；identity 与 content hash 分别标识逻辑对象和版本。"""

    identity: str
    content: str
    kind: Literal["static", "repair"]
    workspace_key: str | None = None
    task_kind: str | None = None
    error_code: str | None = None
    source_sha256: str | None = None

    def __post_init__(self) -> None:
        _required(self.identity, "identity")
        _required(self.content, "content")
        if self.kind == _STATIC_KIND:
            if any(
                value is not None
                for value in (self.workspace_key, self.task_kind, self.error_code, self.source_sha256)
            ):
                raise ValueError("静态知识不得包含 workspace 或修复元数据")
            return
        if self.kind != _DYNAMIC_KIND:
            raise ValueError("未知知识类型")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.workspace_key, self.task_kind, self.error_code, self.source_sha256)
        ):
            raise ValueError("修复知识必须包含 workspace、任务、错误码和源码哈希")
        source_sha256 = self.source_sha256 or ""
        if len(source_sha256) != 64 or any(char not in "0123456789abcdef" for char in source_sha256):
            raise ValueError("source_sha256 必须是小写 SHA-256")

    @property
    def content_sha256(self) -> str:
        return _sha256(self.content)

    @classmethod
    def static(cls, source_id: str, content: str) -> KnowledgeDocument:
        return cls(
            identity=f"{_STATIC_KIND}:{_required(source_id, 'source_id')}",
            content=content,
            kind=_STATIC_KIND,
        )


@dataclass(frozen=True, slots=True)
class KnowledgeWriteReceipt:
    identity: str
    content_sha256: str
    changed: bool


@dataclass(frozen=True, slots=True)
class KnowledgeSearchResult:
    identity: str
    kind: Literal["static", "repair"]
    snippet: str
    score: float
    content_sha256: str
    workspace_key: str | None
    task_kind: str | None
    error_code: str | None
    source_sha256: str | None


class ReportingKnowledgeIndex:
    """在宿主 Workspace 根目录共享的、按 Workspace 过滤的 SQLite 知识库。"""

    def __init__(self, host_workspace_root: str | Path) -> None:
        self.database_path = Path(host_workspace_root).resolve() / "knowledge" / "index.sqlite3"
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        async with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    async def upsert_document(self, document: KnowledgeDocument) -> KnowledgeWriteReceipt:
        async with self._lock:
            connection = self._connection_or_raise()
            return self._upsert_document(connection, document)

    async def index_static_documents(self, documents_root: str | Path) -> tuple[KnowledgeWriteReceipt, ...]:
        root = Path(documents_root)
        documents = tuple(sorted(root.glob("*.md")))
        receipts: list[KnowledgeWriteReceipt] = []
        for path in documents:
            try:
                content = path.read_text(encoding="utf-8")
            except OSError as error:
                logger.warning("无法读取静态知识文档: {}", path.name)
                raise KnowledgeIndexError("无法读取静态知识文档") from error
            receipts.append(await self.upsert_document(KnowledgeDocument.static(path.name, content)))
        return tuple(receipts)

    async def record_successful_repair(
        self,
        *,
        workspace_key: str,
        task_kind: str,
        error_code: str,
        source_sha256: str,
        summary: str,
    ) -> KnowledgeWriteReceipt:
        workspace_key = _required(workspace_key, "workspace_key")
        task_kind = _required(task_kind, "task_kind")
        error_code = _required(error_code, "error_code")
        source_sha256 = _required(source_sha256, "source_sha256")
        summary = _bounded_utf8(_required(summary, "summary"), _MAX_REPAIR_SUMMARY_BYTES)
        identity_payload = json.dumps(
            {
                "workspaceKey": workspace_key,
                "taskKind": task_kind,
                "errorCode": error_code,
                "sourceSha256": source_sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        document = KnowledgeDocument(
            identity=f"repair:{_sha256(identity_payload)}",
            content=summary,
            kind=_DYNAMIC_KIND,
            workspace_key=workspace_key,
            task_kind=task_kind,
            error_code=error_code,
            source_sha256=source_sha256,
        )
        return await self.upsert_document(document)

    async def search(
        self, query: str, *, workspace_key: str | None = None
    ) -> tuple[KnowledgeSearchResult, ...]:
        query = query.strip()
        if not query:
            return ()
        async with self._lock:
            connection = self._connection_or_raise()
            try:
                if len(query) >= 3:
                    rows = self._search_fts(connection, query, workspace_key)
                else:
                    rows = self._search_like(connection, query, workspace_key)
            except sqlite3.Error as error:
                logger.warning("知识检索失败: {}", type(error).__name__)
                raise KnowledgeIndexError("知识索引检索失败") from error
        return tuple(self._search_result(row, uses_fts=len(query) >= 3) for row in rows)

    def _connection_or_raise(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        connection: sqlite3.Connection | None = None
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            connection = sqlite3.connect(self.database_path, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    identity TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN ('static', 'repair')),
                    workspace_key TEXT,
                    task_kind TEXT,
                    error_code TEXT,
                    source_sha256 TEXT,
                    content TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_knowledge_documents_visibility
                    ON knowledge_documents(kind, workspace_key);
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    identity UNINDEXED,
                    content,
                    tokenize='trigram'
                );
                """
            )
        except (OSError, sqlite3.Error) as error:
            if connection is not None:
                connection.close()
            logger.warning("知识索引初始化失败: {}", type(error).__name__)
            raise KnowledgeIndexError("知识索引不可用") from error
        self._connection = connection
        return connection

    @staticmethod
    def _upsert_document(
        connection: sqlite3.Connection, document: KnowledgeDocument
    ) -> KnowledgeWriteReceipt:
        content_sha256 = document.content_sha256
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT content_sha256 FROM knowledge_documents WHERE identity = ?", (document.identity,)
            ).fetchone()
            changed = existing is None or existing["content_sha256"] != content_sha256
            if changed:
                connection.execute(
                    """
                    INSERT INTO knowledge_documents (
                        identity, kind, workspace_key, task_kind, error_code, source_sha256,
                        content, content_sha256, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, unixepoch(), unixepoch())
                    ON CONFLICT(identity) DO UPDATE SET
                        kind = excluded.kind,
                        workspace_key = excluded.workspace_key,
                        task_kind = excluded.task_kind,
                        error_code = excluded.error_code,
                        source_sha256 = excluded.source_sha256,
                        content = excluded.content,
                        content_sha256 = excluded.content_sha256,
                        updated_at = unixepoch()
                    """,
                    (
                        document.identity,
                        document.kind,
                        document.workspace_key,
                        document.task_kind,
                        document.error_code,
                        document.source_sha256,
                        document.content,
                        content_sha256,
                    ),
                )
                connection.execute("DELETE FROM knowledge_fts WHERE identity = ?", (document.identity,))
                connection.execute(
                    "INSERT INTO knowledge_fts(identity, content) VALUES (?, ?)",
                    (document.identity, document.content),
                )
            connection.execute("COMMIT")
        except sqlite3.Error as error:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            logger.warning("知识写入失败: {}", type(error).__name__)
            raise KnowledgeIndexError("知识索引写入失败") from error
        logger.debug("知识文档已写入: identity={}, changed={}", document.identity, changed)
        return KnowledgeWriteReceipt(document.identity, content_sha256, changed)

    @staticmethod
    def _visibility_clause(workspace_key: str | None) -> tuple[str, tuple[str, ...]]:
        if workspace_key:
            return "(d.kind = 'static' OR (d.kind = 'repair' AND d.workspace_key = ?))", (workspace_key,)
        return "d.kind = 'static'", ()

    def _search_fts(
        self, connection: sqlite3.Connection, query: str, workspace_key: str | None
    ) -> list[sqlite3.Row]:
        visibility, parameters = self._visibility_clause(workspace_key)
        phrase = f'"{query.replace(chr(34), chr(34) * 2)}"'
        return connection.execute(
            f"""
            SELECT d.identity, d.kind, d.workspace_key, d.task_kind, d.error_code,
                   d.source_sha256, d.content_sha256,
                   snippet(knowledge_fts, 1, '', '', '…', 64) AS snippet,
                   bm25(knowledge_fts) AS rank
            FROM knowledge_fts
            JOIN knowledge_documents AS d ON d.identity = knowledge_fts.identity
            WHERE knowledge_fts MATCH ? AND {visibility}
            ORDER BY rank ASC, d.identity ASC
            LIMIT {_MAX_RESULTS}
            """,
            (phrase, *parameters),
        ).fetchall()

    def _search_like(
        self, connection: sqlite3.Connection, query: str, workspace_key: str | None
    ) -> list[sqlite3.Row]:
        visibility, parameters = self._visibility_clause(workspace_key)
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return connection.execute(
            f"""
            SELECT d.identity, d.kind, d.workspace_key, d.task_kind, d.error_code,
                   d.source_sha256, d.content_sha256, d.content AS snippet, 0.0 AS rank
            FROM knowledge_documents AS d
            WHERE d.content LIKE ? ESCAPE '\\' AND {visibility}
            ORDER BY d.updated_at DESC, d.identity ASC
            LIMIT {_MAX_RESULTS}
            """,
            (f"%{escaped}%", *parameters),
        ).fetchall()

    @staticmethod
    def _search_result(row: sqlite3.Row, *, uses_fts: bool) -> KnowledgeSearchResult:
        rank = float(row["rank"])
        relevance = max(0.0, -rank)
        score = relevance / (1.0 + relevance) if uses_fts else 1.0
        return KnowledgeSearchResult(
            identity=row["identity"],
            kind=row["kind"],
            snippet=_bounded_utf8(row["snippet"], _MAX_SNIPPET_BYTES),
            score=score,
            content_sha256=row["content_sha256"],
            workspace_key=row["workspace_key"],
            task_kind=row["task_kind"],
            error_code=row["error_code"],
            source_sha256=row["source_sha256"],
        )


__all__ = [
    "KnowledgeDocument",
    "KnowledgeIndexError",
    "KnowledgeSearchResult",
    "KnowledgeWriteReceipt",
    "ReportingKnowledgeIndex",
]
