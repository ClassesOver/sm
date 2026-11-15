# 四格式 AI 源工具接线矩阵（首轮）

日期：2026-11-13。源固定为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本表核对四个主声明文件的 104 个工具名称，另含 PPTX 附件工具；**声明数不代表能力数或完成比例**。源运行时附加技能、条件注册、各工具参数与 DSL 操作仍须继续核对，不据此声称穷尽源能力。

本地“候选”表示复用原生引擎预览及显式采纳，不表示已保存；手工工具存在也不表示 AI 已接线。真实模型、ScriptedModel、浏览器夹具与生产端到端分别计算。

## Word

源：`apps/docs/src/renderer/ai/tools.ts`。本地主要为 `native_word_ai.py`、`native_word_review_ai.py`、`native_word_notes_ai.py` 和 `native_word_read_ai.py`。

| 源工具 | 本地接线与剩余工作 |
| --- | --- |
| `get_document_context`、`read_blocks` | 已注册授权读取与分页；正文编辑与只读任务分别存在，不能扩大选区或访问未授权资料。 |
| `insert_content`、`write_document`、`replace_blocks`、`replace_selection`、`apply_ops` | 部分语义通过 `propose_operations` 的段落／单格／表格操作表达；没有源完整内容模型、整文重写与所有复合操作的等效证明。 |
| `read_revisions`、`accept_changes`、`reject_changes` | 通过授权 `read_review_targets` 与 `resolveTextRevision` 候选覆盖部分正文修订；非同名完整源工具，复杂修订仍开放。 |
| `read_comments`、`reply_comment`、`resolve_comment` | 授权根线程及历史回复读取、回复／解决候选已有专项；使用 `read_review_targets` 和本地原生操作适配，不能视为整文所有批注权限。 |
| `insert_footnote`、`insert_endnote`、`delete_note`、`edit_note`、`read_notes` | 已注册专用工具，受明确注释或引用锚点授权、分页及来源 hash 约束；保持专项边界。 |
| `add_comment`、`delete_comment` | 手工功能不能代替 AI 接线；当前 Word AI 操作集合未开放这两个完整源语义。 |
| `web_search`、`image_search`、`analyze_media`、`insert_image`、`generate_image` | 当前原生 Word planner 未注册；需要复用受控检索／素材／媒体服务及权限、引用、候选与保存链。 |
| `insert_chart`、`edit_chart`、`set_header_footer`、`create_document` | 当前原生 Word planner 未注册源完整工具；现有引擎或报告生成能力不作为 AI 工具完成证据。 |

## XLSX

源：`apps/sheets/src/renderer/ai/tools.ts` 及 `ai/prompts/guides/*.md`。本地主要为 `workbook_ai_tools.py`、`workbook_ai_charts.py`、`workbook_native_ai.py`。

| 源工具 | 本地接线与剩余工作 |
| --- | --- |
| `get_workbook_context`、`read_range`、`aggregate_range`、`load_guide`、`read_formats`、`read_sheet_features`、`read_cells`、`find_cells`、`trace_precedents`、`trace_dependents` | 已注册冻结草稿的范围受控工具；各参数、错误与动态引用语义仍须逐源核对，不能仅按名称关闭。 |
| `propose_operations` | 已注册真实引擎预览；支持单元格 DSL 与部分原生格式／表格／筛选／透视操作。**必须按 DSL 操作逐项对照**。 |
| `select_range` | 尚无独立 AI 导航回执与前端采纳导航协议。 |
| `create_document` | 未接源新文档任务；现有保存新修订不等同新文档创建。 |

图表来源子链已交付：源 `add_chart(dataRange, anchorCell?)`、`edit_chart(seriesData)` 经 `applyChartSource` 按重放时实际工作表生成引用及缓存，拒绝模型自填缓存；限整簿授权、2000 格与可信目标，不与结构操作混批。此前纯数值分类引用及环形图多系列两项失败已修，25 项引擎／5 项手工入口／15 项 Python 专项通过；final8 ScriptedModel 浏览器拒绝／采纳、UndoRedo、草稿恢复与两次保存下载重开通过，172 份资产身份匹配。真实 provider 新增与换绑均通过标题／引用／缓存独立回读，与浏览器证据分别登记。原失败日志保留；单点折线无可见标记、完整图表视觉及生产真实模型浏览器同链仍开放，见[来源图表专项](NATIVE_XLSX_AI_CHART_SOURCES_ACCEPTANCE_20261113.md)。新增 shape／image／sparkline 等语义仍未接全。现有推荐图表、限定对象几何属于手工交付，不重列全缺，也不外推为全部 AI 已交付。

## PDF

源：`apps/pdf/src/renderer/ai/tools.ts`。本地主要为 `native_pdf_ai.py`、`native_pdf_review_ai.py`、`native_pdf_form_ai.py` 及对应任务服务。

| 源工具 | 本地接线与剩余工作 |
| --- | --- |
| `read_pages`、`search_text`、`read_annotations`、`get_outline` | 已有来源绑定只读工具，批注处理复用读取；草稿页身份与合并／拆分映射继续按现有边界。 |
| `markup_text`、`reply_note`、`edit_text` | 部分语义经批注任务的 `propose_markup`、`propose_reply`、`propose_replace_text` 及原位选区候选表达；不是所有页面通用源编辑工具。 |
| `delete_markup` | 已注册批注任务工具，限可信标注身份、相关页读取及明确删除要求。 |
| `list_form_fields`、`apply_ops` | 已注册表单填值工具，限授权字段与实际引擎支持；不是全部页面、对象、表单设计操作。 |
| `goto_page` | 未接独立 AI 页导航回执。 |
| `add_note`、`edit_note`、`delete_note` | 当前批注 planner 未完整注册；已有手工便签／草稿便签不作为这三工具完成证据。 |
| `edit_block`、`move_text_block`、`insert_text`、`add_form_mark`、`list_inserted_text`、`edit_inserted_text`、`move_inserted_text`、`delete_inserted_text` | 当前原生 AI 未完整接入；需明确原文字块与新增 overlay 的身份及组合生命周期。 |
| `image_search`、`generate_image`、`list_page_images`、`insert_image`、`transform_image`、`rotate_image`、`replace_image`、`flip_image`、`set_image_opacity`、`crop_image`、`remove_image_background`、`delete_image` | 当前原生 AI 未完整注册。已有手工图片能力仅能作为可复用引擎基础；素材来源、图像目标与候选必须分别授权。 |
| `insert_blank_page`、`set_page_size`、`crop_pages`、`extract_pages`、`split_pdf`、`split_pages`、`merge_pages`、`replace_pages` | 当前 AI 工具链未完整注册。手工页面操作不等同 AI 已支持；多产物、第二来源与页身份映射需要完整闭环。 |
| `set_watermark`、`set_header_footer`、`create_document` | 当前 AI 工具链未注册完整源语义；不能以手工入口或报告生成替代。 |

OCR 继续遵守此前用户排除范围，不因源其他代码存在而自动加入本目标。

## PPTX

源：`apps/slides/src/renderer/ai/slides-skill.ts`，附件另见 `files-skill.ts`。本地主要为 `slides_ai_tools.py`、`slides_ai_native_operations.py`、`slides_native_ai.py`。

| 源工具 | 本地接线与剩余工作 |
| --- | --- |
| `read_slide` | 已注册选定对象／整稿／备注等任务的分页读取；图表缓存与表格只读已有专项，图片视觉不据此计入。 |
| `apply_ops`、`edit_chart` | 部分语义经 `propose_operations` 的文字、几何、页序、主题、授权表格格位、可信可编辑图表和备注候选表达；不是源全部对象操作。 |
| `execute_slide_script` | 未提供源等效脚本任务；需在既有 Agno 工作区／任务授权中实现受控能力，不能执行 assistant 正文中的伪工具调用或直接开放任意脚本。 |
| `web_search`、`image_search`、`generate_image`、`analyze_media`、`insert_web_image`、`replace_image` | 当前原生 planner 未注册完整工具链；手工插图及图片引擎能力不算 AI 接线。 |
| `ask_clarification` | 尚无独立可恢复的澄清等待／继续任务协议；回答文字中的澄清不等同该生命周期。 |
| `plan_deck`、`regenerate_slide`、`generate_deck` | 尚无源等效规划／生成／单页重生成闭环；已有报告 PPTX 生成不能外推为此工具完成。 |
| `save_style_template`、`list_style_templates`、`load_guide` | 当前原生 toolkit 未注册这套源模板库／指南工具。 |
| `read_attachment`（`files-skill.ts`） | 未在当前原生 PPTX toolkit 中接入附件阅读；后续必须复用受控工作区注册与授权输入，不暴露任意路径。 |

## 共用生命周期与后续顺序

1. 已有共用 Agno 原生事件观察、SSE 有界历史与前端进度；本轮补终态封口、重连重置、提前取消和关闭边界，证据见 [生命周期专项](NATIVE_AI_TASK_LIFECYCLE_ACCEPTANCE_20261113.md)。
2. 选区编辑本轮补请求 ID 幂等与启动期间取消；XLSX／PPTX 和阅读任务沿用原请求协议。
3. XLSX 数据来源驱动的新增／换绑图表协议及保存子链已有分层证据，视觉边界仍保留；继续 PDF 通用对象工具、PPTX 媒体／整稿任务与持久任务基础，每项继续补参数／操作矩阵与真实引擎证据。
4. 当前原生 AI job、事件历史仍在内存，服务重启恢复未完成。`task_execution` 已有仓储、租约、取消与回执，须先核对原生文档 context 与组织／用户／工作区绑定后复用；文件修订持久化不证明 AI 执行可恢复。
5. 完整目标仍开放：所有源工具语义、复杂对象、可恢复长任务以及生产数据库／真实 provider／显式采纳／保存下载／重开的同一链验收均未被本轮替代。
