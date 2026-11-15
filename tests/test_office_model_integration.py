"""Opt-in acceptance of document reads and citations through a real model."""

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.office.knowledge import OfficeKnowledge
from smart_reporting.office.repository import Identity, OfficeRepository


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize('format', ['docx', 'xlsx', 'pptx', 'pdf'])
@pytest.mark.parametrize('attachment', [False, True], ids=['favorite', 'attachment'])
async def test_real_office_knowledge_reads_and_cites_generated_document(format, attachment):
    endpoint = os.environ.get("REPORTING_OFFICE_MODEL_TEST_BASE_URL")
    key = os.environ.get("REPORTING_OFFICE_MODEL_TEST_API_KEY")
    model_id = os.environ.get("REPORTING_OFFICE_MODEL_TEST_ID")
    if not all((endpoint, key, model_id)):
        pytest.skip("requires an explicitly configured Office model acceptance endpoint, key and model ID")

    from agno.models.openai import OpenAIChat

    marker = f"GENOFFICE-{uuid4().hex.upper()}"
    from test_office_knowledge_parsing import make_knowledge_sample

    content = make_knowledge_sample(format, f"Acceptance code: {marker}")
    name = f"验收编号.{format}"

    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        actor = Identity("acceptance", "1", "1")
        await office.bootstrap(actor, "Test user")
        space = (await office.spaces(actor))[0]["id"]
        entry = await office.register_file(
            actor, space, None, name, format, "doc", 1,
            {"database": actor.database, "companyId": actor.company},
        )
        if not attachment:
            await office.favorite(actor, entry["id"], True)

        class Documents:
            async def contents(self, identity, file):
                return await office.file(identity, file), content

        knowledge = OfficeKnowledge(
            office, Documents(), model=OpenAIChat(id=model_id, api_key=key, base_url=endpoint),
        )
        source = "本次附件" if attachment else "收藏文档"
        answer = await knowledge.ask(
            actor, space, f"请读取{source}，原样返回本次验收编号，并引用该文件。",
            attachment_ids=[entry["id"]] if attachment else [],
        )
        assert (await office.library(actor, space))["files"][0]["starred"] is (not attachment)
        assert marker in answer["answer"]
        assert answer["citations"] == [{
            "fileId": entry["id"], "name": name, "revision": 1,
        }]
        assert (await office.knowledge_history(actor, space))[0]["id"] == answer["id"]
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_word_editor_assistant_reads_and_cites_body():
    endpoint = os.environ.get("REPORTING_OFFICE_MODEL_TEST_BASE_URL")
    key = os.environ.get("REPORTING_OFFICE_MODEL_TEST_API_KEY")
    model_id = os.environ.get("REPORTING_OFFICE_MODEL_TEST_ID")
    if not all((endpoint, key, model_id)):
        pytest.skip("requires an explicitly configured Office model acceptance endpoint, key and model ID")

    pytest.importorskip("fcntl")
    from agno.models.openai import OpenAIChat
    from smart_reporting.report_editor.native_word_read_ai import AgnoNativeWordReadPlanner, NativeWordReadTools
    from smart_reporting.reporting.delivery.docx_native import inspect_docx
    from test_office_knowledge_parsing import make_knowledge_sample

    marker = f"GENOFFICE-{uuid4().hex.upper()}"
    reader = NativeWordReadTools(inspect_docx(make_knowledge_sample("docx", f"Acceptance code: {marker}")))
    planner = AgnoNativeWordReadPlanner(OpenAIChat(id=model_id, api_key=key, base_url=endpoint))
    result = await planner(reader=reader, action="ask", instruction="读取正文，原样返回验收编号并引用对应内容块。",
                           session_id="office-word-acceptance", user_id="test")
    assert marker in result["answer"]
    assert [item["blockNumber"] for item in result["citations"]] == [1]
    assert result["coverage"]["scopeReadComplete"] is True


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("format", ["xlsx", "pptx", "pdf"])
async def test_real_native_editor_assistant_reads_and_cites(format):
    endpoint = os.environ.get("REPORTING_OFFICE_MODEL_TEST_BASE_URL")
    key = os.environ.get("REPORTING_OFFICE_MODEL_TEST_API_KEY")
    model_id = os.environ.get("REPORTING_OFFICE_MODEL_TEST_ID")
    if not all((endpoint, key, model_id)):
        pytest.skip("requires an explicitly configured Office model acceptance endpoint, key and model ID")

    pytest.importorskip("fcntl")
    from hashlib import sha256

    from agno.models.openai import OpenAIChat
    from smart_reporting.report_editor.native_models import NativeEditorContext
    from smart_reporting.report_editor.native_office import inspect_office
    from smart_reporting.report_editor.native_pdf_ai import create_native_pdf_read_planner
    from smart_reporting.report_editor.native_slides_read_ai import AgnoNativeSlidesReadPlanner, NativeSlidesReadTools
    from smart_reporting.report_editor.native_workbook_read_ai import AgnoNativeWorkbookReadPlanner, NativeWorkbookReadTools
    from test_office_knowledge_parsing import make_knowledge_sample

    marker = f"GENOFFICE-{uuid4().hex.upper()}"
    content = make_knowledge_sample(format, f"Acceptance code: {marker}")
    model = OpenAIChat(id=model_id, api_key=key, base_url=endpoint)
    options = dict(action="ask", instruction="实际读取验收编号所在位置，原样返回编号并引用来源。",
                   session_id=f"office-{format}-acceptance", user_id="test")
    if format == "pdf":
        context = NativeEditorContext.model_validate({
            "documentId": "acceptance", "revision": 1, "format": "pdf", "origin": "upload",
            "scope": {"database": "db", "companyId": "company", "userId": "test", "threadId": "test"},
            "sourceFile": {"path": "original.pdf", "size": len(content), "sha256": sha256(content).hexdigest(),
                           "mediaType": "application/pdf"},
        })
        result = await create_native_pdf_read_planner(model)(
            context=context, content=content, operations=[], selection=[], **options)
        assert [item["pageNumber"] for item in result["citations"]] == [1]
    elif format == "pptx":
        reader = NativeSlidesReadTools(inspect_office(format, content))
        result = await AgnoNativeSlidesReadPlanner(model)(reader=reader, **options)
        assert {item["slideNumber"] for item in result["citations"]} == {1}
    else:
        reader = NativeWorkbookReadTools(inspect_office(format, content))
        result = await AgnoNativeWorkbookReadPlanner(model)(reader=reader, **options)
        assert any("A2" in item["label"] for item in result["citations"])
    assert marker in result["answer"]
