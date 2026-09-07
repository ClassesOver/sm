from __future__ import annotations

import hashlib

from .contracts import ExecutionApi, RunPythonScriptRequest, RunPythonScriptResult
from .errors import SandboxProviderError


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
