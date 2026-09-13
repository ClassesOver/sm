"""Validate the final AgentOS HTTP surface, including lazy FastAPI routers."""
import warnings

import pytest
from agno.agent import Agent
from agno.os import AgentOS
from agno.os.config import MCPServerConfig
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from smart_reporting.integrations.dingyi_process import DingyiProcessAdapter, mount_process_routes


@pytest.mark.parametrize("deferred", [False, True])
def test_process_router_survives_agentos_without_duplicate_mounts(tmp_path, deferred):
    class Adapter(DingyiProcessAdapter):
        unavailable = deferred

        def _ensure_journal(self):
            if self.unavailable:
                self.unavailable = False
                raise RuntimeError("database not ready yet")
            return super()._ensure_journal()

    adapter = Adapter(create_engine(f"sqlite:///{tmp_path / 'routes.db'}"))
    base = FastAPI()
    mount_process_routes(base, adapter)

    def ping() -> str:
        """Return a local MCP health response."""
        return "pong"

    os = AgentOS(agents=[Agent(id="test-agent")], base_app=base,
                 on_route_conflict="preserve_base_app", telemetry=False,
                 mcp_server=MCPServerConfig(default_tools=False, tools=[ping], allowed_hosts=[
                     "localhost", "127.0.0.1", "host.docker.internal",
                 ]))
    app = os.get_app()
    with TestClient(app) as client:
        for host in ("localhost", "127.0.0.1", "host.docker.internal"):
            response = client.get("/extensions/dingyi/process/v1/capabilities", headers={"Host": host})
            assert response.status_code == 200
            assert response.json()["protocol"] == "dingyi.process.v1"
        with warnings.catch_warnings(record=True) as emitted:
            warnings.simplefilter("always")
            app.openapi_schema = None
            schema = app.openapi()
        assert "/extensions/dingyi/process/v1/capabilities" in schema["paths"]
        assert not [w for w in emitted if "Duplicate Operation ID" in str(w.message)]
