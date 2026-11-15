# 四格式 GenOffice 对齐范围与执行索引

更新：2026-11-13。用户目标：**Word、XLSX、PPTX、PDF 对齐 GenOffice，包括功能区、中文功能区、图标，AI 功能也对齐，AI agent 替换为 Agno 驱动。** 原先Word/XLSX专项只是该完整目标的子集。当前未完成，不给未经穷尽盘点的完成百分比。

剩余工作量评估见[2026-11-13 工量与排期](NATIVE_GENOFFICE_REMAINING_EFFORT_20261113.md)：完整目标暂估 100–180 有效人日，其中四格式 AI 工具与任务生命周期 25–45 人日，已包含在总量内。已专项交付的子能力不再按全缺重估；后续 XLSX AI 来源图表两项回归已修，协议／保存子链及真实 provider 分层验证通过，单点折线等视觉边界和生产同链仍开放，见[来源图表专项](NATIVE_XLSX_AI_CHART_SOURCES_ACCEPTANCE_20261113.md)。

固定参考源 `/home/junge/pros/genoffice-source-full`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。应用分支code截至2026-11-13本轮再次 fetch 后核对与origin/code同步于 `1138887df2541b748ebe5746871e4198bb48a712`，左右提交数 `0 0`；保留全部本地未提交改动。历史验收代表各自冻结构建，不能自动证明快进后的整个产品。

本轮审阅／缩略图／图表／打印续批见[增量记录](NATIVE_PARITY_REVIEW_INCREMENT_20261113.md)，后续[修订视图／图片缩略图／散点图批次](NATIVE_REVIEW_IMAGES_SCATTER_ACCEPTANCE_20261113.md)分别登记实际执行的检查。另有[PDF Page与缩略图源盘点](NATIVE_PDF_SOURCE_INVENTORY_20261113_INCREMENT.md)、[XLSX图表命令族盘点](NATIVE_XLSX_CHART_COMMAND_FAMILY_INVENTORY_20261113.md)、[PPTX文件菜单八入口盘点](NATIVE_PPTX_FILE_SOURCE_INVENTORY_20261113.md)、[当前草稿打印冻结验收](NATIVE_PPTX_PRINT_ACCEPTANCE_20261113.md)、[Word修订设置保存验收](NATIVE_WORD_TRACK_REVISIONS_ACCEPTANCE_20261113.md)和[Three分块运行时专项](NATIVE_THREE_RUNTIME_ACCEPTANCE_20261113.md)。这些是明确子范围证据，完整目标仍未完成。

## 验收要求

1. 四种格式的源真实入口、回调、底层读写及失败边界逐项对应；不能以按钮存在、永久禁用、保留对象或hash替代功能闭环。源自身只会话或没有持久化的功能另记源边界，不静默从完整目标删除。
2. 常规及上下文功能区中文标签、组名、帮助、弹窗和无障碍名称一致，具有相应图标；复用源图标/既有图标库，不把 rb-icon CSS 类名当实际图标证据。
3. AI逐源能力覆盖选择上下文、工具/任务、流式进度与取消、建议预览/采纳/拒绝、Undo及草稿/保存。保留业务权限和文件身份校验，驱动复用现有Agno框架。仅已有一个Agno规划器不等于整套源AI功能已对齐。
4. 有效修改经真实界面、草稿恢复、原生保存、实际下载和明确新修订重开；独立文件回读与视觉核验按功能需求执行。真实模型任务需另有实际调用证据，模拟planner不计真实模型验证。适用的发布非阻断契约保持。

## 已交付子能力与剩余边界（2026-11-13 更正）

以下项目从“全缺／未实现”清单移除，按专项已交付范围登记。下文历史批次中的旧缺口不再代表这些项目的当前状态；历史构建、失败和验收记录保留，不外推为当前整包或生产端到端通过。

| 格式 | 已交付，不再列为全缺 | 仅保留的范围限制与证据 |
| --- | --- | --- |
| Word | 普通符号／编号库、多级列表库、自定义定义及设置编号值（重新开始／继续／继续并前进）。 | 限可信原有顶层段落；编号值需可核验的原始或当前自定义定义，未保存且无定义的快捷列表仍受限。图片项目符号、复杂嵌套目标及完整段落选项仍开放。见[普通列表](NATIVE_WORD_LIST_LIBRARIES_ACCEPTANCE.md)、[多级列表](NATIVE_WORD_MULTILEVEL_ACCEPTANCE.md)、[编号值](NATIVE_WORD_NUMBERING_VALUE_ACCEPTANCE.md)。 |
| XLSX | 推荐图表、多图对象选择、快速布局／配色，以及限定锚点的移动／缩放。 | 两格锚点支持移动和八向缩放，单格锚点只支持移动，absolute 锚点拒绝移动／缩放。完整格式面板、复杂 SelectData 和细粒度 series／point 编辑仍开放。见[推荐图表](NATIVE_XLSX_RECOMMENDED_CHARTS_ACCEPTANCE.md)、[选择与预设](NATIVE_XLSX_CHART_SELECTION_PRESETS_ACCEPTANCE.md)、[对象几何](NATIVE_XLSX_CHART_OBJECT_GEOMETRY_ACCEPTANCE.md)。 |
| PDF | 书签当前页新增／嵌套改名／删子树／清空、Bates 编号、标题／作者／主题／关键词四项属性编辑。 | 复杂或不可信书签树及签名／保护来源仍受限；Bates 为应用时页面身份快照，重排不重编号、删页不补号、后插页不自动编号；属性仅四字段，不扩展为任意 Info／XMP 编辑，受来源能力与既有组合边界限制。见[书签](NATIVE_PDF_SOURCE_GAPS_BOOKMARKS_20261113.md)、[Bates](NATIVE_PDF_BATES_SOURCE_ACCEPTANCE_20261113.md)、[四项属性](NATIVE_PDF_METADATA_SOURCE_ACCEPTANCE_20261113.md)。 |
| PPTX | 普通／排序／大纲／阅读视图，以及拼写检查和翻译预设入口。 | 大纲为浏览选页，阅读为静态逐页浏览，不代表独立大纲编辑或动画／媒体播放。拼写为整稿、翻译为当前页，21 语言预设复用 Agno 候选与显式采纳；ScriptedModel／冻结入口证据不等于真实 provider 翻译质量或预设专项保存下载验收。桌面宿主及其余工具面仍开放。见[普通／排序](NATIVE_PPTX_VIEW_MODES_ACCEPTANCE.md)、[大纲／阅读](NATIVE_PPTX_OUTLINE_READING_ACCEPTANCE.md)、[拼写／翻译](NATIVE_PPTX_AI_PRESETS_ACCEPTANCE.md)。 |

## 当前有源码证据的重点缺口（非穷尽）

以下为当前状态；后文按阶段记录的“未实现／待构建”是历史，不覆盖本表。新增源码尚未构建时，不借上轮静态资产声称本轮浏览器已通过。

| 范围 | 已核实状态 | 下一步 |
| --- | --- | --- |
| Word/XLSX完整功能 | Word 根批注新建与 XLSX 透视表创建/编辑新增真实闭环；e13de64 冻结构建已验取消、历史/恢复、保存下载及新修订重开，并独立 ZIP/lxml/openpyxl 回读。此前批注纯文字编辑、分类汇总、高级筛选及只读表身份保护继续保留。见 [当前缺口](NATIVE_WORD_XLSX_CURRENT_GAPS.md)、[根批注验收](NATIVE_WORD_NEW_COMMENT_ACCEPTANCE.md)、[透视表验收](frontend/WORKBOOK_PIVOT.md)。 | Word 批注回复/删除/解决、复杂锚点/嵌套表；XLSX 完整透视报告筛选/分组/计算字段与源完整工具面仍需逐项闭环。 |
| PPTX功能区中文 | 上轮最终浏览器已核验中文和 96 个命令按钮各具真实 SVG。当前新增六类内建布局中文显示，保持布局 ID/value 及来源自定义对象名；专项与final3严格布局交互浏览器已通过，final4实际入口及相同slides-main原始字节补验通过。 | 新版式下拉、右侧显示及双向立即同步已验收；继续检查未盘点弹窗、媒体与源完整工具面。 |
| 功能区图标 | Word/XLSX/PPTX/PDF 已有中文及图标专项、真实 DOM 与部分浏览器证据；不能以源码 icon 类名代替渲染结果，也没有全源穷尽证明。 | 保持真实图标并逐剩余入口核验功能回调，禁用占位不计功能交付。 |
| PDF AI入口 | 原四个只读 Agno 入口及草稿阅读保留；新增逐根批注改文+AI回复/澄清/跳过、中文SVG面板、完整草稿候选与显式采纳。真实模型9.15秒已验700与AI作者；e2fadd冻结五场景浏览器通过；最后829584 CSS修复构建的实际用户“校验当前修改”已显示700、两项执行、确认框未选且面板可滚动无重叠。真实HTTP/ScriptedModel浏览器与真实provider分层，见 [处理批注验收](NATIVE_PDF_REVIEW_AI_ACCEPTANCE.md)。 | 未保存新增便签的可信append映射与Agno改文回复已新增实际UI/四项执行/精确第二新根IRT验证，见 [草稿便签验收](NATIVE_PDF_REVIEW_PENDING_ACCEPTANCE.md)；合并/拆分页映射、复杂原位重排、全部源 AI 工具、长任务持久恢复与生产整链仍缺；共用 SSE 与终态增量见[任务生命周期](NATIVE_AI_TASK_LIFECYCLE_ACCEPTANCE_20261113.md)；本增量不等于PDF AI全部完成。 |
| PPTX原生上下文AI | 已接专属原生会话路由，现有文字/几何、整稿页序和商务主题经真实引擎候选预览、显式采纳及同一 UndoRedo/保存链。/tmp/pptx-native-ai-verified-20261111/evidence.json 为 ok:true，含新修订下载独立回读；planner 为确定性替身。 | 合成单对象真实 provider 候选/引擎/显式采纳与独立回读已通过；完整源工具、可恢复长任务和媒体 AI 仍缺；共用 SSE 与终态增量见[任务生命周期](NATIVE_AI_TASK_LIFECYCLE_ACCEPTANCE_20261113.md)，现有对象候选不等于全部工具。 |
| XLSX原生上下文AI | 当前新增专属 Agno 服务与路由、范围/整簿明确授权、候选预览和采纳宿主；app 工厂/路由/关闭钩子及 aiEnabled 开关已接，真实装配与权限专项 4 项 RED→GREEN。 | 真实 provider 的 writeValue 字段歧义已按明确布尔合同修复并真实复验通过，显式采纳后 openpyxl 回读正确；最终9f184c1e构建严格浏览器已通过：人工base、过期拒绝、采纳、取消、UndoRedo、新修订2、实际下载openpyxl回读、127实际JS身份与pageErrors=[]。浏览器HTTP/planner仍为明确标记夹具，与真实router及provider专项分层。范围受限结构化候选不等于固定源完整 AI 工具。 |
| Agno已有基础 | 复用既有 ReportingStructuredOutputExecutor 与 create_reporting_generator_agent；新 PDF reader 使用四个来源绑定只读工具，已修复 PDF 模型结构化协议协商，已修复 XLSX 候选字段语义并完成受限真实模型候选复验；真实范围见 [Provider 验收](NATIVE_OFFICE_AI_PROVIDER_ACCEPTANCE.md)。 | 统一生产配置语义，保留每任务工具/模型隔离；继续源完整 tools/stream/session 核实，不宣称 AI 全对齐。 |

源功能和四格式全量inventory、生产权限、桌面等效与真实AI调用目前均未全部核验。此文档确定完整范围和证据门槛，不将未实现事项包装成方案完成。详细后续按一缺口一子agent，最多3个子agent并行（当前环境共4活动槽含root），共享文件编辑分区，root集成及最终核对。不重复完整测试，不提交/推送/部署。

历史图表续批（2026-11-13）：默认/任意命名空间的编辑与删除完成110项定向、两端类型检查、隔离构建/预算及实际浏览器双修订下载重开，见[专项验收](NATIVE_XLSX_CHART_NAMESPACE_ACCEPTANCE.md)。该批当时未覆盖的 selectedVisual 定位、多图对象选择及快速布局/配色，已由后续[选择与预设专项](NATIVE_XLSX_CHART_SELECTION_PRESETS_ACCEPTANCE.md)关闭明确范围；推荐图表与限定拖动/缩放亦见上方已交付表，不再列为全缺。完整格式与四格式穷尽目标仍开放。

## 2026-11-11 本轮验证补充

- XLSX 高级筛选的 14 个主视图向量已分批通过，仍待 built-browser 验收；不能据此关闭完整筛选专项。`workbook-filters.ts` 的 pinned Univer 自定义条件 tuple 类型已修复；来源读取器 `filter-read.ts` 对超过两个条件设置只读，因此转换保持源的一至两个条件约束。
- `/tmp/four-format-build-20261111.log` 对应 `npm run build` 实际退出 0，包含 TypeScript 检查和 Vite 构建。预算及预算契约在同一冻结构建运行通过，日志分别为 `/tmp/four-format-budget-20261111.log`、`/tmp/four-format-budget-contract-20261111.log`。后续源码变更不能自动沿用该构建证据。
- XLSX Page Layout 旧测试仍寻找已替换的禁用 `scale`，已改为在明确有选区的状态下验证实际 `print-scale-open` 可点击并分发命令；仅该条定向回归通过，见 `/tmp/workbook-page-layout-ribbon-final.log`。

## PDF AI 源语义核实（初始调查，后续实施见当前状态）

固定源 `apps/pdf/src/renderer/App.tsx` 的 Home 总结/要点会按 `aiSelection` 选择整文或选区提示，再经 `runAiPreset` 打开同一个 AI 面板；Annotate 的总结审阅同样走该面板，处理批注仅在可编辑时可用。`i18n/strings.ts` 的中文提示及 `ai/pdf-skill.ts` 明确两种审阅行为：总结必须读取全部批注并按页/主题报告、保持只读；处理批注必须逐条定位原文，执行请求的修改后以 AI 身份回复，歧义时询问、跳过纯讨论和 AI 自身批注。不能将二者合并为单次选中文字改写。

源 `ai/tools.ts` 实际声明 `read_pages`、`search_text`、`read_annotations`、`add_note`、`reply_note`、`edit_note` 等工具，并有原位文字/图片/表单、页面和新文档工具。当前本地 `native_ai_api.py::NativeAIStartPayload` 强制非空 selection，`native_ai.py::NativeAIProposal` 强制至少一个编辑 operation；该合同不能表示只读整文总结或批注总结。下一步须复用 Agno 实现可返回只读回答、带页码引用的任务合同和上下文读取，再接入口；不能伪造空修改来绕过现有选区编辑合同。编辑类任务继续经已有候选预览、身份校验及采纳链路，不复用总结结果直接写文件。以上是源码调查证据，不是真实模型调用或功能验收。

## 后续修复证据（待最终构建）

筛选条件修改后Undo残留outline草稿已用真实Univer/main复现并修复：可承载source-filter数据区由workbookFilterOperations写回可见性，outline层级/折叠仍写入但省略冲突raw hidden。6项main回归与14项outline测试通过，覆盖清条件、源缓存隐藏、人工隐藏+group、新建live filter的原始outline写回；严格built smoke尚待新构建。Word已有批注Node/Python薄桥、真实发布下载/验收失败非阻断/幂等回归均通过，纯前端intent模块10项通过；前端main/controller接线中，仍不关闭批注产品缺口。

## 最终构建与真实运行时补充

最终构建日志 /tmp/four-format-build-final3-20261111.log、预算 /tmp/four-format-budget-final3-20261111.log、预算契约 /tmp/four-format-budget-contract-final3-20261111.log 对应同一命令链实际退出0。Word vendor图标独立分包，render为697.1KiB，不提高原710KiB门槛。包含PPTX中文/61按钮图标、Word批注main/controller与显式放弃重载/打开滚动聚焦、XLSX筛选与outline差分及Undo空草稿状态修复。最终Word/XLSX严格浏览器验收分别在独立端口运行，未以早前构建代替。

实际仓库 doc_engine 已执行 npm run bundle:bridges（/tmp/doc-engine-comment-bundle-20261111.log，exit0），并使用默认Python inspect_docx/patch_docx路径直接验证当前dist：中文emoji批注写入，仅word/comments.xml发生变化；不再仅依赖隔离临时bundle。完整批注族的新建/回复/删除/解决、真实FastAPI授权会话与完整四格式AI仍未完成。

## final3 浏览器验收结果

冻结manifest SHA184c94a96f863198c30ffcfaae1ec2169a8e6b6df2eaca50415bbd62538eada5。Word /tmp/docx-comment-gui-GliBSX/result.json：真实生产DOC引擎、122加载JS逐个SHA、errors=[]，改既有批注文字→UndoRedo→刷新→未blur保存→下载→明确新修订；仅comments.xml变更、旧source拒绝、面板无辅助滚动即可见且焦点/顶部保存可用。只关闭“已有可授权批注纯文字编辑”这一范围，完整批注族仍未实现，HTTP授权路由为替身。

XLSX /tmp/xlsx-advanced-filter-built-20261111-final-03/summary.json：ok=true、saveCount=3、resourceCount=126、errors=[]。三场景实际保存下载并ZIP CRC/lxml/openpyxl独立回读；新修订已保存/身份/空草稿成立。改条件→Undo空操作且已保存→Redo恢复同一草稿且未保存→最终Undo还原均严格通过，复制值也在实际await读取后精确一致。不删除前两版失败历史；clipboard原问题为smoke对async waitForFunction的错误使用，已修测试等待，不以放宽断言冒充产品修复。只关闭单列1–2条件AND/OR的明确高级筛选范围，不扩大成Excel所有高级筛选。

PPTX中文与按钮图标已进同一最终构建，26项DOM测试通过；完整PPTX浏览器视觉/宿主及AI仍待继续。PDF完整Agno任务/工具对齐仍未实现，详见NATIVE_PDF_AI_AGNO_ALIGNMENT_PLAN.md。目标保持四格式完整功能区中文/图标/功能及Agno AI，不以本轮三个专项替代完整目标；未提交/推送/部署。


## 2026-11-11 草稿阅读与原生 AI 集成增量

当前最终统一静态资源 manifest 为 9f184c1e8d6a2d8f94de6d61e0a368db19d9cad4141c0d6b0d065567b3e8b9ba；/tmp/four-format-ai-draft-build-final4-20261111.log（41.40秒）、budget-final4、budget-contract-final4 三个命令均实际退出0。既有 chunk-size/circular chunk 警告未伪装为零告警。该构建包含 PDF 草稿投影提示与nullable引用、XLSX AI 宿主及异步采纳卸载保护、PPTX 标准布局中文及右侧/功能区当前值双向同步。XLSX最终严格浏览器、PPTX/PDF最终入口与资产连续性均已通过，精确分层范围见末尾，不用早期构建替代新构建入口。

- 原生 XLSX app 工厂、专属路由、关闭钩子与 AI/office 双权限开关：新专项先2失败/2通过，再4通过，日志 /tmp/workbook-ai-registration-{red,green}-20261111.log。
- PDF 草稿面板投影身份、实际有效页码、真实跳过原因、原始页导航与新增页无原始ID禁用：新增界面回归先失败再通过，并与受影响原面板共6项通过，日志 /tmp/pdf-assistant-draft-{red,green}-20261111.log。后端18项增量、空草稿6项窄回归及9ee冻结构建四草稿严格浏览器，见 NATIVE_PDF_AI_READ_ACCEPTANCE.md；最终构建入口另补最小资产/浏览器验证，不将旧manifest改写为新整套验收。
- 共享取消竞态：原 cancel_edit 等待依赖后才标 cancelled；真实依赖吞 CancelledError 时会继续调用模型或发布候选。改为先登记终态/清候选，再取消等待；NativeAIService/PPTX/XLSX 每个生成阶段的 await 和异常出口均保留终态守卫。PPTX 新6项先失败后通过，连原相关取消共9通过；Word 新2项先失败后通过，连相关原取消共5通过，分别见 /tmp/native-slides-cancel-terminal-{red,green}-20261111.log、/tmp/native-ai-cancel-terminal-{red,green}-20261111.log。
- 独立只读审阅随后发现关闭钩子 aclose 也会继承同类问题。新增 PPTX/XLSX × 吞取消返回/转异常 共4例先全部失败，再以先标终态/清候选/取消/等待的最小修复全部通过，且验证关闭后不可 accept；见 /tmp/native-ai-shutdown-terminal-{red,green}-20261111.log。没有为此添加发布门禁或改变签发链。
- 四格式受限真实模型调用分开记录在 NATIVE_OFFICE_AI_PROVIDER_ACCEPTANCE.md。合成来源、作用域内存仓储与非生产DB边界保留，不把单次成功外推为完整 GenOffice AI 工具、真实部署或复杂文件全覆盖。

本轮没有重复完整测试、提交、推送或部署。完整目标仍未完成。


### final4 最终浏览器与独立审阅

最终磁盘manifest仍为9f184c1e8d6a2d8f94de6d61e0a368db19d9cad4141c0d6b0d065567b3e8b9ba，root独立复读三份最终摘要、源/下载文件SHA和XLSX内容后确认一致。

- XLSX：/tmp/xlsx-native-ai-verified-20261111/evidence.json 为 ok:true，127个实际JS身份、新修订2、明确采纳1次/取消2次、完整base过期拒绝、UndoRedo、实际下载及openpyxl独立回读通过，pageErrors=[]。source.xlsx A1为alpha/bold=true/italic=false；downloaded.xlsx为AI候选标题/bold=false/italic=true，SHA分别为78ac74b9473eb9a85a00052d19fbcbbe98090b740148f92ce521b662f069d7b4、80823d3d37dbe4f7f9527e7c3eb3e6ddfd2907b0edec10483f4daa2d60690a0f。浏览器使用route/planner夹具；真实router/生产model分别另验，不能拼接成生产DB端到端证明。
- XLSX运行时真实缺陷：初次采纳/Undo/Redo各捕获getUnitId空引用。源堆栈证实旧FWorkbook选择订阅在disposeUnit瞬间仍访问已移除unit；修复仅将旧selectionListener.dispose/清引用移到loadWorkbookData前，随后对新unit正常订阅。顺序回归先RED后GREEN，严格browser最终零pageerror，不吞异常或放宽断言。初轮脚本等待不足及后轮真实异常日志均保留；前两轮未在最后断言前落盘原生文件，不伪称有其下载字节证据。详情见WORKBOOK_NATIVE_AI.md。
- PPTX：/tmp/pptx-layout-locales-built-final3-03-20261111/evidence.json 覆盖标准布局中文、自定义源名、原ID/路径、新建草稿、当前版式双向立即同步、96按钮真实SVG，108个实际JS响应核对且错误为空。final4 /tmp/pptx-layout-entry-built-final4-20261111/evidence.json 只补真实入口与初始布局、对象名及108JS身份；slides-main原字节SHA与final3完全相同。不将final4入口补验称为再次完整布局交互测试。
- PDF：9ee冻结构建四草稿严格浏览器、f76冻结构建一次总结分别保留原有范围；final4 /tmp/pdf-ai-final4-entry-only-20261111/summary.json 仅真实入口/四中文SVG控件与21实际JS资源，无AI请求。18模块原字节相同，另3模块只生成导入名变化，按manifest映射替回后精确还原f76字节，非等价列表为空。没有把raw SHA变化说成不变，也没有重复完整四场景/provider测试。
- 独立只读代码审阅覆盖本轮共享取消/关闭、XLSX路由授权、完整base快照、PDFnullable引用与旧任务守卫。唯一发现的关闭P2已以4例RED→GREEN修复，原审阅agent复核关闭；不扩张到本轮未审阅的其它既有工作区差异。root另目视PPTX自定义版式和PDF新增页截图、独立回读XLSX最终产物。

以上仅关闭本轮明确子能力；Word复杂审阅/批注族、复杂嵌套表、四格式完整源AI工具与流式任务、媒体/表单及真实部署等仍待继续，不给未经全量盘点的完成百分比。未提交、推送或部署。

## 本批根批注、透视表与 PDF 审阅增量（2026-11-11）

- Word 根批注：e13de64 冻结构建的完整新建/取消/历史/恢复/未失焦保存/下载/修订2重开通过；root独立回读两条新范围均为chor t、旧批注ID1保留，新ID0/2不碰撞，修改部件仅document.xml/comments.xml。来源与下载SHA均与证据相符，root目视修订2截图。真实HTTP授权与验收失败仍签发下载另有专项，不拼接为生产DB整链。
- XLSX 透视表：e13de64完整交互证据 /tmp/workbook-pivot-built-final-20261111/evidence.json；root独立openpyxl回读真实pivot名称、average/count/max/min、4条cache records、grand average25与手工A1 bold保留，source/download SHA均吻合，root目视中文多值编辑对话框。新实现复用既有xlsx-engine，未造静态汇总替代。
- 独立回读实际修复：透视表average不能写成avg；跨表目标原XML无xmlns:r时必须绑定r；普通无扩展导入透视表重布局须走真实rebuild并清除旧输出尾部。Word跨内部普通空段的精确选区补齐，不以整段降级。PDF原位改字会规范字典键/浮点/字符串转义，需来源精确hash+ref及有界完整引用对象语义比较后重绑，不能放宽为按文字匹配。
- 首统一构建工作簿主包254.9KiB超250KiB预算，透视表改为首次命令懒加载，未调预算。e13de64成功构建39.53秒；随后PDF首浏览器发现旧客户端reply混合守卫及面板重叠，精确修复并保留失败证据。最新统一构建40.06秒、budget/contract均exit0，manifest为e2faddb5fb62f0db91b90b3248be4b8355ab5979d0b110eaa92dfde27dfe4daa。已有模块指令/circular/大chunk等warning仍保留，不称零告警。
- Word final2仅入口补验 /tmp/word-comment-create-entry-final2-20261111/evidence.json：122实际JS身份、中文双入口与源IconComment真实path、无编辑/save/export、错误空；docx-main原字节未变。XLSX final2仅入口补验 /tmp/workbook-pivot-entry-final2-20261111-observed/evidence.json：中文双入口真SVG、动态透视表chunk原字节未变、打开后取消、draft与写请求为空。两者不冒充最终构建重复完整交互。
- root精确连续性 /tmp/four-format-review-build-continuity-20261111.json：Word实际122JS中120原字节相同、2仅生成导入名变化；XLSX128中126原字节相同、2仅生成导入名变化。规范化只将旧/新manifest中的生成资源名映射回唯一稳定模块身份，之后整段脚本精确相等，非等价列表均空；worker依据旧浏览器实际SHA与最终磁盘字节精确相等验证。原始SHA变化不说成不变。
- 新增PDF真实模型任务deepseek-v4.1-flash 9.15秒完成，真实service/Agno/实际预览/显式accept后独立pypdf读回700及AI作者，源与未选择文字不变。合成来源/隔离内存仓储、一次中间解析warning及实际桥版本边界见 NATIVE_OFFICE_AI_PROVIDER_ACCEPTANCE.md。最终修复构建的新增浏览器结果待专属验收追加，不以provider局部成功冒充完整工具面。

此阶段只关闭明确验收的子能力；未保存新增PDF便签的AI处理、复杂Word锚点/回复/解决/删除、复杂嵌套表、完整透视报告筛选/计算字段、四格式完整AI工具/流式任务、未盘点的媒体/表单及完整源功能仍未完成。没有重跑完整项目suite，没有提交、推送或部署。

### 本批最终状态：829584 构建

最终磁盘manifest SHA为82958436439e2cf17b4035f8a60378a29d459e927ff32b87d4998bfd2735cbb9。最后CSS-only构建40.23秒，budget及budget contract均exit0；没有改阈值。Word桥abe54d7c7306eb05a136e6b8caf7255f80e870ee3eee88fa154fb7245b30fd71、PDF桥e423546f4e0ac84d9184e8fe48487b43fb7da769d339e510865330647aa1c711、工作簿桥495c7e78a27805067b8de2ec967db8546190be9e47c436bc81c4347a229ff7b0均核对。

- PDF完整五场景权威结果 /tmp/pdf-ai-review-built-final2c-20261111/summary.json，冻结e2fadd：normal/overflow/clarify/discussion/cancel均通过，21实际JS身份、跨DOM容器不重叠/滚动、源不变及零save/export；实际是Agno ScriptedModel，不能冒充provider。中间一轮helper因合法304响应和缓存假设退出，仅禁用浏览器缓存修正helper，保留失败目录，没有据此改产品。
- 额外真实用户预览发现：在e2fadd中两条执行清单新增108px，画布/确认功能已通过但flex:none面板溢出。仅让新review面板flex:0 1 auto、min-height:0，保留45vh上限/overflow:auto。最终 /tmp/pdf-ai-review-normal-ui-preview-final3-20261111/summary.json 为ok:true：实际点击“校验当前修改”，preview及preview.pdf HTTP200、operations逐字与草稿相同、返回PDF身份相符、PDFjs textLayer含700无500、两个执行条目、确认框初始未选。面板387px、scrollHeight613、实际滚动227，bottom与后方AI面板top均1039；21实际JS、page/console/HTTP错误空，源不变、零save/export。root独立复读摘要并目视实际700截图。
- 版本连续性 /tmp/pdf-ai-review-build-continuity-final3-20261111.json：e2fadd五场景21JS到最终829584中18原字节相同、3仅生成导入名变化，规范化后全文精确相等，非等价为空。没有把final3窄用户预览称为重跑完整五场景。
- Word/XLSX到最终829584连续性 /tmp/four-format-review-build-continuity-final3-20261111.json：实际122/128JS分别120/126原字节相同，各2仅生成导入名变化，规范化后全文精确相等。完整交互仍对应e13de64，真实入口补验对应e2fadd，最终CSS-only构建靠明确资源连续性衔接，不冒称全部场景重新运行。

本阶段新增能力已达到上述限定验收面；原始四格式完整目标仍未完成，当前缺口表继续有效。没有重复完整项目suite、提交、推送或部署。


## 2026-11-11 回复、待保存便签与隐藏页本批收尾

最终统一前端 manifest 为 7536053f7c47638639d26d3f4ac63285b33cd05f64fdb7d7a82229106710696d。/tmp/four-format-reply-pending-hidden-build-final4-20261111.log（Vite 40.92秒）、budget-final4、budget-contract-final4 同一命令链实际 exit0；保留既有 chunk/circular/module 注释警告，没有提高预算或声称零构建警告。未运行完整项目测试，未提交、推送或部署。

- Word 既有根线程文字回复已接真实 OOXML 父关联及同一草稿/历史/恢复/未失焦保存；完整保存下载与修订2仍对应8c3和独立真实HTTP非阻断证据。971b补验锁解除状态提示；独立审阅随后确定多根A空输入切B会把回复错误提交给A，单行修复同步重绑target与当前snapshot，7项控制器回归通过。final4仅运行新增多根切换窄浏览器：122实际JS，PM/草稿精确B、A无新增、UndoRedo与非空拒绝保全、错误全空、零save/export/patch。root独立复读并目视两截图；具体见 NATIVE_WORD_COMMENT_REPLY_ACCEPTANCE.md。不把旧单根保存链说成已在新构建重跑。
- PDF 未保存新增便签可由Agno在完整base绑定下改字并回复，按实际引擎append回执的operationIndex/localId/PDFRef定位，含同外观双根精确归属。8c3窄浏览器实际21JS、正常预览700、四项已执行及未选确认框、真实新增回复25R精确指第二根23R，源与base保全，零save/export；使用真实Agno加ScriptedModel，不能称为本轮真实provider。独立只读审阅未发现指定映射范围的确定缺陷，未动态注入采纳中并发取消/过期。见 NATIVE_PDF_REVIEW_PENDING_ACCEPTANCE.md。
- XLSX 修复table relationships未完整登记tableParts时错误发布不完整owner快照；无完整身份不允许误删依赖。8c3两真实文件官方右键删除路径实际拒绝并给具体原因，两个sheet/草稿/保存状态保留、零mutation和页面错误，每例127JS。只关闭本次关系完整性边界，不重复既有完整删除链。见 NATIVE_XLSX_TABLE_OWNER_COMPLETENESS.md。
- PPTX 隐藏/取消隐藏复用原引擎属性及原页身份，中文真SVG/当前状态、UndoRedo/恢复/重排/保存下载与修订2已在971b完整浏览器通过（108JS、96按钮图标审计）。独立文件回读确认输出hidden=[false,true]且只改允许XML；另修合法show=false及单双引号兼容、复制预隐藏页状态。root目视发现标签竖排后仅改两行CSS；624aae只读重开窄补验确认标签33×16单行、标题和四按钮不被覆盖、零错误/草稿/save/export。root独立实读和目视，见 NATIVE_PPTX_HIDDEN_SLIDES_ACCEPTANCE.md。

最终资源连续性不冒充重跑：/tmp/four-format-reply-pending-hidden-continuity-final4-20261111.json 比较8c3实际浏览器资源与final4，PDF21和XLSX127无真实代码差异，Word122仅docx-main含明确状态/切根修复；/tmp/four-format-reply-pending-hidden-971-to-final4-20261111.json 比较971b，PPTX108无真实代码差异、Word仅docx-main含切根修复。生成导入文件名仅按manifest唯一稳定身份规范化后全文精确比较，未将raw SHA变化说成字节相同。/tmp/four-format-reply-pending-hidden-css-bridges-final4-20261111.json 另确认624aae实际加载6份CSS与final4逐字节相同，DOC/PDF/PPTX三个bridge身份不变。各完整/窄流程保留自己的原manifest与边界。

完整目标仍未完成：Word复杂嵌套表/完整审阅及其它未迁移功能族，XLSX剩余透视/图表/打印/导入能力，PPTX放映/媒体/审阅接线，以及四格式完整AI工具与stream仍需逐项对齐。新增限定源码盘点 NATIVE_PPTX_COMMENTS_SOURCE_INVENTORY.md：固定源经典批注查看/根新增/逐条删除已有实际保存链，本地引擎同源但桥与宿主尚未接；源未实现的回复/解决不误报为本地漏接。该调查不是产品交付，不据此给总完成百分比。

2026-11-11 XLSX 并行增量：CSV 导入当前选区及打印显式四边边框已分别完成冻结构建真实浏览器验收（各129实际JS身份、errors=[]），CSV包含一次保存下载/openpyxl独立回读与修订2重开，打印包含真实File→Print的HTML、截图与1页A4 PDF。详见 ../../docs/parity/2026-11-11-workbook-csv-import.md 与 NATIVE_XLSX_PRINT_RENDERING_ACCEPTANCE.md。最终 npm run build、check:budget、test:budget 通过；主入口246.6KiB低于250KiB。图表只完成Matplotlib生成及单张图片创建/替换真实文件探针，可信资产与宿主入口未交付，见 NATIVE_XLSX_STATIC_CHART_ALIGNMENT_INVESTIGATION.md。完整图表、PrintDialog、连接与其余功能族继续保留缺口。

后续共享构建连续性核对：浏览器专项完成后，共享 static 又被其它工作重建。root 实读本专项下载 XLSX，并比对两份浏览器资源清单：各125/129资源字节未变；4份共享宿主资源发生变化，不能称当前整包重新通过同一专项。workbook-main、CSV独立chunk及print-settings实际字节未变，见 /tmp/xlsx-parallel-shared-build-continuity-20261111.json。浏览器结论绑定各自原冻结证据；未重复完整测试。

2026-11-11 后续XLSX并行增量：已有文件页眉页脚文字打印、查询与连接只读面板完成真实浏览器专项。打印三页验证first/even/odd、页码/总页数、文件名/表名、转义、0.2in距离与50%字体；查询覆盖真实连接/空态/损坏XML，目标导航保留人工草稿与历史，零保存/零外部请求。各130JS身份由root逐字节核对当前static一致，errors=[]。引擎读取4项、打印35项、上下文6项、查询13项、主入口/Ribbon84项定向通过；最终build/check:budget/test:budget通过，主入口247.6KiB/250KiB。见 NATIVE_XLSX_PRINT_HEADER_FOOTER_ACCEPTANCE.md 与 ../../docs/parity/2026-11-11-workbook-queries.md。页眉页脚编辑/图片、完整PrintDialog、图表创建编辑、外链/合并及其它高级能力保留缺口；固定源查询面板本身不执行查询，refresh-all只刷新透视表。

2026-11-11 再次并行增量：默认/奇数页页眉页脚六区编辑与透视表全部刷新完成。页眉两次真实保存下载重开、清空、first/even/flags及其他ZIP保全，最终布局单独补验；页设置日志不承诺native Undo。透视刷新真实多表导入、增长/收缩、UndoRedo保留源草稿、reload、Python bridge保存、独立openpyxl结果180与修订2重开通过，130JS/errors=[]。本轮按固定GenOffice源码参照，未新增依赖或@sheets-web引用；旧本地包名未全局改名。含公式来源、共享缓存/复杂透视、缺records明确拒绝，不刷新外部连接。前后端产物均已重建；定向52项集成、最终tsc/Vite/check:budget通过，main249.8KiB/250KiB。见NATIVE_XLSX_HEADER_FOOTER_EDITOR_ACCEPTANCE.md和../../docs/parity/2026-11-11-workbook-pivot-refresh.md。完整打印、图表创建编辑、合并工作簿与高级透视仍保留缺口。


## 2026-11-13 源入口、图表选择与预设续批

固定参照仍为GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。用户要求的code拉取已实际fetch并ff-only核对：HEAD与origin/code同为`6a713d053527d6b0cec938aeb8c4263709eb1d8b`、ahead/behind=0/0；拉取当时942个本地路径与暂存区不变。其后继续本目标的三条同模型子agent并行工作，不覆盖已有并发改动。

- XLSX：按chartPath选择同名多图，canvas/说明面板键盘入口、Escape/Delete、实例及保护复检、固定源四布局/五配色、饼环分类百分比标签与分类图例已接现有writer和草稿。补pointerup合成双击焦点缺陷及图表修改误走网格撤销栈。最终0015真实人工A1加粗、多次图表编辑、UndoRedo/reload、75%选择/Delete、4→5→6两次保存/点击下载/明确重开通过；171实际JS/CSS SHA匹配，独立openpyxl/lxml/ZIP确认另一图XML原字节不变。详见[选择与预设验收](NATIVE_XLSX_CHART_SELECTION_PRESETS_ACCEPTANCE.md)。不包括拖动/resize、复杂格式、全部图类标签预览或桌面Excel。
- PDF：目录安全HTTP/HTTPS/mailto真实外链、隔离opener，内部按pageId跳页/过滤删除页，已完成8d4真实点击/Enter/双视口专项。0015只续验入口及50实际资源身份，46原字节相同、4仅引用名变化、归一无内容差异，errors=[]；不冒称重跑完整交互。见[目录验收](NATIVE_PDF_OUTLINE_LINKS_ACCEPTANCE.md)。
- PPTX：拼写整稿/翻译当前页的源21语言菜单已接既有Agno候选链，生成前无任务、显式采纳、取消/过期保护。8d4使用真实Agno+ScriptedModel完成候选生命周期和独立PPTX回读，未做save/export/download。0015只续验真实入口和129实际JS身份，126原字节相同、3仅引用名变化、归一全同，错误数组为空，0模型job。见[AI预设验收](NATIVE_PPTX_AI_PRESETS_ACCEPTANCE.md)及[源入口盘点](NATIVE_WORD_PPTX_SOURCE_ENTRY_GAPS_20261113.md)。不等于真实provider翻译质量或全部对象AI工具。

最终隔离static为`/tmp/office-four-format-source-increment-20261113/static`，manifest SHA256=`0015c3b33b9184ffa601a0d60d3d501b498986b98865d7d41eb1e4f6accf3bfe`；完整前端类型检查、43.98秒Vite构建、394 JS原预算通过，保留既有构建警告。引擎9项/前端18项LOCAL适配哈希匹配，原始SOURCE-SHA256不动。只归档和删除本批临时配置，未覆盖共享static/dist、提交、推送或部署，未重复完整测试。

758模块/5215声明点为源码定位快照，不能作为功能总数或完成率。Word复杂目标、图表高级功能、PDF/PPTX其余工具面、流式AI、生产仓储/桌面Office等仍需逐项补齐；整体目标继续active。下载中的验收待复核原因保留且不阻断已核验身份文件签发。


归档时发现共享源码有外部并发漂移，见`/tmp/office-four-format-source-increment-20261113/source-history-postbuild-drift.json`：包括workbook-ribbon及docx/focus-trap/pdf-object-dialog等9文件。0015的ribbon产物相对6bb除局部标识符改名外，实际新增defaultPrevented/isComposing/keyCode229键盘守卫；该外部变化被保留，不归为本批独占修复，也未单独补做该守卫专项。最终171资源与完整XLSX浏览器结论绑定实际0015静态文件；不宣称整个当前工作区已通过相同验证。`source-final-identities.json`逐文件记录当前归档SHA及与构建开始身份是否相同，不将当前副本冒称所有原始受测源码。没有为追赶并发状态反复构建或覆盖他人改动。


## 2026-11-13 多级列表、图表几何、书签编辑与公式续批

固定参照仍为GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。root与三个同模型子agent并行；本批只关闭下列源子能力，不把模块/声明点计作功能分母，整体对齐仍未完成。

| 格式 | 本批交付及实际验证 | 仍保留的边界 |
| --- | --- | --- |
| Word | 八套九级预设，最近/文档/级别区与完整自定义对话框，可信顶层多段单事务；真实UI/UndoRedo/恢复/390px布局，以及68ce修订4→5保存、授权下载、重开，150项HTTP资产匹配；独立lxml/python-docx确认共享numId、九级、第%1章/start4及原文/旧编号/其他部件保全。 | 普通符号/编号库与设置编号值已由后续专项交付；剩余图片符号、完整段落对话框及复杂目标，编号值受可核验定义限制。见[多级列表](NATIVE_WORD_MULTILEVEL_ACCEPTANCE.md)、[普通列表](NATIVE_WORD_LIST_LIBRARIES_ACCEPTANCE.md)及[编号值](NATIVE_WORD_NUMBERING_VALUE_ACCEPTANCE.md)。 |
| XLSX | 两格锚点移动和八向缩放、单格锚点只移动，最小24px、Escape/滚轮取消、UndoRedo/草稿/75%/RTL及人工A1保留；87a手势与68ce RTL/保存续验分层，修订4→5，171项资产匹配，独立openpyxl/lxml/ZIP回读保全另一图锚点和两张chart part。 | absolute锚点明确拒绝，单格锚点仅支持移动；推荐图表已由[后续专项](NATIVE_XLSX_RECOMMENDED_CHARTS_ACCEPTANCE.md)交付，剩余完整ChartPanels轴/间隙/环孔/扇区/标签格式/点填充、复杂SelectData与细粒度series/point选择。同sheet多条applyPageSetups视图覆盖疑点已记录，不宣称视图持久化通过。见[几何验收](NATIVE_XLSX_CHART_OBJECT_GEOMETRY_ACCEPTANCE.md)。 |
| PDF | 书签当前页新增、嵌套改名、删子树和清空，支持空白页/删页/重排/旋转/便签组合；源码真实HTTP保存下载重开及pypdf回读通过，87a冻结最小入口/50资源与桌面/390px验证独立记录。 | URI/异常树/坏目标/签名保护来源只读，固定源其它非AI工具族仍按18行差距表逐项推进。最终68ce连续性结果以[书签专项](NATIVE_PDF_SOURCE_GAPS_BOOKMARKS_20261113.md)最终附录为准，不把87a浏览器结果冒称68ce完整保存重跑。 |
| PPTX | 12模板/自定义Unicode、取消、UndoRedo、草稿/未失焦保存、修订2下载重开；源码HTTP完整链与冻结桥同payload重放分别验收；68ce最小入口/实际131资源及两处并发Ribbon键盘/焦点变化补验。 | 固定源是Cambria Math数学字体文本框，不是OMML。夹具连续插入中心框有明显叠放，像素仅证实绘制可见，不证明无重叠或清晰排版。其余放映/媒体/AI工具面继续开放。见[公式验收](NATIVE_PPTX_EQUATION_ACCEPTANCE.md)。 |

本批最终隔离static为 `/tmp/office-four-format-source-entry-20261113/static`，manifest `68ce99975149470621d980fcf040694372b986a4c037e5463f07d85a8edf67e2`。完整前端类型检查退出0；Vite 51.87秒，397JS原预算failures=[]，没有提高预算；既有循环chunk/PURE/字体URL/大chunk提示保留。四引擎隔离桥构建通过并记录逐SHA，未覆盖共享static/dist。root逐一复核Word150/XLSX171/PPTX131实际HTTP资产与最终磁盘一致，独立重读Word与XLSX实际下载，目视三个重开截图。

真实保存找出两项Python边界漏登：Word docx_native仅追加setParagraphCustomList；XLSX native_office仅追加applyChartAnchors字段。各自真实桥定向RED→GREEN后续验保存通过，均是前端构建后单独验证的Python增量，不假装已包含在原前端源快照。Word/XLSX/PPTX保存仍返回 `validation.ok=false/native_source_review_pending`，已核验身份文件照常下载，不称业务验收通过。PDF写后复核故障同样只告警，原非阻断链保留。

失败证据原样保留：首轮Word超预算、第二轮字体行窄屏裁切、Chromium资源不足、Word烟测误用preview按钮、Word/XLSX Python 422、PPTX过早截图及错误context夹具前提、PDF末端验证器NullObject。只修目标或对应测试条件，不将失败日志删改为通过。87a→68ce slides-main存在其它会话的两处真实Ribbon变化，已明确区分并补必要UI；不是全部仅导入更名，也不归本专项独占。构建后源漂移两文件属于management签章配置，保留原/新身份，不覆盖并发修改。

统一证据 `/tmp/office-four-format-source-entry-20261113/summary.json`，包括构建/预算/桥身份、分层浏览器及下载证据、Python增量、失败和源漂移。Word源迁移七项原始身份已追加SOURCE，LOCAL逐项匹配；XLSX frontend/engine本地适配身份已核对，未改原始SOURCE-SHA。本批临时Vite配置已归档删除，自己的测试服务已结束；未重复完整测试，未提交、推送或部署。完整目标保持active，不能据本批宣布穷尽完成。


PDF 68ce连续性最终补记：root重新运行精确manifest比对脚本，87a浏览器实际50资源中45项原字节相同，5项仅登记的生成资产路径变化，替换后一字不差；静态imports/css/assets闭包51项，补出的cursor SVG原字节相同，依赖图无变化，native.html也仅入口引用变化。真实逻辑变化0。证据 `/tmp/office-pdf-source-gaps-20261113/final-68ce-continuity/resource-continuity.json` 与root复核日志。没有重跑UI或HTTP保存；源码完整保存链、87a实际交互与68ce静态连续性保持分层，不把最后一层称作新的完整保存验收。


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

| 格式 | 本批技术闭环与最终续验 | 保留边界与专项 |
| --- | --- | --- |
| Word | 普通Home新列表优先复用来源未使用的同类编号定义，缺省时沿原writer生成源五级定义；稳定binding/listKind接入设置编号值、UndoRedo、草稿和清除列表。完整链一次保存4→5，独立回读两个numId同指abstractNum7、startOverride1/9、15个非目标parts保全；最终0save层155实际JS/CSS及HTML身份匹配。 | 只限可信已有顶层正文/标题；新增未登记段落、嵌套对象、图片项目符号和全部源自动编号/图库链仍开放。见[Home编号值专项](NATIVE_WORD_HOME_NUMBERING_ACCEPTANCE_20261113.md)。 |
| XLSX | 单plot SelectData可取消、逐系列跨表换绑/增删重排和24系列上限；源缓存行列切换生成literal，补既有numLit读取与原生预览。完整链保留人工J2/bold、390px真实确认、刷新、一次4→5保存与独立回读；最终0save层173资源匹配，canvas实际柱体和值比例一致，ops=[]。 | bar+line组合图逐系列plot/secondaryAxis仍缺，writer仍拒绝组合整体替换；完整ChartPanels、series/point和其它复杂格式不由此关闭。见[SelectData专项](NATIVE_XLSX_SELECT_DATA_ACCEPTANCE.md)。 |
| PDF | 每N页生成多文件，复用原flush/预览确认/保存/新修订授权/提取writer/非阻断签发。最终一次保存4→5后唯一一次N=2拆分，三份实际下载独立pypdf页序[5,4]/[3,2]/[1]，第一份子文档重开；60次实际资源响应（58个不同文件）匹配，390px第三份按钮可达。 | 非splitPages切格或N-up；来源最多10000页，不支持AcroForm/批注/保护来源，来源级书签/附件不保留。合并、比较、签名与其它工具族仍逐项开放，并发compare/native-AI排除。见[拆分专项](NATIVE_PDF_SPLIT_BATCH_SOURCE_ACCEPTANCE_20261113.md)。 |
| PPTX | 固定源runTxn/setText按实际master/layout部件与SPID改已有顶层文字，沿同一NativeDraft；一次保存至修订2，独立回读仅改两个master/layout实体，另45部件及讲稿保全；两页实际继承新文字。最终0save层153资源匹配、两页稳定画布及文字回读通过。 | 纯文字整体改写沿源主样式，非逐run富文本编辑；组内对象、创建/删除母版版式和完整MasterView仍缺，外部放映/动画live变化不在本批。见[母版文字专项](NATIVE_PPTX_MASTER_TEXT_ACCEPTANCE.md)。 |

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

## 2026-11-13 页面边框、Ribbon命令、母版填充、PDF表单检测续批

本批各专项分别完成当前节页面边框快捷项、XLSX真实Ribbon删除图表/合并工作簿、PPTX母版/版式顶层填充、PDF字段候选检测；具体交互、保存件身份与范围见[本批四格式验收](NATIVE_FOUR_FORMAT_PAGE_BORDER_RIBBON_FILL_DETECT_ACCEPTANCE_20261113.md)。四份专项都保留 `validation.ok=false/native_source_review_pending`，技术保存不等于业务验收。当前能力状态不应外推到相邻工具族。

本批统一冻结摘要记录4318份源码，manifest `5ede4bf0e2689e7427f0e90ea296a912ae56aa4ef124be01a1916d8af55c3c90`；原预算未提高。Word/XLSX/PPTX的105个live后端文件执行前后稳定但有两项冻结前差异；PDF的后端复核仅覆盖九个命名文件。XLSX真实runner比冻结runner更新，已分别登记。

root查看了PDF候选/重开、XLSX合并/重开、PPTX实色/none和窄屏填充视图。但本批临时冻结目录及专项 `/dev/shm` 证据在最终汇总检查时无法从文件系统读取；root独立核验脚本没有生成成功报告，也没有复跑已成功的完整保存来重造产物。以上四项以专项原记录为证据，不写成root最终独立复核通过。

之后并发 live 源审计发现 PDF 静态文字、勾号、叉号已接入，另有图像内容流写入与 `GenOfficeStaticFormFills` 元数据回读；该 live 实现未独立验收。本轮应将其列为“实现存在、验证待做”，不是待开发的空白入口。固定源完成后自动回 Home 的小交互差异另记，不影响填写主链。完整四格式源能力穷举仍active。
