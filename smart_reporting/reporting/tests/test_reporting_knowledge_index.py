from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from smart_reporting.reporting.knowledge import KnowledgeDocument, ReportingKnowledgeIndex


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_upserted_document_has_stable_identity_and_content_hash(tmp_path: Path) -> None:
    index = ReportingKnowledgeIndex(tmp_path)
    document = KnowledgeDocument.static("api-contract", "报告 API 契约：字段 report_id。")

    first = await index.upsert_document(document)
    second = await index.upsert_document(document)

    assert first.identity == second.identity == "static:api-contract"
    assert first.content_sha256 == second.content_sha256 == hashlib.sha256(
        document.content.encode("utf-8")
    ).hexdigest()
    assert first.changed is True
    assert second.changed is False
    await index.aclose()


@pytest.mark.anyio
async def test_search_uses_fts_for_long_query_and_like_fallback_for_short_query(
    tmp_path: Path,
) -> None:
    index = ReportingKnowledgeIndex(tmp_path)
    await index.upsert_document(KnowledgeDocument.static("contract", "报告 API 契约与数据字典。"))

    long_results = await index.search("API")
    one_character_results = await index.search("报")
    short_results = await index.search("报告")

    assert [item.identity for item in long_results] == ["static:contract"]
    assert 0 < long_results[0].score <= 1
    assert [item.identity for item in one_character_results] == ["static:contract"]
    assert [item.identity for item in short_results] == ["static:contract"]
    assert short_results[0].score == 1
    await index.aclose()


@pytest.mark.anyio
async def test_repair_knowledge_is_not_visible_outside_its_workspace(tmp_path: Path) -> None:
    index = ReportingKnowledgeIndex(tmp_path)
    source_sha256 = hashlib.sha256(b"print('fixed')\n").hexdigest()
    repair = await index.record_successful_repair(
        workspace_key="workspace-a",
        task_kind="analysis",
        error_code="report_code_mode_execution_failed",
        source_sha256=source_sha256,
        summary="修复 API 字段为空导致的执行失败。",
    )

    visible = await index.search("API", workspace_key="workspace-a")
    hidden = await index.search("API", workspace_key="workspace-b")

    assert [item.identity for item in visible] == [repair.identity]
    assert hidden == ()
    assert visible[0].workspace_key == "workspace-a"
    assert visible[0].source_sha256 == source_sha256
    await index.aclose()


@pytest.mark.anyio
async def test_repair_identity_is_stable_when_its_bounded_summary_is_updated(tmp_path: Path) -> None:
    index = ReportingKnowledgeIndex(tmp_path)
    source_sha256 = hashlib.sha256(b"print('fixed')\n").hexdigest()
    first = await index.record_successful_repair(
        workspace_key="workspace-a",
        task_kind="analysis",
        error_code="report_code_mode_execution_failed",
        source_sha256=source_sha256,
        summary="第一次修复 API。",
    )
    second = await index.record_successful_repair(
        workspace_key="workspace-a",
        task_kind="analysis",
        error_code="report_code_mode_execution_failed",
        source_sha256=source_sha256,
        summary="第二次修复 API，补充了上下文。",
    )

    assert second.identity == first.identity
    assert second.content_sha256 != first.content_sha256
    assert second.changed is True
    await index.aclose()


@pytest.mark.anyio
async def test_fts_treats_special_characters_as_a_phrase(tmp_path: Path) -> None:
    index = ReportingKnowledgeIndex(tmp_path)
    await index.upsert_document(KnowledgeDocument.static("syntax", "使用 a+b 形式拼接。"))

    results = await index.search("a+b")

    assert [item.identity for item in results] == ["static:syntax"]
    await index.aclose()


@pytest.mark.anyio
async def test_static_markdown_documents_are_indexed_in_deterministic_path_order(tmp_path: Path) -> None:
    documents = tmp_path / "knowledge_docs"
    documents.mkdir()
    (documents / "z.md").write_text("最后一份 API 文档", encoding="utf-8")
    (documents / "a.md").write_text("第一份 API 文档", encoding="utf-8")
    index = ReportingKnowledgeIndex(tmp_path / "host")

    written = await index.index_static_documents(documents)
    results = await index.search("API")

    assert [item.identity for item in written] == ["static:a.md", "static:z.md"]
    assert {item.identity for item in results} == {"static:a.md", "static:z.md"}
    await index.aclose()
