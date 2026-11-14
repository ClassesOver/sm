# Word / XLSX 当前缺口索引（非穷尽）
2026-11-14 实施增量已单列：[审计整改进度与真实保存证据](NATIVE_WORD_AUDIT_REMEDIATION_20261114.md)。同ID当前范围以增量索引为准，原始审计保留历史身份。


2026-11-14 Word全入口审计已单列：[844条命令／字段明细与剩余差异](NATIVE_WORD_EXHAUSTIVE_GAPS_20261114.md)。本索引仍为跨格式非穷尽历史汇总，Word当前完整入口盘点请以该审计及其来源身份为准。

更新：2026-11-13。此索引以更新时共享工作区的实际代码为准，替代早期矩阵的“当前状态”用途；不改写 `NATIVE_WORD_XLSX_PARITY_AUDIT.md`、`NATIVE_RIBBON_COMMAND_AUDIT.md` 的历史。固定源 `/home/junge/pros/genoffice-source-full` HEAD 已只读核对为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

2026-11-14 Word 增量：Editor／22语言翻译预设、正文修订范围菜单、文本比较、只读修订摘要预填、HTML／Markdown导出、源主题与字体／颜色预设、墨迹、保护设置、文本框／形状／艺术字插入已接通。图表、常见域、story修订、图片几何格式、同格连续段落设置、表格后新增段落也已补实现；证据层级及剩余边界见[本批验收](NATIVE_WORD_GENOFFICE_ALIGNMENT_20261114.md)。以下旧表的“整个族缺失”只代表旧批次，不能覆盖本增量。顶层多段段落设置原本已有；固定源图片Ribbon没有颜色／透明度入口，不再作为迁移缺口。

**完整对齐仍未完成。本表非穷尽，不给完成百分比。** 本索引汇总实际代码及分层专项证据；Word 根批注新建与 XLSX 透视表创建/编辑已有真实浏览器保存、下载和重开证据；最新构建入口与资产连续性单独补验，具体范围以专属验收文档为准。既有专项未重复全测，不冒充本次重新验收。调查、按钮标签、永久禁用、manifest/hash 通过都不计功能交付。并行工作会改变状态，以下稳定符号比行号更适合作后续查找。

2026-11-13 清单更正：Word 普通／多级列表库和设置编号值、XLSX 推荐图表／多图选择／限定拖动缩放、PDF 书签／Bates／四项属性、PPTX 普通／排序／大纲／阅读视图及拼写翻译预设均已有专项交付，不再列为“全缺”。各自保留的范围限制和验收链接统一见[四格式已交付子能力与剩余边界](NATIVE_GENOFFICE_FOUR_FORMAT_SCOPE.md#已交付子能力与剩余边界2026-11-13-更正)。下文带批次／冻结构建的旧结论仅代表当时范围，以当前表及该更正为准。

2026-11-13 增量：XLSX 网格 `Ctrl/Cmd+;` 静态日期、`Ctrl/Cmd+Shift+;` 静态时间快捷键已接原生单元格草稿操作；测试覆盖 1900/1904 日期纪元、活动格操作、日期草稿 Undo/Redo 及 OOXML 写入回读。图表快速布局／更改颜色入口也已接入 Chart Design；按钮与源预设专项定向测试通过。两项不是剩余 UI 空缺；未重复运行完整 HTTP 保存链。

同日续批：Word 普通连续画布现按分页几何绘制逐页页面边框并在关闭时清除 overlay；完整源页面边框设置对话框已接入原生 section 草稿，支持四边、24种线型、阴影/3D、自定义颜色/宽度、源 art 边框与显示页、距离/offset、前后层级，以及当前节/全文应用。全文按每节来源身份原子提交，跨节保存逐节验证和独立 OOXML 回读；保留兼容方框/无快捷项。前端定向71项、bridge 2项、Python 16项、额外 bundle 写入/显式清除2项通过。PPTX 母版文字 UI 已保留段落/run 身份，支持选区粗体、斜体、下划线，草稿沿用既有 setText transaction；前端定向测试5项及此前全前端类型检查通过。bridge 测试因 Node 24/tsx 无法加载 `text.md` 而未进入断言，故母版保存及文件回读仍待验，不计完整闭环。

2026-11-12 增量：XLSX AI 已有图表格式编辑/删除完成冻结目标身份、严格运行时格式校验、真实工具预览与显式采纳；45项专项和真实浏览器两次保存下载重开通过。后续bar方向/负值零线/空值分类已修并通过17项定向及截图像素，见 [画布增量](NATIVE_XLSX_BAR_CANVAS_ACCEPTANCE.md)；标题/网格文字已定位为验收环境字体解析问题并补预检和像素验证，见 [文字预检](NATIVE_XLSX_CANVAS_FONT_ENVIRONMENT.md)。后续 2026-11-13 已补来源范围驱动的 AI 新建／系列换绑，真实 provider 与 final8 ScriptedModel 浏览器保存重开分别通过，见[来源图表专项](NATIVE_XLSX_AI_CHART_SOURCES_ACCEPTANCE_20261113.md)；不再列为完全未实现。单点折线无可见标记、完整格式／复杂视觉和生产真实 provider 浏览器同链仍缺。既有格式删除范围见 [已有图表 AI 验收](NATIVE_XLSX_AI_EXISTING_CHART_ACCEPTANCE.md)。

后续bar/column常见四侧/none图例、可信名称及显式RGB系列色已通过读取/画布与保存重开像素专项，见 [图例验收](NATIVE_XLSX_LEGEND_CANVAS_ACCEPTANCE.md)。非bar/column图例、复杂索引与手动布局、完整轴/标签等不计通过。

后续bar/column可信轴标题配对、隐藏标记、方向及top/right显示已通过读取和实际像素、带标题的AI保存下载重开，见 [轴标题专项](NATIVE_XLSX_AXIS_TITLE_CANVAS_ACCEPTANCE.md)。轴线/刻度/数值范围、次轴/组合与数据标签仍缺，不能把轴标题算作完整坐标轴能力。

后续bar/column手动数值min/max、反向、零点与越界裁剪、null恢复本地自动范围已通过独立像素和实际候选保存重开，见 [数值范围专项](NATIVE_XLSX_VALUE_RANGE_CANVAS_ACCEPTANCE.md)。完整刻度/自动策略、对数计算、次轴/组合及数据标签仍未关闭。

后续 bar/column 数值轴自动留白、主刻度/数字格式、top/right 与隐藏/反向显示、共享零线已补，见 [数值轴专项](NATIVE_XLSX_VALUE_AXIS_CANVAS_ACCEPTANCE.md)。原源算法750组差分（748一致、2组明确全负零上界修正）、57项前端和34项读取分批通过，真实截图与AI保存重开已验证。类别刻度/完整轴属性、源链接格式继承、对数/次轴与复杂图表仍缺；前述“自动/刻度仍缺”为各专项当时范围，此续批只关闭普通线性数值轴子集。

后续 bar/column 单层类别名称、源 minMax/maxMin 分类与组内系列顺序、实时空槽和外表缓存、top/right/隐藏/长标签已补，见 [类别轴专项](NATIVE_XLSX_CATEGORY_AXIS_CANVAS_ACCEPTANCE.md)。41项读取与75项前端分批通过，固定源排序表达式292个位置一致，最终构建的分类与相关浏览器/保存重开已验证。多级分类、日期比例、换行/旋转、完整轴属性、数据标签、对数/次轴及复杂图表仍开放；不把单层分类续批算完整图表。

后续普通 bar/column 显式数值数据标签（plot/series/point开关与删除、中心/内端/外端、正负与反向、显式格式/空分段）已补，见 [数值标签专项](NATIVE_XLSX_DATA_LABEL_CANVAS_ACCEPTANCE.md)。50项读取和87项前端分批通过，八个真实标签场景、短分类修复和AI带标签保存重开已验证。标签字体/手动偏移/分类及占比内容、完整格式继承、非普通图表仍缺，不能把value标签子集算完整数据标签家族。

后续普通value标签的显式字号/纯RGB/加粗、逐属性继承与取消加粗已补；全局标签模式/格式/位置编辑改为SAX直属节点写回，保留根字体与点级覆盖。76项引擎、90项前端、45项真实CLI AI专项通过，真实字体像素及带原样式保存重开验证见 [标签样式验收](NATIVE_XLSX_DATA_LABEL_STYLE_ACCEPTANCE.md)。字体族、复杂富文本/主题色/完整字体度量与标签家族仍开放。

路径约定：`F=frontend/src/`（相对此文档）；`D=../reporting/doc_engine/`；`X=../reporting/workbook_engine/`；`U=/home/junge/pros/genoffice-source-full/`。源码路径均指实际文件，不指历史审计中已迁移的 `slides_engine` DOCX 路径。

状态严格区分：

- **本地缺功能**：固定源有入口/实现，本地没有相应可执行闭环；保留旧对象不代表能创建/编辑。
- **源缺功能／源边界**：固定源自身没有对应可保存能力，或实际实现有限制；不得包装成本地迁移完成，也不自动从完整产品目标剔除。
- **既有兼容边界**：已交付功能明确只支持部分对象/来源，范围外保留或只读；不是本轮新引入的已确认回归。
- **进行中／未验收**：已有实现但专项最终验收未完成，或只有有限层次证据。不能计最终完成。

## 可核实的本地剩余功能

| 项目 | 当前状态与实际缺口 | 固定源与本地证据 |
| --- | --- | --- |
| Word 完整段落选项与多级列表 | 固定／最小值及自定义倍数行距已接通：当前可信原有顶层段落支持1–1584pt、0.05pt精度，及0.06–132倍、0.01精度，保留六个快捷预设。已验UndoRedo、草稿恢复及四次真实保存下载重开。绝对首行／悬挂／取消特殊缩进已接通，普通正文／标题单段支持0.05–720pt、0.05pt精度，三次真实保存下载重开已验。首行字符单位也已接通（0.01字符精度、保留原生firstLineChars及草稿／UndoRedo，四次保存下载重开已验）。完整 ParagraphDialog、制表位对话框／引导符编辑以及表格／跨段目标仍未覆盖；标尺制表位已在100%缩放的可信单段范围接通五种类型、增删拖动及保存下载重开；标尺左／首行／悬挂已按无字符缩进的可信单段、单栏、非镜像、LTR范围完成真实拖动及保存下载重开；列表、字符来源及复杂标尺目标仍缺，字符悬挂在固定源也未建模。多级列表八套九级库、最近/文档/级别区与完整自定义层级、级间重新开始规则已接通可信原有顶层段落多选，UndoRedo/草稿恢复及真实保存下载重开已验；普通符号六套/编号八套库、最近/文档/级别区及源完整符号/编号定义已接可信顶层目标，845d冻结真实保存下载重开通过；设置编号值restart/continue/advance已在有可核验定义的可信顶层列表接通，并完成6e565冻结真实保存下载重开及同abstractNum/startOverride独立回读，见[编号值验收](NATIVE_WORD_NUMBERING_VALUE_ACCEPTANCE.md)；尚未保存且无定义的Home快捷列表、图片符号和复杂目标仍缺，见[普通列表验收](NATIVE_WORD_LIST_LIBRARIES_ACCEPTANCE.md)。 | [行距增量](NATIVE_WORD_LINE_SPACING_ACCEPTANCE.md)、[自定义倍数验收](NATIVE_WORD_CUSTOM_LINE_SPACING_ACCEPTANCE.md)、[特殊缩进验收](NATIVE_WORD_SPECIAL_INDENT_ACCEPTANCE.md)、[字符首行验收](NATIVE_WORD_CHARACTER_INDENT_ACCEPTANCE.md)、[标尺缩进验收](NATIVE_WORD_RULER_INDENT_ACCEPTANCE.md)与[制表位验收](NATIVE_WORD_TAB_STOPS_ACCEPTANCE.md)；`F/docx-special-indent.ts`、`F/docx-line-spacing.ts`、`D/bridge/docx-line-spacing.ts`；多级列表见[专项验收](NATIVE_WORD_MULTILEVEL_ACCEPTANCE.md)，完整ParagraphDialog等边界仍开放。 |
| Word 目录、引用与批注增量 | 原生“引用”已接入自动目录插入和更新，条目按已保存标题生成；编辑器当前不缓存目录页码，由 Word 更新目录域。普通正文书签创建、精确定位、删除及独立保存已接通并完成冻结浏览器创建/删除两次保存下载重开；复杂锚点只读。普通书签 REF 交叉引用与图/表/公式 SEQ 题注已完成冻结浏览器 5 次真实保存、下载独立 ZIP/lxml 及明确修订重开；来源身份、独立意图、UndoRedo/草稿均接通。缓存不自动更新，复杂书签和复杂/中间插入编号不在本轮范围，实体语义与核心投影不一致的来源交叉引用明确只读。引文、书目和索引仍未接。已有批注面板新增删除、解决和重新打开可信线程；受保护的仅批注模式、复杂线程与完整批量审阅仍未补齐；可信简单正文修订已支持限定范围的批量接受/拒绝。 | `F/docx-toc.ts`、`D/bridge/docx-toc.ts`、`F/docx-comment-thread.ts`、`D/bridge/docx-comment-thread.ts`；相关动作均需独立保存；新增范围与全局检查限制见 [引用增量验收](NATIVE_WORD_REFERENCES_ACCEPTANCE.md)。 |
| Word 复杂分页与打印一致性 | 已定位并修复宿主内置字体误注入 Word 布局指标导致的行距膨胀；同一 DOCX 冻结构建真实预览由 15 页回到固定 GenOffice 的 10 页；连续四次切片稳定，46 段正文、62 表行和三条注释标记齐全。后续补齐页眉测量作用域、有效画布原点及拉丁字体槽，最终冻结浏览器本样本全部 10 页切片与固定源一致（最大误差低于 1e-6 px）；未保存的页眉、链接与页码状态即时预览也已验收。旧页底叠印／串页为截图越过预览视口的误判，已修正探针。项目 LibreOffice 为 12 页；独立报告 PDF 为 8 页，未包含 DOCX 后加的分栏和注释。仍不能认定所有复杂文档或打印路径均对齐。 | [复杂分页实测](NATIVE_WORD_COMPLEX_PAGINATION_ACCEPTANCE.md)。 |
| Word 嵌套表结构与属性 | 本地缺功能。第一层简单叶格文字已交付；内层行列、合并拆分、表头、宽高、AutoFit、对齐、方向、边距、行跨页、自动换行、Alt text 等不能借外层选区操作。需要专用内层目标与持久化协议。 | `U/apps/docs/src/renderer/editor/extensions.ts` 的 `DocNestedTable` 是 model 输入岛；`U/.../editor/table-ops.ts` 以 PM `docTable`/TableMap 选区工作，源也没有完整内层 Ribbon 编辑语义。`F/docx-tables.ts` 的 `nestedInputActive()` 在各上述入口明确拒绝；[嵌套表验收](NATIVE_WORD_NESTED_TABLE_ACCEPTANCE.md) 的“行为与范围”明确内层结构未实现。不能将本项全部归因于本地漏接一个 callback。 |
| Word 完整文件宿主与打印 | 本地缺完整源文件菜单/宿主等效。报告 shell 保存、新修订下载和 PDF 导出已有功能，不等同打开任意文档、另存为全选项、完整 PrintDialog 与各转换格式。各子项需继续追实际宿主，不按标签全算源已支持。 | `U/apps/docs/src/renderer/components/PrintDialog.tsx`；`U/.../components/Ribbon.tsx` 文件宿主 props；`F/docx-ribbon.ts` 的 `pendingGroups.file` 经 `renderPending()` 无 action 映射而禁用；`F/docx-main.tsx` `onExportPdf` 委托报告 shell。完整范围仍需逐项宿主验收。 |
| Word Draw／Design／Mailings 与复杂对象格式 | 本地缺功能。可核实整个待迁移入口族仍未执行：画笔/擦除、主题与页面背景类、邮件合并、图片/形状复杂格式。不是说所有固定源标签都已有完整落盘实现；对应源每个子功能仍须核验。 | `U/apps/docs/src/renderer/components/Ribbon.tsx` `DRAW/DESIGN/MAILINGS` 相关 tab 与 `IMAGE_TABS/SHAPE_TABS`；`F/docx-ribbon.ts` `pendingGroups.draw/design/mailings/pictureFormat/shapeFormat` 经 `renderPending()` 落入 `migrating`。已有简单插图或图片闪烁修复不能抵消这些缺口。 |
| Word 审阅及部分视图 | 部分闭环已交付、其余仍缺。2026-11-11 新增根批注精确选区创建：跨 run/跨段/内部普通空段、取消、UndoRedo/恢复、保存下载与新修订重开已由 e13de64 冻结构建实际验收；仅 document.xml/comments.xml 变动，详见 [新建批注验收](NATIVE_WORD_NEW_COMMENT_ACCEPTANCE.md)。既有唯一根线程的文字回复已接入真实 parent 关联、同一草稿/历史/未失焦保存/下载和重开；8c3完整浏览器、真实HTTP非阻断、971b状态修复及final4多根空输入切换错投修复窄补验分层记录于 [回复验收](NATIVE_WORD_COMMENT_REPLY_ACCEPTANCE.md)。删除、解决和重新打开已接入可信根线程及直接回复；嵌套回复、复杂锚点及受保护 comments-only 仍未接完整。批注/修订已完成24个源真实保存及ZIP/lxml调查，见 [审阅调查](NATIVE_WORD_REVIEW_INVESTIGATION.md)；顶层简单ins/del逐条接受/拒绝已接宿主、草稿恢复及审阅列表，5次真实浏览器保存下载与新修订重开通过，见 [集成验证](NATIVE_WORD_TEXT_REVISION_INTEGRATION_VERIFICATION.md) 与 [built验收](NATIVE_WORD_TEXT_REVISION_BUILT_ACCEPTANCE.md)。本轮补齐“接受/拒绝所有支持的正文修订”：先全批校验、单 PM 事务、一次UndoRedo、保存下载XML回读与新修订重开通过，复杂修订原样保留。复杂/嵌套/move/属性修订、跟踪新建修订、全文件所有故事的接受全部和完整批注编辑仍缺，不能关闭整个审阅功能族；见 [高优先级验收](NATIVE_WORD_HIGH_PRIORITY_ACCEPTANCE.md)。[Review 命令族逐项对照](NATIVE_WORD_REVIEW_COMMAND_FAMILY_INVENTORY_20261113.md) 记录源 Review Ribbon 范围、保护条件与本地 ribbon/host 已接和缺口，不把局部验收扩成整族完成。批注另完成 [身份与扩展保全调查](NATIVE_WORD_COMMENTS_INVESTIGATION.md)：固定源重复身份、跨段回复和 commentsExtended 重写存在边界；已新增严格批注文字编辑纯core及8组专项、实际DOCX独立ZIP/lxml证据，见 [core阶段验收](NATIVE_WORD_COMMENT_TEXT_ACCEPTANCE.md)；只替换 comments.xml 授权片段，保留现代扩展，已新增授权原bytes来源helper（14项专项）及Node inspect/纯批注patch分支（2项真实CLI专项）；Python薄桥及真实发布下载非阻断专项已通过；前端纯intent模块12项、controller8项及main批注6项定向通过；最终构建真实浏览器已通过编辑/UndoRedo/刷新恢复/未blur保存/下载/新修订重开，且仅comments.xml变动；后续3项真实ASGI授权专项已通过：grant/cookie、CSRF/Origin、来源/修订隔离、真实Node引擎预览保存、下载独立回读与验收失败非阻断；仓储仍为内存夹具，不冒充生产DB或浏览器直连真实鉴权整链；已核实最小接入路径及风险，见 [宿主计划](NATIVE_WORD_COMMENT_HOST_PLAN.md)。翻译、比较/保护等仍为待迁移入口；Web/阅读视图和窗口管理未接。标尺已有右缩进/左右边距及后续左／首行／悬挂的限定范围验收，后者真实拖动、原子草稿、保存下载重开已通过；制表位已按100%缩放、已建模绝对来源限定范围验收；非100%缩放／相对／未知属性制表位、字符来源、RTL、列表／表格／跨段、多栏／镜像及其它复杂目标仍只读，见 [制表位验收](NATIVE_WORD_TAB_STOPS_ACCEPTANCE.md)、[标尺缩进验收](NATIVE_WORD_RULER_INDENT_ACCEPTANCE.md)与[标尺与页面验收](NATIVE_WORD_RULER_PAGES_ACCEPTANCE.md)。源24px屏幕辅助网格已接并验收，不等于Word docGrid或表格网格编辑。标题导航窗格与源大纲切换/折叠已按限定范围验收；导航内纯字面搜索已按正文/表格限定范围验收，页面缩略图已按同尺寸单栏整块分页限定范围验收，复杂拆页/混合布局仍缺；标题移动删除升降级仍缺，大纲源 plugin 仅识别 docHeading，不等同导航的样式继承标题。已有 zoom 与分页预览要排除。 | `F/docx-ribbon.ts` `pendingGroups.review/view`；`F/docx-view.ts` 已接 navigation/outline 路由；具体交付及全局检查限制见 [导航大纲与刷新历史验收](NATIVE_WORD_NAVIGATION_ACCEPTANCE.md)，其余 `reason()` 保留未对齐原因。源入口 `U/apps/docs/src/renderer/components/Ribbon.tsx`；不能据 tab 名认定源全部落盘。 |
| XLSX 完整 PrintDialog 与打印渲染等效 | **部分已接通**：File→打印现有 active/selection/workbook 预览、页面导航、隐藏表过滤、跨表连续页码和取消/过期保护；仍缺源完整 `copies/collate/pagesMode`、打印机/PDF host。浏览器负责设备/份数不等于已迁移源宿主。百分比 scale、显式单元格边框及已有文件页眉页脚文字子能力已验收，不能因此关闭整项。 | `U/apps/sheets/src/renderer/PrintDialog.tsx` 的 `range/copies/collate/pagesMode/page/job`、`host.listPrinters/buildJob`；本地 `F/workbook-print-preview.ts` 与 `F/workbook-main.ts` 已接范围预览；页眉页脚图片、部分数值格式与跨页裁切 merge 仍缺。 |
| XLSX 图表创建及编辑 | 九类图表创建已接入现有 OOXML writer：从选区推导表头、分类、系列与引用范围，创建/编辑/删除进入原生草稿和保存协议。Chart Design 已接标题、图表类型、图例位置、分类轴/数值轴标题、数据标签、分组/主网格线格式及单图“选择数据”编辑，按当前工作表唯一可信 `chartPath` 写回；组合图选择数据明确拒绝。带文字表头/分类标签的同表连续矩形已接切换行列及切回，柱/条/线/面积图限定支持；不依赖当前选区并保留未保存数值。已接删除并清理 drawing anchor、relationship、chart part 和 content type override。后续已补多图画布/说明面板选择、源四布局/五配色与饼环分类百分比标签，图表操作接入草稿 Undo/Redo；最终0015构建真实两次保存下载重开通过，见 [选择与预设专项](NATIVE_XLSX_CHART_SELECTION_PRESETS_ACCEPTANCE.md)。两格锚点图表移动/八向缩放及单格锚点只移动已完成真实手势、草稿和保存下载重开，见[几何专项](NATIVE_XLSX_CHART_OBJECT_GEOMETRY_ACCEPTANCE.md)；absolute锚点明确拒绝。推荐图表已按源算法、真实数据SVG/理由、选择插入接通，845d冻结首次真实保存下载重开通过，见[推荐验收](NATIVE_XLSX_RECOMMENDED_CHARTS_ACCEPTANCE.md)；完整格式面板、复杂来源切换行列及系列扩展保全仍缺；不把限定图表专项算成完整Excel功能。 | `F/workbook-chart-add.ts`、`F/workbook-chart-design-dialog.ts`、`F/workbook-chart-switch.ts`、`F/workbook-main.ts`、`X/packages/xlsx-engine/src/chart-add.ts`、`X/packages/xlsx-engine/src/chart-edit.ts`、`X/packages/xlsx-engine/src/chart-delete.ts`；[图表创建/编辑验收](NATIVE_XLSX_CHART_INSERT_ACCEPTANCE.md)。 |
| XLSX 图表命令族增量 | 系列重绑、bar+line逐系列类型/次轴、格式控件、四布局/五配色均有各自保存/回读证据。scatter 可见 x/y 轴刻度及 radar 可见外围分类标签现已真实单击命中；Chromium 157 隔离验收覆盖 scatter 分类轴/数值轴、同一点首击系列再击数据点、radar 分类轴与系列填充外值环位置，选择前后 NativeDraft 均为空、未保存；`chart-render.test.ts` 116 项及 `chart-value-scale.test.ts` 定向测试合计131项通过，scatter自动上界/majorUnit回归对照固定源样例；298 个 JS/CSS 资源响应逐个 SHA 匹配隔离构建，HTTP/page/console 无错误，481 个 JS chunk 预算检查无超限。line/area 新增真实浏览器证据：line 折线段中点选择 series、marker 首击 series/再击 point、area 填充区选择 series，草稿不变；298 个 JS/CSS 响应逐个 SHA 匹配且零错误。证据分别见 `/tmp/workbook-axis-hit-browser-source-scale-20261113/` 与 `/tmp/workbook-line-area-hit-20261113c/`（含 evidence、server/http logs、截图）；构建日志 `/tmp/workbook-axis-hit-build-source-scale.log`。该次build早于 writeBundle 插件隔离修复，仅以隔离输出作浏览器验收，不据此声称 shared static 未被改写。源 scatter 将点坐标 clamp 到 `[0,1]` 且不应用轴 reversed，本地尚未一致；Radar 半径/系列点 clamp/类别数量与值环布局、Scatter displayUnit/gridlines/lineStyles 等视觉差异仍开放。见 [图表系列、坐标轴与交互命令盘点](NATIVE_XLSX_CHART_COMMAND_FAMILY_INVENTORY_20261113.md)。 | 固定源 `U/apps/sheets/src/renderer/WorkbookVisuals.tsx`、`ChartPanels.tsx`、`ribbon-actions.ts`；本地 `frontend/src/workbook-vendor/grid/chart-render.ts`、`workbook-chart-element-hit.ts`、`workbook-chart-format-pane.tsx`；[系列/次轴闭环](NATIVE_XLSX_COMBO_SELECT_DATA_ACCEPTANCE.md)、[格式控件验收](NATIVE_XLSX_CHART_FORMAT_SOURCE_ACCEPTANCE_20261113.md)。 |
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
| XLSX 普通图片导入与公式/图标插入 | 普通 twoCellAnchor/oneCellAnchor PNG/JPEG、完整 EquationDialog/IconsDialog、本地图片选择已接入真实普通 drawing 与保存重开。公式/图标是静态 PNG；原生图片当前不能拖移/删除。absoluteAnchor、外部来源或非法图片锚点会保留源 OOXML，但不导入显示；加载状态提示会给出具体读取原因。图片 family 其余锚点/格式、来源对象交互仍未完成，不能宣称图片全家族完成。 | [XLSX 图片 source 验收](frontend/smoke/workbook-pictures-native-smoke.md)；源 smoke evidence `/home/junge/codex-evidence/smart_reporting/office-richpaste-pictures-signature-recording-20261113/xlsx/source-native/evidence.json` 与 `zip-preservation.json`。 |
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

2026-11-12 标签主题色续批：普通数值标签接通实际主题关系与完整配色的无变换 schemeClr，保留原引用并跟随真实主题切换；47项定向、构建/预算、真实撤销重做与保存下载重开通过。169实际资源身份及独立下载XML/颜色混合像素已核；明暗透明度变换、字体族及复杂标签仍缺，见 [主题色验收](NATIVE_XLSX_DATA_LABEL_THEME_ACCEPTANCE.md)。

2026-11-12 标签亮度续批：普通数值标签的RGB/已解析主题色接通常见lumMod→lumOff亮度组合，保存保留原变换。66项定向、1120组固定源实际执行对比、真实主题切换/撤销重做/下载重开与独立颜色像素通过；Python另6组浮点舍入差异已公开。透明度、其它变换链及完整标签家族仍缺，见 [亮度验收](NATIVE_XLSX_DATA_LABEL_LUMINANCE_ACCEPTANCE.md)。

2026-11-13 图表命名空间续批：默认/任意前缀图表的编辑与精确删除已通过110项定向测试、类型/构建/预算及真实双图UI/Agno工具/UndoRedo/草稿恢复/两次点击下载/修订重开；独立文件回读验证另一图、外来元数据和非目标包成员原字节保持，见[命名空间验收](NATIVE_XLSX_CHART_NAMESPACE_ACCEPTANCE.md)。不能继续笼统称图表只读；该批当时仍有charts.length===1限制且缺快速布局/配色；后续多图对象选择、四布局/五配色及图表草稿历史已由[选择与预设专项](NATIVE_XLSX_CHART_SELECTION_PRESETS_ACCEPTANCE.md)关闭其明确范围。拖动/resize、完整格式工具面、复杂图表依赖清理及四格式穷尽仍未完成。

2026-11-13 并行源入口续批：最终隔离构建 manifest `0015c3b33b9184ffa601a0d60d3d501b498986b98865d7d41eb1e4f6accf3bfe`，完整前端类型检查、43.98秒Vite与394 JS原预算通过。XLSX真实人工A1草稿、同名图2选择/标题/pie/布局/颜色、File撤销恢复、reload、75%选择/Delete及4→5→6两次保存下载重开通过，171实际JS/CSS身份匹配，独立openpyxl/lxml/ZIP验证原图XML不变。保留验收待复核告警并照常下载；不冒充桌面Office/生产仓储或全图表保真。

同批PDF外链目录与PPTX翻译/拼写预设分别见[PDF目录专项](NATIVE_PDF_OUTLINE_LINKS_ACCEPTANCE.md)、[PPTX预设专项](NATIVE_PPTX_AI_PRESETS_ACCEPTANCE.md)。完整交互证据绑定8d4；0015只做实际资源身份及入口续验，PDF50资源、PPTX129JS全部匹配，无浏览器错误。PPTX使用真实Agno+ScriptedModel候选，不含保存下载或真实provider质量验证。758模块/5215声明点仅为源码定位清单，不是功能总数或完成率；四格式完整目标继续开放。


2026-11-13 多级列表/图表几何续批：当前缺口表已局部更新，移除“多级列表仍禁用”与“全部图表拖动/resize仍缺”的过期表述。Word八套九级、最近/文档/级别、自定义/重启、可信顶层多选已完成68ce真实保存下载重开；XLSX两格锚点移动/八向resize及单格只移动已分层完成真实手势与68ce保存闭环，absolute明确拒绝。150/171项资源均独立SHA匹配，文件回读保全原内容；Python两项漏登分别RED→GREEN，验收待核告警保留且不阻断下载。见[Word专项](NATIVE_WORD_MULTILEVEL_ACCEPTANCE.md)和[XLSX专项](NATIVE_XLSX_CHART_OBJECT_GEOMETRY_ACCEPTANCE.md)。普通编号工具及推荐图表已由后续专项交付；剩余复杂目标、完整ChartPanels/复杂SelectData/series-point选择及完整格式能力继续开放；多条applyPageSetups视图覆盖疑点另记未修。最终397JS原预算与类型/构建通过不是整个并发工作区功能完成证明。


## 2026-11-13 普通列表库、推荐图表、Bates与视图续批

固定源仍为 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。root和三个同模型子agent并行，本批物理复制4119份源码身份，构建只在 `/dev/shm/office-four-format-source-library-20261113/source` 执行；隔离static的manifest为 `845d993207be6b2d6eeae28cf0b5abab8c1aaded0b9a9e60e7ca86a890a4d56c`。完整前端类型检查退出0，Vite45.97秒，400个JS原预算failures=[]，四引擎桥构建退出0，未提高任何预算或覆盖共享static/dist。

| 格式 | 本批关闭范围与实际验证 | 仍开放范围 |
| --- | --- | --- |
| Word | 六套符号/八套编号库、最近/文档/级别区、清除和源完整符号/编号定义，可信顶层多段同事务。845d真实UI/UndoRedo/390px/reload/修订4→5保存/下载/新修订重开通过，151实际HTTP资源逐SHA匹配；独立lxml/python-docx/ZIP确认★、两份九级定义、upperRoman/start7/Arial14/颜色/粗斜体/右对齐及旧文和15个部件保全。见[普通列表验收](NATIVE_WORD_LIST_LIBRARIES_ACCEPTANCE.md)。 | 独立设置编号值continue/restart/advance已由[后续专项](NATIVE_WORD_NUMBERING_VALUE_ACCEPTANCE.md)交付，限有可核验定义的可信顶层列表；图片项目符号、完整段落与复杂目标仍开放。 |
| XLSX | 推荐图表源算法、真实选区数据SVG/排名/理由与选择插入，取消/Escape不脏；Year数值分类不误作系列。845d首次完整HTTP链包含D20人工值及bold、FileUndoRedo/reload/保存4→5/下载/重开，171实际资源逐SHA匹配；独立openpyxl/lxml/ZIP确认新LineChart、分类refs/values、原图和anchor及7个part保全。真实文件发现绝对drawing Target解析缺陷，最小移植源已有resolver，4失败→13通过；未改夹具绕过。见[推荐图表验收](NATIVE_XLSX_RECOMMENDED_CHARTS_ACCEPTANCE.md)。 | 完整ChartPanels/SelectData、细粒度series/point及复杂格式仍开放；不称完整图表族完成。 |
| PDF | 源Bates可搜索文字、原字段/六位置、页面身份快照编号；源码HTTP完整保存下载重开及独立pypdf检查通过。最终845d只做最小冻结续验，106资源响应/52独立文件逐SHA匹配，12产品文件三方身份一致，0save；桌面/390px按钮可达。见[Bates验收](NATIVE_PDF_BATES_SOURCE_ACCEPTANCE_20261113.md)。 | 不扩源不存在的suffix，不以图像页脚近似；删除不补号、重排不重编号、后增blank不编号。其它源工具族继续逐项对齐，不把冻结minimal冒称完整保存重跑。 |
| PPTX | 源SlideThumb/slide-selection/useVisibleThumbs与Normal/Sorter，真实多选/拖排/键盘/双击/批删一次历史及备注保留；源码完整HTTP保存下载重开独立ZIP回读只改presentation和目标notes，另45part原字节。845d最小冻结从实际下载重导入、互切/真实缩略图通过，145实际资源含132JS/13CSS及HTML字节匹配，0save。见[视图验收](NATIVE_PPTX_VIEW_MODES_ACCEPTANCE.md)。 | Outline/Reading已由[后续专项](NATIVE_PPTX_OUTLINE_READING_ACCEPTANCE.md)交付，限文字大纲浏览和静态逐页阅读；桌面IPC剪贴板/上下文菜单及其余工具面仍开放，不宣称桌面PowerPoint等价。 |

Word真实浏览器发现源Dropdown置于label内导致选字体后默认二次激活trigger，菜单重开遮挡确认；宿主capture阶段preventDefault局部修复，不改原vendor，真实三种对话框RED→GREEN。JSDOM基线本已通过，不作为复现证据。源码01–04失败和中间失败修复均保留；04末端开发字体URL404使全脚本失败，即使该次下载独立通过也不改称完整GREEN；最终冻结完整链无404并退出0。PPTX冻结首轮harness假定manifest含native.html键失败，改按实际HTML脚本与HTTP字节核验后最小续验通过，未改产品。

Word实际下载38307字节SHA `3a58ed202e9a9c081bf4dd88afef8cf874449e51d282caa17b2f86e10f1bf02c`；XLSX7464字节SHA `7d79ccfa23326729cf464512170b06698abded49d2edf3e26f44301bf766cab8`。两者仍返回validation.ok=false/native_source_review_pending，已核验身份的文件照常签发下载，未标业务验收通过。root额外逐资产核对四格式实际响应与冻结磁盘、独立读回Word/XLSX下载ZIP并目视关键对话框与重开图；不将替身HTTP路由等同生产授权仓储或桌面Office验收。

统一证据 `/dev/shm/office-four-format-source-library-20261113/summary.json`。快照后测试工具两项有意增量：Word开发字体夹具symlink、PPTX实际HTML入口判定；产品身份与冻结源码分别核对，后续并发漂移另表记录、不覆盖或外推。原始来源登记与LOCAL适配身份保持分层；PDF几何/类型为源摘录而非整文件原字节，protocol为本地适配。未重复完整测试，未提交、推送或部署；本批仅关闭明确子能力，四格式整体对齐goal继续active，不给未经穷尽的总完成率。

归档并发边界：最终4119份物理快照身份复核无漂移；live工作区另有9路径变化。两项为本批有意测试工具修正，其余包含docx-line-spacing、pdf-protection、slides-native-chart-edit、workbook-chart-design-dialog/workbook-main及chart-read等并发改动，详见统一目录worktree-drift-final.json。冻结XLSX LOCAL11项与PDF LOCAL200项均匹配；live chart-read与其旧LOCAL登记不匹配属于后续并发状态，未擅自重登记、覆盖或追赶重建。五项实际Python后端文件前后SHA均与物理快照一致。最终结论绑定845d冻结包，不认证这些后续live变化。


## 2026-11-13 编号值／打印设置／文档属性／大纲阅读续批（最终 f9e161a9）

本节记录这一批最终物理版本，覆盖此前历史表格中仍写为缺口的对应子项，不将历史通过结论直接外推到后来并发代码。固定源仍为 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；整体穷尽对齐目标保持 active。

| 格式 | 本批实际交付与证据边界 | 仍开放的范围 |
| --- | --- | --- |
| Word | 原源“设置编号值”对话框接入，restart／continue／advance 从当前项向后重绑，同 abstractNum 的 restartNums／startOverride，保留层级、正文和格式；UndoRedo、过期拒绝、NativeDraft、真实修订4→5保存下载重开、lxml/python-docx/ZIP独立回读通过。最终入口0save续验153个实际JS/CSS及HTML身份匹配。见[编号值专项](NATIVE_WORD_NUMBERING_VALUE_ACCEPTANCE.md)。 | 没有可核验定义的未保存Home synthetic列表、复杂嵌套/只读目标、图片符号及完整段落/其它工具族不在本批关闭范围。 |
| XLSX | 源PrintDialog可执行的范围、纸张、方向、边距、缩放、页码裁切、网格/行列标、HF回返、fit/actual、刷新/取消接入原pageSetupJournal。实际发现并修复隐藏表状态在reader→Univer投影丢失，以及草稿恢复误把窄边距分类为custom。实际spool HTML经Chromium打印为两页B5横向PDF；唯一一次保存/授权下载/修订5重开和独立openpyxl/lxml/ZIP/pypdf回读均有证据。04总脚本因harness在沙箱iframe读storage失败，保留false；产物从原r5/saved.json、HTTP和bytes恢复证据，05/06零保存授权重开均通过，173资源逐字匹配、四live后端起止身份稳定，390px另存PDF/打印/取消均滚动可达。见[打印设置专项](NATIVE_XLSX_PRINT_DIALOG_ACCEPTANCE.md)。 | 桌面打印机枚举/指定设备、静默打印、份数/逐份、应用直接PDF输出无浏览器宿主API，仍是明确缺口；浏览器系统打印中的另存PDF不能被称为应用直接导出。完整图表/其它工具族仍开放。 |
| PDF | title／author／subject／keywords完整草稿→预览确认→保存下载重开；关键字归一与空串清空、取消/历史/恢复、组合重排旋转及其余元数据/书签/附件保留由pypdf独立确认。修复了setMetadata遗漏实际预览加载白名单的问题。最终0save层108响应/54独立资源及HTML身份匹配，390px可滚动到确认。见[属性专项](NATIVE_PDF_METADATA_SOURCE_ACCEPTANCE_20261113.md)。 | 不代表其余PDF源文件工具、批量派生产物和复杂导航/表单保真全部完成；拆分等其余能力仍需独立实现和验收。 |
| PPTX | 复用源Outline提取与Reading静态SlideThumb：大纲标题/正文/省略号、隐藏/空白页、键盘/IME、编辑Canvas历史与草稿、源HTTP保存下载及ZIP/python-pptx回读通过。最终0save层147实际资源及HTML匹配，390px实际阅读Canvas和翻页可用。见[大纲阅读专项](NATIVE_PPTX_OUTLINE_READING_ACCEPTANCE.md)。 | Reading只按源静态逐页显示，不包含动画、转场、媒体播放。母版/版式编辑、桌面IPC及完整AI/其它工具面不由本批关闭；母版等后续改动需对应证据。 |

最终物理源码：`/dev/shm/office-four-format-numbering-print-metadata-20261113-v4/source`。4147份源码摘要、102份后端Python基线摘要、各阶段补丁来源及后续live漂移分别登记。v3严格复制v2，仅加入隐藏表reader/投影、测试与LOCAL摘要；v4严格复制v3，仅将workbook-main的一行边距fallback替换为既有matchMarginPreset并加入测试。没有把后续共享工作树的段落属性、PDF目录显示、PPTX动画预览等并发改动混入本批，也没有覆盖这些改动。后端HTTP宿主实际执行live Python；复制的后端是身份基线，不虚称隔离执行。

最终manifest SHA256 `f9e161a924c55a6c9c0e5dc3bca80f5d9607b62e2c0552663bd39f830fd211be`，HTML `b2693d7db9506a240ca768e33be181c81d579bbfce8bc18451bf6731fd77f9d6`。最终Vite、tsc、原预算和预算合同exit0，Word主块246.2KiB、XLSX主块223.2KiB；原Word252.7KiB超限失败保留，通过列表host/原生操作模块边界拆包解决，没有提高预算。四引擎桥初次全部构建成功，隐藏表修复后重建工作簿桥，其余源/桥字节相同后复用，最终桥摘要均登记。

定向日志：Word前端及相邻51项、原生10项；拆包后8项是前述用例重验，不累加；XLSX既有打印29项、新hidden2项（连相邻6项共8项日志）、新margin1项；PPTX视图及相邻50项；PDF当前非阻断服务1项。均为定向证据，不是完整测试。root独立逐资源再核最终四格式HTTP字节、四个实际下载身份、原r5登记、SOURCE摘要与LOCAL11项，并目视Word/PDF/PPTX窄屏、XLSX打印按钮与实际PDF渲染；结果保存在统一 `root-independent-verification.json` 和 `summary.json`。

实际下载：Word38243B／`d6be33132de0dec65fe1d36d4178c50272e6281f5bd7eb20e49316691b8d6b4c`；XLSX8218B／`23c6012149da45e825f501853eca0669504e1fd5094a6acdb9d1e41e1ef393d1`；PDF1499B／`ca73227b8638444ac05962559f79f80f3723f6a57e6b30f655f981baf72fac81`；PPTX／`aea1806ab2b8086f361a92c02f294cd2e22d9ec0b0c7396214ed384fd0fc111a`。Word/PDF/PPTX保存响应保留native_source_review_pending失败且照常签发；XLSX04响应未持久，明确不伪造其validation字段，登记/HTTP/文件与零保存续验分层保留。业务验收未标通过，四格式整体目标未完成；未重复完整测试，未修改发布门禁、未提交/推送/部署。


## 2026-11-13 Home编号值／SelectData／PDF多文件拆分／母版文字续批（最终 b8b97ee）

固定参照仍为 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。统一物理根 `/dev/shm/office-next-split-master-chart-home-20261113` 的最终源码清单为4203份，最终manifest为 `b8b97ee76d41a565f94e9f8c902e226031ada09ad9cd3bcf52deb886f421f04c`，实际native HTML为 `aaa3eb21c2eb976afff3d1ae6a7ace757b75e2613a1b7272c6613cc4728a29c2`。最终类型检查、Vite、原预算和预算合同exit0，PDF主块249.3KiB，未提高预算。历史构建及失败记录保留。

证据分层：Word、XLSX、PPTX的完整保存/下载/新修订重开绑定原manifest `352eb5fc3903b0d6c145c1f1e873e2ad983a2f58b7ec1e0d3567f18b3ba1a560`；三者在最终b8b97ee上仅重开各自原实际下载文件作0save续验，没有重复保存或签发。PDF的352eb5首次入口因初始化TDZ失败，实际0save/0split；仅修复两处document前置短路并补回归后，b8b97ee才完成该专项首次完整HTTP链。不得把两层合并写为四格式均在最终构建重跑完整保存。

本节是对前述历史缺口的追加限定：普通Home未保存列表没有可信定义、单plot选择数据立即覆盖、每N页多文件拆分入口禁用、已有顶层母版/版式文字无法编辑四个子缺口，已分别完成下列证据范围；不能据此删除各格式其它缺口。

| 子项 | 已补与证据 | 仍开放 |
| --- | --- | --- |
| Word Home编号值 | 来源同类定义复用/源五级缺省定义、稳定绑定及listKind；UndoRedo/草稿/清除/标题恢复、一次4→5保存、独立编号定义回读和最终155资源0save续验。 | 新增未登记段落、嵌套/复杂目标、图片符号与全部自动编号/图库链。 |
| XLSX单plot SelectData | 可取消逐系列编辑、跨表raw一维向量、增删重排与源缓存literal转置；numLit读取/显示、一次4→5保存下载、最终173资源及真实canvas0save续验。 | bar+line逐系列plot/secondaryAxis；完整轴/标签/点格式、细粒度series/point及其它ChartPanels。 |
| PDF每N页拆分 | 必须先确认并保存脏草稿，使用新修订授权生成多份；最终一次保存/一次拆分、三份独立页序回读与60次资源响应（58个不同文件）。 | 非任意复杂PDF无损拆分；AcroForm/批注/保护来源拒绝，来源级书签/附件不保留；其它工具族及并发compare/native-AI不认证。 |
| PPTX母版/版式顶层文字 | 源part-addressed runTxn/setText、同一草稿/历史；一次保存仅改目标master/layout，另45实体保全；最终153资源0save及两页实际继承显示。 | 逐run富文本、组内对象、创建/删除母版版式、完整MasterView和完整播放/媒体链。 |

对应专项：[Word](NATIVE_WORD_HOME_NUMBERING_ACCEPTANCE_20261113.md)、[XLSX](NATIVE_XLSX_SELECT_DATA_ACCEPTANCE.md)、[PDF](NATIVE_PDF_SPLIT_BATCH_SOURCE_ACCEPTANCE_20261113.md)、[PPTX](NATIVE_PPTX_MASTER_TEXT_ACCEPTANCE.md)。实际下载身份分别为Word38145B／`05120581541e4e42d12d4ebb938e52ef9bfc4f59012bcf4270b4deacdf3736e0`、XLSX7124B／`93c520c470488a4f3943ea7b07392683eeb2cd23cb9df755eb55b084d74f3c22`、PPTX／`a50b97dd264d55f4f94659d2318a149c29535c2cb5c89029489a49a2065d5ac9`。PDF三份SHA与页序见专项 `browser-frozen-initialization-fixed/independent-verification.json`。

HTTP宿主实际执行live Python，物理复制的102份后端文件仅为身份基线，不是隔离后端。XLSX四文件、PDF八文件保留实际逐文件before/after哈希且匹配旧基线；PPTX保留102文件匹配的检查回执，未保留每文件原始哈希；Word没有保留逐次后端起止身份回执，不能由前端哈希推定后端稳定。验收结束后的live后端持续并发漂移：初始记录见统一根 `live-backend-drift-after-evidence.json`，更新状态见 `root-independent-verification.json` 的 `postEvidenceLiveBackendDrift`，以具体时间的清单为准，不写全live稳定。不覆盖、不追赶重建，也不把后续live状态纳入本批结论。

保存回执继续保留 `validation.ok=false/native_source_review_pending`；PDF三份派生结果也保持validation false。已核验身份的实际文件照常签发下载，技术闭环不等于业务验收通过。各专项的独立ZIP/lxml/python-docx/openpyxl/python-pptx/pypdf回读按原记录引用；root随后完成统一只读复核，`root-independent-verification.json` 为 `ok=true`：4203源码、四格式实际下载包、最终HTTP资源和LOCAL适配登记匹配，预算未提高。该复核不等于后续live代码或生产数据库鉴权验收。整体四格式穷尽对齐目标仍active，未给全能力完成率。本次仅追加审计记录，没有重跑测试、保存、构建或修改产品。


## 2026-11-13 续批：首字下沉、组合图、PDF合并、母版文字增删

本节更新上述历史缺口，仅关闭已验证范围。详见 [四格式本批验收](NATIVE_FOUR_FORMAT_DROPCAP_COMBO_MERGE_MASTER_ACCEPTANCE_20261113.md) 及其四专项。统一物理根 `/dev/shm/office-next-dropcap-combo-merge-master-elements-20261113`，4283份源码、104份后端身份基线；manifest `615163c4c3ded620bb13234122204fc6f4002f03c2c8079a1d1c444da6373650`。tsc/Vite/原预算/预算契约/四桥通过；PDF仅修构建banner后7个mjs语法通过，前端manifest未变。

- Word：固定源首字下沉无/下沉/悬挂及与正文/局部斜体组合，草稿/UndoRedo/390px/唯一4→5保存下载重开；实际38201B，16非目标部件保全。相邻一个既有装饰断言仍失败并在前批复现，不宣称全部旧测试通过。
- XLSX：bar+line组合图逐系列plot/secondaryAxis、family×axis分组与全局顺序、原主轴保留；人工J2/bold、唯一4→5保存下载重开，实际6900B。不能继续把本轮覆盖的组合子集列为未实现；完整图表格式仍需逐项源核对。
- PDF：多文件按用户列表顺序合并；未确认0save/0merge，之后一次保存及一次merge；实际3931B，独立6页回读3/2/1+B1/A1/A2并派生重开。沿既有6MiB上传边界；外部表单字段树/目录/附件不保证完整迁移、签名有效性不保证，明确告警。
- PPTX：已有母版/版式部件内新增顶层文字框、改pending文字/几何、移除pending、删原文字；唯一保存至修订2，实际48179B，47个非目录文件中只两目标parts变，45个保全。源MasterView并无创建/删除母版版式部件入口且不进入组内；这些仅作边界，不再当作已确认源差距。现有对象填充/描边等仍未由此完成。

四种保存均一次，不重复完整测试。Word/XLSX/PPTX各104实际live Python文件起止相等，但render_preparation.py/service.py两项在运行前已与冻结基线不同；PDF只核验9条签发链且匹配稳定。物理后端副本不是隔离执行。资源Word159/XLSX174/PPTX155不同文件，PDF128条响应/64不同文件均与冻结文件SHA匹配；XLSX未保留完整链原始HTML哈希，不冒充已有该回执。冻结LOCAL四旧登记通过独立sidecar调和，SOURCE和旧清单未改。

root独立复核 `root-independent-verification.json` 为ok=true，四实际下载由ZIP/lxml/python-docx/openpyxl/python-pptx/pypdf独立回读；首次工具误把ZIP目录条目计成文件身份失败保留，修正文件判定后exit0，未改产品或重保存。业务validation仍false且具体原因保留，身份已核验产物正常签发；生产数据库鉴权与全量业务验收未完成。完整对齐goal保持active，未提交/推送/部署，也未覆盖继续变化的并发live工作。


## 2026-11-13 样式窗格／单元格格式／静态填写／音视频续批

本批仅关闭四个明确组件族，见[统一验收](NATIVE_FOUR_FORMAT_STYLES_MEDIA_FORMAT_FILL_ACCEPTANCE_20261113.md)：[Word样式窗格](NATIVE_WORD_STYLES_PANE_ACCEPTANCE_20261113.md)、[XLSX六页签格式](NATIVE_XLSX_FORMAT_CELLS_ACCEPTANCE_20261113.md)、[PDF静态填写](NATIVE_PDF_STATIC_FILL_ACCEPTANCE_20261113.md)、[PPTX媒体](NATIVE_PPTX_MEDIA_ACCEPTANCE_20261113.md)。最终v5 manifest `11c248ae3a4c6fa31fad99f04d2e72437abc4440569e1d846615616b7f442e17`，4361源码身份、类型检查/构建/原预算及root独立回读通过。v4完整交互与v5局部续验分层，不冒称最终重新完整保存四格式。XLSX首次末端资源加载失败保留，随后真实下载重导入和v5原请求最小保存/修订重开通过；PDF低高度裁切经专用滚动修复及真实鼠标滚轮/按钮命中补验。已验收子集不再笼统列为完全未实现，但完整格式/复杂对象/宿主边界与其余源组件继续开放。业务validation仍false，下载正常签发；未重复完整测试、未提交/推送/部署。

## 2026-11-13 下一批完整组件族冻结补充

Word完整PageBorderDialog、XLSX完整Paste Special、PDF CropDialog/CutoutDialog、PPTX FormatBackgroundPane已接线并通过不可变构建/真实保存下载/独立文件回读。详见NATIVE_FOUR_FORMAT_NEXT_FAMILIES_ACCEPTANCE_20261113.md及四专项；该补充仅更新相应组件族，不表示历史清单全量完成。已知Word表格结尾补段与PPTX自定义放映OOXML持久化仍为缺口。

## 2026-11-13 固定源交互续批

固定源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。Word 段落对话框新增可信普通单元格的单段落格式设置，桥接以表、格、段落 XML SHA 身份约束并只补目标 `<w:p>`；前端对话框/草稿采集/回放定向81项通过，真实 DOCX新增桥接用例2项通过。完整 `test_docx_engine_bridge.py` 为120项通过、2项失败（段落字体回读、隔离测试缺少 bridge 依赖）；多段及复杂格仍只读。PDF 缩略图新增 pageId 右键操作菜单（旋转、删除、提取、插入 PDF、插空白页），宿主和外部页定向用例通过。PPTX 母版/版式现有顶层对象新增几何调整及描边/清除描边，身份绑定源部件和 SPID，沿用草稿/撤销链；描边固定1pt，bridge 5项、前端8项、Python协议28项与定向 `tsc`/Ruff 通过。XLSX 页眉/页脚图像现从授权 XLSX ZIP 的 `legacyDrawingHF`/VML/内部媒体关系读取，按 odd/even/first 及左右中槽位写入打印 HTML；真实 ZIP→打印 HTML用例、打印定向19项、引擎 ZIP测试1项及引擎 `tsc` 通过。跨工作簿选择及桌面打印仍缺宿主 API。共享前端全量 `tsc` 此前报 `slides-main.ts` dispose 类型和图表窗格测试 tuple 诊断；全局 `git diff --check` 仍受并发 PDF IPC 文件 EOF 空行影响，本轮改动文件定向检查通过。全格式穷尽对齐继续开放。

## 2026-11-13 Word 正文跟踪修订增量

已接入顶层简单段落单个连续文本变更的修订记录与保存回读：编辑器 operation 不接收作者/日期，服务端从授权 scope 取用户 ID 并生成 UTC 时间；复杂段落、已有修订及重叠目标继续拒绝。Review 跟踪开关现读取/写入 DOCX `word/settings.xml` 的 `w:trackRevisions`，通过来源 SHA 绑定的文档级 operation 保存，受保护文档只读；设置启停、重开读取、非目标 ZIP 部件保全（排除正常更新的 `docProps/core.xml`）已通过 bridge、Python host 和隔离冻结浏览器验证。详见[Word 跟踪修订设置验收](NATIVE_WORD_TRACK_REVISIONS_ACCEPTANCE_20261113.md)。
