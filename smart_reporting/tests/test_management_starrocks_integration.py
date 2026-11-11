"""真实 StarRocks 验收：仅在唯一命名的自有隔离库创建/删除对象。"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url

from smart_reporting.management.data_sources.models import SourceDraftInput
from smart_reporting.management.data_sources.secrets import CredentialVault
from smart_reporting.management.data_sources.service import SourceService
from smart_reporting.management.models import ManagementScope
from smart_reporting.management.profiles import ProfileService
from smart_reporting.management.runtime import ManagedConfigurationProvider
from smart_reporting.management.scopes import ScopeService
from smart_reporting.management.table_access import TableAccessService
from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
from smart_reporting.reporting.models import ReportingError
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def real_warehouse():
    base = os.environ.get("REPORTING_STARROCKS_INTEGRATION_DSN")
    if not base or not os.environ.get("REPORTING_MANAGEMENT_TEST_DB_URL"):
        pytest.skip("需要显式真实 StarRocks DSN 和隔离管理测试库")
    database = f"sr_access_test_{uuid.uuid4().hex}"
    url = make_url(base)
    engine = create_engine(url, connect_args={"connect_timeout": 8, "read_timeout": 30})
    evidence = {
        "database": database,
        "checks": [],
        "cleanup": False,
        "startedAt": datetime.now(UTC).isoformat(),
    }
    created = False
    try:
        with engine.connect() as conn:
            evidence["serverVersion"] = conn.exec_driver_sql(
                "SELECT current_version()"
            ).scalar_one()
            conn.exec_driver_sql(f"CREATE DATABASE `{database}`")
            created = True
            for table in ("visible_orders", "hidden_orders"):
                conn.exec_driver_sql(
                    f"CREATE TABLE `{database}`.`{table}` ("
                    "id BIGINT NOT NULL COMMENT '测试主键', "
                    "amount DECIMAL(18,2) NULL COMMENT '测试金额') "
                    "ENGINE=OLAP DUPLICATE KEY(id) COMMENT '隔离验收表' "
                    "DISTRIBUTED BY HASH(id) BUCKETS 1 PROPERTIES ('replication_num'='1')"
                )
                conn.exec_driver_sql(
                    f"INSERT INTO `{database}`.`{table}` VALUES (1,12.50),(2,NULL)"
                )
            conn.exec_driver_sql(
                f"CREATE VIEW `{database}`.orders_view COMMENT '隔离验收视图' "
                f"AS SELECT id,amount FROM `{database}`.hidden_orders"
            )
        yield url.set(database=database).render_as_string(hide_password=False), evidence
    finally:
        try:
            if created:
                # 名称完全由本fixture生成；绝不复用或清理已有数据库。
                assert database.startswith("sr_access_test_") and len(database) == 47
                with engine.connect() as conn:
                    conn.exec_driver_sql(f"DROP DATABASE `{database}`")
                    remaining = conn.execute(
                        text(
                            "SELECT SCHEMA_NAME FROM information_schema.schemata WHERE SCHEMA_NAME=:name"
                        ),
                        {"name": database},
                    ).all()
                    evidence["cleanup"] = remaining == []
                    assert evidence["cleanup"]
        finally:
            engine.dispose()
            output = os.environ.get("REPORTING_STARROCKS_EVIDENCE_DIR")
            if output:
                Path(output).mkdir(parents=True, exist_ok=True)
                (Path(output) / "integration-facts.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
                )


async def test_real_discovery_publication_frozen_queries_and_view_boundary(
    real_warehouse, auth_context
):
    dsn, facts = real_warehouse
    database = facts["database"]
    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token
    scopes = ScopeService(auth)
    scope = ManagementScope(database, "100")
    await scopes.register(token, scope, "真实隔离验收组织")
    vault = CredentialVault(f"test:{Fernet.generate_key().decode()}")
    sources = SourceService(scopes, vault)
    profiles = ProfileService(scopes)
    profile = await profiles.save_draft(token, scope, {"profileId": "base", "revision": "r1"}, 0)
    await profiles.publish(token, scope, "base", profile["version"])
    await sources.create_draft(
        token,
        scope,
        "operations",
        SourceDraftInput.model_validate(
            {
                "name": "真实隔离数仓",
                "database": database,
                "dsn": dsn,
                "reportingProfileVersionId": "base:1",
            }
        ),
    )
    access = TableAccessService(scopes, vault)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if conn.engine.dialect.name == "starrocks":
            statements.append(statement)

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        discovery = await access.discover(token, scope, "operations", 1)
    finally:
        event.remove(Engine, "before_cursor_execute", capture)
    assert statements
    # 目录发现只访问系统目录和结构反射，不能取业务样本或统计行数。
    for sql in statements:
        if sql.lstrip().upper().startswith("SELECT"):
            assert "information_schema" in sql.lower() or "from" not in sql.lower()
    facts["discoveryStatements"] = statements
    page = await access.tables(token, scope, "operations", discovery["discoveryId"])
    assert page["total"] == 3
    objects = {item["name"]: item for item in page["items"]}
    assert objects["orders_view"]["type"] == "view"
    assert objects["visible_orders"]["type"] == "table"
    assert objects["orders_view"]["description"] == "隔离验收视图"
    views = await access.tables(
        token, scope, "operations", discovery["discoveryId"], kind="view", q="orders", limit=1
    )
    assert views["total"] == 1 and views["items"][0]["name"] == "orders_view"
    assert all(not item["selected"] for item in objects.values())
    assert objects["visible_orders"]["description"] == "隔离验收表"
    columns = await access.columns(
        token, scope, "operations", discovery["discoveryId"], database, "visible_orders"
    )
    facts["columns"] = columns
    # 字段接口保留真实类型、可空性和注释。
    column_list = columns["columns"]
    assert column_list[0]["name"] == "id" and column_list[0]["nullable"] is False
    assert column_list[0]["dataType"] == "BIGINT"
    assert column_list[1]["dataType"].startswith("DECIMAL(18,")
    assert column_list[1]["nullable"] is True
    assert column_list[1]["description"] == "测试金额"
    facts["checks"].append("真实表/视图发现、中文说明、字段类型与可空性；发现不取样本")

    saved = await access.save(
        token, scope, "operations", 1, discovery["discoveryId"], [(database, "visible_orders")]
    )
    await sources.publish(token, scope, "operations", saved["draftVersion"])
    provider = ManagedConfigurationProvider(scopes, vault)

    async def freeze(run_id):
        await provider.register_run(run_id, scope, user_id="7", thread_id=run_id, entrypoint="cli")
        return await provider.freeze(run_id, scope, ("operations",))

    old = await freeze("real-before")
    assert [t.name for t in old.metadata["operations"].tables] == ["visible_orders"]
    discovery = await access.discover(token, scope, "operations", 2)
    saved = await access.save(
        token, scope, "operations", 2, discovery["discoveryId"], [(database, "orders_view")]
    )
    before = await freeze("real-before-publish")
    assert before.source_versions == old.source_versions
    assert before.source_hashes == old.source_hashes
    assert before.metadata == old.metadata
    check = await sources.release_check(token, scope, "operations", saved["draftVersion"])
    assert check["canPublish"]
    assert check["tableAccessChanges"]["added"] == [f"{database}.orders_view"]
    assert check["tableAccessChanges"]["removed"] == [f"{database}.visible_orders"]
    await sources.publish(token, scope, "operations", saved["draftVersion"])
    new = await freeze("real-after")
    restored = await ManagedConfigurationProvider(scopes, vault).load_pinned(scope, old.references)
    assert restored.references == old.references
    assert [t.name for t in restored.metadata["operations"].tables] == ["visible_orders"]
    assert [t.name for t in new.metadata["operations"].tables] == ["orders_view"]
    assert "hidden_orders" not in new.metadata["operations"].model_dump_json()
    facts["checks"].append("发布前原范围、发布后新范围；重建provider恢复旧运行仍为原范围")

    denied = []
    for frozen, table in ((restored, "visible_orders"), (new, "orders_view")):
        adapter = StarRocksDataSourceAdapter(
            frozen.sources["operations"],
            allowed_tables=tuple(
                f"{t.database}.{t.name}" for t in frozen.metadata["operations"].tables
            ),
        )
        executed = []

        def track(conn, cursor, statement, parameters, context, executemany):
            executed.append(statement)

        event.listen(adapter._engine, "before_cursor_execute", track)
        try:
            result = await adapter.query(f"SELECT id,amount FROM {database}.{table} ORDER BY id")
            assert [int(row[0]) for row in result.rows] == [1, 2]
            assert str(result.rows[0][1]) == "12.50" and result.rows[1][1] is None
            materialized = await adapter.materialize(
                f"SELECT id,amount FROM {database}.{table} ORDER BY id"
            )
            assert materialized.row_count == 2 and b"12.50" in materialized.content
            forbidden = [
                f"SELECT * FROM {database}.hidden_orders",
                f"SELECT * FROM {database}.{table} a JOIN {database}.hidden_orders b ON a.id=b.id",
                f"SELECT * FROM {database}.{table} WHERE id IN (SELECT id FROM {database}.hidden_orders)",
                f"WITH x AS (SELECT * FROM {database}.hidden_orders) SELECT * FROM x",
                f"SELECT * FROM another_test_db.{table}",
                f"SELECT * FROM external.{database}.{table}",
                f"SELECT * FROM {database}.{'visible_orders' if table == 'orders_view' else 'orders_view'}",
            ]
            for method in ("query", "materialize"):
                for sql in forbidden:
                    count = len(executed)
                    with pytest.raises(ReportingError) as caught:
                        await getattr(adapter, method)(sql)
                    assert caught.value.code == "sql_table_denied"
                    assert len(executed) == count
                    denied.append(
                        {
                            "scope": table,
                            "method": method,
                            "sql": sql,
                            "code": caught.value.code,
                            "databaseStatements": 0,
                        }
                    )
            facts.setdefault("queryResults", []).append(
                {
                    "table": table,
                    "rows": [
                        [int(row[0]), str(row[1]) if row[1] is not None else None]
                        for row in result.rows
                    ],
                    "materializedRowCount": materialized.row_count,
                    "csv": materialized.content.decode("utf-8"),
                }
            )
            facts["checks"].append(
                f"{table}真实查询及CSV物化成功；越权query/materialize均在执行前拒绝"
            )
        finally:
            await adapter.aclose()
    facts["denials"] = denied
    facts["passed"] = True
