from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .contracts import IsolationKind, ProviderKind


class SandboxBindingRecord(BaseModel):
    """数据库中的 workspace 与具体 Provider 资源绑定。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: ProviderKind
    isolation: IsolationKind
    node: str | None = Field(default=None, min_length=1, max_length=256)
    resource_id: str = Field(min_length=1, max_length=256)
    generation: int = Field(default=1, ge=1)
    dependency_bundle_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
