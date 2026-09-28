from __future__ import annotations

import pytest
from agno.agent import Agent
from agno.os import AgentOS
from agno.os.settings import AgnoAPISettings
from dingyi_agno.process import ProcessJournal, ProcessPublisher
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from smart_reporting.integrations.dingyi_process import DingyiProcessAdapter, mount_process_routes

PREFIX = "/extensions/dingyi/process/v1"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    monkeypatch.delenv("JWT_JWKS_FILE", raising=False)
    engine = create_engine(f"sqlite:///{tmp_path / 'process.db'}")
    journal = ProcessJournal(engine=engine)
    for owner, operation_id in (("smart-reporting", "report-op"), ("other-service", "other-op")):
        ProcessPublisher(
            journal, owner=owner, session_id="thread-a", run_id="run-1",
            component={"type": "agent", "id": "smart-reporting"},
            title="生成报告", operation_id=operation_id, execution="foreground",
        ).start()
    base = FastAPI()
    mount_process_routes(base, DingyiProcessAdapter(engine))
    agent_os = AgentOS(
        agents=[Agent(id="smart-reporting")], base_app=base,
        on_route_conflict="preserve_base_app", telemetry=False,
        settings=AgnoAPISettings(os_security_key="console-test-key"),
    )
    try:
        with TestClient(agent_os.get_app()) as test_client:
            yield test_client
    finally:
        engine.dispose()


@pytest.mark.parametrize("path", ["/capabilities", "/sessions/thread-a/operations", "/operations/report-op"])
def test_process_accepts_agentos_bearer_without_workspace_capability(client, path):
    response = client.get(PREFIX + path, headers={"Authorization": "Bearer console-test-key"})

    assert response.status_code == 200


@pytest.mark.parametrize("authorization", [None, "Bearer incorrect"])
@pytest.mark.parametrize("path", ["/capabilities", "/sessions/thread-a/operations", "/operations/report-op", "/operations/report-op/events"])
def test_process_rejects_missing_or_invalid_agentos_bearer(client, path, authorization):
    headers = {"Authorization": authorization} if authorization else {}

    assert client.get(PREFIX + path, headers=headers).status_code == 401


def test_process_limits_service_bearer_to_reporting_owner(client):
    headers = {"Authorization": "Bearer console-test-key"}
    response = client.get(PREFIX + "/sessions/thread-a/operations", headers=headers)

    assert response.status_code == 200
    assert [item["operationId"] for item in response.json()["items"]] == ["report-op"]
    assert client.get(PREFIX + "/operations/other-op", headers=headers).status_code == 404
    assert client.get(PREFIX + "/sessions/thread-b/operations", headers=headers).json()["items"] == []
