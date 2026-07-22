---
name: workspace-smart-report
description: 分析当前对话工作区中的 CSV、XLS、XLSX、JSON 或 JSONL，并生成中文 PDF 智能报表。
---

# 工作区智能报表

用户要求文件分析、智能报表或 PDF 报表时使用本技能。

1. 优先采用本轮附件的 `workspacePath` 和用户已选工作区文件的 `path`；它们均为相对 `/home/daytona/workspace` 的工作区路径。
2. 仅当用户明确要求分析当前 Odoo 列表或视图时，先调用 `odoo.export_current_view`；CSV 与 XLS 返回的 `path` 均直接用于准备数据。
3. 分析 CSV、XLS、XLSX、JSON 或 JSONL 时，将上述路径原样传给 `report_prepare_dataset`；不得使用 `sandbox_exec`、Python 或 pandas 读取。先调用 `report_list_capabilities` 检查环境，再依次调用 `report_prepare_dataset`、`report_analyze_dataset` 和 `report_compile`。分析操作使用 `{"type": "summary"}`，或使用 `{"type": "trend", "column": "字段名", "limit": 10}` 形状；`top_bottom`、`share`、`pivot`、`iqr` 与 `trend` 形状相同。
4. 根据诉求选择经营、财务或项目模板。结论、KPI、表格和图表必须引用已保存的 `analysis_id`，不得嵌入原始数据。
5. 检查标题、统计口径、单位、空值、截断声明和图表可读性后，调用需要用户确认的 `report_render`。
6. 手动文件流程只请求 PDF 渲染确认；Odoo 当前视图流程还需等待导出确认。

技能不提供脚本，不扩大 Toolkit 权限，也不决定工具是否可用。
