# Reporting 真实模型探针运行时等价性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Reporting 真实模型工具探针以生产 `RunContext` 和动态工具投影运行，并可靠记录十个 CLI 场景的实际可见工具面。

**Architecture:** 生产 `ReportingPhaseOpenAIChat` 保持不变。探针在脚本内部构造与 `ReportTaskRunner` 同形的 `RunContext`，在完整流式 `Agent.arun()` 调用范围内绑定它，并通过仅用于探针的模型子类在委托生产投影前记录工具列表。`ProbeRecorder` 只同步生产已经存在的可视化脚本和后台 session 生命周期状态，仍然使用 mock workspace 的受限文件与命令能力。

**Tech Stack:** Python 3.12、Agno 3.0.1、Reporting `RunContext`/`ReportingPhaseOpenAIChat`、pytest、Ruff、Mypy。

---

## 文件结构

- 修改：`smart_reporting/reporting/tests/test_reporting_agent_projection.py`
  - 直接锁定生产模型在初始、后台 session、recovery 三种可视化状态下的动态工具投影。
- 修改：`smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py`
  - 验证 probe context、Agent 调用参数、动态工具日志、recovery 场景和 mock 状态隔离。
- 修改：`scripts/probe_reporting_tools_agent.py`
  - 仅实现生产形状的 probe context、投影记录、mock 生命周期同步和场景/结果记录。
- 不修改：`smart_reporting/reporting/agent.py`、`smart_reporting/reporting/phase.py`、`smart_reporting/reporting/tools/*`、`smart_reporting/task_execution/*`。

### Task 1: 锁定生产可视化工具投影契约

**Files:**
- Modify: `smart_reporting/reporting/tests/test_reporting_agent_projection.py`

- [ ] **Step 1: 为三种生命周期写失败测试**

  增加从 `smart_reporting.reporting.agent` 导入 `_phase_filtered_report_tools` 的测试辅助函数；使用当前 `tools_for_task("analysis", "visualization_section")` 生成模型工具 schema，并在 `bind_reporting_run_context()` 范围内断言集合。

  ```python
  def _visible_tool_names(context: RunContext) -> set[str]:
      source_tools = [
          {"function": {"name": name}}
          for name in tools_for_task("analysis", "visualization_section") or ()
      ]
      with bind_reporting_run_context(context):
          return {
              tool["function"]["name"]
              for tool in _phase_filtered_report_tools(
                  [Message(role="user", content="probe")], source_tools
              )
          }

  def test_visualization_initial_projection_hides_read_and_process_tools() -> None:
      visible = _visible_tool_names(_context("analysis", "visualization_section"))
      assert {"read_file", "read_tool_output", "process"}.isdisjoint(visible)

  def test_visualization_session_projection_exposes_only_process_addition() -> None:
      context = _context("analysis", "visualization_section")
      context.session_state["reportingVisualizationSessions"] = ["session-1"]
      visible = _visible_tool_names(context)
      assert "process" in visible
      assert {"read_file", "read_tool_output"}.isdisjoint(visible)

  def test_visualization_recovery_projection_exposes_signed_script_reads() -> None:
      context = _context("analysis", "visualization_section")
      context.dependencies[REPORTING_TASK_DEPENDENCY][
          REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY
      ] = True
      visible = _visible_tool_names(context)
      assert {"read_file", "read_tool_output"}.issubset(visible)
      assert {"process", "view_image"}.isdisjoint(visible)
  ```

- [ ] **Step 2: 运行新测试，确认现有生产行为**

  Run:

  ```bash
  .venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_agent_projection.py -q
  ```

  Expected: 新增测试直接通过，证明动态门禁已经是生产事实；后续 probe 改动不得通过修改静态
  能力矩阵改变该结果。

- [ ] **Step 3: 保持生产实现不变，只保留测试导入和上下文辅助**

  在测试模块导入 `REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY` 与
  `_phase_filtered_report_tools`；沿用已有 `_context()`，在后台 session 用例中初始化
  `session_state={}` 后写入 `reportingVisualizationSessions`。不修改生产过滤函数。

- [ ] **Step 4: 重跑生产投影契约测试**

  Run:

  ```bash
  .venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_agent_projection.py -q
  ```

  Expected: 既有用例和三种新增测试均通过，集合精确体现既有生产过滤规则。

- [ ] **Step 5: 提交生产投影测试**

  ```bash
  git add smart_reporting/reporting/tests/test_reporting_agent_projection.py
  git commit -m "test(reporting): lock visualization tool projection"
  ```

### Task 2: 为 probe 引入生产形状上下文与投影日志

**Files:**
- Modify: `scripts/probe_reporting_tools_agent.py`
- Modify: `smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py`

- [ ] **Step 1: 先写 probe context 和 Agent 参数失败测试**

  在脚本测试中导入 `_build_probe_run_context` 和 `_run_scenario`。以 monkeypatch 替换脚本中的
  `Agent` 与 `_build_model`：fake agent 的 `arun()` 保存关键字参数并在 await 期间读取
  `current_reporting_run_context()`。

  ```python
  @pytest.mark.anyio
  async def test_probe_passes_one_bound_production_context_to_agent(monkeypatch) -> None:
      observed: dict[str, object] = {}

      class FakeAgent:
          def __init__(self, **_kwargs: object) -> None:
              pass

          async def arun(self, _prompt: str, **kwargs: object) -> object:
              observed.update(kwargs)
              observed["bound"] = current_reporting_run_context()
              return object()

      monkeypatch.setattr(probe_module, "Agent", FakeAgent)
      monkeypatch.setattr(probe_module, "_build_model", lambda *_args, **_kwargs: object())
      scenario = probe_scenarios()[0]
      await _run_scenario(_settings(), scenario, model_tier="fast", thinking=False, timeout_seconds=1)

      context = observed["run_context"]
      assert observed["bound"] is context
      assert observed["run_id"] == context.run_id
      assert observed["session_id"] == context.session_id
      assert observed["user_id"] == context.user_id
      assert observed["dependencies"] is context.dependencies
      assert observed["stream"] is True
      assert observed["stream_events"] is True
  ```

  再断言 `_build_probe_run_context()` 在 `REPORTING_TASK_DEPENDENCY` 下生成生产所需的
  `externalRunId`、`threadId`、`sandboxId`、`leaseOwner`、`leaseEpoch`、`attemptNo`、phase、task
  kind、模型档位/ID、thinking 和适用预算字段，且每个 scenario 的 run/session id 不相同。

- [ ] **Step 2: 运行新增测试确认失败**

  Run:

  ```bash
  .venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py -q
  ```

  Expected: 失败于缺少 `_build_probe_run_context` 或 `Agent.arun()` 只收到 prompt。

- [ ] **Step 3: 实现最小 probe runtime 辅助和记录模型**

  在脚本中新增以下仅供 probe 使用的部件，不移动或复制生产逻辑：

  ```python
  @dataclass(slots=True)
  class ProbeToolProjection:
      batches: list[list[str]] = field(default_factory=list)

      def record(self, tools: Any) -> None:
          self.batches.append(sorted(name for name in (_report_model_tool_name(tool) for tool in tools or ()) if name))

  def _build_probe_run_context(
      scenario: ProbeScenario, *, model_tier: Literal["fast", "standard"], model_id: str, thinking: bool
  ) -> RunContext:
      binding = {
          "externalRunId": f"probe-{scenario.name}",
          "threadId": f"probe-thread-{scenario.name}",
          "sandboxId": f"probe-sandbox-{scenario.name}",
          "leaseOwner": "reporting-tool-probe",
          "leaseEpoch": 1,
          "attemptNo": 1,
          REPORTING_PHASE_DEPENDENCY_KEY: scenario.phase,
          REPORTING_TASK_KIND_DEPENDENCY_KEY: scenario.task_kind,
          REPORTING_MODEL_TIER_DEPENDENCY_KEY: model_tier,
          REPORTING_MODEL_ID_DEPENDENCY_KEY: model_id,
          REPORTING_THINKING_EFFORT_DEPENDENCY_KEY: "high" if thinking else "off",
      }
      # visualization / analysis 的预算和 recovery 标量使用 execution.py 的同名键。
      return RunContext(
          run_id=f"probe-run-{scenario.name}",
          session_id=f"probe-session-{scenario.name}",
          user_id="reporting-tool-probe",
          session_state={},
          dependencies={REPORTING_TASK_DEPENDENCY: binding},
      )
  ```

  `ProbeReportingPhaseOpenAIChat` 继承 `ReportingPhaseOpenAIChat`，在 `_project()` 中用现有
  `_phase_filtered_report_tools(messages, tools)` 计算并记录本请求可见工具后立即委托
  `super()._project()`。它不重写过滤条件，不改变模型请求，也不接触生产模块。`_build_model()`
  接收一个 `ProbeToolProjection` 并把它绑定到该探针模型。

- [ ] **Step 4: 让完整 `Agent.arun()` 使用同一个上下文**

  在 `_run_scenario()` 中先创建 model、`RunContext`、mock runtime 和工具；将 context 传给
  `ProbeRecorder`。以生产相同参数运行并在完整 await 范围内绑定：

  ```python
  with bind_reporting_run_context(run_context):
      await asyncio.wait_for(
          agent.arun(
              prompt,
              stream=True,
              stream_events=True,
              run_id=run_context.run_id,
              session_id=run_context.session_id,
              user_id=run_context.user_id,
              dependencies=run_context.dependencies,
              run_context=run_context,
          ),
          timeout=timeout_seconds,
      )
  ```

  结果 JSON 保留既有字段，并新增 `visible_tool_batches`、每个调用时的 `visible_tools` 和
  `not_visible_calls`。`protocol_compliant` 必须同时要求没有 `not_visible_calls`，但仍将
  非场景必需的已可见调用记录为 `unexpected_tools`，防止把“可见”误当成“合规”。

- [ ] **Step 5: 重跑 probe 定点测试**

  Run:

  ```bash
  .venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py -q
  ```

  Expected: 全部通过；fake Agent 证明绑定上下文与显式参数是同一对象。

- [ ] **Step 6: 提交 probe runtime 等价性改动**

  ```bash
  git add scripts/probe_reporting_tools_agent.py smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py
  git commit -m "test(reporting): bind probe to production runtime context"
  ```

### Task 3: 同步 mock 生命周期并加入 visualization recovery 场景

**Files:**
- Modify: `scripts/probe_reporting_tools_agent.py`
- Modify: `smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py`

- [ ] **Step 1: 写 recovery 与状态隔离失败测试**

  将一个现有 `visualization-inspect` 场景替换为 `visualization-recovery`，保持总数十个。
  新场景必须要求 `read_file`、`apply_analysis_patch`、`terminal`、`inspect_chart` 和
  `submit_visualization_charts`；`visualization-background` 保留 `inspect_chart` 覆盖，
  `visualization-preview-truncated` 保留 `view_image` 覆盖。

  ```python
  def test_probe_recovery_starts_with_production_visible_script_reads() -> None:
      scenario = next(item for item in probe_scenarios() if item.name == "visualization-recovery")
      context = _build_probe_run_context(scenario, model_tier="fast", model_id="test", thinking=False)
      tools, _recorder = build_mock_probe_tools(scenario.phase, scenario.task_kind, _runtime(), scenario, context)
      assert _probe_visible_tool_names(context, tools) >= {"read_file", "read_tool_output"}
      assert "view_image" not in _probe_visible_tool_names(context, tools)

  @pytest.mark.anyio
  async def test_probe_background_terminal_makes_only_its_context_process_visible() -> None:
      context = _build_probe_run_context(_background_scenario(), model_tier="fast", model_id="test", thinking=False)
      _tools, recorder = build_mock_probe_tools("analysis", "visualization_section", _runtime(), _background_scenario(), context)
      await recorder.invoke("apply_analysis_patch", _chart_patch())
      receipt = await recorder.invoke("terminal", {"command": "python3 analysis/output/outpatient_chart.py", "background": True})
      assert receipt["session_id"] in context.session_state["reportingVisualizationSessions"]
      assert "process" in _probe_visible_tool_names(context, _tools)
  ```

  再以同一固定 background 流程循环 100 次，断言每次 context/session id、recorder calls 和
  workspace calls 独立，且后一次初始 context 不出现前一次的 session 或脚本路径。

- [ ] **Step 2: 运行新增测试确认失败**

  Run:

  ```bash
  .venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py -q
  ```

  Expected: recovery 场景不存在，且 recorder 不会同步 `reportingVisualizationSessions`。

- [ ] **Step 3: 最小同步生产已存在的状态转换**

  为 `ProbeRecorder` 保存当前 `RunContext`。成功 `apply_analysis_patch` 时设置
  `REPORTING_VISUALIZATION_SCRIPT_WRITTEN_STATE_KEY`；可视化 background `terminal` 返回
  `session_id` 时，按 `ReportingToolkitBase._invoke()` 的规则把它加入
  `run_context.session_state["reportingVisualizationSessions"]`；不要把 session 写入全局或
  scenario 对象。

  recovery 初始化在 async `prepare()` 中通过 mock workspace 写入已签发的
  `analysis/output/outpatient_chart.py`，保存返回的文件 identity，并只允许 `read_file` 读取此
  文件。后续 recovery patch 使用该 identity 的 SHA 进行受限覆盖；命令仍只能是
  `python3 analysis/output/outpatient_chart.py`。依赖中的
  `REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY=True` 是唯一打开恢复读取工具的开关。

- [ ] **Step 4: 让动态可见性逐调用落盘**

  `ProbeReportingPhaseOpenAIChat.get_function_calls_to_run()` 在委托生产实现前，把模型请求的
  tool call 与当前 `ProbeToolProjection` 最新 batch 比较；未在 batch 中的调用追加到
  `not_visible_calls`，再无条件委托 `super()` 产生原有 `report_phase_tool_forbidden` 回执。
  `ProbeRecorder.invoke()` 只为实际获准执行的调用附加当前 `visible_tools`，不得调用 mock
  workspace 来“验证”本应不可见的工具。结果汇总两类记录，并在任一 `not_visible_calls` 存在时
  令 `protocol_compliant=False`。

- [ ] **Step 5: 运行 recovery 和重复回归**

  Run:

  ```bash
  .venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py -q
  ```

  Expected: 十个场景覆盖所有当前工具 schema；recovery 只在恢复 context 可读脚本；100 次 mock
  循环无状态泄漏。

- [ ] **Step 6: 提交场景与生命周期同步**

  ```bash
  git add scripts/probe_reporting_tools_agent.py smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py
  git commit -m "test(reporting): cover probe visualization recovery"
  ```

### Task 4: 定点回归、静态检查和真实模型测量

**Files:**
- Modify: only files from Tasks 1-3
- Output: `/tmp/reporting-probe-fast.jsonl`
- Output: `/tmp/reporting-probe-standard.jsonl`

- [ ] **Step 1: 运行定点无网络测试**

  Run:

  ```bash
  .venv-agent/bin/python -m pytest \
    smart_reporting/reporting/tests/test_reporting_agent_projection.py \
    smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py -q
  ```

  Expected: 全部通过，且不连接模型、PostgreSQL 或 Daytona。

- [ ] **Step 2: 运行受影响 Reporting 非集成回归**

  Run:

  ```bash
  .venv-agent/bin/python -m pytest smart_reporting/reporting/tests -m 'not integration' -q
  ```

  Expected: 通过；若既有未提交改动导致失败，记录失败节点和可复现原因，不改无关代码。

- [ ] **Step 3: 格式、静态和差异检查**

  Run:

  ```bash
  .venv-agent/bin/python -m ruff format --check scripts/probe_reporting_tools_agent.py smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py smart_reporting/reporting/tests/test_reporting_agent_projection.py
  .venv-agent/bin/python -m ruff check scripts/probe_reporting_tools_agent.py smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py smart_reporting/reporting/tests/test_reporting_agent_projection.py
  .venv-agent/bin/python -m mypy scripts/probe_reporting_tools_agent.py
  git diff --check
  ```

  Expected: 全部通过；Mypy 若项目配置不纳入 `scripts/`，使用该文件的显式命令并记录结果。

- [ ] **Step 4: 使用两种真实模型各运行十个场景**

  在依赖、API key 和模型端点均已配置时运行；输出只进入 `/tmp`：

  ```bash
  AGENT_MODEL_FAST=qwen3.6-flash \
    .venv-agent/bin/python scripts/probe_reporting_tools_agent.py \
    --env-file .env --model-tier fast --runs 10 --no-thinking \
    --progress-file /tmp/reporting-probe-fast.jsonl

  AGENT_MODEL_STANDARD=deepseek-v4-flash-0731 \
    .venv-agent/bin/python scripts/probe_reporting_tools_agent.py \
    --env-file .env --model-tier standard --runs 10 --no-thinking \
    --progress-file /tmp/reporting-probe-standard.jsonl
  ```

  Expected: 每轮 JSON 含十个场景、`visible_tool_batches`、完成率、严格协议合规率、
  `not_visible_calls`、拒绝码分布、调用序列和耗时。命令失败时保留标准错误摘要与 JSONL 已完成
  记录，禁止因提高表面完成率而放宽 mock workspace 或生产工具门禁。

- [ ] **Step 5: 汇总真实失败分布并提交验证改动**

  逐模型列出 `valid_count`、`protocol_compliant_count`、`not_visible_calls`、`protocol_failures`
  和最常见错误码。仅当两轮测量显示指令理解或恢复编排是主因时，另起规格讨论提示词/恢复优化；
  不在本计划中混入生产策略变更。

  ```bash
  git add scripts/probe_reporting_tools_agent.py smart_reporting/reporting/tests/test_probe_reporting_tools_agent.py smart_reporting/reporting/tests/test_reporting_agent_projection.py
  git commit -m "test(reporting): verify runtime-equivalent tool probe"
  ```

## 覆盖映射自检

- 生产初始、后台 session、recovery 投影：Task 1。
- 同一 `RunContext`、身份、依赖和流式 Agno 调用参数：Task 2。
- 每轮实际可见工具与每次调用的动态合规判定：Task 2 与 Task 3。
- 恢复脚本读取、后台 session 状态和十场景工具覆盖：Task 3。
- 100 次 mock 无泄漏、定点/回归/静态检查以及两种模型各十场景：Task 3 与 Task 4。
- 无权限放宽、无生产工具和 `task_execution` 改动：所有任务的文件边界和 Task 4 验收。
