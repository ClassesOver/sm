#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${AGENTOS_PYTHON:-${repo_root}/.venv/bin/python}"

cd "${repo_root}"
"${python_bin}" -c '
import sys

if sys.version_info[:2] != (3, 12):
    raise SystemExit(
        f"AgentOS 检查要求 Python 3.12，当前为 {sys.version_info.major}.{sys.version_info.minor}。"
    )
'
"${python_bin}" -m ruff format --check smart_reporting
"${python_bin}" -m ruff check smart_reporting
"${python_bin}" -m mypy smart_reporting
"${python_bin}" -m pytest
