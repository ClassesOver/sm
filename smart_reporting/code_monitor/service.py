"""独立 SUB 连接，不复用 agent 的客户端、不持有 kernel 生命周期。"""

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from queue import Empty
from typing import Any

from loguru import logger

from .state import KernelState

SUBSCRIPTION_READY_TIMEOUT = 5


@dataclass(frozen=True)
class Target:
    id: str
    label: str
    connection: dict[str, Any] = field(repr=False)
    generation: str = "1"
    busy: bool | None = None


class CodeMonitor:
    def __init__(self, *, log_streams: bool = False) -> None:
        self.log_streams = log_streams
        self.sources: list[Callable[[], Awaitable[list[Target]]]] = []
        self.states: OrderedDict[str, KernelState] = OrderedDict()
        self.clients: dict[str, Any] = {}
        self._readers: dict[str, asyncio.Task] = {}
        self._generations: dict[str, str] = {}
        self.source_error = False

    async def run(self) -> None:
        try:
            while True:
                targets: list[Target] = []
                try:
                    for source in self.sources:
                        targets.extend(await source())
                    self.source_error = False
                    await self.reconcile(targets)
                except Exception as error:
                    if not self.source_error:
                        logger.warning("code_monitor_discovery_failed error_type={}",
                                       type(error).__name__)
                    self.source_error = True
                await asyncio.sleep(0.25)
        finally:
            await self.aclose()

    async def reconcile(self, targets: list[Target], *, wait_for_ready: bool = False) -> None:
        wanted = {target.id: target for target in targets}
        for kernel_id in list(self.clients):
            target = wanted.get(kernel_id)
            if (target is None or target.generation != self._generations[kernel_id]
                    or self._readers[kernel_id].done()):
                await self._detach(kernel_id)
                self.states[kernel_id].disconnected("kernel 已移除或重启；旧执行结果未知。")
        for target in targets[:50]:
            if target.id in self.clients:
                continue
            # 延迟导入：尚未使用 CodeMode 时不会创建 ZMQ context。
            from jupyter_client import AsyncKernelClient

            client = AsyncKernelClient()
            try:
                client.load_connection_info(target.connection)
                client.start_channels(shell=wait_for_ready, iopub=True, stdin=False,
                                      hb=wait_for_ready, control=False)
                if wait_for_ready:
                    # 宿主执行前用 kernel_info 确认订阅就绪，不执行代码。
                    # 浏览器被动监控保持默认，不发送任何请求。
                    # jupyter_client 清空 IOPub 阶段不检查内部 timeout。
                    async with asyncio.timeout(SUBSCRIPTION_READY_TIMEOUT):
                        await client.wait_for_ready(timeout=SUBSCRIPTION_READY_TIMEOUT)
                    client.shell_channel.stop()
                    client.hb_channel.stop()
            except Exception as error:
                client.stop_channels()
                logger.warning(
                    "code_monitor_attach_failed kernel_id={} error_type={}",
                    target.id, type(error).__name__,
                )
                continue
            except BaseException:
                client.stop_channels()
                raise
            state = KernelState(target.id, target.label)
            if target.id in self.states:
                state.notice = "kernel 已重新连接，旧代执行记录已清除。"
            if target.busy:
                state.status = "busy"
                state.notice += " 接入时会话正在执行；此前代码和输出无法回放。"
            self.states[target.id] = state
            self.states.move_to_end(target.id)
            self.clients[target.id] = client
            self._generations[target.id] = target.generation
            self._readers[target.id] = asyncio.create_task(self._read(target.id, client))
        for kernel_id in list(self.states):
            if len(self.states) <= 50:
                break
            if kernel_id not in self.clients:
                del self.states[kernel_id]

    async def _read(self, kernel_id: str, client: Any) -> None:
        try:
            while True:
                try:
                    message = await client.get_iopub_msg(timeout=1)
                except (Empty, asyncio.TimeoutError):
                    continue
                self.states[kernel_id].accept(message)
                if self.log_streams and message.get("header", {}).get("msg_type") == "stream":
                    content = message.get("content", {})
                    if content.get("text"):
                        logger.info(
                            "report_code_mode_stream session_id={} call_id={} name={} output={}",
                            self.states[kernel_id].label,
                            message.get("parent_header", {}).get("msg_id", ""),
                            content.get("name", "stdout"), content["text"].rstrip("\n"),
                        )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.states[kernel_id].disconnected("订阅中断，等待重新连接。")
            logger.warning("code_monitor_subscription_failed error_type={}",
                           type(error).__name__)
        finally:
            client.stop_channels()

    async def _detach(self, kernel_id: str) -> None:
        task = self._readers.pop(kernel_id)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.clients.pop(kernel_id).stop_channels()
        self._generations.pop(kernel_id, None)

    async def aclose(self) -> None:
        for kernel_id in list(self.clients):
            await self._detach(kernel_id)
            self.states[kernel_id].disconnected("监控已停止；未关闭 kernel。")

    def snapshot(self) -> dict[str, Any]:
        return {"kernels": [state.snapshot() for state in self.states.values()],
                "source_error": self.source_error}
