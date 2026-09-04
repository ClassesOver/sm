# Reporting 可视化固定 Workflow 设计

## 目标

让真实 Reporting CLI 的 `visualization_section` 不再依赖单个模型自行串联工具调用。服务端固定执行阶段，模型只生成当前阶段所需的结构化内容，使 fast 模型在 10 个复杂 mock workspace 场景中达到 10/10 Task 完成和 10/10 严格协议合规。

## 范围

- 本次只改造 `visualization_section`。
- 复用现有 `VisualizationSectionWorkflow`、Reporting Toolkit、任务租约和 durable state。
- `analysis_item` 和普通 `section` 不改变行为，只运行回归验证。
- 不改变公开工具名称、参数 schema、错误码、Workflow ID、数据库结构或 Daytona 隔离策略。
- standalone Agent probe 仅观测模型行为，不再作为真实 CLI 成功率指标。

## 架构

`VisualizationSectionWorkflow` 是可视化执行链的唯一控制器：

```text
prepare/recovery
  -> model_generate
  -> apply_patch
  -> execute/process
  -> inspect
  -> submit
```

模型只输出结构化 `VisualizationScriptDraft`。它不决定下一阶段，不直接选择工作区工具，也不能跳过、重复或倒退阶段。Workflow 使用 Reporting Toolkit 执行受控写入、签发命令、检查和终态提交。

## 阶段契约

### Prepare / Recovery

服务端在访问文件或创建执行前校验 task lease、capability、取消状态、阶段预算和签发路径，并读取 durable checkpoint。已有成功阶段直接复用持久化回执，不重复副作用。

### Model Generate

Visualization Agent 只接收当前章节冻结事实、可视化主题、签发输出路径和上次失败诊断，返回符合 Pydantic schema 的 `VisualizationScriptDraft`。普通生成和一次恢复分别使用现有 generator 与 recovery Agent。

### Apply Patch

Workflow 根据当前脚本内容生成标准 unified diff。首次写入使用 `/dev/null` 基线；覆盖写入必须携带当前 SHA-256。写入回执的路径和身份必须与签发脚本一致。

### Execute / Process

Workflow 只执行 `visualizationWorkspace.allowedTerminalCommand`。前台执行直接校验退出状态；后台执行由服务端保存受信 session ID 并等待完成，模型不生成 `process` 参数。

### Inspect

`visualInspectionMode=vision` 时逐图执行正式检查并验证路径身份；确定性模式使用既有确定性验收。检查失败属于可恢复内容错误，最多进入一次 Recovery Agent。

### Submit

Workflow 一次提交当前章节全部图表。只有 `accepted`、`committed` 或 `already_committed` 才能结束任务；成功后冻结图表身份，禁止重复提交和后续修改。

## 错误与恢复

- 脚本执行失败、图表检查失败和可修复内容错误最多恢复一次，然后从 `apply_patch` 重走。
- task lease 冲突、取消、超时、capability 无效、工作区不可用和文件身份变化直接失败关闭。
- 每个产生副作用的阶段使用既有幂等键和 durable state；重放返回已存结果，不再次写入、执行或提交。
- Recovery Agent 无法返回合法结构化草案时结束任务，不回退为自由工具编排。

## 测试与指标

使用 `AGENT_MODEL_FAST=qwen3.6-flash` 连续运行 10 个复杂 Reporting CLI mock 场景。每次使用独立 workspace、RunContext 和 durable state。

验收必须同时满足：

- 10/10 Task 到达 accepted 终态；
- 10/10 严格协议合规；
- 无越权调用、重复终态、状态泄漏或超时；
- 阶段日志符合固定顺序；
- Recovery 场景最多恢复一次；
- 脚本失败、后台 session、截断输出、SHA 冲突、取消和幂等重放均有定点覆盖。

## 淘汰条件

真实 CLI 和 test agent 全部切换到固定 Workflow 后，删除 `visualization_section` 为单 Agent 自由工具编排保留的动态生命周期投影；若其他 Reporting 能力仍使用该投影，则只保留其真实消费者需要的部分。
