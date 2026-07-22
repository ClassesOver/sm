---
name: workspace-smart-report
description: 使用当前对话的 Daytona 沙箱自由分析工作区文件，生成中文 Markdown 智能报表并渲染为 PDF。
---

# 工作区智能报表

用户要求文件分析、智能报表或 PDF 报表时使用本技能。

1. 优先采用本轮附件的 `workspacePath` 和用户已选工作区文件的 `path`；它们均为相对 `/home/daytona/workspace` 的工作区路径。仅当用户明确要求分析当前 Odoo 列表或视图时，先调用 `odoo.export_current_view` 并使用返回的 `path`。
2. 调用 `report_list_analysis_capabilities` 获取沙箱实际可用的 Python 库和系统命令，再将输入路径原样传给 `report_prepare_dataset`，保存返回的 `jobId`。
3. 使用 `report_analyze_dataset` 执行 Python、Shell 或 SQL 分析，每轮执行前等待工具确认，并让命令向标准输出写出本轮分析结果。模型根据每轮结果自行决定轮数；若返回 `ok: false`，读取 `exitCode` 和 `output`，修正命令后以同一 `jobId` 发起下一轮，直到至少一轮返回 `ok: true`。不得把失败结果当作分析结论，也不得另行向用户提问。
4. 可在后续轮次读取前面生成的脚本、中间数据和图片。根据用户诉求自由决定分析方法、章节、表格、图表类型和图表数量；对关键统计口径和异常结论增加复核轮次。
5. 在 `报表/生成结果/<jobId>/` 下生成完整 UTF-8 Markdown 和图片。Markdown 是报表正文的唯一来源，图片使用相对 Markdown 文件的 PNG、JPEG、GIF 或 WebP 路径；不要写 raw HTML、外部 URL 或绝对路径，PDF 输出必须使用尚不存在的新路径。
6. 检查标题、数据范围、统计口径、单位、空值、截断声明、结论依据和所有图片后，直接调用无需确认的 `report_render_markdown`。只使用其返回的 `markdownPath`、`pdfPath`、`pageCount`、`imageCount` 和 `size` 报告结果。
7. 智能报表的能力发现、准备和 PDF 渲染无需确认；任意分析命令和 Odoo 当前视图导出遵循各自的确认或授权链路。

本技能不使用 `report_compile`、`blocks`、固定模板或固定分析操作。沙箱仍受当前 thread、工作区、网络、超时和输出大小边界约束。
