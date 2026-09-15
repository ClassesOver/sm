from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from agno.run import RunContext

from smart_reporting.reporting.code_agent.context import (
    ReportingCodingTaskBinding,
    ReportingCodingTaskContext,
)
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingWorkspaceRegistry,
)
from smart_reporting.reporting.knowledge import (
    KnowledgeDocument,
    KnowledgeSearchResult,
    ReportingKnowledgeIndex,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.runtime.code_generation import (
    ReportingCodeGenerationRunner,
)
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope
from smart_reporting.runtime.execution import (
    ExecutionContext,
    close_execution_resources,
    create_execution_context,
)
from smart_reporting.runtime.settings import AgentSettings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _binding(tmp_path: Path) -> ReportingCodingTaskBinding:
    scope = ReportingWorkflowScope(
        run_id="run-1",
        external_run_id="external-run-1",
        session_id="session-1",
        caller_thread_id="thread-1",
        user_id="user-1",
        database="database-1",
        company_id="company-1",
        thread_lease_key="lease-1",
        workspace_key="workspace-a",
    )
    identity = ReportingWorkspaceRegistry(tmp_path, secret="0" * 32).resolve(scope)
    workspace = HostReportingWorkspace(identity)
    return ReportingCodingTaskBinding(
        ReportingCodingTaskContext(
            task_id="task-1",
            task_kind="analysis",
            code_mode_session_id="code-task-1",
            workspace_key="workspace-a",
            workspace_root=workspace.identity.root,
            script_path="analysis/script.py",
            authorized_read_paths=(),
            authorized_write_paths=("analysis/script.py", "analysis/out.json"),
            declared_output_paths=("analysis/out.json",),
            max_source_bytes=128 * 1024,
        ),
        workspace,
    )


class _Knowledge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def search(
        self, query: str, *, workspace_key: str | None = None
    ) -> tuple[KnowledgeSearchResult, ...]:
        self.calls.append((query, workspace_key))
        return (
            KnowledgeSearchResult(
                identity="static:api",
                kind="static",
                snippet="API 契约",
                score=1.0,
                content_sha256="0" * 64,
                workspace_key=None,
                task_kind=None,
                error_code=None,
                source_sha256=None,
            ),
        )


class _Runtime:
    def __init__(self) -> None:
        self.shutdowns: list[str] = []

    async def shutdown(self, session_id: str) -> None:
        self.shutdowns.append(session_id)


@pytest.mark.anyio
async def test_knowledge_tool_is_opt_in_and_workspace_scoped(tmp_path: Path) -> None:
    binding = _binding(tmp_path)
    runtime = _Runtime()
    knowledge = _Knowledge()

    disabled = ReportingCodeModeToolkit(binding, runtime)
    enabled = ReportingCodeModeToolkit(binding, runtime, knowledge_index=knowledge)
    result = await enabled.search_knowledge("API")

    assert "search_knowledge" not in {function.name for function in disabled.tool_functions}
    assert "search_knowledge" in {function.name for function in enabled.tool_functions}
    assert knowledge.calls == [("API", "workspace-a")]
    assert result == {
        "ok": True,
        "results": [
            {
                "identity": "static:api",
                "kind": "static",
                "snippet": "API 契约",
                "score": 1.0,
                "contentSha256": "0" * 64,
            }
        ],
    }


@pytest.mark.anyio
async def test_runner_passes_knowledge_index_to_its_task_local_toolkit(tmp_path: Path) -> None:
    binding = _binding(tmp_path)
    runtime = _Runtime()
    knowledge = _Knowledge()

    class SearchOnlyAgent:
        def __init__(self, tools) -> None:
            self.tools = {tool.name: tool for tool in tools}

        async def arun(self, _prompt: str, **_kwargs: object) -> None:
            await self.tools["search_knowledge"].entrypoint(query="API")

    runner = ReportingCodeGenerationRunner(
        lambda tools: SearchOnlyAgent(tools), runtime, knowledge_index=knowledge
    )
    with pytest.raises(ReportingError, match="report_code_generation_no_submission"):
        await runner.run(
            binding.context,
            binding.workspace,
            {},
            run_context=RunContext(run_id="task-1", session_id="session-1"),
        )

    assert knowledge.calls == [("API", "workspace-a")]
    assert runtime.shutdowns == ["code-task-1"]


def test_execution_context_creates_shared_knowledge_index_under_host_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AgentSettings.from_environment(
        {
            "REPORTING_HOST_WORKSPACE_ROOT": str(tmp_path),
            "AGENT_WORKSPACE_HMAC_SECRET": "0" * 32,
        },
        load_env_file=False,
    )
    database = type("Database", (), {"async_db": object(), "sync_db": object()})()
    monkeypatch.setattr(
        "smart_reporting.runtime.execution.AsyncSandboxRegistry",
        lambda _database: object(),
    )
    monkeypatch.setattr(
        "smart_reporting.runtime.execution.create_sandbox_provider",
        lambda *_args, **_kwargs: object(),
    )

    context = create_execution_context(
        settings,
        database_factory=lambda _url: database,
        tracing_configurer=lambda *_args, **_kwargs: None,
        workspace_factory=lambda **_kwargs: object(),
    )

    assert isinstance(context.reporting_knowledge_index, ReportingKnowledgeIndex)
    assert context.reporting_knowledge_index.database_path == tmp_path / "knowledge" / "index.sqlite3"


@pytest.mark.anyio
async def test_execution_resource_close_closes_shared_knowledge_index() -> None:
    class ClosableKnowledge:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    knowledge = ClosableKnowledge()
    context = ExecutionContext(
        settings=object(),  # type: ignore[arg-type]
        database=object(),
        workspace_service=object(),  # type: ignore[arg-type]
        reporting_knowledge_index=knowledge,  # type: ignore[arg-type]
    )

    await close_execution_resources(context, tracing_flusher=lambda: True)

    assert knowledge.closed is True


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
