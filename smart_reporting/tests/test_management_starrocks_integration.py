"""真实 StarRocks 验收：仅在唯一命名的自有隔离库创建/删除对象。"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from smart_reporting.management.data_sources.models import SourceDraftInput
from smart_reporting.management.data_sources.secrets import CredentialVault
from smart_reporting.management.data_sources.service import SourceService
from smart_reporting.management.table_access import TableAccessService
from smart_reporting.reporting.models import ReportingError
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




async def test_real_office_workspace_grant_and_member_table_limit(real_warehouse, auth_context):
    from smart_reporting.office.repository import Identity, OfficeError, OfficeRepository
    from smart_reporting.office.source_management import OfficeSourceScopes
    from smart_reporting.office.source_runtime import OfficeSourceRuntime

    dsn, facts = real_warehouse
    database = facts["database"]
    _, repository, _ = auth_context
    office = OfficeRepository(repository.engine)
    await office.create_schema()
    admin = Identity(database, "office-test", "admin")
    member = Identity(database, "office-test", "member")
    await office.bootstrap(admin, "Office administrator")
    await office.provision(admin, member.user, "Office member")
    token = await office.create_session(admin)
    scopes = OfficeSourceScopes(office)
    scope = await scopes.ensure_registered(await office.authenticate(token))
    vault = CredentialVault(f"test:{Fernet.generate_key().decode()}")
    sources = SourceService(scopes, vault)
    await sources.create_draft(token, scope, "office-test", SourceDraftInput.model_validate({
        "name": "Office test warehouse", "database": database, "dsn": dsn,
    }))
    access = TableAccessService(scopes, vault)
    discovery = await access.discover(token, scope, "office-test", 1)
    visible, hidden = (f"{database}.{name}" for name in ("visible_orders", "hidden_orders"))
    saved = await access.save(token, scope, "office-test", 1, discovery["discoveryId"],
                              [(database, "visible_orders"), (database, "hidden_orders")])
    await sources.publish(token, scope, "office-test", saved["draftVersion"])
    workspace = (await office.create_space(admin, "Office test team", admin.user))["id"]
    await office.set_member(admin, workspace, member.user, "viewer")
    runtime = OfficeSourceRuntime(office, vault)
    await runtime.authorize_grant(admin, "office-test", [visible, hidden])
    await office.grant_source(admin, workspace, "office-test", [visible, hidden])
    await office.limit_source_member(admin, workspace, "office-test", member.user, [visible])
    actor = await office.authenticate(await office.create_session(member))

    result = await runtime.query(actor, workspace, "office-test", f"SELECT id FROM {visible} ORDER BY id")
    assert [tuple(row) for row in result["rows"]] == [(1,), (2,)]
    with pytest.raises(ReportingError):
        await runtime.query(actor, workspace, "office-test", f"SELECT id FROM {hidden}")
    await office.grant_source(admin, workspace, "office-test", [])
    with pytest.raises(OfficeError, match="权限"):
        await runtime.query(actor, workspace, "office-test", f"SELECT id FROM {visible}")
    facts["checks"].append("Office 工作区授权、成员表收窄和撤销在真实 StarRocks 上生效")
