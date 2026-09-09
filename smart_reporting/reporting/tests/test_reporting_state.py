from __future__ import annotations

import asyncio
import os
from collections import deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, insert, text, update

from smart_reporting.reporting.workflow import repository as reporting_repository_module
from smart_reporting.reporting.workflow import state as reporting_state_module
from smart_reporting.reporting.workflow.checkpoint import (
    CheckpointError,
    ContextTrace,
    ReportingCheckpoint,
)
from smart_reporting.reporting.workflow.repository import ReportingStateRepository
from smart_reporting.reporting.workflow.state import (
    ReportingPhase,
    ReportingRunState,
    ReportingStateConflict,
    ReportingStateError,
    ReportingStateReducer,
    ReportingStateVersionUnsupported,
)
from smart_reporting.runtime.database import create_agent_database


def initial_state() -> ReportingRunState:
    return ReportingRunState.initial(
        report_run_id="workflow-run-1",
        external_run_id="external-run-1",
        thread_id="thread-1",
        owner_user_id="user-1",
        now=datetime(2026, 8, 13, tzinfo=UTC),
    )


def apply_phase(state: ReportingRunState, name: str) -> ReportingRunState:
    return ReportingStateReducer.apply(
        state,
        {"name": name, "commandId": f"{name}-{state.state_version}"},
        state.state_version,
    ).state


def make_visualization_state() -> ReportingRunState:
    return apply_phase(apply_phase(initial_state(), "start_analysis"), "start_visualization")


def make_chart_registration(chart_id: str, source_path: str | None = None) -> dict[str, object]:
    return {
        "chartId": chart_id,
        "sourcePath": source_path or f"analysis/charts/{chart_id}.png",
        "title": chart_id,
        "altText": f"{chart_id} chart",
        "citationIds": ["citation-1"],
        "metricCodes": ["metric-1"],
        "currentPeriod": "2026",
        "sourceDatasetId": "dataset-1",
        "aggregationGrain": "month",
    }


def make_file_identity(path: str) -> dict[str, object]:
    return {"path": path, "size": 1, "sha256": "a" * 64}


def submit_section(
    state: ReportingRunState,
    section_code: str,
    *,
    chart_id: str = "chart_a",
    source_path: str | None = None,
) -> ReportingRunState:
    return ReportingStateReducer.apply(
        state,
        {
            "name": "submit_visualization_charts",
            "commandId": f"submit-{section_code}",
            "payload": {
                "sectionCode": section_code,
                "charts": [make_chart_registration(chart_id, source_path)],
                "files": [],
            },
        },
        state.state_version,
    ).state


def state_with_chart(chart_id: str, section_code: str) -> ReportingRunState:
    return submit_section(make_visualization_state(), section_code, chart_id=chart_id)


def make_submit_command(section_code: str) -> dict[str, object]:
    return {
        "name": "submit_visualization_charts",
        "commandId": f"submit-{section_code}",
        "payload": {"sectionCode": section_code, "charts": [], "files": []},
    }


def test_repository_requires_postgresql() -> None:
    database = SimpleNamespace(db_engine=SimpleNamespace(dialect=SimpleNamespace(name="mysql")))

    with pytest.raises(ValueError, match="只支持 PostgreSQL"):
        ReportingStateRepository(database)  # type: ignore[arg-type]


def test_repository_models_run_identity_as_parent_aggregate() -> None:
    database = SimpleNamespace(db_engine=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))

    repository = ReportingStateRepository(database)  # type: ignore[arg-type]

    assert {
        "report_run_id",
        "external_run_id",
        "entrypoint",
        "workflow_id",
        "agno_session_id",
        "agno_run_id",
        "caller_session_id",
        "caller_run_id",
        "thread_id",
        "owner_user_id",
        "database",
        "company_id",
        "revision",
        "status",
        "finalization_pending",
    } <= set(repository.runs.c.keys())
    assert repository.states.c.report_run_id.foreign_keys
    assert repository.command_receipts.c.report_run_id.foreign_keys
    assert repository.workflow_thread_owners.c.report_run_id.foreign_keys
    assert repository.mcp_requests.c.report_run_id.nullable is True
    assert {index.name for index in repository.workflow_thread_owners.indexes} >= {
        "ix_reporting_workflow_thread_owners_report_run_id"
    }
    assert {index.name for index in repository.mcp_requests.indexes} >= {
        "ix_reporting_mcp_requests_report_run_id"
    }


class _FakeResult:
    def __init__(self, *, row: dict[str, Any] | None = None, rowcount: int = 1) -> None:
        self._row = SimpleNamespace(_mapping=row) if row is not None else None
        self.rowcount = rowcount

    def first(self):
        return self._row


class _RecordingConnection:
    def __init__(
        self,
        *,
        row: dict[str, Any] | None = None,
        upgraded_row: dict[str, Any] | None = None,
        update_rowcounts: tuple[int, ...] = (),
    ) -> None:
        self.statements: list[Any] = []
        self.row = row
        self.upgraded_row = upgraded_row
        self.update_rowcounts = deque(update_rowcounts)
        self.run_sync_calls = 0

    async def execute(self, statement: Any, _parameters: Any = None) -> _FakeResult:
        self.statements.append(statement)
        if getattr(statement, "is_update", False):
            rowcount = self.update_rowcounts.popleft() if self.update_rowcounts else 1
            if rowcount == 1 and self.upgraded_row is not None:
                self.row = self.upgraded_row
            return _FakeResult(rowcount=rowcount)
        if getattr(statement, "is_select", False):
            return _FakeResult(row=self.row)
        return _FakeResult()

    async def scalar(self, statement: Any) -> bool:
        self.statements.append(statement)
        return False

    async def run_sync(self, callback) -> None:
        self.run_sync_calls += 1


class _RecordingEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, connection: _RecordingConnection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def begin(self):
        yield self.connection

    @asynccontextmanager
    async def connect(self):
        yield self.connection


class _LifecycleLockConnection:
    def __init__(self, engine: _LifecycleLockEngine) -> None:
        self.engine = engine
        self.holds_lock = False

    async def execute(self, statement: Any, _parameters: Any = None) -> _FakeResult:
        sql = str(statement)
        if "pg_advisory_unlock" in sql:
            if self.holds_lock:
                self.holds_lock = False
                self.engine.advisory_lock.release()
            return _FakeResult()
        if "pg_advisory_lock" in sql:
            self.engine.record_lock_attempt()
            await self.engine.advisory_lock.acquire()
            self.holds_lock = True
        return _FakeResult()

    async def scalar(self, statement: Any, _parameters: Any = None) -> bool:
        assert "pg_try_advisory_lock" in str(statement)
        self.engine.record_lock_attempt()
        if self.engine.advisory_lock.locked():
            return False
        await self.engine.advisory_lock.acquire()
        self.holds_lock = True
        return True

    async def commit(self) -> None:
        if (
            self.engine.block_first_acquire_commit
            and self.holds_lock
            and not self.engine.acquire_commit_blocked
        ):
            self.engine.acquire_commit_blocked = True
            self.engine.acquire_commit_started.set()
            await asyncio.Future()


class _LifecycleLockEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, *, pool_size: int, block_first_acquire_commit: bool = False) -> None:
        self.pool = asyncio.Semaphore(pool_size)
        self.advisory_lock = asyncio.Lock()
        self.lock_attempts = 0
        self.second_lock_attempted = asyncio.Event()
        self.block_first_acquire_commit = block_first_acquire_commit
        self.acquire_commit_blocked = False
        self.acquire_commit_started = asyncio.Event()

    def record_lock_attempt(self) -> None:
        self.lock_attempts += 1
        if self.lock_attempts >= 2:
            self.second_lock_attempted.set()

    @asynccontextmanager
    async def connect(self):
        await self.pool.acquire()
        try:
            yield _LifecycleLockConnection(self)
        finally:
            self.pool.release()


def _fake_repository(connection: _RecordingConnection) -> ReportingStateRepository:
    return ReportingStateRepository(SimpleNamespace(db_engine=_RecordingEngine(connection)))  # type: ignore[arg-type]


def _lifecycle_lock_repository(engine: _LifecycleLockEngine) -> ReportingStateRepository:
    return ReportingStateRepository(SimpleNamespace(db_engine=engine))  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_lifecycle_lock_waiter_releases_pool_connection_between_attempts() -> None:
    engine = _LifecycleLockEngine(pool_size=2)
    repository = _lifecycle_lock_repository(engine)

    async def wait_for_lock() -> None:
        async with repository.workflow_thread_lifecycle_lock("thread"):
            pass

    async with repository.workflow_thread_lifecycle_lock("thread"):
        waiter = asyncio.create_task(wait_for_lock())
        await engine.second_lock_attempted.wait()
        try:
            async with asyncio.timeout(0.05):
                async with engine.connect():
                    pass
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.anyio
async def test_lifecycle_lock_cancellation_during_acquire_commit_releases_session_lock() -> None:
    engine = _LifecycleLockEngine(pool_size=1, block_first_acquire_commit=True)
    repository = _lifecycle_lock_repository(engine)

    async def hold_lock() -> None:
        async with repository.workflow_thread_lifecycle_lock("thread"):
            pass

    holder = asyncio.create_task(hold_lock())
    await engine.acquire_commit_started.wait()
    holder.cancel()
    await asyncio.gather(holder, return_exceptions=True)

    async with asyncio.timeout(0.05):
        async with repository.workflow_thread_lifecycle_lock("thread"):
            pass


@pytest.mark.anyio
async def test_lifecycle_lock_contention_times_out_and_returns_pool_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _LifecycleLockEngine(pool_size=1)
    repository = _lifecycle_lock_repository(engine)
    await engine.advisory_lock.acquire()
    monkeypatch.setattr(reporting_repository_module, "_WORKFLOW_THREAD_LOCK_WAIT_SECONDS", 0)

    try:
        with pytest.raises(ReportingStateError) as conflict:
            async with asyncio.timeout(0.05):
                async with repository.workflow_thread_lifecycle_lock("thread"):
                    pass
    finally:
        engine.advisory_lock.release()

    assert conflict.value.code == "report_workflow_thread_lifecycle_timeout"
    async with asyncio.timeout(0.05):
        async with engine.connect():
            pass


def _run_row(**overrides: Any) -> dict[str, Any]:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    return {
        "report_run_id": "report-run",
        "external_run_id": "external-run",
        "entrypoint": "agentos",
        "workflow_id": "enterprise-reporting-workflow-v1",
        "agno_session_id": "workflow-session",
        "agno_run_id": "report-run",
        "caller_session_id": "caller-session",
        "caller_run_id": "external-run",
        "thread_id": "thread",
        "owner_user_id": "user",
        "database": "odoo",
        "company_id": "11",
        "revision": 1,
        "status": "running",
        "finalization_pending": False,
        "created_at": now,
        "started_at": now,
        "finished_at": None,
        "updated_at": now,
        **overrides,
    }


@pytest.mark.anyio
async def test_repository_initialize_upgrades_legacy_schema_in_dependency_order() -> None:
    connection = _RecordingConnection()
    repository = _fake_repository(connection)

    await repository.initialize()

    sql = [str(statement) for statement in connection.statements]
    joined = "\n".join(sql)
    assert connection.run_sync_calls == 1
    assert "INSERT INTO agentos_reporting.reporting_runs" in joined
    assert "FROM agentos_reporting.reporting_run_states" in joined
    assert joined.index("INSERT INTO agentos_reporting.reporting_runs") < joined.index(
        "UPDATE agentos_reporting.reporting_workflow_thread_owners"
    )
    assert joined.index("UPDATE agentos_reporting.reporting_workflow_thread_owners") < joined.index(
        "VALIDATE CONSTRAINT fk_reporting_workflow_thread_owners_report_run_id"
    )
    assert "fk_reporting_run_states_report_run_id" in joined
    assert "fk_reporting_command_receipts_report_run_id" in joined
    assert "fk_reporting_mcp_requests_report_run_id" in joined
    assert "ON CONFLICT" in joined
    assert "DROP " not in joined.upper()


@pytest.mark.anyio
async def test_repository_initialize_legacy_upgrade_sql_is_repeatable() -> None:
    connection = _RecordingConnection()
    database = SimpleNamespace(db_engine=_RecordingEngine(connection))
    first_repository = ReportingStateRepository(database)  # type: ignore[arg-type]
    second_repository = ReportingStateRepository(database)  # type: ignore[arg-type]

    await first_repository.initialize()
    first_count = len(connection.statements)
    await second_repository.initialize()

    assert len(connection.statements) == first_count * 2
    assert [str(item) for item in connection.statements[:first_count]] == [
        str(item) for item in connection.statements[first_count:]
    ]
    assert all(
        "IF NOT EXISTS" in str(statement) or "ON CONFLICT" in str(statement)
        or "UPDATE agentos_reporting" in str(statement)
        or "VALIDATE CONSTRAINT" in str(statement)
        or "CREATE SCHEMA IF NOT EXISTS" in str(statement)
        or "pg_advisory_xact_lock" in str(statement)
        or "SELECT EXISTS" in str(statement)
        for statement in connection.statements
    )


@pytest.mark.anyio
async def test_repository_upgrades_unknown_placeholder_to_real_registration() -> None:
    placeholder = _run_row(
        entrypoint="unknown",
        agno_session_id="thread",
        caller_session_id=None,
        caller_run_id=None,
        database="default",
        company_id="default",
    )
    real = _run_row()
    connection = _RecordingConnection(row=placeholder, upgraded_row=real)
    repository = _fake_repository(connection)
    repository._initialized = True

    stored = await repository.register_run(**real)

    assert stored == real
    assert any(getattr(statement, "is_update", False) for statement in connection.statements)


@pytest.mark.anyio
async def test_repository_rejects_real_registration_with_changed_caller_identity() -> None:
    stored = _run_row()
    connection = _RecordingConnection(row=stored)
    repository = _fake_repository(connection)
    repository._initialized = True

    with pytest.raises(ReportingStateError) as conflict:
        await repository.register_run(
            **{**stored, "caller_session_id": "other-session", "caller_run_id": "other-run"}
        )

    assert conflict.value.code == "report_run_identity_conflict"


@pytest.mark.anyio
async def test_repository_unknown_upgrade_fails_closed_on_concurrent_conflict() -> None:
    placeholder = _run_row(
        entrypoint="unknown",
        agno_session_id="thread",
        caller_session_id=None,
        caller_run_id=None,
        database="default",
        company_id="default",
    )
    connection = _RecordingConnection(row=placeholder, update_rowcounts=(0,))
    repository = _fake_repository(connection)
    repository._initialized = True

    with pytest.raises(ReportingStateError) as conflict:
        await repository.register_run(**_run_row())

    assert conflict.value.code == "report_run_identity_conflict"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("operation", "expected_code"),
    [
        ("attach", "report_mcp_request_not_found"),
        ("status", "report_run_not_found"),
    ],
)
async def test_repository_write_to_missing_parent_link_fails_closed(
    operation: str, expected_code: str
) -> None:
    connection = _RecordingConnection(update_rowcounts=(0,))
    repository = _fake_repository(connection)
    repository._initialized = True

    with pytest.raises(ReportingStateError) as missing:
        if operation == "attach":
            await repository.attach_request_run("missing-external", "report-run")
        else:
            await repository.update_run_status("missing-report", status="failed")

    assert missing.value.code == expected_code


@pytest.mark.anyio
async def test_repository_status_update_none_preserves_finalization_pending() -> None:
    connection = _RecordingConnection(update_rowcounts=(1,))
    repository = _fake_repository(connection)
    repository._initialized = True

    await repository.update_run_status(
        "report-run", status="failed", finalization_pending=None
    )

    statement = next(item for item in connection.statements if getattr(item, "is_update", False))
    assert "finalization_pending" not in statement.compile().params


@pytest.mark.anyio
async def test_repository_nonterminal_status_clears_finished_at() -> None:
    connection = _RecordingConnection(update_rowcounts=(1,))
    repository = _fake_repository(connection)
    repository._initialized = True

    await repository.update_run_status("report-run", status="running")

    statement = next(item for item in connection.statements if getattr(item, "is_update", False))
    assert statement.compile().params["finished_at"] is None


@pytest.mark.anyio
async def test_durable_complete_keeps_parent_running_until_workflow_terminal_update() -> None:
    running = apply_phase(initial_state(), "start_analysis")
    finalized = ReportingStateReducer.apply(
        running,
        {
            "name": "set_workflow_checkpoint",
            "commandId": "workflow-checkpoint-v2:1:finalize",
            "payload": {"checkpoint": {"phase": "finalize", "revision": 1}},
        },
        running.state_version,
    ).state

    class ApplyConnection(_RecordingConnection):
        async def execute(self, statement: Any, _parameters: Any = None) -> _FakeResult:
            self.statements.append(statement)
            if getattr(statement, "is_select", False):
                if "reporting_run_states" in str(statement):
                    return _FakeResult(
                        row=ReportingStateRepository._row_values(finalized)
                    )
                return _FakeResult()
            return _FakeResult()

    connection = ApplyConnection()
    repository = _fake_repository(connection)
    repository._initialized = True

    result = await repository.apply(
        finalized.report_run_id,
        {"name": "complete", "commandId": "report-complete:1:manifest"},
        expected_version=finalized.state_version,
    )

    run_update = [
        statement
        for statement in connection.statements
        if getattr(statement, "is_update", False)
        and "reporting_runs" in str(statement)
    ][-1]
    assert result.state.phase is ReportingPhase.COMPLETED
    assert run_update.compile().params["status"] == "running"
    assert run_update.compile().params["finished_at"] is None

    await repository.update_run_status(finalized.report_run_id, status="completed")

    terminal_update = [
        statement
        for statement in connection.statements
        if getattr(statement, "is_update", False)
        and "reporting_runs" in str(statement)
    ][-1]
    assert terminal_update.compile().params["status"] == "completed"
    assert terminal_update.compile().params["finished_at"] is not None


@pytest.mark.anyio
async def test_repository_reads_parent_run_by_report_and_external_identity() -> None:
    stored = _run_row(finalization_pending=True, status="failed")
    connection = _RecordingConnection(row=stored)
    repository = _fake_repository(connection)
    repository._initialized = True

    assert await repository.get_run("report-run") == stored
    assert await repository.get_run_by_external("external-run") == stored

    selects = [item for item in connection.statements if getattr(item, "is_select", False)]
    assert len(selects) == 2


@pytest.mark.anyio
@pytest.mark.integration
async def test_repository_serializes_first_schema_initialization_across_engines() -> None:
    database_url = _integration_database_url()
    first_database = create_agent_database(database_url)
    second_database = create_agent_database(database_url)
    try:
        async with first_database.async_engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS agentos_reporting CASCADE"))
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": reporting_repository_module._REPORTING_SCHEMA_LOCK_KEY},
            )
            initializations = (
                asyncio.create_task(
                    ReportingStateRepository(first_database.async_db).initialize()
                ),
                asyncio.create_task(
                    ReportingStateRepository(second_database.async_db).initialize()
                ),
            )
            await asyncio.sleep(0.1)
            assert all(not initialization.done() for initialization in initializations)

        await asyncio.wait_for(asyncio.gather(*initializations), timeout=2)

        async with first_database.async_engine.connect() as connection:
            table_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'agentos_reporting'"
                )
            )
        assert table_count == 5
    finally:
        async with first_database.async_engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS agentos_reporting CASCADE"))
        await first_database.async_engine.dispose()
        first_database.sync_engine.dispose()
        await second_database.async_engine.dispose()
        second_database.sync_engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_repository_rejects_legacy_state_parent_identity_conflict() -> None:
    database = create_agent_database(_integration_database_url())
    repository = ReportingStateRepository(database.async_db)
    now = datetime(2026, 9, 9, tzinfo=UTC)
    try:
        async with database.async_engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS agentos_reporting CASCADE"))
            await connection.execute(text("CREATE SCHEMA agentos_reporting"))
            await connection.run_sync(repository.runs.create)
            await connection.execute(
                text(
                    """
                    CREATE TABLE agentos_reporting.reporting_run_states (
                        report_run_id VARCHAR(256) PRIMARY KEY,
                        external_run_id VARCHAR(256) NOT NULL UNIQUE,
                        thread_id VARCHAR(256) NOT NULL,
                        owner_user_id VARCHAR(256) NOT NULL,
                        revision BIGINT NOT NULL,
                        schema_version BIGINT NOT NULL,
                        state_version BIGINT NOT NULL,
                        phase VARCHAR(64) NOT NULL,
                        payload JSON NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            await connection.execute(
                insert(repository.runs).values(
                    **_run_row(
                        external_run_id="external-run",
                        owner_user_id="wrong-owner",
                    )
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO agentos_reporting.reporting_run_states (
                        report_run_id, external_run_id, thread_id, owner_user_id,
                        revision, schema_version, state_version, phase, payload,
                        created_at, updated_at
                    ) VALUES (
                        'report-run', 'external-run', 'thread', 'user',
                        1, 1, 0, 'analysis_running', '{}'::json, :now, :now
                    )
                    """
                ),
                {"now": now},
            )

        with pytest.raises(ReportingStateError) as conflict:
            await repository.initialize()

        assert conflict.value.code == "report_run_legacy_identity_conflict"
    finally:
        async with database.async_engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS agentos_reporting CASCADE"))
        await database.async_engine.dispose()
        database.sync_engine.dispose()


def test_submit_visualization_charts_persists_section_submission() -> None:
    result = ReportingStateReducer.apply(
        make_visualization_state(),
        {
            "name": "submit_visualization_charts",
            "commandId": "viz-section:1:section_001:abc",
            "payload": {
                "sectionCode": "section_001",
                "charts": [make_chart_registration("chart_a")],
                "files": [make_file_identity("charts/section_001/attempt-1/chart_a.png")],
            },
        },
    )

    payload = result.state.payload
    assert payload["visualizationSections"]["section_001"]["charts"][0]["chartId"] == "chart_a"
    assert payload["visualizationSections"]["section_001"]["files"] == [
        make_file_identity("charts/section_001/attempt-1/chart_a.png")
    ]
    assert "section_001" in payload["completedVisualizationSections"]


def test_submit_visualization_charts_allows_empty_charts() -> None:
    result = ReportingStateReducer.apply(
        make_visualization_state(),
        {
            "name": "submit_visualization_charts",
            "commandId": "viz-section:1:section_002:empty",
            "payload": {"sectionCode": "section_002", "charts": [], "files": []},
        },
    )

    payload = result.state.payload
    assert payload["visualizationSections"]["section_002"] == {"charts": [], "files": []}
    assert "section_002" in payload["completedVisualizationSections"]


def test_submit_visualization_charts_rejects_cross_section_duplicate() -> None:
    state = state_with_chart("chart_a", "section_001")
    with pytest.raises(ReportingStateError) as exc_info:
        ReportingStateReducer.apply(
            state,
            {
                "name": "submit_visualization_charts",
                "commandId": "viz-section:1:section_002:def",
                "payload": {
                    "sectionCode": "section_002",
                    "charts": [make_chart_registration("chart_a")],
                    "files": [],
                },
            },
        )
    assert exc_info.value.code == "report_visualization_section_conflict"


def test_submit_visualization_charts_rejects_different_repeat_submission_for_section() -> None:
    state = state_with_chart("chart_a", "section_001")

    with pytest.raises(ReportingStateError) as exc_info:
        ReportingStateReducer.apply(
            state,
            {
                "name": "submit_visualization_charts",
                "commandId": "viz-section:2:section_001:changed",
                "payload": {
                    "sectionCode": "section_001",
                    "charts": [make_chart_registration("chart_b")],
                    "files": [],
                },
            },
            state.state_version,
        )

    assert exc_info.value.code == "report_visualization_section_conflict"


def test_submit_visualization_charts_accepts_identical_repeat_submission_for_section() -> None:
    state = state_with_chart("chart_a", "section_001")

    result = ReportingStateReducer.apply(
        state,
        {
            "name": "submit_visualization_charts",
            "commandId": "viz-section:2:section_001:identical",
            "payload": {
                "sectionCode": "section_001",
                "charts": [make_chart_registration("chart_a")],
                "files": [],
            },
        },
        state.state_version,
    )

    assert result.state.payload["visualizationSections"]["section_001"] == {
        "charts": [
            {
                **make_chart_registration("chart_a"),
                "comparisonPeriod": None,
                "comparisonType": "none",
                "comparability": "strict",
            }
        ],
        "files": [],
    }


def test_submit_visualization_charts_rejects_cross_section_duplicate_source_path() -> None:
    source_path = "analysis/charts/shared.png"
    state = submit_section(
        make_visualization_state(),
        "section_001",
        chart_id="chart_a",
        source_path=source_path,
    )

    with pytest.raises(ReportingStateError) as exc_info:
        ReportingStateReducer.apply(
            state,
            {
                "name": "submit_visualization_charts",
                "commandId": "viz-section:1:section_002:source-path-conflict",
                "payload": {
                    "sectionCode": "section_002",
                    "charts": [make_chart_registration("chart_b", source_path)],
                    "files": [],
                },
            },
        )

    assert exc_info.value.code == "report_visualization_section_conflict"


def test_submit_visualization_charts_blocked_after_analysis_phase() -> None:
    with pytest.raises(ReportingStateError):
        ReportingStateReducer.apply(
            initial_state().model_copy(update={"phase": ReportingPhase.FINALIZE}),
            make_submit_command("section_003"),
        )


def test_submit_visualization_charts_rejects_malformed_top_level_payload() -> None:
    with pytest.raises(ReportingStateError) as exc_info:
        ReportingStateReducer.apply(
            make_visualization_state(),
            {
                "name": "submit_visualization_charts",
                "commandId": "viz-section:1:malformed-top-level",
                "payload": {
                    "sectionCode": "section_001",
                    "charts": {},
                    "files": [],
                },
            },
        )

    assert exc_info.value.code == "report_visualization_section_invalid"


def test_submit_visualization_charts_rejects_malformed_chart_and_file_payload() -> None:
    with pytest.raises(ReportingStateError) as exc_info:
        ReportingStateReducer.apply(
            make_visualization_state(),
            {
                "name": "submit_visualization_charts",
                "commandId": "viz-section:1:malformed-items",
                "payload": {
                    "sectionCode": "section_001",
                    "charts": [{"chartId": "chart_a"}],
                    "files": [{"path": "charts/chart_a.png", "size": 0, "sha256": "invalid"}],
                },
            },
        )

    assert exc_info.value.code == "report_visualization_section_invalid"


def test_submit_visualization_charts_rejects_malformed_file_identity() -> None:
    with pytest.raises(ReportingStateError) as exc_info:
        ReportingStateReducer.apply(
            make_visualization_state(),
            {
                "name": "submit_visualization_charts",
                "commandId": "viz-section:1:malformed-file",
                "payload": {
                    "sectionCode": "section_001",
                    "charts": [make_chart_registration("chart_a")],
                    "files": [{"path": "charts/chart_a.png", "size": 1, "sha256": "invalid"}],
                },
            },
        )

    assert exc_info.value.code == "report_visualization_section_invalid"


def _integration_database_url() -> str:
    value = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not value:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL 持久化集成测试。")
    return value


@pytest.mark.parametrize(
    ("commands", "expected"),
    [
        (("start_analysis",), ReportingPhase.ANALYSIS_RUNNING),
        (("start_analysis", "start_visualization"), ReportingPhase.VISUALIZATION),
        (
            ("start_analysis", "start_visualization", "freeze_analysis"),
            ReportingPhase.ANALYSIS_FREEZING,
        ),
        (
            ("start_analysis", "start_visualization", "freeze_analysis", "enter_sections"),
            ReportingPhase.SECTIONS,
        ),
        (
            (
                "start_analysis",
                "start_visualization",
                "freeze_analysis",
                "enter_sections",
                "start_finalize",
                "complete",
            ),
            ReportingPhase.COMPLETED,
        ),
    ],
)
def test_reducer_allows_declared_phase_paths(commands, expected):
    state = initial_state()
    for command in commands:
        state = apply_phase(state, command)
    assert state.phase is expected
    assert state.state_version == len(commands)


def test_reducer_rejects_illegal_transition_and_stale_version():
    state = initial_state()
    with pytest.raises(ReportingStateError) as illegal:
        apply_phase(state, "start_finalize")
    assert illegal.value.code == "report_state_transition_invalid"

    with pytest.raises(ReportingStateConflict):
        ReportingStateReducer.apply(
            state,
            {"name": "start_analysis", "commandId": "start"},
            expected_version=3,
        )


def test_record_artifact_is_idempotent_and_rejects_identity_change() -> None:
    identity = {"path": "analysis/evidence.json", "size": 12, "sha256": "a" * 64}
    state = initial_state()
    recorded = ReportingStateReducer.apply(
        state,
        {
            "name": "record_artifact",
            "commandId": "artifact-1",
            "payload": {"artifact": identity},
        },
        state.state_version,
    ).state
    replayed = ReportingStateReducer.apply(
        recorded,
        {
            "name": "record_artifact",
            "commandId": "artifact-2",
            "payload": {"artifact": identity},
        },
        recorded.state_version,
    ).state

    assert replayed.payload["artifacts"] == [identity]
    with pytest.raises(ReportingStateError) as raised:
        ReportingStateReducer.apply(
            replayed,
            {
                "name": "record_artifact",
                "commandId": "artifact-changed",
                "payload": {
                    "artifact": {
                        **identity,
                        "size": 13,
                        "sha256": "b" * 64,
                    }
                },
            },
            replayed.state_version,
        )

    assert raised.value.code == "report_artifact_identity_mismatch"


def test_complete_analysis_items_can_finish_out_of_order_and_remain_running():
    state = apply_phase(initial_state(), "start_analysis")
    state = ReportingStateReducer.apply(
        state,
        {
            "name": "set_analysis_plan",
            "commandId": "plan",
            "payload": {"analysisIds": ["analysis_001", "analysis_002"]},
        },
        state.state_version,
    ).state

    second_completed_first = ReportingStateReducer.apply(
        state,
        {
            "name": "complete_analysis_item",
            "commandId": "complete-002",
            "payload": {"analysisId": "analysis_002", "summary": "成本已复算"},
        },
        state.state_version,
    ).state
    assert second_completed_first.phase is ReportingPhase.ANALYSIS_RUNNING
    assert second_completed_first.payload["completedAnalysisIds"] == ["analysis_002"]
    assert second_completed_first.payload["currentAnalysisId"] == "analysis_001"

    completed = ReportingStateReducer.apply(
        second_completed_first,
        {
            "name": "complete_analysis_item",
            "commandId": "complete-001",
            "payload": {"analysisId": "analysis_001", "summary": "收入已复算"},
        },
        second_completed_first.state_version,
    ).state
    assert completed.phase is ReportingPhase.ANALYSIS_RUNNING
    assert completed.payload["currentAnalysisId"] is None


def test_finalize_checkpoint_advances_durable_phase_in_same_reducer_call() -> None:
    running = apply_phase(initial_state(), "start_analysis")

    finalized = ReportingStateReducer.apply(
        running,
        {
            "name": "set_workflow_checkpoint",
            "commandId": "workflow-checkpoint-v2:1:finalize",
            "payload": {"checkpoint": {"phase": "finalize", "revision": 1}},
        },
        running.state_version,
    ).state

    assert finalized.phase is ReportingPhase.FINALIZE
    assert finalized.payload["workflowCheckpoint"]["phase"] == "finalize"
    completed = apply_phase(finalized, "complete")
    assert completed.phase is ReportingPhase.COMPLETED


def test_non_finalize_checkpoint_does_not_advance_durable_phase() -> None:
    running = apply_phase(initial_state(), "start_analysis")

    persisted = ReportingStateReducer.apply(
        running,
        {
            "name": "set_workflow_checkpoint",
            "commandId": "workflow-checkpoint-v2:1:analysis",
            "payload": {"checkpoint": {"phase": "analysis", "revision": 1}},
        },
        running.state_version,
    ).state

    assert persisted.phase is ReportingPhase.ANALYSIS_RUNNING


def test_v2_finalize_checkpoint_is_not_blocked_by_legacy_command_receipt() -> None:
    running = apply_phase(initial_state(), "start_analysis")
    running.payload["appliedCommands"]["workflow-checkpoint:1:same-digest"] = {
        "name": "set_workflow_checkpoint"
    }

    finalized = ReportingStateReducer.apply(
        running,
        {
            "name": "set_workflow_checkpoint",
            "commandId": "workflow-checkpoint-v2:1:same-digest",
            "payload": {"checkpoint": {"phase": "finalize", "revision": 1}},
        },
        running.state_version,
    ).state

    assert finalized.phase is ReportingPhase.FINALIZE


def test_complete_transitions_directly_from_section_phase() -> None:
    state = apply_phase(initial_state(), "start_analysis")

    completed = ReportingStateReducer.apply(
        state,
        {
            "name": "complete",
            "commandId": "complete-section-coding",
            "payload": {"markdown": {"path": "report.md"}},
        },
        state.state_version,
    ).state

    assert completed.phase is ReportingPhase.COMPLETED


def test_set_analysis_plan_freezes_matching_durable_plan_details():
    state = apply_phase(initial_state(), "start_analysis")
    plans = {
        "analysis_001": {
            "analysisId": "analysis_001",
            "domain": "income",
            "datasetIds": ["dataset-1"],
        }
    }

    frozen = ReportingStateReducer.apply(
        state,
        {
            "name": "set_analysis_plan",
            "commandId": "plan-details",
            "payload": {"analysisIds": ["analysis_001"], "analysisPlans": plans},
        },
        state.state_version,
    ).state
    plans["analysis_001"]["domain"] = "changed"

    assert frozen.payload["analysisPlans"]["analysis_001"]["domain"] == "income"
    with pytest.raises(ReportingStateError) as raised:
        ReportingStateReducer.apply(
            state,
            {
                "name": "set_analysis_plan",
                "commandId": "plan-details-invalid",
                "payload": {
                    "analysisIds": ["analysis_001"],
                    "analysisPlans": {"analysis_002": {}},
                },
            },
            state.state_version,
        )
    assert raised.value.code == "report_analysis_plan_invalid"


def test_targeted_rework_requires_analysis_ids_and_missing_evidence():
    state = initial_state()
    state = apply_phase(state, "start_analysis")
    state = ReportingStateReducer.apply(
        state,
        {
            "name": "set_analysis_plan",
            "commandId": "rework-plan",
            "payload": {"analysisIds": ["analysis_001"]},
        },
        state.state_version,
    ).state
    state = ReportingStateReducer.apply(
        state,
        {
            "name": "complete_analysis_item",
            "commandId": "rework-analysis-complete",
            "payload": {"analysisId": "analysis_001", "summary": "收入已复算"},
        },
        state.state_version,
    ).state
    with pytest.raises(ReportingStateError) as invalid:
        ReportingStateReducer.apply(
            state,
            {
                "name": "request_analysis_rework",
                "commandId": "bad-rework",
                "payload": {"analysisIds": ["analysis_001"]},
            },
            state.state_version,
        )
    assert invalid.value.code == "report_analysis_rework_invalid"

    rework = ReportingStateReducer.apply(
        state,
        {
            "name": "request_analysis_rework",
            "commandId": "rework-1",
            "payload": {
                "analysisIds": ["analysis_001"],
                "missingEvidence": ["缺少同比明细"],
                "reason": "章节证据不足",
            },
        },
        state.state_version,
    ).state
    assert rework.phase is ReportingPhase.ANALYSIS_REWORK
    assert rework.payload["rework"]["analysisIds"] == ["analysis_001"]


def test_section_start_is_idempotent_and_rejects_other_work_item() -> None:
    state = initial_state().model_copy(update={"phase": ReportingPhase.SECTIONS})
    started = ReportingStateReducer.apply(
        state,
        {
            "name": "start_section",
            "commandId": "start-section-1",
            "payload": {"sectionCode": "section_001", "workItemHash": "a" * 64},
        },
        state.state_version,
    ).state

    assert started.payload["runningSections"] == {"section_001": "a" * 64}
    with pytest.raises(ReportingStateError) as raised:
        ReportingStateReducer.apply(
            started,
            {
                "name": "start_section",
                "commandId": "start-section-conflict",
                "payload": {"sectionCode": "section_001", "workItemHash": "b" * 64},
            },
            started.state_version,
        )

    assert raised.value.code == "report_section_start_conflict"


def test_targeted_rework_only_invalidates_selected_analysis_and_dependent_sections():
    state = initial_state().model_copy(
        update={
            "phase": ReportingPhase.SECTIONS,
            "payload": {
                **initial_state().payload,
                "analysisIds": ["analysis_001", "analysis_002"],
                "completedAnalysisIds": ["analysis_001", "analysis_002"],
                "analysisItems": {
                    "analysis_001": {"analysisId": "analysis_001"},
                    "analysis_002": {"analysisId": "analysis_002"},
                },
                "completedSections": ["overview", "income"],
                "runningSections": {
                    "overview": "overview-old-hash",
                    "income": "income-old-hash",
                },
                "sectionArtifacts": {
                    "overview": {"sectionCode": "overview", "analysisIds": ["analysis_002"]},
                    "income": {"sectionCode": "income", "analysisIds": ["analysis_001"]},
                },
                "visualizationSections": {
                    "income": {
                        "charts": [make_chart_registration("income")],
                        "files": [make_file_identity("analysis/charts/income.png")],
                    },
                    "overview": {
                        "charts": [make_chart_registration("overview")],
                        "files": [make_file_identity("analysis/charts/overview.png")],
                    },
                },
                "completedVisualizationSections": ["income", "overview"],
                "reportBrief": {"objective": "旧目标"},
                "analysisEvidenceManifest": {
                    "version": "2",
                    "evidence": [
                        {"analysisId": "analysis_001", "chartIds": ["income"]},
                        {"analysisId": "analysis_002", "chartIds": ["overview"]},
                    ],
                },
                "profileReadReceipts": [{"receiptId": "receipt-1", "datasetId": "dataset-1"}],
                "workflowCheckpoint": {
                    "phase": "sections",
                    "reportBrief": {"objective": "旧目标"},
                    "evidenceManifest": {"version": "1"},
                    "analysisManifestFile": {
                        "path": "analysis/old.json",
                        "size": 1,
                        "sha256": "b" * 64,
                    },
                },
                "checkpointMirrorFile": {
                    "path": "analysis/checkpoint.json",
                    "size": 1,
                    "sha256": "c" * 64,
                },
            },
        }
    )
    rework = ReportingStateReducer.apply(
        state,
        {
            "name": "request_analysis_rework",
            "commandId": "rework-income",
            "payload": {
                "analysisIds": ["analysis_001"],
                "missingEvidence": ["缺少收入同比明细"],
            },
        },
        state.state_version,
    ).state

    assert rework.payload["completedAnalysisIds"] == ["analysis_002"]
    assert set(rework.payload["analysisItems"]) == {"analysis_002"}
    assert rework.payload["completedSections"] == ["overview"]
    assert rework.payload["runningSections"] == {"overview": "overview-old-hash"}
    assert set(rework.payload["sectionArtifacts"]) == {"overview"}
    assert rework.payload["pendingSections"] == ["income"]
    assert set(rework.payload["visualizationSections"]) == {"overview"}
    assert rework.payload["completedVisualizationSections"] == ["overview"]
    assert rework.payload["reportBrief"] is None
    assert rework.payload["analysisEvidenceManifest"] is None
    assert rework.payload["profileReadReceipts"] == [
        {"receiptId": "receipt-1", "datasetId": "dataset-1"}
    ]
    assert rework.payload["workflowCheckpoint"]["phase"] == "analysis"
    assert rework.payload["workflowCheckpoint"]["reportBrief"] is None
    assert rework.payload["workflowCheckpoint"]["evidenceManifest"] is None
    assert rework.payload["workflowCheckpoint"]["analysisManifestFile"] is None
    assert rework.payload["checkpointMirrorFile"] is None

    restarted_income = ReportingStateReducer.apply(
        rework,
        {
            "name": "start_section",
            "commandId": "restart-income",
            "payload": {"sectionCode": "income", "workItemHash": "income-new-hash"},
        },
        rework.state_version,
    ).state
    assert restarted_income.payload["runningSections"] == {
        "overview": "overview-old-hash",
        "income": "income-new-hash",
    }

    running = apply_phase(restarted_income, "start_analysis")
    assert running.phase is ReportingPhase.ANALYSIS_RUNNING
    assert running.payload["currentAnalysisId"] == "analysis_001"

    visualization = ReportingStateReducer.apply(
        running,
        {
            "name": "complete_analysis_item",
            "commandId": "rework-analysis-complete",
            "payload": {"analysisId": "analysis_001", "summary": "收入已复算"},
        },
        running.state_version,
    ).state
    supplemented = ReportingStateReducer.apply(
        visualization,
        {
            "name": "submit_visualization_charts",
            "commandId": "rework-charts",
            "payload": {
                "sectionCode": "income",
                "charts": [make_chart_registration("income", "analysis/charts/income-v2.png")],
                "files": [make_file_identity("analysis/charts/income-v2.png")],
            },
        },
        visualization.state_version,
    ).state

    assert set(supplemented.payload["visualizationSections"]) == {"overview", "income"}
    assert supplemented.payload["completedVisualizationSections"] == ["overview", "income"]


def test_write_intent_is_durable_and_identity_conflicts_fail_closed():
    state = apply_phase(initial_state(), "start_analysis")
    intent = {
        "intentId": "a" * 64,
        "toolName": "create_analysis_file",
        "arguments": {"path": "analysis/large.txt", "content": "x"},
        "affectedPaths": ["analysis/large.txt"],
        "expectedStates": {"analysis/large.txt": "present"},
    }
    pending = ReportingStateReducer.apply(
        state,
        {"name": "record_write_intent", "commandId": "intent", "payload": {"intent": intent}},
        state.state_version,
    ).state
    assert pending.payload["writeIntents"]["a" * 64]["status"] == "pending"

    identity = {"path": "analysis/large.txt", "size": 40_000, "sha256": "b" * 64}
    committed = ReportingStateReducer.apply(
        pending,
        {
            "name": "commit_write_intent",
            "commandId": "commit",
            "payload": {"intentId": "a" * 64, "artifacts": [identity]},
        },
        pending.state_version,
    ).state
    assert committed.payload["writeIntents"]["a" * 64]["artifacts"] == [identity]

    with pytest.raises(ReportingStateError) as conflict:
        ReportingStateReducer.apply(
            committed,
            {
                "name": "commit_write_intent",
                "commandId": "commit-changed",
                "payload": {
                    "intentId": "a" * 64,
                    "artifacts": [{**identity, "sha256": "c" * 64}],
                },
            },
            committed.state_version,
        )
    assert conflict.value.code == "report_analysis_write_identity_mismatch"


def test_write_intent_commit_sequence_follows_actual_commit_order():
    state = apply_phase(initial_state(), "start_analysis")
    intents = (
        {
            "intentId": "a" * 64,
            "toolName": "create_analysis_file",
            "arguments": {"path": "analysis/chart.py", "content": "a"},
            "affectedPaths": ["analysis/chart.py"],
            "expectedStates": {"analysis/chart.py": "present"},
        },
        {
            "intentId": "b" * 64,
            "toolName": "create_analysis_file",
            "arguments": {"path": "analysis/chart.py", "content": "b"},
            "affectedPaths": ["analysis/chart.py"],
            "expectedStates": {"analysis/chart.py": "present"},
        },
    )
    for intent in intents:
        state = ReportingStateReducer.apply(
            state,
            {
                "name": "record_write_intent",
                "commandId": f"record-{intent['intentId']}",
                "payload": {"intent": intent},
            },
            state.state_version,
        ).state

    for intent, sha256 in ((intents[1], "b" * 64), (intents[0], "a" * 64)):
        state = ReportingStateReducer.apply(
            state,
            {
                "name": "commit_write_intent",
                "commandId": f"commit-{intent['intentId']}",
                "payload": {
                    "intentId": intent["intentId"],
                    "artifacts": [{"path": "analysis/chart.py", "size": 1, "sha256": sha256}],
                },
            },
            state.state_version,
        ).state

    committed = state.payload["writeIntents"]
    assert committed["b" * 64]["commitSequence"] < committed["a" * 64]["commitSequence"]


def test_duplicate_section_completion_is_idempotent_only_for_same_artifact():
    state = apply_phase(initial_state(), "start_analysis")
    state = ReportingStateReducer.apply(
        state,
        {
            "name": "set_analysis_plan",
            "commandId": "plan",
            "payload": {"analysisIds": ["analysis_001"]},
        },
        state.state_version,
    ).state
    state = ReportingStateReducer.apply(
        state,
        {
            "name": "complete_section",
            "commandId": "section-1",
            "payload": {
                "sectionCode": "income",
                "analysisIds": ["analysis_001"],
                "artifactFile": {"path": "a.json", "size": 1, "sha256": "a" * 64},
            },
        },
        state.state_version,
    ).state
    with pytest.raises(ReportingStateError) as conflict:
        ReportingStateReducer.apply(
            state,
            {
                "name": "complete_section",
                "commandId": "section-2",
                "payload": {
                    "sectionCode": "income",
                    "analysisIds": ["analysis_001"],
                    "artifactFile": {"path": "b.json", "size": 1, "sha256": "b" * 64},
                },
            },
            state.state_version,
        )
    assert conflict.value.code == "report_section_completion_conflict"


@pytest.fixture
async def state_repository():
    database = create_agent_database(_integration_database_url())
    repository = ReportingStateRepository(database.async_db)
    try:
        await repository.initialize()
        async with database.async_engine.begin() as connection:
            await connection.execute(
                delete(repository.command_receipts).where(
                    repository.command_receipts.c.report_run_id == "workflow-run-1"
                )
            )
            await connection.execute(
                delete(repository.states).where(
                    repository.states.c.report_run_id == "workflow-run-1"
                )
            )
            await connection.execute(
                delete(repository.workflow_thread_owners).where(
                    repository.workflow_thread_owners.c.thread_id == "thread-1"
                )
            )
        yield repository
    finally:
        async with database.async_engine.begin() as connection:
            await connection.execute(
                delete(repository.command_receipts).where(
                    repository.command_receipts.c.report_run_id == "workflow-run-1"
                )
            )
            await connection.execute(
                delete(repository.states).where(
                    repository.states.c.report_run_id == "workflow-run-1"
                )
            )
            await connection.execute(
                delete(repository.workflow_thread_owners).where(
                    repository.workflow_thread_owners.c.thread_id == "thread-1"
                )
            )
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_repository_create_cas_idempotency_and_conflict(state_repository):
    created = await state_repository.create(initial_state())
    assert created.state_version == 0

    command = {"name": "start_analysis", "commandId": "start-1"}
    first = await state_repository.apply(
        created.report_run_id, command, expected_version=created.state_version
    )
    assert first.state.phase is ReportingPhase.ANALYSIS_RUNNING
    assert first.state.state_version == 1

    replay = await state_repository.apply(
        created.report_run_id, command, expected_version=created.state_version
    )
    assert replay.idempotent is True
    assert replay.state.state_version == 1

    with pytest.raises(ReportingStateConflict):
        await state_repository.apply(
            created.report_run_id,
            {"name": "freeze_analysis", "commandId": "freeze-1"},
            expected_version=0,
        )


@pytest.mark.anyio
@pytest.mark.integration
async def test_repository_rejects_command_id_rebound_to_other_payload(state_repository):
    created = await state_repository.create(initial_state())
    await state_repository.apply(
        created.report_run_id,
        {
            "name": "set_analysis_plan",
            "commandId": "same-id",
            "payload": {"analysisIds": ["analysis_001"]},
        },
        expected_version=0,
    )
    with pytest.raises(ReportingStateError) as conflict:
        await state_repository.apply(
            created.report_run_id,
            {
                "name": "set_analysis_plan",
                "commandId": "same-id",
                "payload": {"analysisIds": ["analysis_002"]},
            },
            expected_version=0,
        )
    assert conflict.value.code == "report_command_replay_conflict"


@pytest.mark.anyio
@pytest.mark.integration
async def test_repository_keeps_idempotency_after_inline_command_cache_eviction(
    state_repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reporting_state_module, "MAX_INLINE_APPLIED_COMMANDS", 2)
    state = await state_repository.create(initial_state())
    first = {"name": "trace", "commandId": "trace-0", "payload": {"index": 0}}
    for index in range(3):
        command = {"name": "trace", "commandId": f"trace-{index}", "payload": {"index": index}}
        state = (
            await state_repository.apply(
                state.report_run_id,
                command,
                expected_version=state.state_version,
            )
        ).state

    assert "trace-0" not in state.payload["appliedCommands"]
    replay = await state_repository.apply(
        state.report_run_id,
        first,
        expected_version=0,
    )

    assert replay.idempotent is True
    assert replay.state.state_version == state.state_version
    assert replay.state.payload["trace"] == state.payload["trace"]


@pytest.mark.anyio
@pytest.mark.integration
async def test_repository_rejects_evicted_command_id_rebound_to_other_payload(
    state_repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reporting_state_module, "MAX_INLINE_APPLIED_COMMANDS", 1)
    state = await state_repository.create(initial_state())
    for index in range(2):
        state = (
            await state_repository.apply(
                state.report_run_id,
                {"name": "trace", "commandId": f"trace-{index}", "payload": {"index": index}},
                expected_version=state.state_version,
            )
        ).state

    with pytest.raises(ReportingStateError) as conflict:
        await state_repository.apply(
            state.report_run_id,
            {"name": "trace", "commandId": "trace-0", "payload": {"index": 99}},
            expected_version=0,
        )

    assert conflict.value.code == "report_command_replay_conflict"


@pytest.mark.anyio
@pytest.mark.integration
async def test_repository_rejects_concurrent_workflow_execution_lock(state_repository) -> None:
    async with state_repository.workflow_execution_lock("external-run-1"):
        assert await state_repository.is_workflow_run_active("external-run-1")
        with pytest.raises(ReportingStateError) as conflict:
            async with state_repository.workflow_execution_lock("external-run-1"):
                pass

    assert conflict.value.code == "report_workflow_run_conflict"
    assert not await state_repository.is_workflow_run_active("external-run-1")


@pytest.mark.anyio
@pytest.mark.integration
async def test_repository_serializes_same_thread_lifecycle_lock(state_repository) -> None:
    async with state_repository.workflow_thread_lifecycle_lock("thread-1"):
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                async with state_repository.workflow_thread_lifecycle_lock("thread-1"):
                    pass

    async with state_repository.workflow_thread_lifecycle_lock("thread-1"):
        pass


@pytest.mark.anyio
@pytest.mark.integration
async def test_repository_persists_workflow_thread_owner_across_instances(
    state_repository,
) -> None:
    assert await state_repository.claim_workflow_thread(
        thread_id="thread-1", external_run_id="run-1", owner_user_id="user-1"
    )

    restarted = ReportingStateRepository(state_repository.db)
    assert await restarted.ensure_workflow_thread_owner(
        thread_id="thread-1", external_run_id="run-1", owner_user_id="user-1"
    )
    assert not await restarted.claim_workflow_thread(
        thread_id="thread-1", external_run_id="run-2", owner_user_id="user-1"
    )
    assert not await restarted.ensure_workflow_thread_owner(
        thread_id="thread-1", external_run_id="run-2", owner_user_id="user-1"
    )


@pytest.mark.anyio
@pytest.mark.integration
async def test_repository_only_releases_matching_workflow_thread_owner(
    state_repository,
) -> None:
    await state_repository.claim_workflow_thread(
        thread_id="thread-1", external_run_id="run-1", owner_user_id="user-1"
    )

    assert not await state_repository.release_workflow_thread(
        thread_id="thread-1", external_run_id="run-2", owner_user_id="user-1"
    )
    assert await state_repository.release_workflow_thread(
        thread_id="thread-1", external_run_id="run-1", owner_user_id="user-1"
    )
    assert await state_repository.claim_workflow_thread(
        thread_id="thread-1", external_run_id="run-2", owner_user_id="user-1"
    )


@pytest.mark.anyio
@pytest.mark.integration
async def test_analysis_facts_survive_repository_restart(state_repository):
    state = await state_repository.create(initial_state())
    for command in (
        {"name": "start_analysis", "commandId": "start"},
        {
            "name": "set_analysis_plan",
            "commandId": "plan",
            "payload": {"analysisIds": ["analysis_001", "analysis_002"]},
        },
        {
            "name": "record_profile_receipt",
            "commandId": "receipt-1",
            "payload": {"receipt": {"receiptId": "receipt-1", "datasetId": "dataset-1"}},
        },
        {
            "name": "complete_analysis_item",
            "commandId": "item-1",
            "payload": {"analysisId": "analysis_001", "summary": "收入规模已复算"},
        },
    ):
        result = await state_repository.apply(
            state.report_run_id, command, expected_version=state.state_version
        )
        state = result.state

    restarted = ReportingStateRepository(state_repository.db)
    restored = await restarted.get(state.report_run_id)

    assert restored is not None
    assert restored.phase is ReportingPhase.ANALYSIS_RUNNING
    assert restored.payload["currentAnalysisId"] == "analysis_002"
    assert restored.payload["profileReadReceipts"][0]["receiptId"] == "receipt-1"
    assert restored.payload["analysisItems"]["analysis_001"]["summary"] == "收入规模已复算"


def test_section_chart_submission_is_idempotent_and_rejects_changed_content():
    state = apply_phase(initial_state(), "start_analysis")
    first = ReportingStateReducer.apply(
        state,
        {
            "name": "submit_visualization_charts",
            "commandId": "charts-1",
            "payload": {
                "sectionCode": "section_001",
                "charts": [make_chart_registration("chart-1")],
                "files": [],
            },
        },
        state.state_version,
    ).state
    assert [
        item["chartId"] for item in first.payload["visualizationSections"]["section_001"]["charts"]
    ] == ["chart-1"]
    replayed = ReportingStateReducer.apply(
        first,
        {
            "name": "submit_visualization_charts",
            "commandId": "charts-1",
            "payload": {
                "sectionCode": "section_001",
                "charts": [make_chart_registration("chart-1")],
                "files": [],
            },
        },
        first.state_version,
    )
    assert replayed.idempotent is True

    with pytest.raises(ReportingStateError) as conflict:
        ReportingStateReducer.apply(
            first,
            {
                "name": "submit_visualization_charts",
                "commandId": "charts-2",
                "payload": {
                    "sectionCode": "section_001",
                    "charts": [make_chart_registration("chart-2")],
                    "files": [],
                },
            },
            first.state_version,
        )
    assert conflict.value.code == "report_visualization_section_conflict"


def test_chart_inspection_receipt_is_durable_idempotent_and_identity_bound() -> None:
    state = apply_phase(apply_phase(initial_state(), "start_analysis"), "start_visualization")
    receipt = {
        "sourcePath": "analysis/charts/income.png",
        "sha256": "a" * 64,
        "inspectionMode": "vision",
        "visualReviewStatus": "passed",
        "inspectorId": None,
        "modelId": "vision-model",
        "reviewed": True,
        "requiresRevision": False,
        "issues": [],
        "summary": "检查完成",
        "warnings": [],
        "suggestions": [],
    }
    first = ReportingStateReducer.apply(
        state,
        {
            "name": "record_chart_inspection",
            "commandId": "chart-inspection-1",
            "payload": {"receipt": receipt},
        },
        state.state_version,
    ).state

    assert first.payload["chartInspectionReceipts"] == [receipt]
    replayed = ReportingStateReducer.apply(
        first,
        {
            "name": "record_chart_inspection",
            "commandId": "chart-inspection-2",
            "payload": {"receipt": receipt},
        },
        first.state_version,
    ).state
    assert replayed.payload["chartInspectionReceipts"] == [receipt]

    changed = {**receipt, "modelId": "different-model"}
    with pytest.raises(ReportingStateError) as conflict:
        ReportingStateReducer.apply(
            replayed,
            {
                "name": "record_chart_inspection",
                "commandId": "chart-inspection-conflict",
                "payload": {"receipt": changed},
            },
            replayed.state_version,
        )
    assert conflict.value.code == "report_chart_inspection_conflict"


def test_profile_receipt_reuses_stable_identity_when_purpose_changes() -> None:
    state = apply_phase(initial_state(), "start_analysis")
    first_receipt = {
        "receiptId": "profile-read-abc",
        "datasetId": "dataset-1",
        "query": "variables.area.value_counts_without_nan",
        "snapshotHash": "a" * 64,
        "purpose": "读取院区分布",
    }
    first = ReportingStateReducer.apply(
        state,
        {
            "name": "record_profile_receipt",
            "commandId": "profile-purpose-1",
            "payload": {"receipt": first_receipt},
        },
        state.state_version,
    ).state
    reused = ReportingStateReducer.apply(
        first,
        {
            "name": "record_profile_receipt",
            "commandId": "profile-purpose-2",
            "payload": {
                "receipt": {**first_receipt, "purpose": "复核院区结构"},
            },
        },
        first.state_version,
    ).state

    assert reused.payload["profileReadReceipts"] == [first_receipt]


@pytest.mark.anyio
@pytest.mark.integration
async def test_repository_rejects_legacy_schema_row(state_repository):
    state = await state_repository.create(initial_state())
    async with state_repository.db.db_engine.begin() as connection:  # type: ignore[attr-defined]
        await connection.execute(
            update(state_repository.states)
            .where(state_repository.states.c.report_run_id == state.report_run_id)
            .values(schema_version=1)
        )
    with pytest.raises(ReportingStateVersionUnsupported):
        await state_repository.get(state.report_run_id)


def _minimal_checkpoint_payload() -> dict[str, object]:
    """构造仅含必填字段的合法 v2 checkpoint 载荷,供 Schema 兼容性测试复用。"""
    return {
        "revision": 1,
        "phase": "analysis",
        "outlineHash": "0" * 64,
        "profileCoverage": {
            "authorizedDatasetCount": 1,
            "coveredDatasetCount": 1,
            "datasets": [
                {
                    "datasetId": "d1",
                    "datasetPath": "d.csv",
                    "datasetSize": 1,
                    "datasetSnapshotHash": "1" * 64,
                    "profileFile": {"path": "p.json", "size": 1, "sha256": "2" * 64},
                    "rowCount": 1,
                    "fieldCount": 1,
                    "fields": ["x"],
                }
            ],
        },
    }


def test_checkpoint_error_accepts_visualization_section_work_kind() -> None:
    # 章节身份写入 sectionCode,analysisId 保持 analysis_NNN pattern 不变
    error = CheckpointError.model_validate(
        {
            "phase": "analysis",
            "code": "report_analysis_phase_failed",
            "message": "章节图表 worker 失败。",
            "workKind": "visualization_section",
            "sectionCode": "section_001",
        }
    )
    assert error.work_kind == "visualization_section"
    assert error.section_code == "section_001"
    assert error.analysis_id is None


def test_checkpoint_error_rejects_section_code_in_analysis_id() -> None:
    with pytest.raises(ValidationError):
        CheckpointError.model_validate(
            {
                "phase": "analysis",
                "code": "x",
                "message": "m",
                "workKind": "visualization_section",
                "analysisId": "section_001",
            }
        )


def test_context_trace_accepts_new_work_kinds() -> None:
    trace = ContextTrace.model_validate(
        {
            "phase": "analysis",
            "workKind": "visualization_section",
            "sectionCode": "section_001",
            "attempt": 0,
        }
    )
    assert trace.work_kind == "visualization_section"
    visualization = ContextTrace.model_validate(
        {
            "phase": "analysis",
            "workKind": "visualization_section",
            "sectionCode": "section_001",
            "attempt": 0,
        }
    )
    assert visualization.work_kind == "visualization_section"


@pytest.mark.parametrize("model", [CheckpointError, ContextTrace])
def test_old_visualization_work_kind_is_rejected(
    model: type[CheckpointError | ContextTrace],
) -> None:
    payload = {"phase": "analysis", "workKind": "visualization"}
    if model is CheckpointError:
        payload.update({"code": "x", "message": "m"})

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_checkpoint_visualization_section_errors_default_empty() -> None:
    checkpoint = ReportingCheckpoint.model_validate(_minimal_checkpoint_payload())
    assert checkpoint.visualization_section_errors == {}
    # 历史 checkpoint(无该字段)反序列化后必须仍是合法模型
    payload = checkpoint.model_dump(mode="json", by_alias=True)
    payload.pop("visualizationSectionErrors")
    assert ReportingCheckpoint.model_validate(payload).visualization_section_errors == {}
