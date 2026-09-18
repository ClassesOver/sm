"""Agno 兼容边界：只在所属事件循环中读取 CodeMode 注册表。

不修改/替换任何方法，不启动 kernel，不调用 execute、variables 或 value。
升级 Agno 时只需复核本模块及真实 CodeMode 集成测试。
"""

import asyncio
from typing import Any

from .service import Target


class CodeModeSource:
    def __init__(self, *owners: Any) -> None:
        self.owners = list(owners)

    def register(self, code_mode: Any) -> None:
        """供工作流在自己的装配层显式注册动态创建的实例。"""
        if not any(owner is code_mode for owner in self.owners):
            self.owners.append(code_mode)

    def _modes(self) -> list[Any]:
        pending = list(self.owners)
        seen: set[int] = set()
        modes = []
        while pending:
            owner = pending.pop()
            if id(owner) in seen:
                continue
            seen.add(id(owner))
            if any(cls.__name__ == "CodeMode" and cls.__module__.startswith("agno.tools.code")
                   for cls in type(owner).__mro__):
                modes.append(owner)
                continue
            # 仅遍历公开装配字段，不扫描任意对象图。
            for name in ("tools", "members", "steps", "agent", "team"):
                value = getattr(owner, name, None)
                if isinstance(value, (list, tuple)):
                    pending.extend(value)
                elif value is not None and not callable(value):
                    pending.append(value)
        return modes

    @staticmethod
    async def _snapshot(mode: Any) -> list[Target]:
        targets = []
        for session_id, session in mode._sessions.items():
            if session.km is None or session.kc is None:
                continue
            connection = session.km.get_connection_info()
            targets.append(Target(
                id=f"{id(mode):x}:{session_id}", label=str(session_id),
                connection=connection,
                generation=f"{session.generation}:{session.km.connection_file}",
                busy=session.lock.locked(),
            ))
        return targets

    async def __call__(self) -> list[Target]:
        targets = []
        for mode in self._modes():
            runner = mode._runner
            if not runner.started:
                continue
            future = asyncio.wrap_future(runner.submit(self._snapshot(mode)))
            targets.extend(await asyncio.wait_for(future, timeout=2))
        return targets
