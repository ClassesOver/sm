from fastapi.testclient import TestClient

from agentos_dev.app import app


def test_public_config_and_protected_routes():
    client = TestClient(app)

    config = client.get("/config")
    assert config.status_code == 200
    assert set(config.json()) == {
        "protocol", "bundle_version", "command_catalog_hash", "skills",
    }

    workspace = client.get(
        "/workspace/files",
        params={"threadId": "thread-1"},
        headers={"X-AGUI-Thread": "thread-1"},
    )
    assert workspace.status_code == 401

    run = client.post(
        "/agui",
        json={"threadId": "body-thread"},
        headers={"X-AGUI-Thread": "header-thread"},
    )
    assert run.status_code == 403
    assert run.json() == {"error": "capability_thread_mismatch"}
