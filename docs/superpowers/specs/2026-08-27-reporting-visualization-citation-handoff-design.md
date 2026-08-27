# Reporting 可视化引用交接设计

**日期：** 2026-08-27

## 背景

可视化 Analysis Task 的服务端验收契约已签发全量 `citationIds`，`register_report_charts` 也只接受其中的引用。任务指令却没有给模型说明某个分析项可使用哪些引用。

可视化恢复任务在探索预算耗尽后会隐藏事实查询工具。这时模型既不能查询映射，也不能从指令获得映射，因而无法合法登记图表引用。

## 目标与范围

在可视化任务指令中交接最小的、服务端派生的 `analysisId -> citationIds` 映射。正常尝试和恢复尝试必须得到相同映射。

本次不改变图表登记校验、可视化工具白名单、事实文件访问、引用正文投影、预算规则或纯 Coding 产品链路。

## 设计

在 `ReportingWorkflowRuntime._run_visualization_task` 构造 `instruction_payload` 时新增 `analysisCitationIds`：

```json
{
  "analysis_001": ["citation-income"],
  "analysis_002": ["citation-budget", "citation-workload"]
}
```

每个数组由冻结分析计划中该 `analysisId` 的 `datasetIds` 与受信 `citation_bindings` 的 `datasetId` 匹配得出，顺序沿用 `citation_bindings`。映射只传递稳定引用 ID，不传递引用注册表、证据正文、快照内容或文件路径。

`phase_contract.citationIds` 继续作为图表登记时的唯一服务端授权集合；`analysisCitationIds` 只是模型执行任务时的受信提示，不放宽 `register_report_charts` 的校验。

恢复任务沿用同一段 payload 构造逻辑，因此在探索工具被隐藏时仍可依据该索引选择合法引用。

## 验证

先增加运行时可视化任务的回归测试，构造两个分析项、不同数据集和三个引用，断言交给 `task_runner.start` 的 JSON 指令：

- 含每个分析项的正确 `analysisCitationIds`；
- 不含 `citationRegistry` 或引用正文；
- 在恢复条件下仍保留相同映射。

测试先在现有实现上失败，再以最小生产改动转绿。完成后运行对应定点 pytest、改动文件的 Ruff format/lint 和必要的 Mypy 检查。
