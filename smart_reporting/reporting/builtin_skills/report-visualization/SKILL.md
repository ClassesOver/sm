---
name: report-visualization
description: 为 Reporting 可视化章节选择、生成、复核和提交图表。仅在 visualization Task 按需读取。
---

# Reporting 图表

## 阶段边界

- `visualization_section` 只处理任务 JSON 指定章节：读取签发的 facts/evidence，写入签发的脚本和图表输出路径，最后只调用一次 `submit_visualization_charts`。不得登记全局图表或冻结分析。
- `visualization_finalize` 只消费已提交的章节草案和受信语义目录：调用 `register_report_charts` 后立即调用 `finalize_report_analysis`；不重跑图表脚本或提交章节草案。

## 选择

- 先明确管理问题、比较对象、期间、粒度和可用数据，再判断是否需要图表及其表达。
- 趋势与变化可使用折线、区间带、同比哑铃/斜率图或瀑布图；结构与贡献可使用排序条形、Pareto、漏斗或子弹图；分布与关系可使用箱线、散点、气泡或热力图。
- 选择必须符合数据语义：漏斗需要真实阶段顺序，目标或参考区间缺失时不补造基准，气泡面积映射规模而非半径，色阶、缺失值和极端值处理应清楚可辨。
- 这些示例不是模板、白名单或验收条件；不要求固定图表数量、类型或多样性。

## 事实与保密

- 使用当前 Task 实际注册的工具和工作区能力生成图表。所有数值必须由本轮不可变数据复算；视觉设计不能代替数据、口径和 citation 校验。
- 用户可见图表只使用业务名称、业务期间和必要指标。Dataset 路径、血缘信息、来源文件名和其他内部标识不得进入图表或用户可见报告；不得泄露内部路径。
- `comparability=reference_only` 时，标题和图注应明确包含“参考”，不得表述为严格同比。

## 可读性

- 标题说明对象、指标和期间；检查坐标轴、单位、图例、标签、注释、边界、对比度和中文字体。
- TopN 或长标签优先使用横向条形图，并按数据密度调整画布高度、采用语义缩写或换行。少量指标优先使用紧凑对比图、哑铃图或表格。
- 默认目标像素至少为 1200 x 675，并为标题、坐标轴、图例和标签保留清晰边界。这些是可读性原则，不限制其他更合适的图形表达，也不构成固定模板或图表白名单。

## 复核

- `visualInspectionMode=vision` 时，每张最终图先调用 `inspect_chart`；`visualInspectionMode=deterministic` 时不得调用该工具，由提交工具执行确定性检查。`view_image` 仅在当前 Task 注册时用于辅助复查。
- `submit_visualization_charts` 成功或返回 `already_committed` 后，`taskFinished=true` 表示当前 Task 已结束；不得继续调用工具、修改图表或重复提交。
- 多图总览可生成带文件名的临时联系表辅助定位问题。联系表只用于检查，不登记为报告图表，不通过 `chartIds` 引用，也不进入 Manifest、PDF 或 Word。
