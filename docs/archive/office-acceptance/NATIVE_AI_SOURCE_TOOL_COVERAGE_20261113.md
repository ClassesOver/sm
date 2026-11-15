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
| `select_range` | XLSX 阅读与原生候选编辑助手均已接可信 navigation_requested 回执及真实网格定位；候选助手支持纯定位且不产生可采纳的空修改。静态只读视图与来源立即回执仍待对齐。见[阅读导航](NATIVE_XLSX_AI_NAVIGATION_ACCEPTANCE_20261115.md)及[候选导航验收](NATIVE_XLSX_AI_CANDIDATE_NAVIGATION_ACCEPTANCE_20261115.md)。 |
| `create_document` | 未接源新文档任务；现有保存新修订不等同新文档创建。 |

图表来源子链已交付：源 `add_chart(dataRange, anchorCell?)`、`edit_chart(seriesData)` 经 `applyChartSource` 按重放时实际工作表生成引用及缓存，拒绝模型自填缓存；限整簿授权、2000 格与可信目标，不与结构操作混批。此前纯数值分类引用及环形图多系列两项失败已修，25 项引擎／5 项手工入口／15 项 Python 专项通过；final8 ScriptedModel 浏览器拒绝／采纳、UndoRedo、草稿恢复与两次保存下载重开通过，172 份资产身份匹配。真实 provider 新增与换绑均通过标题／引用／缓存独立回读，与浏览器证据分别登记。原失败日志保留，完整图表视觉及生产真实模型浏览器同链仍开放，见[来源图表专项](NATIVE_XLSX_AI_CHART_SOURCES_ACCEPTANCE_20261113.md)。新增 shape、image 等语义仍未接全。现有推荐图表、限定对象几何属于手工交付，不重列全缺，也不外推为全部 AI 已交付。

2026-11-15 补齐 `add_sparkline`。整簿授权下支持线形、柱形和盈亏图，可指定颜色与起始格，也可放在来源右侧。每行生成一个迷你图，最多取前 200 行。复用原生 `appendSheetSparklines` 写入 Excel x14 记录，保留候选预览、显式采纳与保存链路。单点折线的同表换绑已通过保存下载重开复测，见[来源图表专项](NATIVE_XLSX_AI_CHART_SOURCES_ACCEPTANCE_20261113.md)。

柱形迷你图浏览器验收使用 `WORKBOOK_AI_CHARTS_SPARKLINE=1` 运行 `frontend/smoke/workbook-ai-charts-smoke.mjs`。Edge 经实际 HTTP、Agno 工具与 XLSX 写入器完成采纳、撤销重做、草稿恢复及修订 4→5 的下载重开。画布在采纳、草稿恢复、下载重开三处均为 B8 和 B9 各绘制两根格内柱。独立回读确认 x14 引用与颜色、两张原图、源数据和手工加粗。验收仍返回 `native_source_review_pending`，实际文件照常签发。验收使用 ScriptedModel 与内存修订仓储，证据位于 Windows `%TEMP%/genoffice-ai-sparkline-edge`。

XLSX 图表删除也接受源 DSL `delete_visual(visualId)`。目标使用冻结草稿中的唯一 `chartPath`，所属工作表由草稿解析。与原生图表删除共用候选及保存链路，尚未覆盖形状和图片的 `visualId`。

XLSX 编辑工具接入 `set_range` 和 `clear_range`。矩形写入可使用起始格或同尺寸范围，支持公式和空值。单元格级操作每批最多展开 2000 格。大范围清空每项最多覆盖 200000 格，写入器只修改实际有内容的单元格，保留样式和范围外的共享公式。选区授权检查整个目标矩形，浏览器候选显示工作表和待清空范围。纯单元格源操作中，后续条件写入按同批变更后的值和公式核对，包括大范围清空。

XLSX `add_chart` 接入本地 GenOffice 参考源码 `19a389b3` 的 `columns` 参数。第一列作为分类，后续列按传入顺序作为系列。首行作为表头，列可不相邻，XLSX 引用及缓存由实际工作表生成。回读覆盖分类列 C 和系列 D、B，保持原数据范围决定的默认锚点。

XLSX `add_table` 接到原生 Excel 表格写入器。表头从操作重放时的草稿读取，空白补为 `ColumnN`，重复名补数字后缀，并同步表头格与表格列名。支持默认全簿唯一名称、显式名称、内置样式与隔行底纹。尚无法核实实时计算值的公式表头会保留原样并拒绝该候选。

表格浏览器验收使用 `WORKBOOK_AI_CHARTS_TABLE=1` 运行 `frontend/smoke/workbook-ai-charts-smoke.mjs`。Edge 在采纳后、草稿恢复后和下载重开后均从表格设计页读到 Revenue。撤销会移除表格。独立回读确认 A1:B3、内置样式、隔行底纹关闭、人工加粗、两张原图及源数据。修订 4→5 的验收返回 `native_source_review_pending` 并照常签发实际下载。首次构建主引擎块为 431.0 KiB；拆出表格写入模块后为 414.1 KiB，预算保持 428 KiB。拆分后用同一 XLSX 零保存复验，305 个实际资源通过身份校验。两次证据位于 Windows `%TEMP%/genoffice-ai-table-edge` 和 `%TEMP%/genoffice-ai-table-reopen-final`，使用 ScriptedModel 和内存修订仓储。

XLSX `set_hyperlink` 接到既有超链接写入器，支持网页地址、工作簿内部位置以及传 `null` 移除链接。沿用手工插入链接的地址规范化和目标校验，保留原值或公式及其他格式，只更新链接本身、字体颜色和下划线。现阶段需要整簿授权。

XLSX `set_freeze` 在整簿授权下复用原生工作表视图写入器。行列从左上角计数，各支持 0–100，两个零取消冻结。独立回读覆盖仅冻结行、仅冻结列、同时冻结和取消冻结，并确认网格线设置和单元格内容仍在。

XLSX `move_sheet` 接到原生工作表顺序写入器，标签位置从 1 开始。同一候选的多个移动依次应用。回读验证活动工作表、局部名称及跨表公式仍指向原工作表，所有工作表部件保持字节一致。

XLSX `add_sheet`、`rename_sheet` 和 `delete_sheet` 接到原生结构写入器，可与 `move_sheet` 在同一工作表结构候选中顺序执行。按当前工作表名寻址；重命名更新跨表引用，仍被引用的表由引擎拒绝删除。新建使用 Excel 空白工作表，桌面临时网格的 rows／columns 参数未接入。

XLSX `set_page_setup` 接到原生打印设置写入器，支持纸张、方向、缩放或按页适配、边距、打印网格线和标题、打印区域、重复行列、页眉页脚及手动分页。只改某一适配轴时保留另一轴的已知设置。Excel 重复标题保存为带工作表限定的行列引用。

XLSX `set_note` 在整簿授权下更新 Excel 旧式单元格备注，`null` 删除。每步从当前重放文件核对备注身份，替换文字时保留原作者，模型参数只提供地址和文字。沿用写入器对线程批注与带图备注的限制。

XLSX `refresh_pivot` 接到按工作表限定的原生刷新。透视表从操作重放时的源数据更新，其他工作表的独立缓存和输出保留。跨表共享缓存会拒绝单表刷新。现有全簿刷新继续可用；无法在编辑器内重建输出的外部透视表仍沿用 Excel 打开时重算的缓存路径。

XLSX `set_row_height` 和 `set_col_width` 在整簿授权下复用原生尺寸写入器。行号从 1 开始，列号使用字母，省略 `count` 时只调整一行或一列。尺寸按源执行器取整到像素。网页版 XLSX 写入器最多保存 255 字符列宽，对应 1790 像素，源 DSL 接受的超限值会明确拒绝。

XLSX `find_replace` 在授权范围内按顺序重放，支持区分大小写和整格匹配。原生引擎扫描最多 200,000 格的范围，仅改写匹配的已有文本，保留单元格样式，并跳过公式、数字、布尔值和 Excel 错误值。富文本匹配后写回纯文本，沿用源操作语义。

XLSX `set_sheet_hidden` 接到原生工作表结构写入器。隐藏当前工作表时，活动标签转到可见工作表。独立回读验证跨表公式和工作表部件保留，并覆盖拒绝隐藏最后一张可见表、显示 `veryHidden` 表、修改受保护结构和从选区授权修改整表。

XLSX `set_rows_hidden` 和 `set_cols_hidden` 复用原生分组写入器，仅更新指定跨度内的可见性。独立回读覆盖按列拆分已有分组、保留行高和列宽、保留折叠状态及同批隐藏和显示操作。

XLSX `set_data_validation` 支持内联列表、同表范围列表、数值区间、日期区间、复选框、自定义公式和清除。每项操作从当前草稿包读取规则，裁去目标区域，并按新的首格平移剩余规则的相对引用。无法以 Excel 内联格式表示的列表应使用同表范围，既有规则无法完整读取时拒绝覆盖。

XLSX `add_conditional_format` 支持桌面源协议的八类规则。新增保留已有规则及优先级；`clear_conditional_formats` 清除指定工作表的全部可编辑规则，对含有无法安全移除的 Excel 扩展规则的工作表拒绝清除。数据条沿用网页引擎的基础 OOXML 格式，使用一个颜色。

## PDF

源：`apps/pdf/src/renderer/ai/tools.ts`。本地主要为 `native_pdf_ai.py`、`native_pdf_review_ai.py`、`native_pdf_form_ai.py` 及对应任务服务。

| 源工具 | 本地接线与剩余工作 |
| --- | --- |
| `read_pages`、`search_text`、`read_annotations`、`get_outline` | 已有来源绑定只读工具，批注处理复用读取；草稿页身份与合并／拆分映射继续按现有边界。 |
| `markup_text`、`reply_note`、`edit_text` | 部分语义经批注任务的 `propose_markup`、`propose_reply`、`propose_replace_text` 及原位选区候选表达；不是所有页面通用源编辑工具。 |
| `delete_markup` | 已注册批注任务工具，限可信标注身份、相关页读取及明确删除要求。 |
| `list_form_fields`、`apply_ops` | 已注册表单填值工具，限授权字段与实际引擎支持；不是全部页面、对象、表单设计操作。 |
| `goto_page` | 已接阅读助手的可信待定位回执与真实页面跳转，核验草稿页面映射、当前视图和实际可见性后确认；与助手 UI 同步验收，见[PDF 导航专项](NATIVE_PDF_AI_NAVIGATION_ACCEPTANCE_20261115.md)。桌面即时回执仍为网页异步适配。 |
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
| `load_guide` | 已注册源 groups 枚举，完整返回六组固定源指南，顺序去重；原文与原生权限／单位适配说明分别返回。见[PPTX 指南验收](NATIVE_PPTX_AI_GUIDES_ACCEPTANCE_20261115.md)。 |
| `save_style_template`、`list_style_templates` | 当前原生 toolkit 未注册这套源模板库工具。 |
| `read_attachment`（`files-skill.ts`） | 未在当前原生 PPTX toolkit 中接入附件阅读；后续必须复用受控工作区注册与授权输入，不暴露任意路径。 |

## 共用生命周期与后续顺序

1. 已有共用 Agno 原生事件观察、SSE 有界历史与前端进度；本轮补终态封口、重连重置、提前取消和关闭边界，证据见 [生命周期专项](NATIVE_AI_TASK_LIFECYCLE_ACCEPTANCE_20261113.md)。
2. 选区编辑本轮补请求 ID 幂等与启动期间取消；XLSX／PPTX 和阅读任务沿用原请求协议。
3. XLSX 数据来源驱动的新增／换绑图表协议及保存子链已有分层证据，视觉边界仍保留；继续 PDF 通用对象工具、PPTX 媒体／整稿任务与持久任务基础，每项继续补参数／操作矩阵与真实引擎证据。
4. 当前原生 AI job、事件历史仍在内存，服务重启恢复未完成。`task_execution` 已有仓储、租约、取消与回执，须先核对原生文档 context 与组织／用户／工作区绑定后复用；文件修订持久化不证明 AI 执行可恢复。
5. 完整目标仍开放：所有源工具语义、复杂对象、可恢复长任务以及生产数据库／真实 provider／显式采纳／保存下载／重开的同一链验收均未被本轮替代。
