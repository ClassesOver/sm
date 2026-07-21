---
name: odoo-current-view-report
description: 分析当前 Odoo List/Kanban 的真实 BasicModel 范围并生成标准 PDF 报表。用户要求分析、汇总、绘图或导出“当前列表、当前筛选、已勾选记录”时使用；不适用于表单页、任意记录 ID、模型猜测或旧的 @筛选引用报表。
---

# Odoo 标准报表分析协议

把 `agui.report.config.v1` 作为 `ReportAssemblyInput`：Odoo 宿主绑定数据，Agent 只定义标题、维度、指标、图表和章节，可信脚本负责校验并渲染。只通过本轮声明的受控工具处理数据。

不要把 domain、context、排序、分组、记录 ID 或原始行写入消息、Agent 状态、配置或参数。范围语义固定：有勾选记录时导出当前 domain 与勾选 IDs 的交集；没有勾选记录时导出完整当前 domain。Agent 不得提交 domain、context、IDs 或自行改选范围。

## 工作流

1. 检查“HRP 宿主快照”：仅接受交互式 `list` 或 `kanban`，原样使用其中的 `viewTarget`。其他页面直接说明不支持，不导航到别处猜测数据源。
2. 调用 `odoo.business.report.filters`：`source={"kind":"current_view"}`、`target=viewTarget`、`mode="describe"`、`requests=[{}]`。宿主会在准备命令前本地绑定完整 BasicModel 状态。
3. 根据当前用户需求和 describe 返回的 `scope`、`selectedCount`、`rowCount`、字段 schema、时区和指纹确定报告目的、字段、维度、指标、图表和章节。缺少会改变口径的信息时再询问用户；不要请求或推断 domain、context、ID。
4. 明细报表原样复用 `sourceHandle` 与 `viewTarget`，以 `mode="detail"` 和一个 `fields` 请求导出。不得修改范围。超过 100000 行、30 字段、100 MiB 或 128 MiB 时，请用户缩小范围；只有用户明确同意 Odoo 聚合口径时才改用 `aggregate`。
5. 对 manifest 先用 `pandas_profile_dataset`；仅在确有必要时调用 `pandas_sample_dataset`，且最多 20 行、10 列。样例只用于本轮内部核对，不得写入配置、说明或最终 PDF。用 group、pivot 工具取得派生分析；只有用户需要预览时才调用 chart 工具。不要用 `workspace_read_file` 读取原始 JSONL 分片。
6. 调用 `pandas_create_report_config` 写入非原始配置，将用户需求提炼为 `purpose`，并用 `sections` 按需选择和排序 `overview`、`notes`、`chart`、`analysis`。该工具生成 `报表/配置/<report-id>/报表配置.json`，不要自行拼接路径。需要字段结构时读取 `report-manifest.md`；需要脚本信封和错误码时读取 `report-protocol.md`。
7. 向用户一次性确认最终口径和将生成 PDF。确认后调用 `run_skill_script`，使用 `skill_name="odoo-current-view-report"`、`script_path="generate_reports.py"`、`args=["render", configPath]` 和允许的最大超时。正常流程不要单独执行 `capabilities` 或 `validate`；`render` 会完成相同校验。
8. 只有脚本退出码为 0，且 stdout 是 `agui.odoo.report.skill.v1`、`operation="render"`、`ok=true` 的 JSON 时才报告完成。唯一产物是 `报表/生成结果/<report-id>/分析报告.pdf`。

该 Skill 只接受中文 current-view manifest 和受控配置路径，不接受旧报表来源、内嵌数据或自定义输出路径。
