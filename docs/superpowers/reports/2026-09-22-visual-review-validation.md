# 视觉审查真实验证记录

## 范围与结果

- 任务：2025年收入趋势分析，一个章节。
- 基线提交：`2274632`，Coding 实际请求为 low；独立视觉审查关闭思考。
- 运行：`cli-report-b29249fc8a73489eadcc9f34d856d5af`。
- 时间：2026-09-22 17:40:39 至 18:22:33，约 41 分 54 秒。
- 结果：失败，不能标记完整报表验收通过。最终 `report_coding_workflow_output_invalid`；之前有多次 `report_code_custom_tool_protocol_error`。
- 本地日志：`.local/reporting-validation/visual-fix.log`。此前临时目录中的验证会话及日志丢失，不计入有效验收。

## 已确认的审查队列缺陷及补修

`build_delivery_state` 将所有可视化输出列入待审查队列，包含 `.plotly.json`；但 `submit_script` 和提交诊断已经排除这些 JSON 文件。两处口径不一致，使模型被要求把 JSON 交给图片审查。

本轮 18:09:24 出现 `report_chart_source_invalid`，随后进入 read/edit 修复，未再出现先前的 unavailable 连续六次循环。逐一使用生产图片检查函数检查 attempt-3 的真实产物：5 张 PNG 全部通过，5 个 Plotly JSON 全部返回无法解码的 `report_chart_source_invalid`。原调用日志未记录失败路径，因此不能声称已从日志直接证明那一次调用的参数，也不能反推此前历史故障必定同因。

补修：交付状态排除 `.plotly.json`，与提交门禁保持一致；本地检查失败增加路径及错误码日志。未放宽图片审查、工具协议或精确 patch 校验。运行中的进程未加载本次补修。

定向回归：PNG + Plotly JSON 输出只调度 PNG；PNG 审查通过后开放 submit_script。1 项通过，Ruff 与 diff 检查通过。

## 独立真实视觉验证

对 attempt-3 的 5 张 PNG 使用生产 `ReportVisionReviewer` 调用真实服务：

- 模型：`qwen3.6-flash`。
- 请求配置：`extra_body.enable_thinking=false`。
- 结果：5/5 `reviewed=true`、`visualReviewStatus=passed`、`requiresRevision=false`。
- 记录：`.local/reporting-validation/real-image-review.jsonl`。

此结果证明这些图片及当前视觉服务可用，不代表报表最终提交成功，也不代表之前不存在瞬时服务故障。

## 未完成及后续阻断

1. 完整报表提交仍未通过。在只声明 run_script 的状态下，模型多次返回 edit_script 或 read_script，触发协议拒绝并引发外层恢复。需检查编辑后工具集合是否过度收窄，保持结构化调用校验和局部 patch 约束。
2. 新增 JSON 队列筛选修复尚未完成端到端真实回放；应优先复用可视化输入定向验证，避免重复全流程。
3. Coding 指标顶层 reasoningEffort 仍写 high，但逐请求 wire 参数为 low；不可用顶层字段进行 A/B 归因。
4. prepare-analysis-context 首次处理耗时 342 秒并报错，后续流程继续；这是独立耗时来源，不能归因于 Coding reasoning。

更正监控记录：17:58 的执行失败属于 analysis_005，而非当时评论所称的第三项。以持久日志中的 analysis_id 为准。

## 后续修复：编辑后保留局部操作能力

成功 edit_script 后源码 SHA 改变，旧失败诊断按设计不再生效；原状态机因此退回仅允许 run_script，导致跨响应继续局部编辑或读取变成未声明调用。

已将“已有源码但无有效执行回执”状态的工具集合统一为 read_script、edit_script、run_script。提示仍推荐修改完成后直接运行，不要求额外读取；缺少源码时仍以 write_script 创建，已有源码不能完整重写，成功执行及视觉审查后的提交门禁不变。SHA、唯一匹配、局部修改和原生 custom 类型校验不变。

验证：交付状态、原生输入协议和混合调用批次共 118 项通过；新增用例通过两轮读取及精确局部编辑确认 provider 工具声明持续保留 edit_script/custom，运行通过后切换至 submit_script。Ruff 通过。

限制：历史失败响应还把 edit_script 返回成 function 类型；开放工具不会豁免此类型错误。本次状态修复尚未经过真实模型定向回放，不代表整份报表已通过。

## 后续修复：协议错误停止重试

`report_code_custom_tool_protocol_error` 已归类为 Coding 任务致命协议错误。该错误表示 provider 返回的工具名称或 wire 类型与当前声明不一致，继续使用相同上下文重试不会修复类型，反而会重复消耗模型请求。现在首次出现即停止并保留诊断；不会把 function 调用放宽为 custom，也不会解析 assistant 正文中的伪调用。

协议策略定向测试通过；真实回放仍需在后续复验中确认请求次数明显下降。
