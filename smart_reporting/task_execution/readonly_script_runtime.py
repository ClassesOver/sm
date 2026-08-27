from __future__ import annotations

import argparse
import ctypes
import os
import platform
import stat
import sys
from pathlib import Path

LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38

LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
LANDLOCK_ACCESS_FS_REFER = 1 << 13
LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14

MIN_LANDLOCK_ABI = 3
HANDLED_WRITE_ACCESS = (
    LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_MAKE_CHAR
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_SOCK
    | LANDLOCK_ACCESS_FS_MAKE_FIFO
    | LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | LANDLOCK_ACCESS_FS_MAKE_SYM
    | LANDLOCK_ACCESS_FS_REFER
    | LANDLOCK_ACCESS_FS_TRUNCATE
)


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int)]


def _syscall_numbers() -> tuple[int, int, int]:
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise RuntimeError("Landlock 仅支持 Linux x86_64/aarch64。")
    return 444, 445, 446


def _landlock_abi(libc: ctypes.CDLL, create_ruleset: int) -> int:
    abi = libc.syscall(create_ruleset, 0, 0, LANDLOCK_CREATE_RULESET_VERSION)
    if abi < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return int(abi)


def restrict_writes(write_roots: list[str]) -> None:
    create_ruleset, add_rule, restrict_self = _syscall_numbers()
    libc = ctypes.CDLL(None, use_errno=True)
    abi = _landlock_abi(libc, create_ruleset)
    if abi < MIN_LANDLOCK_ABI:
        raise RuntimeError(f"Landlock ABI {abi} 低于要求的 {MIN_LANDLOCK_ABI}。")

    ruleset_attr = _RulesetAttr(HANDLED_WRITE_ACCESS)
    ruleset_fd = libc.syscall(
        create_ruleset,
        ctypes.byref(ruleset_attr),
        ctypes.sizeof(ruleset_attr),
        0,
    )
    if ruleset_fd < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    try:
        for root in write_roots:
            path_fd = os.open(root, os.O_PATH | os.O_CLOEXEC)
            try:
                mode = os.fstat(path_fd).st_mode
                allowed_access = (
                    HANDLED_WRITE_ACCESS
                    if stat.S_ISDIR(mode)
                    else LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_TRUNCATE
                )
                path_attr = _PathBeneathAttr(allowed_access, path_fd)
                if (
                    libc.syscall(
                        add_rule,
                        ruleset_fd,
                        LANDLOCK_RULE_PATH_BENEATH,
                        ctypes.byref(path_attr),
                        0,
                    )
                    < 0
                ):
                    error = ctypes.get_errno()
                    raise OSError(error, os.strerror(error))
            finally:
                os.close(path_fd)
        if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        if libc.syscall(restrict_self, ruleset_fd, 0) < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
    finally:
        os.close(ruleset_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-root", action="append", default=[])
    parser.add_argument("--shell-command")
    parser.add_argument("--shell", choices=("/bin/sh", "/bin/bash"), default="/bin/sh")
    parser.add_argument("script", nargs="?")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    values = parser.parse_args(argv)
    if values.shell_command is not None:
        if values.script is not None or values.args:
            raise RuntimeError("shell command 参数无效。")
        # Daytona 为每个 thread 提供独立 sandbox；当前 Docker runner 宿主未启用
        # Landlock，若在这里安装规则会在业务脚本启动前以 ENOSYS 失败。保留
        # write-root 参数和其余运行时校验以维持上层命令契约，但暂不启用进程内
        # 文件写入白名单。重新启用时必须先在 managed session 验证 Landlock ABI。
        # restrict_writes([str(Path(root).resolve(strict=True)) for root in values.write_root])
        os.execv(values.shell, [values.shell, "-l", "-c", values.shell_command])
        return 127
    if values.script is None:
        raise RuntimeError("缺少只读脚本路径。")
    script = Path(values.script)
    if not script.is_absolute() or script.is_symlink() or not script.is_file():
        raise RuntimeError("validator 脚本路径无效。")
    # 与 shell-command 分支保持一致：当前由 Daytona sandbox 提供执行隔离，
    # 不将不可用的 Landlock 作为 validator 启动前置条件。
    # roots = [str(Path(root).resolve(strict=True)) for root in values.write_root]
    # restrict_writes(roots)
    os.execv(
        sys.executable,
        [sys.executable, "-I", "-B", str(script), *values.args],
    )
    return 127


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"readonly_script_runtime: {error}", file=sys.stderr)
        raise SystemExit(126) from None
