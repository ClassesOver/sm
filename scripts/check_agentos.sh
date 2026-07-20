#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${AGENTOS_PYTHON:-${repo_root}/.venv-agent/bin/python}"

cd "${repo_root}"
"${python_bin}" -m ruff format --check agentos_dev
"${python_bin}" -m ruff check agentos_dev
"${python_bin}" -m mypy agentos_dev
"${python_bin}" -m pytest
