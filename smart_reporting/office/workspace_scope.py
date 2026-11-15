"""工作区隔离作用域：host workspace registry 解析专属目录所需的已签名身份。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceScope:
    run_id: str
    external_run_id: str
    session_id: str
    caller_thread_id: str
    user_id: str
    database: str
    company_id: str
    thread_lease_key: str
    workspace_key: str

    def as_state(self) -> dict[str, str]:
        return {
            "externalRunId": self.external_run_id,
            "sessionId": self.session_id,
            "threadId": self.workspace_key,
            "callerThreadId": self.caller_thread_id,
            "userId": self.user_id,
            "database": self.database,
            "companyId": self.company_id,
            "threadLeaseKey": self.thread_lease_key,
        }


__all__ = ["WorkspaceScope"]
