from __future__ import annotations

import hashlib

from .contracts import ExecutionApi, RunPythonScriptRequest, RunPythonScriptResult
from .errors import SandboxProviderError

_OUTPUT_TRUNCATION_MARKER = b"\n...[output truncated]...\n"


def bounded_python_output(value: str | bytes, limit: int) -> tuple[str, bool]:
    """按字节限制 runner 输出，并保留 traceback 的异常尾部。"""

    raw = value if isinstance(value, bytes) else value.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return raw.decode("utf-8", errors="replace"), False
    if limit <= len(_OUTPUT_TRUNCATION_MARKER):
        return raw[-limit:].decode("utf-8", errors="ignore"), True
    available = limit - len(_OUTPUT_TRUNCATION_MARKER)
    head_size = available // 4
    tail_size = available - head_size
    selected = raw[:head_size] + _OUTPUT_TRUNCATION_MARKER + raw[-tail_size:]
    return selected.decode("utf-8", errors="ignore"), True


class PythonScriptRunner:
    """Provider 无关的结构化 Python 执行边界。"""

    def __init__(self, execution: ExecutionApi) -> None:
        self._execution = execution

    async def run(self, request: RunPythonScriptRequest) -> RunPythonScriptResult:
        expected_hash = hashlib.sha256(request.script.encode()).hexdigest()
        result = await self._execution.run_python_script(request)
        if result.script_hash != expected_hash:
            raise SandboxProviderError("sandbox 返回的脚本身份与请求不一致。")
        return result
