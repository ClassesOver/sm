import asyncio
import importlib.util

import pytest


@pytest.mark.parametrize("failure", ["timeout", "error", "cancel"])
def test_subscription_failure_is_bounded_and_isolated(monkeypatch, failure):
    from types import SimpleNamespace

    import jupyter_client

    from smart_reporting.code_monitor import service

    clients = []

    class Client:
        def __init__(self):
            self.stopped = False
            self.shell_channel = self.hb_channel = SimpleNamespace(stop=lambda: None)
            clients.append(self)

        def load_connection_info(self, connection):
            self.bad = connection["bad"]

        def start_channels(self, **kwargs):
            pass

        async def wait_for_ready(self, timeout):
            if self.bad:
                if failure == "timeout":
                    await asyncio.Event().wait()  # 模拟内部 timeout 无法约束的清空阶段。
                elif failure == "cancel":
                    raise asyncio.CancelledError
                else:
                    raise RuntimeError("disconnected")

        async def get_iopub_msg(self, timeout):
            await asyncio.Event().wait()

        def stop_channels(self):
            self.stopped = True

    monkeypatch.setattr(jupyter_client, "AsyncKernelClient", Client)
    monkeypatch.setattr(service, "SUBSCRIPTION_READY_TIMEOUT", 0.02, raising=False)

    async def scenario():
        monitor = service.CodeMonitor()
        targets = [service.Target("bad", "bad", {"bad": True}),
                   service.Target("good", "good", {"bad": False})]
        try:
            if failure == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await monitor.reconcile(targets, wait_for_ready=True)
                assert len(clients) == 1
            else:
                await asyncio.wait_for(monitor.reconcile(targets, wait_for_ready=True), 0.5)
                assert set(monitor.clients) == {"good"}
            assert clients[0].stopped
        finally:
            await monitor.aclose()

    asyncio.run(scenario())


def message(kind, parent="cell-1", **content):
    return {"header": {"msg_type": kind}, "parent_header": {"msg_id": parent},
            "content": content}


def test_monitor_package_exists():
    assert importlib.util.find_spec("smart_reporting.code_monitor") is not None


def test_running_cell_stream_error_and_idle():
    from smart_reporting.code_monitor.state import KernelState

    state = KernelState("session-a", "报表分析")
    state.accept(message("status", execution_state="busy"))
    state.accept(message("execute_input", code="print('你好')", execution_count=1))
    state.accept(message("stream", name="stdout", text="你好\n"))
    snapshot = state.snapshot()
    assert snapshot["status"] == "busy"
    assert snapshot["cells"][0]["code"] == "print('你好')"
    assert snapshot["cells"][0]["output"] == "你好\n"
    assert snapshot["cells"][0]["finished_at"] is None
    state.accept(message("error", traceback=["ValueError: failed"]))
    state.accept(message("status", execution_state="idle"))
    assert state.snapshot()["cells"][0]["status"] == "error"
    assert state.snapshot()["cells"][0]["finished_at"] is not None


def test_late_attach_keeps_orphan_output_and_bounds_history():
    from smart_reporting.code_monitor.state import KernelState

    state = KernelState("a", "a")
    state.accept(message("stream", text="still working", name="stdout"))
    assert state.snapshot()["cells"][0]["code"] is None
    assert state.snapshot()["cells"][0]["output"] == "still working"
    for index in range(40):
        state.accept(message("execute_input", parent=str(index), code="x"))
        state.accept(message("stream", parent=str(index), text="a" * 100_000))
        state.accept(message("status", parent=str(index), execution_state="idle"))
    cells = state.snapshot()["cells"]
    assert len(cells) <= 30
    assert len(cells[-1]["output"]) <= 65536
    assert cells[-1]["truncated"]


def test_internal_comm_and_silent_status_do_not_create_user_cells():
    from smart_reporting.code_monitor.state import KernelState

    state = KernelState("a", "a")
    state.accept(message("comm_msg", data={"secret": "private"}))
    state.accept(message("status", execution_state="busy"))
    state.accept(message("status", execution_state="idle"))
    assert state.snapshot()["cells"] == []
    assert "private" not in str(state.snapshot())


def test_real_kernel_monitor_is_passive_and_does_not_shutdown(monkeypatch):
    from jupyter_client import AsyncKernelManager
    from jupyter_client.session import Session

    from smart_reporting.code_monitor.service import CodeMonitor, Target

    async def scenario():
        km = AsyncKernelManager()
        await km.start_kernel()
        owner = km.client()
        owner.start_channels()
        monitor = CodeMonitor()
        try:
            await owner.wait_for_ready(timeout=20)
            target = Target("test", "测试", km.get_connection_info(), "1")
            await monitor.reconcile([target])
            # SUB 建立异步握手；监控端不允许用 kernel_info 请求探测就绪。
            await asyncio.sleep(0.3)
            subscriber = monitor.clients["test"]
            # 公共属性会懒创建 socket；检查字段避免测试自己打开通道。
            assert subscriber._shell_channel is None
            assert subscriber._control_channel is None
            assert subscriber._stdin_channel is None
            assert subscriber._hb_channel is None
            original_send = Session.send

            def guard_send(session, *args, **kwargs):
                assert session is not subscriber.session, "monitor sent a kernel request"
                return original_send(session, *args, **kwargs)

            monkeypatch.setattr(Session, "send", guard_send)
            owner.execute("import time\nprint('working', flush=True)\ntime.sleep(1)\n42")
            async with asyncio.timeout(10):
                while not monitor.snapshot()["kernels"][0]["cells"]:
                    await asyncio.sleep(0.02)
                assert monitor.snapshot()["kernels"][0]["status"] == "busy"
                while monitor.snapshot()["kernels"][0]["status"] != "idle":
                    await asyncio.sleep(0.02)
            cell = monitor.snapshot()["kernels"][0]["cells"][0]
            assert "working" in cell["output"] and "42" in cell["output"]
            await monitor.aclose()
            assert await km.is_alive()
            request = owner.execute("21*2")
            async with asyncio.timeout(10):
                while True:
                    reply = await owner.get_shell_msg(timeout=5)
                    if reply.get("parent_header", {}).get("msg_id") == request:
                        assert reply["content"]["status"] == "ok"
                        break
        finally:
            await monitor.aclose()
            owner.stop_channels()
            await km.shutdown_kernel(now=True)

    asyncio.run(scenario())
