"""在宿主机用 Ruff 格式化源码，不执行脚本或读取 Workspace 配置。"""

from __future__ import annotations

import asyncio
import subprocess
import sys


async def format_python_source(source: str) -> str:
    result = await asyncio.to_thread(
        subprocess.run,
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
