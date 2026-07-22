---
name: workspace-smart-report
description: 使用当前对话的 Daytona 沙箱自由分析工作区文件，生成中文 Markdown 智能报表并渲染为 PDF。
---

# 工作区智能报表

用户要求文件分析、智能报表或 PDF 报表时使用本技能。

1. 优先采用本轮附件的 `workspacePath` 和用户已选工作区文件的 `path`；它们均为相对 `/home/daytona/workspace` 的工作区路径。仅当用户明确要求分析当前 Odoo 列表或视图时，先调用 `odoo.export_current_view` 并使用返回的 `path`。
2. 调用 `report_list_analysis_capabilities` 获取沙箱实际可用的 Python 库和系统命令，再将输入路径原样传给 `report_prepare_dataset`，保存返回的 `jobId`。随后调用 `report_profile_dataset` 获取 job 已绑定输入的确定性数据基线；剖析结果标记为 sampled 时，引用统计必须说明样本范围。
3. `report_analyze_dataset` 无需确认。使用它执行 Python、Shell 或 SQL 分析时，每次调用都必须提交本轮拟执行的完整非空命令并向标准输出写出分析结果，禁止用空字符串占位。模型根据每轮结果自行决定轮数，并参考剖析基线判断证据是否充分；若返回 `ok: false`，读取 `exitCode` 和 `output`，修正命令后以同一 `jobId` 发起下一轮，直到至少一轮返回 `ok: true`。不得把失败结果当作分析结论，也不得另行向用户提问。
4. 可在后续轮次读取前面生成的脚本、中间数据和图片。根据用户诉求自由决定分析方法、章节、表格、图表类型和图表数量；对关键统计口径和异常结论增加复核轮次。沙箱已为 Matplotlib/Seaborn 配置 Noto CJK 图表字体；不要覆盖为 DejaVu-only 字体，中文图表标题、坐标轴和图例必须使用可覆盖 CJK 的字体。
5. 在 `报表/生成结果/<jobId>/` 下生成完整 UTF-8 Markdown 和图片。Markdown 是报表正文的唯一来源，图片使用相对 Markdown 文件的 PNG、JPEG、GIF 或 WebP 路径；不要写 raw HTML、外部 URL 或绝对路径，PDF 输出必须使用尚不存在的新路径。
6. 检查标题、数据范围、统计口径、单位、空值、截断声明、结论依据和所有图片后，直接调用无需确认的 `report_render_markdown`，再用返回的 `pdfPath` 调用 `report_validate_pdf`。空白页、图片缺失或其他验收失败时，修正 Markdown 或图片并使用新的 PDF 路径重新渲染和验收。
7. 最后调用 `report_job_status`。只有状态为 `validated` 且产物没有 `changed` 时，才可使用状态返回的 Markdown/PDF 相对路径、页数、图片数、大小和 SHA-256 报告完成；`rendered`、`validation_failed` 或 `artifact_changed` 都不代表完成。
8. 智能报表的能力发现、准备、剖析、分析、状态读取、PDF 渲染和视觉验收无需确认；Odoo 当前视图导出仍遵循自身的授权链路。

本技能不使用 `report_compile`、`blocks`、固定模板或固定分析操作。沙箱仍受当前 thread、工作区、网络、超时和输出大小边界约束。
