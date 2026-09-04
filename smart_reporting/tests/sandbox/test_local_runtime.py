from pathlib import Path

from smart_reporting.sandbox.local.runtime import LaunchPolicy, build_python_argv


def test_runtime_builds_fixed_offline_python_argv(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    bundle = tmp_path / "bundle"
    workspace = tmp_path / "workspace"
    seccomp = tmp_path / "seccomp.bpf"
    for directory in (rootfs, bundle, workspace):
        directory.mkdir()
    seccomp.write_bytes(b"policy")

    argv = build_python_argv(
        LaunchPolicy(
            bwrap="/usr/bin/bwrap",
            rootfs=rootfs,
            bundle=bundle,
            workspace=workspace,
            seccomp=seccomp,
        ),
        "jobs/script.py",
    )

    assert "--unshare-net" in argv
    assert ("--ro-bind", str(rootfs), "/") == argv[
        argv.index("--ro-bind") : argv.index("--ro-bind") + 3
    ]
    assert argv[-4:] == ("/usr/bin/python3", "-I", "-B", "/workspace/jobs/script.py")
    assert "python" not in " ".join(argv[:-4])
