from __future__ import annotations

from sqlalchemy import insert, select

from .data_sources.secrets import CredentialVault
from .models import ManagementError, ManagementScope
from .repository import runtime_snapshots
from .scopes import ScopeService


class ManagedConfigurationProvider:
    def __init__(self, scope_service: ScopeService, vault: CredentialVault):
        self.scope_service = scope_service
        self.repository = scope_service.repository
        self.vault = vault

    async def register_run(
        self, run_id: str, scope: ManagementScope, *, user_id: str, thread_id: str, entrypoint: str
    ) -> None:
        """仅供服务端已核验入口调用；不注册为 HTTP 或模型工具。"""
        if entrypoint not in {"http-capability", "mcp", "cli"} or any(
            not item or len(item) > 256 for item in (run_id, user_id, thread_id)
        ):
            raise ManagementError("management_run_identity_invalid", "缺少可信报告入口身份。", 403)
        async with self.repository.transaction() as connection:
            scope_row = await ScopeService.require_registered(connection, scope)
            current = (
                (
                    await connection.execute(
                        select(runtime_snapshots).where(
                            runtime_snapshots.c.scope_id == scope_row["id"],
                            runtime_snapshots.c.run_id == run_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if current:
                if (current["user_id"], current["thread_id"], current["entrypoint"]) != (
                    user_id,
                    thread_id,
                    entrypoint,
                ):
                    raise ManagementError(
                        "management_run_identity_conflict", "运行身份与已登记记录不一致。", 403
                    )
                return
            await connection.execute(
                insert(runtime_snapshots).values(
                    scope_id=scope_row["id"],
                    run_id=run_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    entrypoint=entrypoint,
                    references=None,
                    reference_hash=None,
                    created_at=self.scope_service.auth.clock(),
                )
            )

    @staticmethod
    async def _run(connection, scope_id, run_id):
        row = (
            (
                await connection.execute(
                    select(runtime_snapshots).where(
                        runtime_snapshots.c.scope_id == scope_id,
                        runtime_snapshots.c.run_id == run_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ManagementError(
                "management_run_identity_missing", "运行尚未登记可信组织身份。", 403
            )
        return row

    async def assert_identity(
        self, run_id: str, scope: ManagementScope, *, user_id: str, thread_id: str
    ):
        async with self.repository.transaction() as connection:
            registered = await ScopeService.require_registered(connection, scope)
            row = await self._run(connection, registered["id"], run_id)
            if row["user_id"] != user_id or row["thread_id"] != thread_id:
                raise ManagementError(
                    "management_run_identity_conflict", "运行身份与已登记记录不一致。", 403
                )

    async def freeze(
        self, run_id: str, scope: ManagementScope, source_ids: tuple[str, ...] | None = None
    ):
        raise ManagementError(
            'report_contract_retired',
            '旧业务Profile执行契约已停用，请按新统计口径创建报告。',
            409,
        )

    async def load_pinned(self, scope: ManagementScope, references: dict):
        raise ManagementError(
            'report_contract_retired',
            '旧业务Profile运行不支持恢复，请按新统计口径创建报告。',
            409,
        )
