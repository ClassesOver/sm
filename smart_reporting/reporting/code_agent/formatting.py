"""在宿主机用 Ruff 格式化源码，不执行脚本或读取 Workspace 配置。"""

from __future__ import annotations

import asyncio
import subprocess
import sys


async def format_python_source(source: str) -> str:
    return await asyncio.to_thread(format_python_source_sync, source)


def format_python_source_sync(source: str) -> str:
    """供离线证明核验复用与真实 write_script 完全相同的宿主格式化规则。"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "ruff",
            "format",
            "--isolated",
            "--no-cache",
            "--target-version",
            "py312",
            "--line-length",
            "100",
            "--stdin-filename",
            "script.py",
            "-",
        ],
        input=source,
        capture_output=True,
        encoding="utf-8",
        check=True,
        timeout=5,
    )
    return result.stdout
