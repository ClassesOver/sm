"""真实PgVector配固定非语义向量，只验存储/隔离协议，不冒充中文召回。"""

import asyncio
import os
from uuid import uuid4

import pytest
from agno.exceptions import EmbeddingError
from agno.knowledge.embedder.base import Embedder
from sqlalchemy import create_engine, event, func, select, update

from smart_reporting.reporting.business_knowledge.ingestion import parse_document

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


class ProtocolEmbedder(Embedder):
    def __init__(self):
        super().__init__(dimensions=8)
        self.failure = None

    def get_embedding(self, text):
        if self.failure == "error":
            raise EmbeddingError("synthetic embedding fault", model_id="protocol-only")
        return [] if self.failure == "empty" else [1.0] + [0.0] * 7

    def get_embedding_and_usage(self, text):
        return self.get_embedding(text), None

    async def async_get_embedding(self, text):
        return self.get_embedding(text)

    async def async_get_embedding_and_usage(self, text):
        return self.get_embedding_and_usage(text)


@pytest.fixture
async def index_context():
    url = os.getenv("REPORTING_KNOWLEDGE_TEST_DB_URL")
    if not url:
        pytest.skip("需要独立 REPORTING_KNOWLEDGE_TEST_DB_URL")
    from agno.vectordb.pgvector import PgVector

    from smart_reporting.reporting.business_knowledge.index import AgnoEvidenceIndex

    engine = create_engine(url, hide_parameters=True)
    embedder = ProtocolEmbedder()
    store = PgVector(table_name=f"evidence_{uuid4().hex}", schema="semantic_probe", db_engine=engine, embedder=embedder)
    await store.async_create()
    index = AgnoEvidenceIndex(store, embedding_identity="synthetic-protocol-v1")
    try:
        yield index, store, embedder
    finally:
        await store.async_drop()
        index.close()
        engine.dispose()


def source_document(text="执行率采用执行额合计÷预算额合计。", document_id="rules"):
    from smart_reporting.reporting.business_knowledge.index import IndexDocument
    return IndexDocument(document_id=document_id, revision=1, parsed=parse_document(text.encode(), filename="rules.txt"))


async def test_build_preserves_quotes_and_filters_scope_build_before_limit(index_context):
    index, store, _ = index_context
    for number in range(6):
        await index.build("foreign", f"foreign-{number}", (source_document(),))
    text = "执行额  合计÷预算额合计，保留  两处空格。"
    receipt = await index.build("first", "build-a", (source_document(text),))
    await index.build("first", "build-b", (source_document("不能读取新版"),))
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "ORDER BY" in statement and "embedding" in statement:
            statements.append(statement)

    event.listen(store.db_engine, "before_cursor_execute", capture)
    try:
        hits = await index.search(receipt, "执行率", document_keys=("rules:1",), limit=1)
    finally:
        event.remove(store.db_engine, "before_cursor_execute", capture)
    assert len(hits) == 1
    assert hits[0].quote == text
    assert hits[0].document_id == "rules"
    assert hits[0].locator.line_start == 1
    assert statements and all(" IN (" in statement and statement.index("WHERE") < statement.index("ORDER BY") < statement.index("LIMIT") for statement in statements)
    assert receipt.chunk_count == 1


async def test_repeated_build_is_idempotent_and_changed_content_cannot_replace_it(index_context):
    from smart_reporting.reporting.business_knowledge.index import EvidenceIndexConflict
    index, store, _ = index_context
    first = await index.build("first", "build-a", (source_document(),))
    assert await index.build("first", "build-a", (source_document(),)) == first
    with pytest.raises(EvidenceIndexConflict):
        await index.build("first", "build-a", (source_document("different"),))
    with store.db_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(store.table)) == 1
    assert (await index.search(first, "执行率", document_keys=("rules:1",)))[0].quote == "执行率采用执行额合计÷预算额合计。"


@pytest.mark.parametrize("fault", ["error", "empty"])
async def test_failed_or_empty_embedding_never_returns_ready_receipt(index_context, fault):
    from smart_reporting.reporting.business_knowledge.index import EvidenceIndexUnavailable
    index, _, embedder = index_context
    embedder.failure = fault
    with pytest.raises(EvidenceIndexUnavailable):
        await index.build("first", "build-a", (source_document(),))
    embedder.failure = None
    receipt = await index.build("first", "build-a", (source_document(),))
    assert receipt.chunk_count == 1


async def test_query_embedding_and_missing_index_are_unavailable_not_no_match(index_context):
    from smart_reporting.reporting.business_knowledge.index import EvidenceIndexUnavailable
    index, store, embedder = index_context
    receipt = await index.build("first", "build-a", (source_document(),))
    assert await index.search(receipt, "执行率", document_keys=("unselected:1",)) == ()
    embedder.failure = "error"
    with pytest.raises(EvidenceIndexUnavailable):
        await index.search(receipt, "执行率", document_keys=("rules:1",))
    embedder.failure = None
    await store.async_drop()
    with pytest.raises(EvidenceIndexUnavailable):
        await index.search(receipt, "执行率", document_keys=("rules:1",))


async def test_missing_embedding_invalidates_ready_receipt(index_context):
    from smart_reporting.reporting.business_knowledge.index import EvidenceIndexUnavailable
    index, store, _ = index_context
    receipt = await index.build("first", "build-a", (source_document(),))
    with store.db_engine.begin() as connection:
        connection.execute(update(store.table).values(embedding=None))
    with pytest.raises(EvidenceIndexUnavailable):
        await index.search(receipt, "执行率", document_keys=("rules:1",))


async def test_receipt_survives_replacement_instance_and_long_quotes_are_exact(index_context):
    from smart_reporting.reporting.business_knowledge.index import (
        AgnoEvidenceIndex,
        IndexBuildReceipt,
    )
    index, store, _ = index_context
    original = "执行额  除以预算额；" * 200
    receipt = await index.build("first", "build-a", (source_document(original),))
    restored = IndexBuildReceipt.model_validate_json(receipt.model_dump_json())
    replacement = AgnoEvidenceIndex(store, embedding_identity="synthetic-protocol-v1")
    try:
        hits = await replacement.search(restored, "执行率", document_keys=("rules:1",))
        assert len(hits) == receipt.chunk_count > 1
        assert all(hit.quote in original and len(hit.quote) <= 1200 for hit in hits)
        assert sum(len(hit.quote) for hit in hits) == len(original)
    finally:
        replacement.close()


async def test_concurrent_different_build_inputs_cannot_both_commit(index_context):
    from smart_reporting.reporting.business_knowledge.index import EvidenceIndexConflict
    index, store, _ = index_context
    results = await asyncio.gather(
        index.build("first", "build-a", (source_document("first input"),)),
        index.build("first", "build-a", (source_document("second input"),)),
        return_exceptions=True,
    )
    assert sum(isinstance(result, EvidenceIndexConflict) for result in results) == 1
    with store.db_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(store.table)) == 1


async def test_selected_documents_are_searched_in_one_filtered_query(index_context):
    index, store, _ = index_context
    receipt = await index.build("first", "build-a", (
        source_document("第一份制度", "first-rules"),
        source_document("第二份制度", "second-rules"),
        source_document("未选中的制度", "hidden-rules"),
    ))
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "ORDER BY" in statement and "embedding" in statement:
            statements.append(statement)

    event.listen(store.db_engine, "before_cursor_execute", capture)
    try:
        hits = await index.search(receipt, "制度", document_keys=("first-rules:1", "second-rules:1"))
    finally:
        event.remove(store.db_engine, "before_cursor_execute", capture)
    assert {hit.document_id for hit in hits} == {"first-rules", "second-rules"}
    assert len(statements) == 1
    assert " IN (" in statements[0] and statements[0].index("WHERE") < statements[0].index("ORDER BY")


async def test_replacement_embedding_identity_cannot_use_old_build(index_context):
    from smart_reporting.reporting.business_knowledge.index import (
        AgnoEvidenceIndex,
        EvidenceIndexUnavailable,
    )
    index, store, _ = index_context
    receipt = await index.build("first", "build-a", (source_document(),))
    replacement = AgnoEvidenceIndex(store, embedding_identity="different-embedding-same-dimensions")
    try:
        with pytest.raises(EvidenceIndexUnavailable):
            await replacement.search(receipt, "执行率", document_keys=("rules:1",))
    finally:
        replacement.close()


async def test_cancelled_waiter_releases_connection_without_delaying_owner(index_context, monkeypatch):
    index, store, embedder = index_context
    started, release = asyncio.Event(), asyncio.Event()
    original_embedding = embedder.async_get_embedding_and_usage

    async def slow_embedding(value):
        started.set()
        await release.wait()
        return await original_embedding(value)

    monkeypatch.setattr(embedder, "async_get_embedding_and_usage", slow_embedding)
    owner = asyncio.create_task(index.build("first", "build-a", (source_document(),)))
    waiter = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        waiter = asyncio.create_task(index.build("first", "build-a", (source_document(),)))
        await asyncio.sleep(0.1)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(waiter, 1)
        release.set()
        receipt = await asyncio.wait_for(owner, 3)
        assert await asyncio.wait_for(index.build("first", "build-a", (source_document(),)), 2) == receipt
    finally:
        release.set()
        await asyncio.gather(owner, *([waiter] if waiter else []), return_exceptions=True)


async def test_result_conversion_failure_cannot_be_reported_as_no_match(index_context, monkeypatch):
    import agno.vectordb.pgvector.pgvector as module

    from smart_reporting.reporting.business_knowledge.index import EvidenceIndexUnavailable
    index, _, _ = index_context
    receipt = await index.build("first", "build-a", (source_document(),))

    def fail_conversion(*args, **kwargs):
        raise RuntimeError("synthetic conversion fault")

    monkeypatch.setattr(module, "normalize_score", fail_conversion)
    with pytest.raises(EvidenceIndexUnavailable):
        await index.search(receipt, "执行率", document_keys=("rules:1",))
