from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalProviderConfig:
    profile: str
    endpoint: str
    rootfs_digest: str
    ca_cert: str | None = None
    client_cert: str | None = None
    client_key: str | None = None
    request_timeout: float = 65.0

    @classmethod
    def from_settings(cls, settings: object) -> LocalProviderConfig:
        profile = getattr(settings, "sandbox_local_profile", None)
        endpoint = getattr(settings, "sandbox_local_endpoint", None)
        digest = getattr(settings, "sandbox_rootfs_digest", None)
        if not profile or not endpoint or not digest:
            raise ValueError("LocalProvider 配置不完整。")
        return cls(
            profile=profile,
            endpoint=endpoint,
            rootfs_digest=digest,
            ca_cert=getattr(settings, "sandbox_local_ca_cert", None),
            client_cert=getattr(settings, "sandbox_local_client_cert", None),
            client_key=getattr(settings, "sandbox_local_client_key", None),
        )
