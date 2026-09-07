from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class DependencyBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: str = Field(pattern=r"^(ubuntu|openeuler)$")
    arch: str = Field(min_length=1, max_length=32)
    python_abi: str = Field(pattern=r"^cp[0-9]{3}$")
    policy: str = Field(min_length=1, max_length=64)
    rootfs_path: Path
    rootfs_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    bundle_path: Path
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    manifest_path: Path
    manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sbom_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    signature: str = Field(min_length=1, max_length=16_384)
    modules: frozenset[str] = frozenset()


class _CatalogDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    bundles: list[DependencyBundle] = Field(min_length=1)


class DependencyCatalog:
    def __init__(self, bundles: tuple[DependencyBundle, ...]) -> None:
        self._bundles = bundles

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        artifact_root: Path,
        verify_signature: Callable[[bytes, str], bool],
    ) -> DependencyCatalog:
        root = artifact_root.resolve(strict=True)
        if path.is_symlink():
            raise ValueError("catalog 不能是符号链接")
        raw = json.loads(path.read_text(encoding="utf-8"))
        document = _CatalogDocument.model_validate(raw)
        for bundle in document.bundles:
            for artifact in (bundle.rootfs_path, bundle.bundle_path, bundle.manifest_path):
                if artifact.is_symlink():
                    raise ValueError("sandbox 制品不能是符号链接")
                if not artifact.resolve(strict=False).is_relative_to(root):
                    raise ValueError("sandbox 制品必须位于管理员制品根目录")
                artifact.resolve(strict=True)
            actual = "sha256:" + hashlib.sha256(bundle.manifest_path.read_bytes()).hexdigest()
            if actual != bundle.manifest_digest or actual != bundle.digest:
                raise ValueError("dependency bundle digest 不匹配")
            signed = bundle.model_dump(mode="json", exclude={"signature"})
            payload = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode()
            if not verify_signature(payload, bundle.signature):
                raise ValueError("dependency bundle 签名无效")
        return cls(tuple(document.bundles))

    def resolve(self, profile: str, arch: str, python_abi: str, policy: str) -> DependencyBundle:
        matches = [
            bundle
            for bundle in self._bundles
            if (bundle.profile, bundle.arch, bundle.python_abi, bundle.policy)
            == (profile, arch, python_abi, policy)
        ]
        if len(matches) != 1:
            raise ValueError("离线依赖目录没有唯一匹配的 bundle")
        return matches[0]
