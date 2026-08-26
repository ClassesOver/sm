# Reporting Python 写入原子性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 拒绝会使 Reporting 分析 Python 文件语法无效的写入，并保证该拒绝不会改变 Workspace 或提交写入意图。

**Architecture:** 在 `write_analysis_files` 调用 Workspace patch 前构造本次写入的候选文本。对候选 `.py` 内容执行现有执行预检相同的 `ast.parse` 与 `compile`；unified patch 复用 `build_workspace_changes`，其余三种写入沿用 Kernel 的文本语义。预检失败直接返回稳定 Reporting 错误，不产生 patch 或 durable mutation。

**Tech Stack:** Python 3.12、pytest、pytest-anyio、`ast`、现有 WorkspaceService/TaskExecution patch helpers。

---

### Task 1: 锁定拒绝无效 Python 的回归契约

**Files:**
- Modify: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py:1420-1455`

- [x] **Step 1: 写入失败用例**

在现有 analysis 写入测试相邻位置加入下列测试。它以真实 `replace_text` 入参把有效脚本改成未闭合字符串，并只 mock Workflow/Daytona 边界：

```python
@pytest.mark.anyio
async def test_analysis_write_rejects_invalid_python_before_workspace_mutation() -> None:
    @asynccontextmanager
    async def context(value):
        yield value

    source = "print('ok')\\n"
    scope = SimpleNamespace(thread_id="thread-1")
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()
    toolkit.kernel = SimpleNamespace(
        bound_external_run_id=lambda _run_context: "external-run-1",
        task_scheduler=lambda _external_run_id: context(SimpleNamespace(write=lambda: context(None))),
        scope=AsyncMock(return_value=scope),
        patch=AsyncMock(),
        service=SimpleNamespace(file_bytes=lambda _thread_id, _path: (source.encode(), "text/x-python")),
    )
    toolkit._phase_parameters = lambda _scope, _phase: (
        {}, {"taskKind": "analysis_item", "analysisOutputRoot": "analysis"}
    )
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(payload={"writeIntents": {}}))
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.write_analysis_files(
        operation="replace_text",
        path="analysis/report.py",
        old_string="print('ok')",
        new_string="print('",
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["code"] == "report_analysis_python_syntax_invalid"
    assert result["details"]["path"] == "analysis/report.py"
    assert source == "print('ok')\\n"
    toolkit.kernel.patch.assert_not_awaited()
    toolkit._apply_durable.assert_not_awaited()
```

- [x] **Step 2: 运行失败用例，确认其因缺少预检而失败**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_tool_contracts.py::test_analysis_write_rejects_invalid_python_before_workspace_mutation -q`

Expected: FAIL；当前实现会调用 `kernel.patch`，测试在 `assert_not_awaited()` 处失败。

### Task 2: 写入前构造候选 Python 并验证语法

**Files:**
- Modify: `smart_reporting/reporting/tools/analysis.py:15-35`
- Modify: `smart_reporting/reporting/tools/analysis.py:270-425`
- Modify: `smart_reporting/reporting/tools/toolkit.py:1280-1335`

- [x] **Step 1: 导入原子 patch 的候选内容构造器**

将现有导入：

```python
from ...task_execution.tools import parse_unified_diff
```

改为：

```python
from ...task_execution.tools import build_workspace_changes, parse_unified_diff
```

- [x] **Step 2: 增加只读预检方法**

在 `RuntimeAnalysisMixin.write_analysis_files` 前添加 `_preflight_analysis_python_write`。方法接收 `scope`、`tool_name` 和 `canonical`，为四种现有 primitive 构造与 Kernel 一致的候选 `changes`，筛选操作为 `create` 或 `update` 的 `.py` 文件，并执行：

```python
try:
    tree = ast.parse(content, filename=path)
    compile(tree, path, "exec")
except SyntaxError as error:
    raise ReportingError(
        "report_analysis_python_syntax_invalid",
        "写入会使分析 Python 脚本语法无效，已拒绝写入。",
        details={"path": path, "line": error.lineno, "offset": error.offset},
    ) from error
```

具体候选内容来源：

```python
if tool_name == "create_files":
    changes = [
        {"operation": "create", "path": item["path"], "content": item["content"]}
        for item in canonical["files"]
    ]
elif tool_name == "overwrite_file":
    changes = [{"operation": "update", "path": canonical["path"], "content": canonical["content"]}]
elif tool_name == "replace_text":
    content, _mime = await asyncio.to_thread(
        self.kernel.service.file_bytes, scope.thread_id, canonical["path"]
    )
    original = content.decode("utf-8")
    changes = [{
        "operation": "update",
        "path": canonical["path"],
        "content": original.replace(
            canonical["old_string"], canonical["new_string"],
            -1 if canonical["replace_all"] else 1,
        ),
    }]
else:
    changes = await asyncio.to_thread(
        build_workspace_changes, self.kernel.service, scope.thread_id, canonical["patch"]
    )
```

对 `replace_text` 先保留 Kernel 已有的原文存在性和唯一性约束：原文不存在或 `replace_all=False` 且计数不为一时抛出同样的 `WorkspaceError`。不要在预检中写入或修改 durable state。

- [x] **Step 3: 在首次 durable mutation 前调用预检**

在 `write_analysis_files` 内，`self._require_analysis_task_output_paths(contract, paths)` 之后、`payload = json.dumps(...)` 与 `record_write_intent` 之前插入：

```python
await self._preflight_analysis_python_write(
    scope=scope,
    tool_name=canonical_tool_name,
    canonical=canonical,
)
```

这样 `ReportingError` 会被现有外层错误转换为工具失败回执，且没有 Workspace patch 或 pending/committed write intent。

- [x] **Step 4: 保留稳定的错误定位信息**

在 `ReportWorkspaceTaskToolkit._failure` 的 ReportingError details allow-list 中加入
`report_analysis_python_syntax_invalid`，并为该 code 设置：

```python
result["requiredActions"] = [
    "修正 details.path 指向的 Python 语法错误后，使用原 operation 重新提交。"
]
```

这样回执会保留预检提供的 `path`、`line` 和 `offset`，不会回显脚本源码。

- [x] **Step 5: 运行失败用例，确认转绿**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_tool_contracts.py::test_analysis_write_rejects_invalid_python_before_workspace_mutation -q`

Expected: PASS；`kernel.patch` 与 `_apply_durable` 均未被调用。

### Task 3: 防止预检误拒绝有效替换

**Files:**
- Modify: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py:1420-1455`

- [x] **Step 1: 增加有效 Python 替换测试**

沿用 Task 1 的 scheduler、scope 和 `source` fixture，将 `new_string` 改为 `print('done')`，设置：

```python
identity = {
    "path": "analysis/report.py",
    "size": len("print('done')\\n".encode()),
    "sha256": hashlib.sha256("print('done')\\n".encode()).hexdigest(),
}
toolkit.kernel.patch = AsyncMock(return_value={"ok": True})
toolkit._analysis_write_hash_files = AsyncMock(return_value=[identity])
```

断言结果为 `{"ok": True, "status": "committed", ...}`，`kernel.patch` 恰好 await 一次，且 `_apply_durable` 的第二次调用使用：

```python
name="commit_write_intent"
payload={"intentId": result["intentSha256"], "artifacts": [identity]}
```

- [x] **Step 2: 运行新增用例，确认当前预检没有误拒绝**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_tool_contracts.py::test_analysis_write_allows_valid_python_replace -q`

Expected: PASS。

### Task 4: 定点回归与静态验证

**Files:**
- Modify: `smart_reporting/reporting/tools/analysis.py`
- Modify: `smart_reporting/reporting/tools/toolkit.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`

- [x] **Step 1: 运行关联测试文件**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_tool_contracts.py -q`

Expected: PASS，且无失败。

- [x] **Step 2: 格式化、静态检查和差异检查**

Run:

```bash
cd smart_reporting
ruff format reporting/tools/analysis.py reporting/tools/toolkit.py reporting/tests/test_reporting_tool_contracts.py
ruff check reporting/tools/analysis.py reporting/tools/toolkit.py reporting/tests/test_reporting_tool_contracts.py
mypy reporting/tools/analysis.py reporting/tools/toolkit.py
git -C .. diff --check
```

Expected: 每条命令退出码为 0。

- [x] **Step 3: 检查最终差异并提交**

Run:

```bash
git diff -- smart_reporting/reporting/tools/analysis.py smart_reporting/reporting/tools/toolkit.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py
git status --short
git add smart_reporting/reporting/tools/analysis.py smart_reporting/reporting/tools/toolkit.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py
git commit -m "fix(reporting): reject invalid analysis python writes"
```

Expected: 只包含预检实现和两条回归测试。
