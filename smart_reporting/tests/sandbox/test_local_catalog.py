import hashlib
import json
from pathlib import Path

import pytest

from smart_reporting.sandbox.local.catalog import DependencyCatalog


def _write_catalog(tmp_path: Path) -> tuple[Path, str]:
    rootfs = tmp_path / "artifacts" / "rootfs"
    bundle = tmp_path / "artifacts" / "bundle"
    rootfs.mkdir(parents=True)
    bundle.mkdir()
    marker = bundle / "manifest.txt"
    marker.write_text("numpy==2.0\n")
    digest = "sha256:" + hashlib.sha256(marker.read_bytes()).hexdigest()
    payload = {
        "version": 1,
        "bundles": [
            {
                "profile": "ubuntu",
                "arch": "x86_64",
                "python_abi": "cp312",
                "policy": "reporting",
                "rootfs_path": str(rootfs),
                "rootfs_digest": "sha256:" + "a" * 64,
                "bundle_path": str(bundle),
                "digest": digest,
                "manifest_path": str(marker),
                "manifest_digest": digest,
                "sbom_digest": "sha256:" + "c" * 64,
                "signature": "signed",
                "modules": ["numpy", "pandas"],
            }
        ],
    }
    path = tmp_path / "artifacts" / "catalog.json"
    path.write_text(json.dumps(payload))
    return path, digest


def test_catalog_selects_exact_profile_arch_and_python_abi(tmp_path: Path) -> None:
    path, digest = _write_catalog(tmp_path)
    catalog = DependencyCatalog.load(
        path,
        artifact_root=tmp_path / "artifacts",
        verify_signature=lambda _payload, signature: signature == "signed",
    )

    bundle = catalog.resolve("ubuntu", "x86_64", "cp312", "reporting")

    assert bundle.digest == digest
    assert bundle.modules == frozenset({"numpy", "pandas"})


def test_catalog_rejects_artifact_outside_admin_root(tmp_path: Path) -> None:
    path, _digest = _write_catalog(tmp_path)
    value = json.loads(path.read_text())
    value["bundles"][0]["bundle_path"] = "/tmp/untrusted"
    path.write_text(json.dumps(value))

    with pytest.raises(ValueError, match="制品根目录"):
        DependencyCatalog.load(
            path,
            artifact_root=tmp_path / "artifacts",
            verify_signature=lambda *_args: True,
        )
