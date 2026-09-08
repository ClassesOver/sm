from __future__ import annotations

from importlib import import_module
from typing import Any

from ..runtime.settings import AgentSettings
from .daytona import DaytonaProvider


def create_sandbox_provider(
    settings: AgentSettings,
    *,
    registry: Any,
    daytona_client: Any | None = None,
) -> Any:
    secret = settings.workspace_hmac_secret.encode("utf-8")
    if settings.sandbox_provider == "daytona":
        return DaytonaProvider(
            client=daytona_client,
            registry=registry,
            snapshot=settings.workspace_snapshot,
            binding_secret=secret,
            network_allow_list=settings.daytona_network_allow_list,
        )

    # 延迟导入使 Daytona 部署不加载 Local 控制面依赖；Local 配置已经在 settings 阶段
    # 完整校验，模块缺失属于部署错误，不能静默回退到 Daytona。
    module = import_module("smart_reporting.sandbox.local.client")
    provider_type = getattr(module, "LocalProvider")
    return provider_type.from_settings(settings, registry=registry, binding_secret=secret)
