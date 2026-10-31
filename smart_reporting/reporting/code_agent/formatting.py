"""在宿主机用 Ruff 格式化源码，不执行脚本或读取 Workspace 配置。"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from functools import lru_cache


async def format_python_source(source: str) -> str:
    return await asyncio.to_thread(format_python_source_sync, source)


@lru_cache(maxsize=1)
def _ruff_command() -> tuple[str, ...]:
    """直接调用 ruff 二进制，省去每次 write_script 先启动一个 Python 解释器。"""
    try:
        from ruff.__main__ import find_ruff_bin

        return (str(find_ruff_bin()),)
    except Exception:
        return (sys.executable, "-I", "-m", "ruff")


def format_python_source_sync(source: str) -> str:
    """供离线证明核验复用与真实 write_script 完全相同的宿主格式化规则。"""
    result = subprocess.run(
        [
            *_ruff_command(),
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
