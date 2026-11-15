"""Opt-in transport check using original DSH and a local synthetic model."""

import json
import os
import shutil
import threading
import time
from contextlib import AsyncExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.report_acp_client import ReportAcpClient
from smart_reporting.report_channel_acp import ReportChannelAcp
from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router
from smart_reporting.report_channel_invitation import Invitation
from smart_reporting.report_channel_repository import ReportChannelRepository


@pytest.fixture
def anyio_backend():
    return "asyncio"


def dsh_command(configured_bin: str) -> tuple[str, ...]:
    node = os.getenv("REPORT_ACP_TEST_NODE") or shutil.which("node")
    assert node
    loader = os.getenv("REPORT_ACP_TEST_NODE_LOADER")
    entry = Path(configured_bin).resolve(strict=True)
    return (*((loader,) if loader else ()), node, str(entry), "acp")


@pytest.mark.anyio
async def test_original_dsh_live_model_retains_synthetic_context_after_resume(tmp_path):
    configured_home = os.getenv("REPORT_ACP_LIVE_DSH_HOME")
    configured_bin = os.getenv("REPORT_ACP_TEST_DSH_BIN")
    if not configured_home or not configured_bin:
        pytest.skip("Set REPORT_ACP_LIVE_DSH_HOME and REPORT_ACP_TEST_DSH_BIN for live-model acceptance")
    dsh_home = Path(configured_home).resolve(strict=True)
    assert dsh_home.is_dir()
    env = dict(os.environ, DSH_HOME=str(dsh_home))
    command = dsh_command(configured_bin)
    marker = f"SYNTH-{uuid4().hex[:12]}"
    async with ReportAcpClient(command, tmp_path, env=env, timeout=60) as client:
        session = await client.open_session()
        answer = await client.prompt(
            f"The synthetic report reference is {marker}. Reply with only this reference."
        )
        assert answer.strip() == marker
    async with ReportAcpClient(command, tmp_path, env=env, timeout=60) as client:
        await client.open_session(resume=session)
        answer = await client.prompt("What was the synthetic report reference? Reply with only the reference.")
        assert answer.strip() == marker


@pytest.mark.anyio
@pytest.mark.parametrize("durable", [False, pytest.param(True, marks=pytest.mark.integration)])
async def test_report_invitation_round_trips_through_original_dsh(tmp_path, durable):
    configured_bin = os.getenv("REPORT_ACP_TEST_DSH_BIN")
    if not configured_bin:
        pytest.skip("Set REPORT_ACP_TEST_DSH_BIN to the original DSH Node entry")
    db_url = os.getenv("REPORTING_TEST_DB_URL")
    if durable and not db_url:
        pytest.skip("Requires the disposable PostgreSQL test database")
    command = dsh_command(configured_bin)
    model_history = []
    prepared_instruction = "Clarify the count of 12 books without changing the facts."

    class LocalModel(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if not self.path.endswith("/messages"):
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            model_history.append(body["messages"])
            reply = ("12", "books", prepared_instruction)[len(model_history) - 1]
            message = dict(id="msg_synthetic", type="message", role="assistant",
                           model=body["model"], content=[], stop_reason=None,
                           stop_sequence=None, usage=dict(input_tokens=5, output_tokens=0))
            events = [
                dict(type="message_start", message=message),
                dict(type="content_block_start", index=0, content_block=dict(type="text", text="")),
                dict(type="content_block_delta", index=0, delta=dict(type="text_delta", text=reply)),
                dict(type="content_block_stop", index=0),
                dict(type="message_delta", delta=dict(stop_reason="end_turn", stop_sequence=None),
                     usage=dict(output_tokens=1)),
                dict(type="message_stop"),
            ]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for event in events:
                self.wfile.write(
                    (f"event: {event['type']}\ndata: {json.dumps(event)}\n\n").encode()
                )

    identity = ConnectorIdentity("dsh", "synthetic", "synthetic-session")
    channel = uuid4().hex if durable else "report-a"
    references = ("A" * 43, "B" * 43) if not durable else tuple(
        f"{uuid4().hex}{uuid4().hex[:11]}" for _ in range(2)
    )

    class Grants:
        active = False
        async def exchange(self, reference, **claims):
            assert reference in references and claims["subject"] == identity.subject
            self.active = True
            return SimpleNamespace(channel="report-a")

        async def member_grant(self, channel, member):
            return "synthetic-grant" if self.active and channel == "report-a" and member == identity else None

        async def has_member(self, channel, member):
            return await self.member_grant(channel, member) is not None

    async def auth(request):
        return identity if request.headers.get("authorization") == "Bearer synthetic" else None

    async def delegate(channel, caller, payload):
        assert caller == identity and payload.request_id == "word-1"
        assert payload.instruction == prepared_instruction
        return {"taskId": "synthetic-candidate", "status": "running"}

    engine = create_async_engine(db_url) if durable else None
    grants = ReportChannelRepository(engine) if engine is not None else Grants()
    with ThreadingHTTPServer(("127.0.0.1", 0), LocalModel) as model:
        thread = threading.Thread(target=model.serve_forever, daemon=True)
        thread.start()
        env = dict(os.environ, DSH_HOME=str(tmp_path / "profile"),
                   DEEPSEEK_API_KEY="synthetic-local-only",
                   DEEPSEEK_BASE_URL=f"http://127.0.0.1:{model.server_port}")

        def client():
            return ReportAcpClient(command, tmp_path, env=env)

        def host():
            repository = ReportChannelRepository(engine) if engine is not None else grants
            app = FastAPI()
            app.include_router(create_report_channel_router(
                repository, auth, acp=ReportChannelAcp(repository, client, durable=durable),
                delegate_word=delegate,
            ))
            return AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test",
                               headers={"authorization": "Bearer synthetic"})

        try:
            if engine is not None:
                await grants.create_schema()
                for reference in references:
                    await grants.issue(reference, Invitation(
                        channel, identity.connector, identity.subject, time.time() + 120,
                    ))
            async with AsyncExitStack() as stack:
                http = await stack.enter_async_context(host())
                joined = await http.post("/reports/v1/channels/invitations/exchange",
                                         json={"reference": references[0]})
                receipt = joined.raise_for_status().json()
                path = receipt["acpMessagesPath"]
                for prompt, reply in [("Synthetic report counted 12 books.", "12"),
                                      ("What item was counted?", "books")]:
                    payload = {"message_id": f"turn-{reply}", "text": prompt}
                    response = await http.post(path, json=payload)
                    assert response.raise_for_status().json() == {"reply": reply}
                    if reply == "12":
                        if durable:
                            await http.aclose()
                            http = await stack.enter_async_context(host())
                            replay_after_restart = await http.post(path, json=payload)
                            assert replay_after_restart.raise_for_status().json() == {"reply": reply}
                        rejoined = await http.post("/reports/v1/channels/invitations/exchange",
                                                   json={"reference": references[1]})
                        assert rejoined.raise_for_status().json()["acpMessagesPath"] == path
                    replay = await http.post(path, json=payload)
                    assert replay.raise_for_status().json() == {"reply": reply}
                    conflict = await http.post(path, json={**payload, "text": "Different text"})
                    assert conflict.status_code == 409
                word = {"request_id": "word-1", "instruction": "Make the conclusion clearer.",
                        "prepare_with_acp": True}
                for _ in range(2):
                    task = await http.post(receipt["wordTasksPath"], json=word)
                    assert task.raise_for_status().json() == {
                        "taskId": "synthetic-candidate", "status": "running",
                    }
                conflict = await http.post(receipt["wordTasksPath"], json={
                    **word, "instruction": "Change the introduction.",
                })
                assert conflict.status_code == 409
                if engine is not None:
                    await grants.revoke(channel, connector=identity.connector, subject=identity.subject)
                else:
                    grants.active = False
                assert (await http.post(path, json=payload)).status_code == 403
                assert (await http.post(receipt["wordTasksPath"], json=word)).status_code == 403
                assert len(model_history) == 3
                assert "12 books" in json.dumps(model_history[1])
                assert "What item was counted?" in json.dumps(model_history[2])
        finally:
            model.shutdown()
            thread.join()
            if engine is not None:
                try:
                    await grants.revoke(channel, connector=identity.connector, subject=identity.subject)
                finally:
                    await engine.dispose()
