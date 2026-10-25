# 报告编辑器 AI 指导改图设计

> 状态：设计稿（2026-10-25）。范围只含 Matplotlib 静态图；Plotly 交互图逻辑已弃用（见 AGENTS.md），本设计不产出、不扩展任何 Plotly / `.plotly.json` / `interactiveCharts` 内容。

## 1. 目标

用户在报告编辑器里选中一张图，用自然语言说明想怎么改（“改成横向柱状图并按金额降序”“只看住院和门诊两组”“加上同比”“标题改成……”），AI 生成改后的图，经用户对比确认后替换正文中的图，导出新 revision 时改后的图与原图一样可追溯、可核验。

**非目标**

- 不在编辑器里做新的统计计算：改图只能使用该图所属分析项已登记的冻结事实与作图数据。超出登记事实的要求如实说明原因，不猜、不估算。
- 不支持上传图片、手写绘图代码或任意 JavaScript。
- 不改写图表以外的正文；图注（图片 alt / 紧随的图注段落）的改动与图一起进入审阅。

## 2. 现状（设计依据）

| 环节 | 现有实现 | 本设计的用法 |
| --- | --- | --- |
| 编辑器 AI | `report_editor/ai.py`：Agno Agent 流式改写选区，结果进入 Milkdown Diff Review，用户接受才写回 | 沿用“生成 → 审阅 → 接受才写回”的交互原则 |
| 图在正文中的形态 | Markdown 图片 `![标题](相对路径)`；`job.render.images` 登记 `{path,size,sha256}`，`read_asset` 只放行登记且哈希未变的 PNG/JPEG | 改后的图同样以登记身份放行 |
| 作图数据 | 生成阶段由 `chart_inputs` 按 `dataBindings` 物化 chart-input/v1，归档为 `<图名>--N.chart-input.json`，`ChartTraceV1.plotDataFileResourceIds` 指向它们；文件内含 `source.analysisId/path/dataPath` 与 `columns/rows` | 改图的数据起点：作图数据与其来源绑定都可从归档文件还原 |
| 可绑定数据 | `_visualization_section_fact_projection` 由事实文件计算 `dataDescriptors`；`_validate_visualization_plan_bindings` 校验绑定必须逐字来自签发目录 | 取数类改图复用同一目录与校验，越界即拒绝使用 |
| 作图执行 | 可视化章节由 CodeMode（`write_script`/`run`）在工作区写脚本并执行；`inspect_chart_file` 做确定性检查，`aview_image` 做视觉审查并出 `ChartVisualInspectionReceipt` | 改图复用同一代码代理、同一主题与同一检查 |
| 导出 | `_export_revision` → `rebuild_edited_manifest`：正文中的图必须是 manifest 已登记的图，否则抛 `report_artifact_chart_invalid`（追溯降级、照常签发）；`_copy_revision_assets` 复制登记图片 | 新增“改图登记”来源，使改后的图进入新 revision 的 manifest 与追溯索引 |
| 脚本归档 | `ChartTraceV1.scriptFileResourceId` 字段存在，但生成阶段未登记脚本 | 改图登记其脚本，追溯可看到生成代码 |

## 3. 用户流程

1. 用户把光标放在图上或悬停图片，图片工具条出现「AI 改图」（也可从右键菜单 / 斜杠菜单进入）。
2. 弹出改图面板：显示当前图缩略图、所属分析与数据范围摘要，输入框 + 快捷指令（换图形、排序、显示数值标签、只显示部分分组、改标题/坐标轴、调色、加对比期间）。
3. 提交后面板显示进度（理解要求 → 准备数据 → 绘图 → 检查），可取消。
4. 完成后进入**改图审阅卡**：
   - 左右对比原图与新图（窄屏上下排列）；
   - 变更清单：图形变化（类型、排序、样式），数据变化（“作图数据未变”或列出新增/移除的登记数据项）；
   - 标题、图注的文字差异；
   - 软告警（视觉审查问题、范围提示、图注数字核对结果）——只提示，不阻止接受；
   - 操作：接受替换 / 放弃 / 继续调整（在本次结果上追加要求，多轮对话）。
5. 接受后替换正文中的图片节点（路径、alt），图注改动一并写入，进入正常自动保存；可用编辑器撤销恢复原图。
6. 导出时改后的图登记进新 revision，来源面板中该图显示“编辑器 AI 改图”、用户要求摘要、作图数据与脚本。

**不可用时的提示**（按钮置灰并说明原因，而非报错）：来源已过期（`snapshot_expired`）、该图没有登记作图数据（旧报告 / `plotDataKind` 为空）、只读或受限会话、功能开关关闭。

## 4. 改图分级

模型先把用户要求归为三级，决定后续路径：

| 级别 | 含义 | 示例 | 数据处理 |
| --- | --- | --- | --- |
| L1 呈现 | 只改外观，作图数据不变 | 换图形、排序、配色、数值标签、坐标轴/单位显示、图例位置、标题、只显示前 N 组（明确标注为子集） | 直接使用原 chart-input 文件 |
| L2 换绑 | 换用该分析已登记的另一组数据 | 换维度（按科室 → 按收入类型）、加入已登记的同比 / 预算对比、换期间序列 | 新 `dataBindings` 必须来自同一分析的签发目录，经同一校验后由服务端重新物化 chart-input |
| L3 超出 | 需要未登记的计算或数据 | 新口径、跨分析拼算、未拆分的维度、预测 | 不作图；返回原因与可行建议（如“该维度未拆分，可在重新生成报告时增加此分析”） |

一次要求可同时含 L1 与 L2；含 L3 的部分说明后跳过，其余照常执行。

## 5. 架构

### 5.1 组件

```
前端 chart-ai-edit.ts ──HTTP──> report_editor/api.py
                                   │
                                   ▼
                         report_editor/chart_ai.py  (ChartAIEditService)
                                   │  Agno Workflow：plan → bind → materialize → draw → inspect → register
             ┌─────────────────────┼──────────────────────────────┐
             ▼                     ▼                              ▼
 chart_inputs / 绑定目录与校验   code_agent（CodeMode write_script/run）   host_workspace.inspect_chart_file / aview_image
 （复用生成阶段实现）            （仅 Matplotlib，报告视觉主题）            （确定性检查 + 视觉回执）
```

- 新模块 `smart_reporting/report_editor/chart_ai.py`，执行链用 Agno Workflow Steps 编排（遵循“agno 框架内支持优先”），不另造调度。
- 生成阶段需要复用的纯函数从 `analysis.py` / `visualization_section_workflow.py` 抽到可共享位置：
  - 由事实文件计算 `dataDescriptors`（含 `_breakdown_descriptors`）；
  - 绑定目录构建与 `_validate_visualization_plan_bindings`；
  - `_ranked_detail_scope_issues`。
  编辑器与生成阶段使用同一份实现，避免两套规则漂移。

### 5.2 执行步骤

1. **plan**：结构化输出 `ChartEditPlan`。输入：用户要求（不可信文本）、原图元数据（标题、图注、`AnalysisChart` 语义字段）、原作图数据摘要（列与行数、前若干行）、该分析的签发 `dataDescriptors`、上一轮结果（多轮时）。输出：级别、新 `ChartDraft` 语义字段（标题、altText、visualForm、比较类型等）、新 `dataBindings`（L2）、L3 跳过说明、拟改图注。模型可看原图（`aview_image`），以保持风格一致。
2. **bind**（仅 L2）：用签发目录校验绑定；不在目录中的绑定一律拒绝使用（安全边界，fail closed），该部分要求按 L3 说明。排序子集范围问题沿用 `_ranked_detail_scope_issues`，作为软告警写入结果。
3. **materialize**：L1 直接引用原归档 chart-input；L2 由服务端 `chart_inputs` 重新物化到改图工作目录。脚本只能读取这些文件。
4. **draw**：CodeMode 写 Matplotlib 脚本并执行，输出路径由服务端指定。沿用生成阶段的禁止路径操作检查、执行修复上限（3 次）与报告视觉主题（`REPORT_VISUAL_THEME`）。只认 provider 返回的结构化 `custom_tool_call`，`write_script`/`run` 保持原生 free-form（AGENTS CodeMode 约束）。
5. **inspect**：`inspect_chart_file` 确定性检查（解码、尺寸、空白等，失败即本次改图失败并给出原因）；`aview_image` 视觉审查生成回执。视觉问题为软告警，可触发一次自动修复，修复后仍有问题则带告警交付审阅。
6. **register**：写入改图登记记录（5.3），返回预览。图注如含数字，必须使用登记数值引用，并用 `statement_review_warnings` 核对，结果作为软告警。

### 5.3 改图登记（draft 侧车）

与草稿同目录新增 `.chart-edits.json`（与现有 draft origin 记录同一锁 `_draft_lock`、同一写入方式），每条记录：

```json
{
  "editId": "cedit-…",
  "chartId": "原图 chartId",
  "baseImagePath": "原图路径（多轮时为上一轮新图路径）",
  "instruction": "用户要求（截断存档）",
  "level": ["L1", "L2"],
  "image": {"path": "…/chart-edits/<editId>/chart.png", "size": 0, "sha256": "…"},
  "script": {"path": "…/chart-edits/<editId>/chart.py", "size": 0, "sha256": "…"},
  "plotDataFiles": [{"path": "…", "size": 0, "sha256": "…"}],
  "dataBindings": [{"analysisId": "…", "factPath": "…", "dataPath": "…", "fields": ["…"], "role": "…"}],
  "chart": {"title": "…", "altText": "…", "visualForm": "…", "citationIds": ["…"], "sourceDatasetId": "…"},
  "visualInspectionReceipt": {},
  "warnings": ["…"],
  "skipped": [{"request": "…", "reason": "…"}],
  "status": "succeeded",
  "createdAt": "…",
  "userId": "…"
}
```

- 图片、脚本、作图数据写入不可变路径（`chart-edits/<editId>/`），身份即登记身份。
- **不需要单独的“接受”接口**：接受只是前端把正文图片换成新路径并照常保存；登记记录中被正文引用的那条即为采用的版本，未被引用的在导出或修订清理时回收。避免“接受状态”与正文不同步。

## 6. 接口

| 方法 | 路径（前缀 `/reports/v1/editor/{report_id}/{revision}/api`） | 说明 |
| --- | --- | --- |
| POST | `/charts/{chart_id}/ai-edits` | 请求体 `{instruction, baseImagePath?, previousEditId?, expectedSha256}`；需写权限与 CSRF；返回 202 `{editId}` |
| GET | `/charts/{chart_id}/ai-edits/{edit_id}` | 状态 `queued/running/succeeded/failed/cancelled`、阶段进度；成功时返回预览资源路径、变更清单、拟改标题/图注、告警、跳过说明 |
| POST | `/charts/{chart_id}/ai-edits/{edit_id}/cancel` | 取消运行中的改图 |
| GET | `/asset/{path}`（现有） | 扩展：除 `job.render.images` 外，同一 report/revision 的改图登记中、哈希一致的 PNG/JPEG 也放行 |

- 后台任务与轮询沿用导出的 `start_export` / `export_status` 模式（长任务不占同步请求）。
- 错误码沿用 `ReportingError` + `_editor_http_error` 映射，例如 `report_editor_chart_ai_unavailable`、`report_editor_chart_ai_busy`、`report_editor_chart_ai_timeout`。

## 7. 导出与追溯

在 `_export_revision` 中：

1. 解析正文图片路径；不在 manifest 中的路径到改图登记中查找（记录状态 `succeeded`，图片、脚本与作图数据哈希都一致）。
2. 命中的生成 `ChartArtifact`（`renderer="matplotlib"`，无交互规格）交给 `rebuild_edited_manifest`（新增参数 `edited_charts`），并生成 `ChartTraceV1`：
   - `imageFileResourceId` / `plotDataFileResourceIds` / `scriptFileResourceId` 指向复制到新 revision 目录的文件；
   - `datasetIds` 由绑定的事实文件与 citation 映射得出；
   - `transformNotes` 记录“编辑器 AI 改图：<要求摘要>”与跳过说明。
3. `_copy_revision_assets` 一并复制改图文件；`job.render.images` 加入新图登记。被替换的旧图若不再被正文引用，按现有规则不进入新 manifest，其 `interactiveCharts` 映射也随之不再生效。
4. **非阻断（AGENTS 发布契约）**：改图登记读取失败、哈希变化、追溯快照失败，只把原因写入 `validation.issues` 或 lineage issue 并放弃使用该追溯数据；已核验身份的 PDF/Word 照常签发，不能用 `raise` 终止签发。只有图片本身无法核验身份时，该图不能进入渲染（与现有 `report_editor_asset_changed` 规则一致），原因同样随结果返回。
   - 本链路新增的可能失败步骤，须在 `test_http_publication_lineage.py` 故障注入用例中登记；新增签发函数登记到 `_SIGNING_CHAIN`。

## 8. 校验与告警口径

| 类别 | 处理 |
| --- | --- |
| 路径、身份、作用域（绑定不在签发目录、文件哈希变化、跨 report/revision 引用、脚本越权路径） | fail closed：拒绝使用对应数据；改图任务按失败或 L3 说明返回 |
| 图片确定性检查失败（无法解码、空白） | 本次改图失败，返回原因，原图不受影响 |
| 视觉审查问题、排序子集范围、图注数字核对、标题与数据不一致等语义问题 | 软告警：审阅卡展示，不阻止接受与导出 |

## 9. 安全与资源

- 用户要求是不可信文本：只作为 `<user_instruction>` 数据传给模型，系统指令声明其不能改变工具、路径与数据范围。
- 代码只在该报告工作区的改图目录执行，只读改图作图数据，不联网；输出路径、文件名由服务端分配。
- 限流：同一图同时只允许一个运行中的改图；每会话每小时改图次数上限（配置项）；单次墙钟超时（建议 180 秒），超时取消并返回原因。
- 模型与思考预算沿用可视化脚本的路由（`select_reporting_thinking(operation="visualization_script")`），预算计入工具预算台账。
- 功能开关 `REPORT_EDITOR_CHART_AI_ENABLED`，默认关闭，按环境灰度。
- 日志用 loguru：`report_editor_chart_ai_started/succeeded/failed`，带 `report_id`、`revision`、`chart_id`、`edit_id`、级别、耗时、失败码；不记录用户要求全文。

## 10. 前端

- 新模块 `frontend/src/chart-ai-edit.ts`（面板、轮询、审阅卡）与对应测试；图片工具条入口挂在现有图片预览（`createImagePreview`）与证据定位（`findEvidenceChartImage`）能力上。
- 接受替换用一次 Milkdown 事务修改图片节点 `src`/`alt` 与图注段落，确保撤销一步恢复；审阅期间暂停该节点的自动保存，与现有 `editReviewObserver` 的“审阅结束才保存”一致。
- 审阅卡可访问：焦点陷阱（`focus-trap`）、键盘操作、对比图提供文字说明（标题 + 变更清单）；移动端上下排列。
- 改后的图不做交互增强（Plotly 已弃用）。

## 11. 测试

- 后端单测：
  - L1 / L2 / L3 分级与跳过说明；
  - 不在签发目录的绑定被拒绝使用；
  - 改图登记的锁与原子写；
  - `read_asset` 对改图图片的哈希放行与拒绝；
  - 超时与取消；
  - 视觉问题只出软告警。
- 导出：
  - 改后的图进入新 manifest 与 `ChartTraceV1`（含脚本）；
  - 改图登记损坏 / 哈希变化时，照常签发 PDF/Word 并返回原因（加入故障注入用例）；
  - 8 条非阻断回归契约保持通过。
- 前端 Vitest：入口可用性与禁用原因、进度与取消、审阅卡对比与告警、接受替换与撤销、多轮调整。
- 真实链路冒烟：在可用渲染环境用真实报告完成一次 L1 与一次 L2 改图并导出，核对 PDF/Word 中的图与来源面板。

## 12. 分期

1. **P1**：L1 呈现类改图全链路（改图登记、接口、前端审阅、导出登记与追溯、非阻断）。
2. **P2**：L2 换绑（共享绑定目录与物化、变更清单中的数据差异）。
3. **P3**：多轮调整体验、快捷指令按图形推荐、改图历史在来源面板中展示。

## 13. 待确认

- 每会话改图次数上限与单次超时的具体数值。
- 图注自动改写的默认行为：默认只建议、由用户勾选采用，还是随图一起进入审阅（本稿为后者）。
- 无作图数据的旧报告图：是否允许仅凭原图做 L1 改图（无法保证数值一致，本稿为不允许）。
