---
name: workspace-smart-report
description: 使用当前对话的 Daytona 沙箱自由分析工作区文件，生成中文 Markdown 智能报表并渲染为 PDF。
---

# 工作区智能报表

用户要求文件分析、智能报表或 PDF 报表时使用本技能。

1. 本技能只作为 `report-agent` 的显式路由入口。优先采用本轮附件的 `workspacePath` 和用户已选工作区文件的 `path`；它们均为相对 `/home/daytona/workspace` 的工作区路径。仅当用户明确要求分析当前 Odoo 列表或视图时，先调用 `odoo.export_current_view` 并使用返回的 `path`。
2. 先调用 `report_list_data_sources` 和 `report_describe_data_source` 发现当前消息引用、目录直接子项和服务端注册数据库；随后调用 `report_materialize_dataset`，保存返回的 `datasetId`，再将 `dataset_ids` 传给 `report_prepare_dataset`。只有服务端返回的句柄可进入报表输入绑定。
3. 分析完全使用生产 Coding 工具：先用受控只读工具检查文件、搜索内容和查看 Git 状态或差异，只用 `terminal` 探测依赖及执行 Python、Shell 或当前 Daytona 工作区允许的其他命令。新脚本使用 `create_file`；完整覆盖已有脚本使用 `overwrite_file` 并提供最新 `expected_sha256`；小范围修改优先使用 `replace_text`，删除、移动或多文件修改使用 `apply_patch`。运行中使用返回的持久 `session_id` 调用 `process` 的 `poll/wait/write/submit/kill`；输出被截断时用 `read_tool_output` 按需重读。生产 Coding Toolkit 声明的工具均不要求确认。Report 层不限制分析命令、输出大小、执行轮次或分析方式；失败时读取 `output` 和 `exit_code`，修正脚本或命令后继续。不得把失败结果当作分析结论，也不得另行向用户提问。
4. 可在后续轮次读取前面生成的脚本、中间数据和图片。根据用户诉求自由决定分析方法、章节、表格、图表类型和图表数量；对关键统计口径和异常结论增加复核轮次。沙箱已为 Matplotlib/Seaborn 配置 Noto CJK 图表字体；不要覆盖为 DejaVu-only 字体，中文图表标题、坐标轴和图例必须使用可覆盖 CJK 的字体。
5. 在 `报表/生成结果/<jobId>/` 下生成完整 UTF-8 Markdown 和图片。Markdown 是报表正文的唯一来源，图片使用相对 Markdown 文件的 PNG、JPEG、GIF 或 WebP 路径；不要写 raw HTML、外部 URL 或绝对路径，PDF 输出必须使用尚不存在的新路径。
6. 用 `view_image` 检查生成的图表，并核对标题、数据范围、统计口径、单位、空值、截断声明和结论依据；随后直接调用无需确认的 `report_render_markdown`，再用返回的 `pdfPath` 调用 `report_validate_pdf`。PDF 最多 200 MiB、200 页；空白页、图片缺失或其他验收失败时，修正 Markdown 或图片并使用新的 PDF 路径重新渲染和验收。
7. 调用 `report_job_status`。只有状态为 `validated` 且产物没有 `changed` 时，才能在最后一次 mutation 后调用 `verify`，并把 Markdown、PDF 和主要数据产物路径提交给 `finish_task`；普通 `terminal` 不计为验证，`verification_ids` 可省略以自动选择当前 mutation 最近一次成功的显式验证。只有 `finish_task` 返回 `accepted` 才可报告完成。`rendered`、`validation_failed` 或 `artifact_changed` 都不代表完成。
8. 数据源发现、报表准备、状态读取、PDF 渲染、视觉验收以及生产 Coding Toolkit 的编码和分析均不要求确认；Odoo 当前视图导出仍遵循自身的授权链路。

本技能不使用 `report_compile`、`blocks`、固定模板或固定分析操作。沙箱仍受当前 thread、工作区、网络、超时和输出大小边界约束。
