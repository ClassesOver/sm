# Word / XLSX 当前缺口索引（非穷尽）

更新：2026-11-11。此索引以更新时共享工作区的实际代码为准，替代早期矩阵的“当前状态”用途；不改写 `NATIVE_WORD_XLSX_PARITY_AUDIT.md`、`NATIVE_RIBBON_COMMAND_AUDIT.md` 的历史。固定源 `/home/junge/pros/genoffice-source-full` HEAD 已只读核对为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

**完整对齐仍未完成。本表非穷尽，不给完成百分比。** 本索引汇总实际代码及分层专项证据；Word 根批注新建与 XLSX 透视表创建/编辑已有真实浏览器保存、下载和重开证据；最新构建入口与资产连续性单独补验，具体范围以专属验收文档为准。既有专项未重复全测，不冒充本次重新验收。调查、按钮标签、永久禁用、manifest/hash 通过都不计功能交付。并行工作会改变状态，以下稳定符号比行号更适合作后续查找。

2026-11-12 增量：XLSX AI 已有图表格式编辑/删除完成冻结目标身份、严格运行时格式校验、真实工具预览与显式采纳；45项专项和真实浏览器两次保存下载重开通过。后续bar方向/负值零线/空值分类已修并通过17项定向及截图像素，见 [画布增量](NATIVE_XLSX_BAR_CANVAS_ACCEPTANCE.md)；标题/网格文字已定位为验收环境字体解析问题并补预检和像素验证，见 [文字预检](NATIVE_XLSX_CANVAS_FONT_ENVIRONMENT.md)。AI 新建图表/替换数据、真实provider整链和复杂样式视觉对齐仍缺。见 [已有图表 AI 验收](NATIVE_XLSX_AI_EXISTING_CHART_ACCEPTANCE.md)。

后续bar/column常见四侧/none图例、可信名称及显式RGB系列色已通过读取/画布与保存重开像素专项，见 [图例验收](NATIVE_XLSX_LEGEND_CANVAS_ACCEPTANCE.md)。非bar/column图例、复杂索引与手动布局、完整轴/标签等不计通过。

路径约定：`F=frontend/src/`（相对此文档）；`D=../reporting/doc_engine/`；`X=../reporting/workbook_engine/`；`U=/home/junge/pros/genoffice-source-full/`。源码路径均指实际文件，不指历史审计中已迁移的 `slides_engine` DOCX 路径。

状态严格区分：

- **本地缺功能**：固定源有入口/实现，本地没有相应可执行闭环；保留旧对象不代表能创建/编辑。
- **源缺功能／源边界**：固定源自身没有对应可保存能力，或实际实现有限制；不得包装成本地迁移完成，也不自动从完整产品目标剔除。
- **既有兼容边界**：已交付功能明确只支持部分对象/来源，范围外保留或只读；不是本轮新引入的已确认回归。
- **进行中／未验收**：已有实现但专项最终验收未完成，或只有有限层次证据。不能计最终完成。

## 可核实的本地剩余功能

| 项目 | 当前状态与实际缺口 | 固定源与本地证据 |
| --- | --- | --- |
| Word 完整段落选项与多级列表 | 固定／最小值及自定义倍数行距已接通：当前可信原有顶层段落支持1–1584pt、0.05pt精度，及0.06–132倍、0.01精度，保留六个快捷预设。已验UndoRedo、草稿恢复及四次真实保存下载重开。绝对首行／悬挂／取消特殊缩进已接通，普通正文／标题单段支持0.05–720pt、0.05pt精度，三次真实保存下载重开已验。首行字符单位也已接通（0.01字符精度、保留原生firstLineChars及草稿／UndoRedo，四次保存下载重开已验）。完整 ParagraphDialog、制表位对话框／引导符编辑以及表格／跨段目标仍未覆盖；标尺制表位已在100%缩放的可信单段范围接通五种类型、增删拖动及保存下载重开；标尺左／首行／悬挂已按无字符缩进的可信单段、单栏、非镜像、LTR范围完成真实拖动及保存下载重开；列表、字符来源及复杂标尺目标仍缺，字符悬挂在固定源也未建模。多级列表库、自定义层级与级间重新开始规则仍为禁用入口，不能把已有普通列表／级别调整当成完整列表能力。 | [行距增量](NATIVE_WORD_LINE_SPACING_ACCEPTANCE.md)、[自定义倍数验收](NATIVE_WORD_CUSTOM_LINE_SPACING_ACCEPTANCE.md)、[特殊缩进验收](NATIVE_WORD_SPECIAL_INDENT_ACCEPTANCE.md)、[字符首行验收](NATIVE_WORD_CHARACTER_INDENT_ACCEPTANCE.md)、[标尺缩进验收](NATIVE_WORD_RULER_INDENT_ACCEPTANCE.md)与[制表位验收](NATIVE_WORD_TAB_STOPS_ACCEPTANCE.md)；`F/docx-special-indent.ts`、`F/docx-line-spacing.ts`、`D/bridge/docx-line-spacing.ts`；`F/docx-home-source.tsx` 的 `list-multilevel-gallery` 仍明确给出未接入原因。 |
| Word 目录、引用与批注增量 | 原生“引用”已接入自动目录插入和更新，条目按已保存标题生成；编辑器当前不缓存目录页码，由 Word 更新目录域。普通正文书签创建、精确定位、删除及独立保存已接通并完成冻结浏览器创建/删除两次保存下载重开；复杂锚点只读。普通书签 REF 交叉引用与图/表/公式 SEQ 题注已完成冻结浏览器 5 次真实保存、下载独立 ZIP/lxml 及明确修订重开；来源身份、独立意图、UndoRedo/草稿均接通。缓存不自动更新，复杂书签和复杂/中间插入编号不在本轮范围，实体语义与核心投影不一致的来源交叉引用明确只读。引文、书目和索引仍未接。已有批注面板新增删除、解决和重新打开可信线程；受保护的仅批注模式、复杂线程与完整批量审阅仍未补齐；可信简单正文修订已支持限定范围的批量接受/拒绝。 | `F/docx-toc.ts`、`D/bridge/docx-toc.ts`、`F/docx-comment-thread.ts`、`D/bridge/docx-comment-thread.ts`；相关动作均需独立保存；新增范围与全局检查限制见 [引用增量验收](NATIVE_WORD_REFERENCES_ACCEPTANCE.md)。 |
| Word 复杂分页与打印一致性 | 已定位并修复宿主内置字体误注入 Word 布局指标导致的行距膨胀；同一 DOCX 冻结构建真实预览由 15 页回到固定 GenOffice 的 10 页；连续四次切片稳定，46 段正文、62 表行和三条注释标记齐全。后续补齐页眉测量作用域、有效画布原点及拉丁字体槽，最终冻结浏览器本样本全部 10 页切片与固定源一致（最大误差低于 1e-6 px）；未保存的页眉、链接与页码状态即时预览也已验收。旧页底叠印／串页为截图越过预览视口的误判，已修正探针。项目 LibreOffice 为 12 页；独立报告 PDF 为 8 页，未包含 DOCX 后加的分栏和注释。仍不能认定所有复杂文档或打印路径均对齐。 | [复杂分页实测](NATIVE_WORD_COMPLEX_PAGINATION_ACCEPTANCE.md)。 |
| Word 嵌套表结构与属性 | 本地缺功能。第一层简单叶格文字已交付；内层行列、合并拆分、表头、宽高、AutoFit、对齐、方向、边距、行跨页、自动换行、Alt text 等不能借外层选区操作。需要专用内层目标与持久化协议。 | `U/apps/docs/src/renderer/editor/extensions.ts` 的 `DocNestedTable` 是 model 输入岛；`U/.../editor/table-ops.ts` 以 PM `docTable`/TableMap 选区工作，源也没有完整内层 Ribbon 编辑语义。`F/docx-tables.ts` 的 `nestedInputActive()` 在各上述入口明确拒绝；[嵌套表验收](NATIVE_WORD_NESTED_TABLE_ACCEPTANCE.md) 的“行为与范围”明确内层结构未实现。不能将本项全部归因于本地漏接一个 callback。 |
| Word 完整文件宿主与打印 | 本地缺完整源文件菜单/宿主等效。报告 shell 保存、新修订下载和 PDF 导出已有功能，不等同打开任意文档、另存为全选项、完整 PrintDialog 与各转换格式。各子项需继续追实际宿主，不按标签全算源已支持。 | `U/apps/docs/src/renderer/components/PrintDialog.tsx`；`U/.../components/Ribbon.tsx` 文件宿主 props；`F/docx-ribbon.ts` 的 `pendingGroups.file` 经 `renderPending()` 无 action 映射而禁用；`F/docx-main.tsx` `onExportPdf` 委托报告 shell。完整范围仍需逐项宿主验收。 |
| Word Draw／Design／Mailings 与复杂对象格式 | 本地缺功能。可核实整个待迁移入口族仍未执行：画笔/擦除、主题与页面背景类、邮件合并、图片/形状复杂格式。不是说所有固定源标签都已有完整落盘实现；对应源每个子功能仍须核验。 | `U/apps/docs/src/renderer/components/Ribbon.tsx` `DRAW/DESIGN/MAILINGS` 相关 tab 与 `IMAGE_TABS/SHAPE_TABS`；`F/docx-ribbon.ts` `pendingGroups.draw/design/mailings/pictureFormat/shapeFormat` 经 `renderPending()` 落入 `migrating`。已有简单插图或图片闪烁修复不能抵消这些缺口。 |
| Word 审阅及部分视图 | 部分闭环已交付、其余仍缺。2026-11-11 新增根批注精确选区创建：跨 run/跨段/内部普通空段、取消、UndoRedo/恢复、保存下载与新修订重开已由 e13de64 冻结构建实际验收；仅 document.xml/comments.xml 变动，详见 [新建批注验收](NATIVE_WORD_NEW_COMMENT_ACCEPTANCE.md)。既有唯一根线程的文字回复已接入真实 parent 关联、同一草稿/历史/未失焦保存/下载和重开；8c3完整浏览器、真实HTTP非阻断、971b状态修复及final4多根空输入切换错投修复窄补验分层记录于 [回复验收](NATIVE_WORD_COMMENT_REPLY_ACCEPTANCE.md)。删除、解决和重新打开已接入可信根线程及直接回复；嵌套回复、复杂锚点及受保护 comments-only 仍未接完整。批注/修订已完成24个源真实保存及ZIP/lxml调查，见 [审阅调查](NATIVE_WORD_REVIEW_INVESTIGATION.md)；顶层简单ins/del逐条接受/拒绝已接宿主、草稿恢复及审阅列表，5次真实浏览器保存下载与新修订重开通过，见 [集成验证](NATIVE_WORD_TEXT_REVISION_INTEGRATION_VERIFICATION.md) 与 [built验收](NATIVE_WORD_TEXT_REVISION_BUILT_ACCEPTANCE.md)。本轮补齐“接受/拒绝所有支持的正文修订”：先全批校验、单 PM 事务、一次UndoRedo、保存下载XML回读与新修订重开通过，复杂修订原样保留。复杂/嵌套/move/属性修订、跟踪新建修订、全文件所有故事的接受全部和完整批注编辑仍缺，不能关闭整个审阅功能族；见 [高优先级验收](NATIVE_WORD_HIGH_PRIORITY_ACCEPTANCE.md)。批注另完成 [身份与扩展保全调查](NATIVE_WORD_COMMENTS_INVESTIGATION.md)：固定源重复身份、跨段回复和 commentsExtended 重写存在边界；已新增严格批注文字编辑纯core及8组专项、实际DOCX独立ZIP/lxml证据，见 [core阶段验收](NATIVE_WORD_COMMENT_TEXT_ACCEPTANCE.md)；只替换 comments.xml 授权片段，保留现代扩展，已新增授权原bytes来源helper（14项专项）及Node inspect/纯批注patch分支（2项真实CLI专项）；Python薄桥及真实发布下载非阻断专项已通过；前端纯intent模块12项、controller8项及main批注6项定向通过；最终构建真实浏览器已通过编辑/UndoRedo/刷新恢复/未blur保存/下载/新修订重开，且仅comments.xml变动；后续3项真实ASGI授权专项已通过：grant/cookie、CSRF/Origin、来源/修订隔离、真实Node引擎预览保存、下载独立回读与验收失败非阻断；仓储仍为内存夹具，不冒充生产DB或浏览器直连真实鉴权整链；已核实最小接入路径及风险，见 [宿主计划](NATIVE_WORD_COMMENT_HOST_PLAN.md)。翻译、比较/保护等仍为待迁移入口；Web/阅读视图和窗口管理未接。标尺已有右缩进/左右边距及后续左／首行／悬挂的限定范围验收，后者真实拖动、原子草稿、保存下载重开已通过；制表位已按100%缩放、已建模绝对来源限定范围验收；非100%缩放／相对／未知属性制表位、字符来源、RTL、列表／表格／跨段、多栏／镜像及其它复杂目标仍只读，见 [制表位验收](NATIVE_WORD_TAB_STOPS_ACCEPTANCE.md)、[标尺缩进验收](NATIVE_WORD_RULER_INDENT_ACCEPTANCE.md)与[标尺与页面验收](NATIVE_WORD_RULER_PAGES_ACCEPTANCE.md)。源24px屏幕辅助网格已接并验收，不等于Word docGrid或表格网格编辑。标题导航窗格与源大纲切换/折叠已按限定范围验收；导航内纯字面搜索已按正文/表格限定范围验收，页面缩略图已按同尺寸单栏整块分页限定范围验收，复杂拆页/混合布局仍缺；标题移动删除升降级仍缺，大纲源 plugin 仅识别 docHeading，不等同导航的样式继承标题。已有 zoom 与分页预览要排除。 | `F/docx-ribbon.ts` `pendingGroups.review/view`；`F/docx-view.ts` 已接 navigation/outline 路由；具体交付及全局检查限制见 [导航大纲与刷新历史验收](NATIVE_WORD_NAVIGATION_ACCEPTANCE.md)，其余 `reason()` 保留未对齐原因。源入口 `U/apps/docs/src/renderer/components/Ribbon.tsx`；不能据 tab 名认定源全部落盘。 |
| XLSX 完整 PrintDialog 与打印渲染等效 | **部分已接通**：File→打印现有 active/selection/workbook 预览、页面导航、隐藏表过滤、跨表连续页码和取消/过期保护；仍缺源完整 `copies/collate/pagesMode`、打印机/PDF host。浏览器负责设备/份数不等于已迁移源宿主。百分比 scale、显式单元格边框及已有文件页眉页脚文字子能力已验收，不能因此关闭整项。 | `U/apps/sheets/src/renderer/PrintDialog.tsx` 的 `range/copies/collate/pagesMode/page/job`、`host.listPrinters/buildJob`；本地 `F/workbook-print-preview.ts` 与 `F/workbook-main.ts` 已接范围预览；页眉页脚图片、部分数值格式与跨页裁切 merge 仍缺。 |
| XLSX 图表创建及编辑 | 九类图表创建已接入现有 OOXML writer：从选区推导表头、分类、系列与引用范围，创建/编辑/删除进入原生草稿和保存协议。Chart Design 已接标题、图表类型、图例位置、分类轴/数值轴标题、数据标签、分组/主网格线格式及单图“选择数据”编辑，按当前工作表唯一可信 `chartPath` 写回；组合图选择数据明确拒绝。带文字表头/分类标签的同表连续矩形已接切换行列及切回，柱/条/线/面积图限定支持；不依赖当前选区并保留未保存数值。已接删除并清理 drawing anchor、relationship、chart part 和 content type override。仍缺多图画布命中选择、推荐图表、完整格式面板和原生 Undo/Redo；复杂来源切换行列及系列扩展保全仍缺，真实浏览器尚未验收。 | `F/workbook-chart-add.ts`、`F/workbook-chart-design-dialog.ts`、`F/workbook-chart-switch.ts`、`F/workbook-main.ts`、`X/packages/xlsx-engine/src/chart-add.ts`、`X/packages/xlsx-engine/src/chart-edit.ts`、`X/packages/xlsx-engine/src/chart-delete.ts`；[图表创建/编辑验收](NATIVE_XLSX_CHART_INSERT_ACCEPTANCE.md)。 |
| XLSX 外部工作簿 picker 与外链管理 | 部分接通：已从当前已授权 XLSX 的 externalLink parts 读取外链索引、opaque URI 和 sheet names；函数参数对话框支持闭合外簿的手工 A1 范围引用。未接其它已打开工作簿的跨窗选择，也未接更新、断链、重定向面板。opaque URI 仅展示，不会访问外部路径。 | `F/workbook-function-runtime.ts`、`F/workbook-function-arguments-dialog.tsx`；GenOffice 的 open-workbook range relay 和 `ExternalLinksPanel` 更新/断链流程仍需各自安全宿主/sidecar 闭环。 |
| XLSX 透视表创建/编辑 | 已有真实闭环：来源表/区域、目标表/锚点、有序多级行列、五种值聚合与格式/百分比、编辑原有定义。e13de64 冻结浏览器已验创建/编辑/取消/UndoRedo/草稿恢复/手工格式保留/保存下载/新修订重开；独立 openpyxl 可读取真实缓存和4条记录。报告筛选/切片器/时间线、分组/计算字段、共享缓存重排、动态表来源跟随尚未接全；源与引擎均有限制列轴只支持单值，不伪装列轴多值。 | F/workbook-pivot.ts、F/workbook-pivot-dialog.ts、F/workbook-main.ts 与既有 xlsx-engine；[透视表验收](frontend/WORKBOOK_PIVOT.md)。原均无 command 的历史状态不再代表当前；平均值标准 OOXML/目标表 xmlns:r/普通导入输出旧尾部修复均有真实回读证据。 |
| XLSX 迷你图、切片器、时间线 | 迷你图新增、按宿主删除和参数组编辑已接通：局部更新 type/color/negativeColor/markers/showAxis，Ribbon 弹窗可编辑并保留目标身份校验，接入 Undo/Redo 和保存；跨表新增仍缺。切片器/时间线已有本地会话筛选入口，可选择透视表行/列字段并保存成员隐藏状态及透视输出；不会生成/保存 OOXML 控件本体，含存量原生控件的工作簿拒绝该入口编辑。 | `F/workbook-sparklines.ts`、`F/workbook-sparkline-dialog.ts`、`F/workbook-ribbon.ts`、`X/packages/xlsx-engine/src/sparkline-additions.ts`、`X/.../sparklines.ts`；本地筛选入口见 `F/workbook-main.ts`、`F/workbook-pivot-filters-dialog.ts`/`workbook-pivot-filters.ts`；源会话浮层见 `U/apps/sheets/src/renderer/pivot-actions.ts` 与 `SlicerPanel.tsx`/`TimelinePanel.tsx`。 |
| XLSX 原生 AI 完整工具与任务流 | 本轮已新增范围/整簿明确授权、冻结人工草稿、Agno候选、真实引擎预览、显式采纳与同一UndoRedo/保存宿主；受限真实provider与openpyxl单格回读已通过。完整源工具、流式任务进度与复杂操作尚未对齐。最终浏览器曾发现旧选择订阅在重建瞬间访问空unit，解绑时序已先RED后GREEN修复；9f184c1e冻结构建严格浏览器pageErrors=[]，人工草稿/明确采纳/UndoRedo/新修订2/实际下载openpyxl回读通过。浏览器route/planner夹具与真实router、provider专项分层，不计完整源AI工具已交付。 | F/workbook-native-ai.ts、F/native-office-view.ts、F/workbook-main.ts、workbook_native_ai.py／workbook_native_ai_api.py；[真实Provider范围](NATIVE_OFFICE_AI_PROVIDER_ACCEPTANCE.md)，当前工作簿验收见 WORKBOOK_NATIVE_AI.md。 |
| XLSX 高级筛选／部分数据导入与连接 | 本地缺功能。普通筛选、排序、去重、模拟运算表、求解/合并计算已有，不能再列整组“数据未实现”；高级筛选明确范围已验收；CSV 导入当前选区已接通；查询与连接只读面板已接通。**合并工作簿已接入口与原子计划器**：追加值/格式/几何/合并区，公式缓存待重算或缺失时拒绝；图表、表对象、外部连接仍不导入。refresh-all 已接透视表实际结果与缓存重算，见专属验收文档。 | `F/workbook-merge.ts`、`F/workbook-main.ts` Data→合并工作簿；复杂对象与外部查询执行仍属后续范围。 |
| XLSX 其他明确禁用项 | 单元格上下标已接入整格读写闭环（OOXML `<vertAlign>`、Univer `s.va`、Ribbon 切换及清除、重开回读）；仍缺受保护可编辑区域、背景图、拆分视口，以及桌面窗口管理。窗口功能需真实 web 等效或用户明确缩减目标；不能因 web host 不同自动算完成。 | `F/workbook-ribbon.ts`、`F/workbook-vendor/core/style-map.ts` 与 `xlsx-engine` 样式读写；固定源相应入口 `U/apps/sheets/src/renderer/ExcelShell.tsx`，其余桌面宿主选项仍需追菜单/API。 |

`action(label,id)` 未传 command 会生成无 `command` 的对象；`F/workbook-ribbon.ts` 渲染时 `item.command === undefined` 永久禁用。因此上表无 command 的判断不是单凭按钮中文文案或 grep 未找到实现。

## 源缺功能／源边界，不能误报为本地漏接

| 项目 | 可核实事实 | 证据与处理 |
| --- | --- | --- |
| Word 整表左缩进可编辑 | 固定源 TablePropertiesDialog 没有左缩进控件；仅通过 generic PM 改 `indentTwips` 的真实保存会恢复原 `tblInd`，源没有这条可保存编辑链。本地已实现整表对齐且保留 raw tblInd；独立编辑 tblInd 仍无协议。 | [对齐／缩进调查](NATIVE_WORD_TABLE_ALIGNMENT_INDENT_INVESTIGATION.md) 的9种真实 direct 向量与 parser-reference-only 区分；`F/docx-table-alignment-core.ts`/`D/bridge/docx-table-alignment.ts` 仅 alignment。需单独范围、协议和验收，不能捆绑称已完成或称源完整支持。 |
| Word 嵌套表完整表格命令 | 固定源 nested 输入岛不是 PM docTable，内部 DOM caret 不会自动变成 TableMap 选区；深层和复杂叶格也非全部可逆。 | `U/apps/docs/src/renderer/editor/extensions.ts` `DocNestedTable` 与 `table-ops.ts`；本地文字链已补独立身份，但不能照搬外层命令得到内层属性能力。 |
| XLSX 切片器／时间线控制本体持久化 | 固定源和本地均有可执行会话控制与透视筛选输出，但不生成/保存 slicer/cache 控件 parts；时间线同为会话状态。完整 OOXML 控制本体持久化不是可直接搬来的源已实现功能。 | `U/apps/sheets/src/renderer/SlicerPanel.tsx:9` TODO 与 `TimelinePanel.tsx:9` 明确说明；本地 `F/workbook-pivot-filters-dialog.ts` 明确提示保存成员选择而非控件本体，含存量控件时拒绝编辑。 |
| XLSX 透视缓存来源范围随行列同步 | 固定源没有通用同步算法，保存时拒绝来源页行列移位；本地已补对应原子保护，不等同实现 worksheetSource.ref/cacheFields 同步。 | [透视来源结构调查及已执行保护验收](NATIVE_XLSX_PIVOT_SOURCE_SHIFT_INVESTIGATION.md)；新增同步必须另做设计和真实文件验收。 |
| XLSX 源打印比例上限不一致 | 源 UI/保存接受10–400%，源 print renderer `MAX_PRINT_SCALE=2` 实际最多200%。这是固定源真实不一致，本地不应为复制该限制而破坏合法保存比例。 | [打印 scale 调查](NATIVE_XLSX_PRINT_SCALE_INVESTIGATION.md) 的实际源20项探针及 renderer 表达式记录；不冒充完整源浏览器/打印机验收。 |
| XLSX 错误检查、公式追踪能力定义 | 固定源错误检查是当前缓存错误导航，不是 Excel 完整语义修复向导；追踪是有限引用收集，不是完整计算依赖图。 | [错误检查验收](NATIVE_XLSX_ERROR_CHECKING_ACCEPTANCE.md)、[公式追踪验收](NATIVE_XLSX_FORMULA_TRACE_ACCEPTANCE.md)；按真实源定义交付，完整 Excel 等价另列范围，不能发明源不存在的菜单来认定迁移缺失。 |

## 既有兼容边界与未验收项

| 项目 | 当前边界／未验收内容 | 证据 |
| --- | --- | --- |
| Word 表格 Alt text | **专项已验收**：统一构建与预算通过，4 来源/4 次真实保存、下载和明确修订重开通过，覆盖缺 tblPr、特殊实体/LF、仅改标题、合并格及 RTL 浮动清空。仍限已授权外层表，不包含嵌套表属性。 | [Alt text 验收](NATIVE_WORD_TABLE_ALT_TEXT_ACCEPTANCE.md)；`/tmp/word-table-alt-built-manifest.json`，121 个实际 JS 身份、errors=[]；root 目视 RTL 浮动重开截图。 |
| XLSX 打印百分比 scale | **专项已验收**：10–400校验、确认式入口与既有 page setup journal 接通；10/100/400三次真实保存下载重开及打印HTML比例通过，关闭fit并保留其它页设置。仍不包含完整 PrintDialog 与打印机验收；边框及已有文件页眉页脚文字另见后续专项。 | [scale 验收](NATIVE_XLSX_PRINT_SCALE_ACCEPTANCE.md)；`/tmp/workbook-print-scale-built.log` exit0，3保存、121实际JS身份、errors=[]；源30pt行对应3/30/120pt，400%为8页。 |
| Word 嵌套文字已支持范围外 | 第一层简单叶格之外，合并、修订、包装/网格映射不可靠、含更深嵌套、tab/段内换行、超预算来源等只读。 | [嵌套表验收](NATIVE_WORD_NESTED_TABLE_ACCEPTANCE.md)，`D/bridge/docx-nested-tables.ts`。属于明确兼容边界，不应再说全部嵌套表不可编辑。 |
| Word 局部格式与清除格式 | 顶层已有局部 run 格式/高亮/上下标、大小写转换和清格式闭环；表格/文本框/页眉页脚子编辑器、含内联对象、新增未保存段落等仍不自动取得相同能力；部分同段文字+格式组合需分次保存。清格式 GUI 的局部/标题/列表/多段只具定向集成/文件证据，未全部逐项真实浏览器验收。 | [清格式验收“尚未覆盖”](NATIVE_WORD_CLEAR_FORMATTING_ACCEPTANCE.md)、[段落格式组合](NATIVE_WORD_PARAGRAPH_FORMAT_COMBINATION_ACCEPTANCE.md)、[大小写与拆分](NATIVE_WORD_XLSX_CASE_SPLIT_ACCEPTANCE.md)。不能沿用早期“局部格式全缺”。 |
| XLSX 公式追踪复杂引用 | 定义名称、结构化、动态引用不完整；跨表只计数，不伪造同表箭头；不可见或复杂 merge 等几何明确不画。 | [公式追踪验收](NATIVE_XLSX_FORMULA_TRACE_ACCEPTANCE.md) 与 `F/workbook-formula-trace.ts`。既有已交付导航边界，完整计算依赖图未交付。 |
| XLSX 监视窗口删表真实菜单路径 | 监视、saved态重开、会话隔离已验收；删表浏览器官方离屏菜单路径尚未通过，仅真实 main facade deleteSheet+Undo 验证 gone 恢复。 | [监视窗口验收](NATIVE_XLSX_WATCH_WINDOW_ACCEPTANCE.md)。不能把这一 UI 未验收项说成整个监视窗口未实现。 |
| 生产授权／发布、桌面 Office 与真实打印输出 | 多项浏览器专项使用替身 HTTP 授权/修订路由；真实 Python 文件/HTTP下载字节/浏览器不是生产鉴权、桌面 Word/Excel、PDF或打印机视觉等价证明。 | 各专项验收尾部均明确证据边界；此处统一登记，不重复跑已过专项，也不据此停发身份可读取的既有产物。发布必须继续遵守 AGENTS.md 非阻断契约。 |

## 已有后续闭环、应从早期“未实现”列表排除

本轮新增 XLSX 子能力：File→打印现已打开 active/selection/workbook 范围预览，支持隐藏表过滤、跨表连续页码和取消/过期保护；Data→合并工作簿已接文件选择器，追加值/格式/几何/合并区并在公式缓存不可信时原子拒绝。两者仍不关闭完整 PrintDialog、图表/表对象/外部连接等更大范围缺口；静态图表继续保持只读调查状态。

以下排除只针对专项明确范围，不代表整个 tab 或格式已全部对齐。验收证据按各专项记录区分；本轮新增分类汇总闭环，旧专项未复跑。

| 已完成专项范围 | 当前证据索引 |
| --- | --- |
| Word 标尺绝对制表位的可信单段编辑（100%缩放） | [制表位验收](NATIVE_WORD_TAB_STOPS_ACCEPTANCE.md)；26项标尺／意图、23项真实DOCX分批通过，9项相关回归通过；同一冻结浏览器132 JS身份，类型循环、键盘／真实鼠标、继承clear、草稿恢复、真实保存下载重开及110%只读补验通过，errors=[]。构建／JS预算通过；本次完整tsc报告无关PDF表单测试两处重复字段错误。非100%缩放、相对／未知来源、复杂目标及引导符编辑仍缺。 |
| Word 标尺左／首行／悬挂的可信单段编辑 | [标尺缩进验收](NATIVE_WORD_RULER_INDENT_ACCEPTANCE.md)；25项标尺前端、24项真实DOCX及42项相关格式分批通过；同一冻结资产可编辑／只读各132 JS身份、真实鼠标、草稿恢复、两段原子保存／下载／修订2重开，errors=[]。该批全部JS预算与完整tsc通过。制表位后续限定范围见下行，字符来源、RTL及复杂目标仍只读。 |
| Word 原有顶层普通正文／标题单段首行字符单位 | [字符首行验收](NATIVE_WORD_CHARACTER_INDENT_ACCEPTANCE.md)；前端37项加1项补验、相关格式40项、真实DOCX30项加1项字号重解析通过；冻结浏览器132 JS身份，字符→pt首行→悬挂→取消四次真实保存／下载／独立XML回读／明确修订重开，errors=[]。字符悬挂为固定源未建模边界，字符来源标尺及复杂目标仍缺；后续标尺续批已消除既有类型缺口并通过完整tsc，见[标尺缩进验收](NATIVE_WORD_RULER_INDENT_ACCEPTANCE.md)。 |
| Word 原有顶层普通正文／标题单段绝对首行、悬挂及取消缩进 | [特殊缩进验收](NATIVE_WORD_SPECIAL_INDENT_ACCEPTANCE.md)；22项前端专项、16项真实DOCX专项；冻结浏览器132 JS身份、三次真实保存／下载／独立XML回读／明确修订重开、errors=[]。保留左右缩进及其字符属性，显式覆盖直接／继承字符特殊缩进；后续首行字符输入见上行；标尺拖动已按无字符缩进的可信单段范围另行验收，列表／表格／跨段目标仍缺。 |
| Word 原有顶层单段固定／最小值、自定义倍数行距及六种快捷预设 | [固定／最小值验收](NATIVE_WORD_LINE_SPACING_ACCEPTANCE.md)与[自定义倍数验收](NATIVE_WORD_CUSTOM_LINE_SPACING_ACCEPTANCE.md)；最新36项行距前端专项、31项相关Python定向加4项自定义值回写通过；同一冻结浏览器131 JS身份、4次真实保存／下载／独立DOCX回读／明确修订重开、errors=[]。不关闭完整段落对话框、多段或表格编辑缺口；当时全局tsc有既有标尺测试类型错误，后续标尺续批接通extendedIndents后完整tsc已通过。 |
| Word 导航内纯字面搜索、源24px屏幕辅助网格、Word渲染分包预算 | [视图工具增量验收](NATIVE_WORD_VIEW_TOOLS_ACCEPTANCE.md)；两个真实浏览器专项各128 JS身份、0保存导出/errors=[]；分包后实际Markdown/HTML消费者96 JS身份与真实DOCX内容回读通过。Word render723373<727040、main251159<256000；未放宽阈值；当时PDF/XLSX全局预算和完整tsc未过，后续标尺续批的冻结资产已通过全部JS预算及完整tsc（不反推旧资产）。 |
| Word 标题导航/源大纲视图、同 Editor 成功外部刷新建立新历史基线 | [导航大纲与刷新历史验收](NATIVE_WORD_NAVIGATION_ACCEPTANCE.md)；最终同一冻结资产三项真实浏览器各125 JS身份，errors=[]、0保存导出。导航/视图不写草稿；刷新失败/锁定保留原Editor历史，成功后新编辑可UndoRedo。缩略图/标题编辑、样式继承的大纲支持及完整视图族未关闭；导航内搜索见后续视图工具专项。 |
| Word 普通单段书签 REF 交叉引用、图/表/公式简单 SEQ 题注限定插入 | [引用增量验收](NATIVE_WORD_REFERENCES_ACCEPTANCE.md)；5 次真实保存/下载/重开，2 个专项各 122 JS 身份、errors=[]；完整引用功能族仍未关闭。 |
| Word 第一层简单嵌套叶格文字：身份、输入岛、未离焦保存、草稿和下载重开 | [NATIVE_WORD_NESTED_TABLE_ACCEPTANCE.md](NATIVE_WORD_NESTED_TABLE_ACCEPTANCE.md) |
| Word 列宽/分配列、行高/分配行、AutoFit、九宫格对齐、文字方向 | [列宽](NATIVE_WORD_TABLE_COLUMN_WIDTH_ACCEPTANCE.md)、[行高](NATIVE_WORD_TABLE_ROW_HEIGHT_ACCEPTANCE.md)、[分配行](NATIVE_WORD_DISTRIBUTE_ROW_HEIGHT_ACCEPTANCE.md)、[AutoFit](NATIVE_WORD_TABLE_AUTOFIT_ACCEPTANCE.md)、[九宫格](NATIVE_WORD_TABLE_CELL_ALIGNMENT_ACCEPTANCE.md)、[方向](NATIVE_WORD_TABLE_TEXT_DIRECTION_ACCEPTANCE.md) |
| Word 整表对齐（保留原缩进）、默认边距、单格覆盖/恢复继承、行跨页、自动换行 | [整表对齐](NATIVE_WORD_TABLE_ALIGNMENT_ACCEPTANCE.md)、[默认边距](NATIVE_WORD_TABLE_CELL_MARGINS_ACCEPTANCE.md)、[单格覆盖](NATIVE_WORD_CELL_MARGIN_OVERRIDES_ACCEPTANCE.md)、[行跨页](NATIVE_WORD_TABLE_ROW_BREAKS_ACCEPTANCE.md)、[自动换行](NATIVE_WORD_CELL_WRAP_ACCEPTANCE.md) |
| Word 局部高亮/上下标、清格式、样式组合、大小写/半全角、段落格式组合、脚注尾注及页眉页脚已交付子集 | [局部上下标](NATIVE_WORD_VERTICAL_ACCEPTANCE.md)、[样式](NATIVE_WORD_STYLE_MAJORITY_ACCEPTANCE.md)、[清格式](NATIVE_WORD_CLEAR_FORMATTING_ACCEPTANCE.md)、[大小写](NATIVE_WORD_XLSX_CASE_SPLIT_ACCEPTANCE.md)、[组合](NATIVE_WORD_PARAGRAPH_FORMAT_COMBINATION_ACCEPTANCE.md)、[注释输入](NATIVE_WORD_NOTE_REFERENCE_INPUT_ACCEPTANCE.md)、[调查与实际范围](NATIVE_WORD_INSERT_HF_INVESTIGATION.md)。不能把引用tab或完整HF所有选项整体算完成。 |
| XLSX 透视来源重命名／删表依赖保护、来源页行列结构原子拒绝 | [来源移位调查与最终 built](NATIVE_XLSX_PIVOT_SOURCE_SHIFT_INVESTIGATION.md)、`F/workbook-pivot-source-structure.ts`（以实际模块符号为准）、`X` 的 pivot source rename/removal 路径；这些已交付保护不等同 pivot-open/pivot-edit。 |
| XLSX 相邻分组分类汇总：sum/count/average、单次UndoRedo、原子回滚、草稿及保存下载重开 | [分类汇总验收](NATIVE_XLSX_SUBTOTAL_ACCEPTANCE.md)、[集成验证](NATIVE_XLSX_SUBTOTAL_INTEGRATION_VERIFICATION.md)。首行表头、一个分组列/值列、最多200组；复杂依赖按预检边界拒绝。 |
| XLSX CSV 导入当前选区：原生文件选择、编码/分隔符、字面公式、UndoRedo、草稿与保存下载重开 | [CSV 验收](../../docs/parity/2026-11-11-workbook-csv-import.md)；真实 Chromium 129 JS 身份、1 次保存、新修订2重开、openpyxl 回读、errors=[]。 |
| XLSX 已有文件页眉页脚文字打印：六变体、字段、页码、转义与缩放 | [页眉页脚验收](NATIVE_XLSX_PRINT_HEADER_FOOTER_ACCEPTANCE.md)；真实三页A4 PDF、130 JS身份、errors=[]；默认页眉页脚编辑已由后续专项接通；图片/富文本字体仍不含。 |
| XLSX 默认／奇数页页眉页脚六区编辑、清空、草稿恢复及保存下载重开 | [编辑验收](NATIVE_XLSX_HEADER_FOOTER_EDITOR_ACCEPTANCE.md)；两次真实保存下载重开，first/even/flags和其余ZIP保留；最终布局单独补验。首页/偶数页只保留，无native Undo。 |
| XLSX 透视表全部刷新：当前草稿重算结果/缓存、分类增长/收缩及原子提交 | [全部刷新验收](../../docs/parity/2026-11-11-workbook-pivot-refresh.md)；130JS、Python真实bridge保存、下载openpyxl结果180、UndoRedo/草稿/修订2重开；不执行外部查询。 |
| XLSX 查询与连接只读面板：真实元数据、脱敏、已加载目标导航与错误区分 | [查询验收](../../docs/parity/2026-11-11-workbook-queries.md)；真实3来源场景、130 JS身份、0保存/0外部请求/errors=[]；不执行或刷新查询。 |
| XLSX 打印显式四边边框、颜色/线宽、页内合并锚点与相邻冲突 | [边框验收](NATIVE_XLSX_PRINT_RENDERING_ACCEPTANCE.md)；28 项定向测试、真实 File→Print、129 JS 身份、HTML/截图/PDF，errors=[]；不关闭完整打印功能族。 |
| XLSX 分页预览、源隐藏列结构移动与尺寸保存 | [分页预览](NATIVE_XLSX_PAGE_BREAK_PREVIEW_ACCEPTANCE.md)、[隐藏列](NATIVE_XLSX_HIDDEN_COLUMN_PERSISTENCE_ACCEPTANCE.md) |
| XLSX 引用/从属追踪与清除、监视窗口、错误检查导航 | [追踪](NATIVE_XLSX_FORMULA_TRACE_ACCEPTANCE.md)、[监视](NATIVE_XLSX_WATCH_WINDOW_ACCEPTANCE.md)、[错误检查](NATIVE_XLSX_ERROR_CHECKING_ACCEPTANCE.md) |
| XLSX 交叉高亮、Go To滚动、公式栏视图、复选框、去重、条件格式/数据验证已验收子集 | [高亮](NATIVE_XLSX_CROSS_HIGHLIGHT_ACCEPTANCE.md)、[Go To](NATIVE_XLSX_GOTO_SCROLL_ACCEPTANCE.md)、[公式栏](NATIVE_XLSX_FORMULA_BAR_VIEW_ACCEPTANCE.md)、[复选框](NATIVE_XLSX_CHECKBOX_ACCEPTANCE.md)、[去重](NATIVE_XLSX_DEDUPE_ACCEPTANCE.md)、[CF](NATIVE_XLSX_CF_FRONTEND_ACCEPTANCE.md)、[DV](NATIVE_XLSX_DATA_VALIDATION_ACCEPTANCE.md) |

后续更新规则：以实际可执行入口、授权操作/草稿/保存/独立回读/明确修订重开及对应失败边界为关闭证据；视图导航核验不写草稿/历史/文件。完成子能力只移除对应缺口，保留完整 PrintDialog、复杂对象、外部宿主及兼容边界。需要完整 inventory 时再逐源 callback/gallery/context-menu 扩充本索引；本表没有穷尽所有静态标签，未列项目不能推定完成或不存在。

2026-11-11 视图续批：标尺与导航页面的限定能力、最终冻结浏览器、独立XML回读及剩余边界见 [专项验收](NATIVE_WORD_RULER_PAGES_ACCEPTANCE.md)。本批最终tsc/全部JS预算通过；不能据此反推其它批次或所有Word场景均已验收。
