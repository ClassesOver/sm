# Reporting Code Agent 独立视觉模型工具设计

## 目标

将 visualization 的视觉审查完全移入 Reporting Code Agent 工具循环。Coding 主模型本身不具备视觉能力，因此 `view_image` 由独立视觉模型执行图片判断，并向主模型返回结构化文字反馈。主模型在同一个 Responses API run 内根据反馈修改脚本、重新执行和重新审查，直至满足签发门禁。

固定 Workflow 不再调用视觉模型，也不再维护视觉修复循环。它只消费 Code Agent 已签发的脚本、输出身份和视觉回执。

目标交互：

```text
write_script
→ run_script
→ view_image(path)
→ 独立视觉模型返回结构化问题
→ write_script
→ run_script
→ view_image(path)
→ submit_script
```

## 已确认约束

- Coding 主模型没有视觉能力，不能直接消费图片或 data URL。
- 使用独立视觉模型，复用现有 `ReportVisionReviewer` 的模型策略和结构化审查契约。
- 工具命名与调用体验参考 Codex `view_image(path, detail)`，但返回值是独立视觉模型的结构化结论，不是给主模型的原始图片。
- 不保留旧 `inspect_chart`、外层视觉审查或旧工具兼容别名。
- 不提供外层二次视觉复核；服务端通过文件身份和视觉回执强制签发门禁。
- CodeMode 继续直接使用会话正式 Workspace，不引入临时 Workspace。
- 视觉业务建议可以是软告警；空图、严重遮挡、裁切和误导性呈现等现有阻断结论继续阻止签发。

## 非目标

- 不为 Coding 主模型增加多模态能力。
- 不把图片编码为 base64 JSON 返回给 Coding 主模型。
- 不允许主模型自行声明图片已通过审查。
- 不持久化未签发 task 的视觉草稿状态。
- 不兼容旧 `inspect_chart` 工具参数、回调或测试 fixture。

## 核心架构

```text
VisualizationSectionWorkflow
  └── ReportingCodeGenerationRunner
      └── ReportingCodeModeToolkit
          ├── write_script
          ├── run_script
          ├── view_image ─────────────┐
          └── submit_script           │
                                     ▼
                              ReportVisionReviewer
                                     │
                                     ▼
                         ChartVisualInspectionReceipt
```

`ReportVisionReviewer` 是唯一视觉判断者。Toolkit 负责路径授权、执行回执关联、文件身份复核和回执缓存。`submit_script` 是唯一签发入口，并强制验证所有视觉回执。

## `view_image` 工具

### 工具协议

`view_image` 是普通 JSON function tool：

```json
{
  "type": "object",
  "properties": {
    "path": {"type": "string"},
    "detail": {"type": "string", "enum": ["high", "original"]}
  },
  "required": ["path"],
  "additionalProperties": false
}
```

`detail` 默认 `high`。工具只对 `task_kind=visualization` 暴露；analysis task 不注册该工具。

### 调用前门禁

Toolkit 按顺序执行：

1. 要求存在最近一次成功 `run_script` 产生的 `ExecutionReceipt`；
2. 规范化 `path`，拒绝绝对路径、`..`、符号链接和非普通文件；
3. 要求 `path` 属于当前 task 的 `declared_output_paths`；
4. 要求 `path` 存在于当前 `ExecutionReceipt.output_files`；
5. 重新读取当前文件身份，并要求它与执行回执完全一致；
6. 要求文件为受支持的 PNG/JPEG 图片，并满足现有大小与解码限制。

模型不能通过 `view_image` 浏览任意 Workspace 文件，也不能审查未由当前脚本成功执行生成的图片。

### 独立视觉审查

Toolkit 调用 `ReportVisionReviewer.review(workspace_key, path, detail)`。Reviewer 通过现有 Workspace 图片读取边界获得内存字节，独立视觉模型不获得宿主机绝对路径或通用文件访问能力。

返回值继续使用 `ChartVisualInspectionReceipt`，至少包含：

```text
sourcePath
sha256
reviewed
visualReviewStatus
requiresRevision
modelId
summary
issues
warnings
suggestions
```

`requiresRevision=true` 是一次成功的工具调用和有效的审查结论，不是技术异常。工具将结构化问题返回 Coding 主模型，由它决定如何修复脚本。

视觉供应商失败、输出解析失败或图片解码失败返回稳定的可恢复工具错误，不伪造 `reviewed=true`。

### 审查期间身份复核

视觉模型返回后，Toolkit 再次读取图片身份。审查前、视觉回执和审查后三者的 SHA-256 必须一致，否则返回 `report_code_visual_output_changed`，且不记录回执。

## Task 内存状态

`ReportingCodingTaskBinding` 新增：

```text
visual_inspection_receipts: dict[path, ChartVisualInspectionReceipt]
visual_revision_history: 有界的失败视觉摘要
```

规则：

- 工具成功后由服务端直接记录回执，主模型不能提交或修改回执；
- 相同路径和 SHA-256 已存在回执时直接复用，避免重复视觉费用；
- `write_script` 使执行回执和全部视觉回执失效；
- `run_script` 开始前清除当前执行回执和视觉回执；
- Kernel restart 不改变文件，但清除尚未签发的执行及视觉回执，要求重新执行；
- 输出文件变化后，旧回执即使仍在内存中也不能通过 SHA-256 门禁；
- revision history 只保存错误分类和有界摘要，不保存图片字节或绝对路径。

## 签发门禁

visualization task 的 `submit_script` 在现有源码及输出身份门禁之后增加：

1. 每个声明图片输出都有视觉回执；
2. 回执 `sourcePath` 与声明输出路径一致；
3. 回执 SHA-256 与当前 `ExecutionReceipt.output_files` 一致；
4. `reviewed=true`；
5. `visualReviewStatus=passed`；
6. `requiresRevision=false`。

失败返回可恢复错误：

```text
report_code_visual_review_required
report_code_visual_revision_required
report_code_visual_output_changed
report_code_visual_review_unavailable
```

回执缺失或要求修订时 Agent 继续当前工具循环。视觉服务不可用可以在工具调用预算内重试；预算耗尽后本次 Code Agent run 失败，由固定 Workflow 使用现有 visualization 降级策略处理。

`CodeGenerationResult` 扩展为：

```text
script_file
execution_receipt
visual_inspection_receipts
visual_repair_diagnostic（可选、有界）
```

analysis task 的视觉回执必须为空。

## Workflow 改造

`VisualizationSectionWorkflow` 删除：

- `inspect_chart` 构造参数；
- 外层逐图视觉审查；
- `MAX_VISUALIZATION_REVIEW_REPAIRS`；
- `visual_review_repairs` 状态；
- 外层 `report_visualization_review_failed` 修复循环。

Workflow 收到 `CodeGenerationResult` 后只执行确定性核对：

1. 脚本身份等于 execution receipt 的 source identity；
2. 计划图表都存在于签发输出；
3. 视觉回执路径集合等于计划图表路径集合；
4. 每个视觉回执 SHA-256 等于对应签发输出；
5. 每个回执均为已审查、通过且无需修订；
6. 调用领域提交并携带这些视觉回执。

这里不再次调用视觉模型。任何身份或回执不一致均属于不可恢复的 `report_phase_artifact_changed`。

Code Agent 内曾出现视觉失败、最终修复并通过时，Workflow 只在领域提交 accepted 后记录成功修复知识。

## 工具调用预算

`view_image` 每次只审查一张图片，保证路径、问题和文件身份一一对应。visualization task 的 `tool_call_limit` 固定为 `20 + 声明图片数量 + 9`：20 是现有基础预算，9 为最多三轮 `write_script → run_script → view_image` 修复预留。服务端硬上限为 140；按当前最多 100 张计划图表计算，最大预算为 129，不会产生无界调用。

相同 SHA-256 的回执复用不消耗视觉模型调用。若图表数量超过允许的 Code Agent 工具预算，任务在进入 Agent 前以稳定技术错误拒绝，不静默跳过图片。

## 资源与配置

- `ReportVisionReviewer` 继续由 Reporting runtime 持有，并显式注入 `ReportingCodeGenerationRunner` 和 task-local Toolkit；
- Toolkit 不创建视觉模型或 reviewer；
- reviewer 每次审查继续创建隔离视觉 Agent；
- task 完成、异常或取消后，视觉回执随 binding 释放；
- 未配置独立视觉模型时 visualization coding task 启动即失败，不回退到无视觉签发；
- analysis coding task 不要求 reviewer。

## 删除与不兼容变更

直接删除且不提供兼容层：

- Reporting phase Toolkit 的旧 `inspect_chart` function tool；
- visualization Workflow 的 `inspect_chart` 回调；
- 外层视觉审查和外层视觉修复循环；
- 旧工具描述中“临时 view_image、正式 inspect_chart”的双轨语义；
- 旧 durable `chartInspectionReceipts` 写入路径中仅服务于外层审查的部分；
- 依赖旧 `generate_script/repair_script/execute_script/inspect_chart` 构造器的 V0 测试。

现有 `ReportVisionReviewer`、`ChartVisualInspectionReceipt` 和图片安全读取边界继续复用，不重新实现视觉模型调用或图片解析。

## 测试

### Toolkit

- analysis task 不暴露 `view_image`；
- visualization task 暴露 `view_image`；
- 未执行脚本、未声明路径、非图片、符号链接和身份变化均被拒绝；
- 独立视觉模型收到当前 Workspace 中的真实图片；
- revision 结果作为结构化反馈返回并记录；
- 相同 SHA-256 复用回执；
- 重新写入、执行和 restart 后回执失效；
- 视觉审查期间图片变化不记录回执。

### 签发

- 缺少任一图片回执不能签发；
- revision required 不能签发；
- 回执哈希过期不能签发；
- 所有当前图片审查通过后可以签发；
- 主模型伪造工具文本不能改变服务端回执；
- analysis task 保持无需视觉回执的签发路径。

### Responses 与 Agent E2E

- 同一 run 完成 `run_script → view_image → 修复 → run_script → view_image → submit_script`；
- 主模型只收到结构化视觉文字，不收到图片内容；
- submit 视觉拒绝后 Agent 继续；
- 成功 submit 后停止；
- 视觉调用计入动态工具预算。

### Workflow

- Workflow 不调用视觉模型；
- Workflow 接受 Code Agent 签发的匹配视觉回执并提交；
- 回执路径、哈希或状态不一致时拒绝；
- Code Agent 视觉修复耗尽后沿用 visualization 降级；
- 领域提交拒绝时不记录成功视觉修复知识。

## 验收标准

- Coding 主模型在没有视觉能力的前提下，通过独立视觉工具反馈完成图表修复。
- 每张签发图片都具有服务端记录、绑定当前 SHA-256 的通过回执。
- 主模型无法伪造、跳过或复用过期视觉回执。
- visualization Workflow 不再调用视觉模型或执行视觉修复循环。
- 不存在 `inspect_chart` 兼容工具或旧 Workflow 回调。
- CodeMode 仍直接使用正式 Workspace。
- 正常、失败、异常和取消路径不遗留 Kernel、binding 或视觉 task 状态。
- 相关定点测试通过。
